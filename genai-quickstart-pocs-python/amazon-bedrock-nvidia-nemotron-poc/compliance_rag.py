"""
Backend: Bedrock-only Retrieval-Augmented Generation for the compliance assistant.

Keeps the POC self-contained and quick to run:
  * Embeds a small local regulatory knowledge base with Amazon Titan Text
    Embeddings V2 (cached in memory) — no external vector store required.
  * Retrieves the most relevant passages with cosine similarity.
  * Generates a grounded, citation-backed answer with the Amazon Bedrock
    Converse API.

All AWS access is via boto3. No frontend / Streamlit code lives here.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import boto3
import numpy as np

log = logging.getLogger(__name__)

REGION = os.getenv("AWS_REGION", "us-east-1")
# Text generation model (Bedrock). Defaults to NVIDIA Nemotron 3 Super 120B, a
# fully managed serverless model on Amazon Bedrock. Confirm the exact model ID
# for your region in the Bedrock console, or override with BEDROCK_MODEL_ID
# (e.g. a Claude model) if Nemotron access is not yet enabled.
GENERATION_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "nvidia.nemotron-super-3-120b")
EMBED_MODEL_ID = os.getenv("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
TOP_K = int(os.getenv("RAG_TOP_K", "4"))

KNOWLEDGE_BASE_PATH = Path(__file__).parent / "knowledge_base.jsonl"

SYSTEM_PROMPT = (
    "You are a financial regulatory compliance assistant. Answer the user's "
    "question using ONLY the provided context passages. You MUST cite your "
    "sources inline using the [SOURCE: citation] format shown in the context. "
    "If the context does not contain enough information to answer, say so "
    "explicitly and do not guess."
)


class ComplianceRAG:
    """In-memory Bedrock RAG over a local regulatory knowledge base."""

    def __init__(self) -> None:
        self._bedrock = boto3.client("bedrock-runtime", region_name=REGION)
        self._docs: list[dict] = self._load_knowledge_base()
        self._embeddings: Optional[np.ndarray] = None

    # ── Setup ────────────────────────────────────────────────────────────────
    def _load_knowledge_base(self) -> list[dict]:
        docs = []
        with open(KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    docs.append(json.loads(line))
        log.info("Loaded %d knowledge-base passages", len(docs))
        return docs

    def _embed(self, text: str) -> np.ndarray:
        resp = self._bedrock.invoke_model(
            modelId=EMBED_MODEL_ID,
            body=json.dumps({"inputText": text}),
        )
        vec = json.loads(resp["body"].read())["embedding"]
        return np.asarray(vec, dtype=np.float32)

    def build_index(self) -> None:
        """Embed all knowledge-base passages once and cache them in memory."""
        if self._embeddings is not None:
            return
        vectors = [self._embed(f"{d['text']} {d.get('citation', '')}") for d in self._docs]
        self._embeddings = np.vstack(vectors)
        log.info("Built in-memory index: %s", self._embeddings.shape)

    # ── Retrieval ────────────────────────────────────────────────────────────
    def retrieve(self, query: str, top_k: int = TOP_K) -> list[dict]:
        self.build_index()
        q = self._embed(query)
        # Cosine similarity
        norms = np.linalg.norm(self._embeddings, axis=1) * (np.linalg.norm(q) + 1e-9)
        scores = (self._embeddings @ q) / (norms + 1e-9)
        top_idx = np.argsort(scores)[::-1][:top_k]
        results = []
        for i in top_idx:
            doc = dict(self._docs[int(i)])
            doc["score"] = float(scores[int(i)])
            results.append(doc)
        return results

    @staticmethod
    def format_context(chunks: list[dict]) -> str:
        parts = []
        for i, c in enumerate(chunks, 1):
            parts.append(f"[{i}] SOURCE: {c['citation']} (domain: {c.get('domain', 'n/a')})\n    {c['text']}")
        return "\n\n".join(parts)

    # ── Generation ───────────────────────────────────────────────────────────
    def generate(self, question: str, context: str) -> str:
        resp = self._bedrock.converse(
            modelId=GENERATION_MODEL_ID,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{
                "role": "user",
                "content": [{"text": f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer with citations:"}],
            }],
            inferenceConfig={"maxTokens": 600, "temperature": 0.1},
        )
        return resp["output"]["message"]["content"][0]["text"].strip()

    # ── Full pipeline ────────────────────────────────────────────────────────
    def run(self, question: str) -> dict:
        chunks = self.retrieve(question)
        if not chunks:
            return {"answer": "No relevant regulatory passages found.", "context": "", "sources": []}
        context = self.format_context(chunks)
        answer = self.generate(question, context)
        sources = [{"citation": c["citation"], "domain": c.get("domain", ""), "text": c["text"]} for c in chunks]
        return {"answer": answer, "context": context, "sources": sources}
