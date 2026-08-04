"""Tests for the guardrail engine wrapper (no AWS calls made)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compliance_guardrails import ComplianceGuardrails  # noqa: E402


def test_engine_reports_a_known_value():
    """Constructing the engine must not require network access and must report
    either the NeMo Guardrails engine or the Python fallback."""
    cg = ComplianceGuardrails()
    assert cg.engine in {"NeMo Guardrails", "Python fallback rails"}


def test_fallback_blocks_off_topic_without_network(monkeypatch):
    """Force the fallback path and confirm an off-topic query is blocked without
    calling Bedrock."""
    cg = ComplianceGuardrails()
    cg._rails = None  # force Python fallback
    result = cg.run("What's a good pasta recipe?")
    assert result["blocked"] is True
    assert "topic_rail" in result["rails_fired"]
