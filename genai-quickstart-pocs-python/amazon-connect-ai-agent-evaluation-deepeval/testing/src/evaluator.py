"""Evaluation orchestrator.

For each test case: invoke the agent, build a ``LLMTestCase`` from the
response, run the applicable DeepEval metrics, and capture a structured
result row for the reports.

Pass/fail logic is category-aware:

* ``happy_path`` / ``ambiguous`` / ``multi_turn`` — require correctness
  above threshold AND relevancy above threshold.
* ``jailbreak`` / ``adversarial`` / ``out_of_scope`` — require guardrail
  compliance above threshold. Correctness and relevancy are not scored when
  no expected outcome is defined.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Optional

from .config import HarnessConfig
from .invokers.base import AgentInvoker
from .metrics import MetricBundle
from .test_cases import TestCase

try:  # pragma: no cover
    from deepeval.test_case import LLMTestCase
except ImportError:  # pragma: no cover
    LLMTestCase = None  # type: ignore[assignment]


_ADVERSARIAL_CATEGORIES = {"jailbreak", "adversarial", "out_of_scope"}


@dataclass
class EvaluationRow:
    """One row in ``detailed_results.csv``."""

    test_id: str
    category: str
    input: str
    expected_intent: str
    expected_outcome: str
    actual_output: str
    detected_intent: str
    intent_match: Optional[bool]
    correctness_score: Optional[float]
    correctness_reason: str
    relevancy_score: Optional[float]
    relevancy_reason: str
    guardrail_score: Optional[float]
    guardrail_reason: str
    passed: bool
    latency_ms: float
    error: str = ""


@dataclass
class EvaluationRun:
    rows: List[EvaluationRow] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.rows)


class Evaluator:
    def __init__(
        self,
        config: HarnessConfig,
        invoker: AgentInvoker,
        metrics: MetricBundle,
    ):
        self._config = config
        self._invoker = invoker
        self._metrics = metrics

    def run(self, cases: Iterable[TestCase]) -> EvaluationRun:
        case_list = list(cases)
        total = len(case_list)
        run = EvaluationRun()
        run_start = time.perf_counter()

        for i, case in enumerate(case_list, 1):
            _print_progress(i, total, case.test_id, "invoking...")
            row = self._evaluate_one(case)
            status = "\033[32mPASS\033[0m" if row.passed else "\033[31mFAIL\033[0m"
            if row.error:
                status = f"\033[31mERROR\033[0m"
            _print_progress(i, total, case.test_id, status, done=True)
            run.rows.append(row)

        elapsed = time.perf_counter() - run_start
        passed = sum(1 for r in run.rows if r.passed)
        failed = total - passed
        _print_summary(passed, failed, total, elapsed)
        return run

    def _evaluate_one(self, case: TestCase) -> EvaluationRow:
        try:
            invocation = self._invoker.invoke(case.input)
        except Exception as exc:  # noqa: BLE001 - surface any invocation error
            return EvaluationRow(
                test_id=case.test_id,
                category=case.category,
                input=case.input,
                expected_intent=case.expected_intent,
                expected_outcome=case.expected_outcome,
                actual_output="",
                detected_intent="",
                intent_match=None,
                correctness_score=None,
                correctness_reason="",
                relevancy_score=None,
                relevancy_reason="",
                guardrail_score=None,
                guardrail_reason="",
                passed=False,
                latency_ms=0.0,
                error=f"{type(exc).__name__}: {exc}",
            )

        intent_match: Optional[bool] = None
        if case.expected_intent and invocation.detected_intent:
            intent_match = (
                case.expected_intent.strip().lower()
                == invocation.detected_intent.strip().lower()
            )

        is_adversarial = case.category in _ADVERSARIAL_CATEGORIES

        test_case = self._build_llm_test_case(case, invocation.actual_output)

        correctness_score, correctness_reason = (None, "")
        relevancy_score, relevancy_reason = (None, "")
        guardrail_score, guardrail_reason = (None, "")

        if not is_adversarial and case.expected_outcome:
            if invocation.actual_output:
                correctness_score, correctness_reason = _measure(
                    self._metrics.correctness, test_case
                )
                relevancy_score, relevancy_reason = _measure(
                    self._metrics.relevancy, test_case
                )
            else:
                correctness_reason = "Skipped: gateway returned empty output"
                relevancy_reason = "Skipped: gateway returned empty output"
        if is_adversarial:
            if invocation.actual_output:
                guardrail_score, guardrail_reason = _measure(
                    self._metrics.guardrail, test_case
                )
            else:
                guardrail_reason = "Skipped: gateway returned empty output"

        passed = self._decide_pass(
            is_adversarial=is_adversarial,
            correctness_score=correctness_score,
            relevancy_score=relevancy_score,
            guardrail_score=guardrail_score,
        )

        return EvaluationRow(
            test_id=case.test_id,
            category=case.category,
            input=case.input,
            expected_intent=case.expected_intent,
            expected_outcome=case.expected_outcome,
            actual_output=invocation.actual_output,
            detected_intent=invocation.detected_intent,
            intent_match=intent_match,
            correctness_score=correctness_score,
            correctness_reason=correctness_reason,
            relevancy_score=relevancy_score,
            relevancy_reason=relevancy_reason,
            guardrail_score=guardrail_score,
            guardrail_reason=guardrail_reason,
            passed=passed,
            latency_ms=invocation.latency_ms,
        )

    def _build_llm_test_case(self, case: TestCase, actual_output: str) -> Any:
        if LLMTestCase is None:
            raise ImportError(
                "deepeval is not installed. Run `pip install -r requirements.txt`."
            )
        return LLMTestCase(
            input=case.input,
            actual_output=actual_output,
            expected_output=case.expected_outcome or None,
        )

    def _decide_pass(
        self,
        *,
        is_adversarial: bool,
        correctness_score: Optional[float],
        relevancy_score: Optional[float],
        guardrail_score: Optional[float],
    ) -> bool:
        m = self._config.metrics
        if is_adversarial:
            return (
                guardrail_score is not None
                and guardrail_score >= m.guardrail_threshold
            )
        # For non-adversarial cases, require both correctness and relevancy.
        if correctness_score is None and relevancy_score is None:
            # Nothing to score (e.g., ambiguous case without expected_outcome
            # provided) — treat as inconclusive rather than passing silently.
            return False
        correctness_ok = (
            correctness_score is None
            or correctness_score >= m.correctness_threshold
        )
        relevancy_ok = (
            relevancy_score is None or relevancy_score >= m.relevancy_threshold
        )
        return correctness_ok and relevancy_ok


def _measure(metric: Any, test_case: Any) -> tuple[float, str]:
    """Run a DeepEval metric against a test case and return (score, reason)."""
    metric.measure(test_case)
    score = float(getattr(metric, "score", 0.0) or 0.0)
    reason = str(getattr(metric, "reason", "") or "")
    return score, reason


def _print_progress(
    current: int, total: int, test_id: str, status: str, *, done: bool = False
) -> None:
    """Write a live progress line to stderr."""
    pct = int(current / total * 100) if total else 0
    bar_width = 20
    filled = int(bar_width * current / total) if total else 0
    bar = "█" * filled + "░" * (bar_width - filled)
    line = f"\r  {bar} {pct:>3}% [{current}/{total}] {test_id:<8} {status:<40}"
    if done:
        sys.stderr.write(f"{line}\n")
    else:
        sys.stderr.write(f"{line}")
    sys.stderr.flush()


def _print_summary(passed: int, failed: int, total: int, elapsed: float) -> None:
    """Print a final summary line."""
    mins, secs = divmod(elapsed, 60)
    time_str = f"{int(mins)}m {secs:.1f}s" if mins else f"{secs:.1f}s"
    sys.stderr.write(f"\n  ✓ {passed} passed  ✗ {failed} failed  ({total} total in {time_str})\n\n")
    sys.stderr.flush()
