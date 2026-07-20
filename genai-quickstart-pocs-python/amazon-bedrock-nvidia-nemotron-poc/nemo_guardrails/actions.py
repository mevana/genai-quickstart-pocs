"""
Custom actions behind the Colang rails. NeMo Guardrails auto-discovers the
@action functions in this file when the config directory is loaded.

The rails are implemented as deterministic action-based flows (see rails.co):
each input/output rail calls one of these actions and branches on the result,
rather than relying on LLM intent matching. Rail logic is shared with the
plain-Python fallback in ``guardrails.py``; ``rag_answer`` runs the Bedrock RAG
and stores the retrieved context so the fact-check rail can verify grounding.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nemoguardrails.actions import action  # noqa: E402
from nemoguardrails.actions.actions import ActionResult  # noqa: E402

import guardrails as gr  # noqa: E402
from compliance_rag import ComplianceRAG  # noqa: E402

_rag = None


def _get_rag() -> ComplianceRAG:
    global _rag
    if _rag is None:
        _rag = ComplianceRAG()
        _rag.build_index()
    return _rag


@action(name="check_jailbreak")
async def check_jailbreak(text: str = "") -> bool:
    """Return True if the input looks like a prompt-injection/jailbreak attempt."""
    return gr.check_jailbreak(text or "")


@action(name="check_off_topic")
async def check_off_topic(text: str = "") -> bool:
    """Return True if the input is NOT an on-topic compliance question."""
    return not gr.check_topic(text or "")


@action(name="anonymize_pii")
async def anonymize_pii(text: str = "") -> str:
    masked, _ = gr.anonymize_pii(text or "")
    return masked


@action(name="check_grounding")
async def check_grounding(response: str = "", retrieved: str = "") -> bool:
    # NOTE: do not name a parameter ``context`` — NeMo Guardrails treats that as
    # a reserved parameter and injects the whole context dict.
    return gr.check_grounding(response or "", retrieved or "")


@action(name="validate_citation_format")
async def validate_citation_format(response: str = "") -> bool:
    return gr.validate_citation(response or "")


@action(name="add_citation_disclaimer")
async def add_citation_disclaimer(response: str = "") -> str:
    return (
        (response or "")
        + "\n\n_Note: no properly formatted citation was produced. "
        "Please verify against the original regulatory text._"
    )


@action(name="rag_answer", is_system_action=False)
async def rag_answer(query: str = "") -> ActionResult:
    """Run the Bedrock RAG pipeline and expose the retrieved context to the
    output rails via a context update ($retrieved_context)."""
    result = _get_rag().run(query or "")
    return ActionResult(
        return_value=result["answer"],
        context_updates={"retrieved_context": result["context"]},
    )
