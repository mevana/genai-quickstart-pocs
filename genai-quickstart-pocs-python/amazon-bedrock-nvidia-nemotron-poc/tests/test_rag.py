"""Unit tests for the RAG helper logic that does not require AWS access."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compliance_rag import ComplianceRAG, KNOWLEDGE_BASE_PATH  # noqa: E402


def test_format_context_includes_citations():
    chunks = [
        {"citation": "31 CFR 1010.311", "domain": "aml", "text": "CTR threshold is $10,000."},
        {"citation": "FINRA Rule 2111", "domain": "securities", "text": "Suitability obligations."},
    ]
    ctx = ComplianceRAG.format_context(chunks)
    assert "31 CFR 1010.311" in ctx
    assert "FINRA Rule 2111" in ctx
    assert "SOURCE:" in ctx


def test_knowledge_base_is_valid_jsonl():
    with open(KNOWLEDGE_BASE_PATH, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert len(records) > 0
    for r in records:
        assert {"id", "domain", "citation", "text"} <= set(r.keys())
