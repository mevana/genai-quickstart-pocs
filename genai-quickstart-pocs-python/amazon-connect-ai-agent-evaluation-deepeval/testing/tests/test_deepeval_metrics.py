"""DeepEval-native pytest integration.

Teams that prefer test-runner semantics can run:

    deepeval test run tests/test_deepeval_metrics.py

This produces the same evaluation results as ``python -m src``, but surfaces
each assertion as a distinct pytest outcome. Useful for integration into
existing pytest-driven CI pipelines.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.config import load_config
from src.invokers import build_invoker
from src.judge import get_bedrock_judge
from src.metrics import build_metrics
from src.test_cases import load_test_cases

try:
    from deepeval import assert_test
    from deepeval.test_case import LLMTestCase
except ImportError:  # pragma: no cover
    assert_test = None  # type: ignore[assignment]
    LLMTestCase = None  # type: ignore[assignment]


_ADVERSARIAL_CATEGORIES = {"jailbreak", "adversarial", "out_of_scope"}


def _load_test_cases_for_pytest():
    config_path = os.environ.get("HARNESS_CONFIG") or str(
        Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    )
    cfg = load_config(config_path)
    cases_path = os.environ.get("HARNESS_TEST_CASES") or cfg.test_cases.path
    return cfg, load_test_cases(cases_path)


_CONFIG, _CASES = _load_test_cases_for_pytest()


@pytest.fixture(scope="session")
def metrics():
    judge = get_bedrock_judge(
        model_id=_CONFIG.aws.bedrock_model_id,
        region=_CONFIG.aws.region,
    )
    return build_metrics(
        judge_model=judge,
        correctness_threshold=_CONFIG.metrics.correctness_threshold,
        relevancy_threshold=_CONFIG.metrics.relevancy_threshold,
        guardrail_threshold=_CONFIG.metrics.guardrail_threshold,
    )


@pytest.fixture(scope="session")
def invoker():
    name = os.environ.get("HARNESS_INVOKER") or _CONFIG.invoker.default
    inv = build_invoker(name, _CONFIG)
    yield inv
    inv.close()


@pytest.mark.parametrize("case", _CASES, ids=[c.test_id for c in _CASES])
def test_agent_response(case, invoker, metrics):
    if assert_test is None:  # pragma: no cover
        pytest.skip("deepeval is not installed")

    result = invoker.invoke(case.input)
    llm_case = LLMTestCase(
        input=case.input,
        actual_output=result.actual_output,
        expected_output=case.expected_outcome or None,
    )

    if case.category in _ADVERSARIAL_CATEGORIES:
        assert_test(llm_case, [metrics.guardrail])
    elif case.expected_outcome:
        assert_test(llm_case, [metrics.correctness, metrics.relevancy])
    else:
        assert_test(llm_case, [metrics.relevancy])
