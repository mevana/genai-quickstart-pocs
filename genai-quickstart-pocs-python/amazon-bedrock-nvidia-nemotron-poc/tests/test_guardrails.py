"""Unit tests for the compliance guardrails (no AWS access required)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import guardrails  # noqa: E402


def test_anonymize_pii_masks_ssn():
    masked, found = guardrails.anonymize_pii("My SSN is 123-45-6789 please help")
    assert "123-45-6789" not in masked
    assert "[SSN REDACTED]" in masked
    assert found is True


def test_anonymize_pii_masks_multiple():
    masked, found = guardrails.anonymize_pii("SSN 123-45-6789 and EIN 12-3456789")
    assert "[SSN REDACTED]" in masked
    assert "[EIN REDACTED]" in masked
    assert found is True


def test_anonymize_pii_no_pii():
    text = "What is the CTR threshold under the BSA?"
    masked, found = guardrails.anonymize_pii(text)
    assert masked == text
    assert found is False


def test_check_topic_on_domain():
    assert guardrails.check_topic("What are the FINRA suitability rules?") is True
    assert guardrails.check_topic("Explain the CTR filing threshold under the BSA") is True


def test_check_topic_off_domain():
    assert guardrails.check_topic("What is a good pasta recipe?") is False


def test_validate_citation():
    assert guardrails.validate_citation("Answer. [SOURCE: 31 CFR 1010.311]") is True
    assert guardrails.validate_citation("Answer with no citation.") is False


def test_check_grounding_true_when_claims_supported():
    context = "SOURCE: 31 CFR 1010.311  CTR filing threshold is $10,000."
    response = "The CTR threshold is $10,000. [SOURCE: 31 CFR 1010.311]"
    assert guardrails.check_grounding(response, context) is True


def test_check_grounding_false_when_unsupported():
    context = "SOURCE: 31 CFR 1010.311  CTR filing threshold is $10,000."
    response = "The threshold is $50,000 for large filers."
    assert guardrails.check_grounding(response, context) is False


def test_check_grounding_no_context():
    assert guardrails.check_grounding("Any claim of $10,000.", "") is False


def test_apply_input_rails_blocks_off_topic():
    result = guardrails.apply_input_rails("What's a good pasta recipe?")
    assert result["blocked"] is True
    assert "topic_rail" in result["rails_fired"]


def test_apply_input_rails_masks_and_allows_on_topic():
    result = guardrails.apply_input_rails("For account 123-45-6789, what is the SAR rule?")
    assert result["blocked"] is False
    assert "pii_rail" in result["rails_fired"]
    assert "123-45-6789" not in result["query"]


def test_apply_output_rails_adds_disclaimer_when_uncited():
    out = guardrails.apply_output_rails("An answer without any citation.", context="")
    assert "citation_rail" in out["rails_fired"]
    assert "verify against the original" in out["answer"].lower()
