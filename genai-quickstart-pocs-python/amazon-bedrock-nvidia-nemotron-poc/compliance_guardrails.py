"""
Guardrail engine for the compliance assistant.

Primary path: **NeMo Guardrails** (config in ``nemo_guardrails/``) orchestrates
input rails (jailbreak, PII, topic), the RAG answer, and output rails
(grounding, citation validation) around Amazon Bedrock.

Fallback path: if NeMo Guardrails is unavailable or fails to initialize (e.g.
the optional dependency is not installed, or model access is not yet granted),
the equivalent rails implemented in ``guardrails.py`` are applied instead, so the
app always runs. The active engine is reported via ``.engine``.
"""

import logging
from pathlib import Path

import guardrails as gr
from compliance_rag import ComplianceRAG

log = logging.getLogger(__name__)

NEMO_CONFIG_DIR = str(Path(__file__).parent / "nemo_guardrails")


def _build_bedrock_llm(model_id: str, region: str):
    """Build a Bedrock chat model for NeMo Guardrails.

    NVIDIA Nemotron on the Bedrock Converse API does not accept the
    ``stopSequences`` field that NeMo Guardrails passes when calling the LLM, so
    we wrap the model to drop any ``stop`` argument.
    """
    from langchain_aws import ChatBedrockConverse

    class _BedrockNoStop(ChatBedrockConverse):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return super()._generate(messages, stop=None, run_manager=run_manager, **kwargs)

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return await super()._agenerate(messages, stop=None, run_manager=run_manager, **kwargs)

    return _BedrockNoStop(
        model=model_id,
        region_name=region,
        temperature=0.1,
        max_tokens=600,
    )


class ComplianceGuardrails:
    def __init__(self) -> None:
        self._rag = ComplianceRAG()
        self._rails = None
        self._engine = "Python fallback rails"
        self._init_nemo()

    def _init_nemo(self) -> None:
        try:
            from nemoguardrails import LLMRails, RailsConfig

            from compliance_rag import GENERATION_MODEL_ID, REGION

            # Build the Bedrock chat model explicitly and hand it to NeMo
            # Guardrails. This avoids version-sensitive provider auto-resolution
            # and works with NVIDIA Nemotron (or any Bedrock chat model).
            llm = _build_bedrock_llm(GENERATION_MODEL_ID, REGION)
            config = RailsConfig.from_path(NEMO_CONFIG_DIR)
            self._rails = LLMRails(config, llm=llm)
            self._engine = "NeMo Guardrails"
            log.info("NeMo Guardrails initialized from %s", NEMO_CONFIG_DIR)
        except Exception as e:  # noqa: BLE001 - resilience: any failure -> fallback
            log.warning("NeMo Guardrails unavailable (%s); using Python fallback rails.", e)
            self._rails = None

    @property
    def engine(self) -> str:
        return self._engine

    def run(self, question: str) -> dict:
        if self._rails is not None:
            try:
                res = self._run_nemo(question)
                if res.get("answer", "").strip():
                    return res
                log.warning("NeMo Guardrails returned an empty answer; using fallback rails.")
            except Exception as e:  # noqa: BLE001 - fall back on any runtime error
                log.warning("NeMo Guardrails runtime error (%s); using fallback.", e)
        return self._run_fallback(question)

    # ── NeMo Guardrails path ─────────────────────────────────────────────────
    def _run_nemo(self, question: str) -> dict:
        result = self._rails.generate(messages=[{"role": "user", "content": question}])
        answer = result.get("content", "") if isinstance(result, dict) else str(result)

        # The rails are enforced inside NeMo. We derive display metadata with the
        # same deterministic checks the rail actions use, so the UI reflects what
        # the rails did (which rail fired, sources, grounding/citation status).
        rails_fired: list[str] = []
        if gr.check_jailbreak(question):
            return {"engine": "NeMo Guardrails", "answer": answer, "blocked": True,
                    "rails_fired": ["jailbreak_rail"], "grounded": True, "cited": True, "sources": []}
        masked, pii_found = gr.anonymize_pii(question)
        if pii_found:
            rails_fired.append("pii_rail")
        if not gr.check_topic(masked):
            return {"engine": "NeMo Guardrails", "answer": answer, "blocked": True,
                    "rails_fired": rails_fired + ["topic_rail"], "grounded": True,
                    "cited": True, "sources": []}

        chunks = self._rag.retrieve(masked)
        context = self._rag.format_context(chunks)
        grounded = gr.check_grounding(answer, context)
        cited = gr.validate_citation(answer)
        if not grounded:
            rails_fired.append("factcheck_rail")
        if not cited:
            rails_fired.append("citation_rail")
        return {
            "engine": "NeMo Guardrails",
            "answer": answer,
            "blocked": False,
            "rails_fired": rails_fired,
            "grounded": grounded,
            "cited": cited,
            "sources": [
                {"citation": c["citation"], "domain": c.get("domain", ""), "text": c["text"]}
                for c in chunks
            ],
        }

    # ── Python fallback path ─────────────────────────────────────────────────
    def _run_fallback(self, question: str) -> dict:
        inp = gr.apply_input_rails(question)
        if inp["blocked"]:
            return {
                "engine": self._engine, "answer": inp["block_reason"], "blocked": True,
                "rails_fired": inp["rails_fired"], "grounded": True, "cited": True, "sources": [],
            }
        result = self._rag.run(inp["query"])
        out = gr.apply_output_rails(result["answer"], result["context"])
        return {
            "engine": self._engine, "answer": out["answer"], "blocked": False,
            "rails_fired": inp["rails_fired"] + out["rails_fired"],
            "grounded": out["grounded"], "cited": out["cited"], "sources": result["sources"],
        }
