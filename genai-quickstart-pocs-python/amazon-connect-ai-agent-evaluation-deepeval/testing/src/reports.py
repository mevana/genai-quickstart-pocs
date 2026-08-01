"""Report generation.

Each evaluation run produces a timestamped folder containing three files:

* ``detailed_results.csv`` — one row per test case, including DeepEval's
  natural-language ``reason`` for each metric score. The reason field is the
  diagnostic transparency MRM teams expect.
* ``summary.json`` — machine-readable aggregate metrics.
* ``summary.md`` — human-readable summary suitable for MRM packages.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .evaluator import EvaluationRow, EvaluationRun


_CSV_FIELDNAMES = [
    "test_id",
    "category",
    "input",
    "expected_intent",
    "detected_intent",
    "intent_match",
    "expected_outcome",
    "actual_output",
    "correctness_score",
    "correctness_reason",
    "relevancy_score",
    "relevancy_reason",
    "guardrail_score",
    "guardrail_reason",
    "passed",
    "latency_ms",
    "error",
]


def write_reports(run: EvaluationRun, output_dir: str | Path) -> Path:
    """Write the three report files to a timestamped subdirectory.

    Returns the path of the timestamped folder.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = Path(output_dir) / ts
    folder.mkdir(parents=True, exist_ok=True)

    _write_detailed_csv(run.rows, folder / "detailed_results.csv")
    summary = _build_summary(run.rows)
    (folder / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    (folder / "summary.md").write_text(_render_markdown(summary), encoding="utf-8")
    return folder


def _write_detailed_csv(rows: List[EvaluationRow], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "test_id": row.test_id,
                    "category": row.category,
                    "input": row.input,
                    "expected_intent": row.expected_intent,
                    "detected_intent": row.detected_intent,
                    "intent_match": _fmt_optional_bool(row.intent_match),
                    "expected_outcome": row.expected_outcome,
                    "actual_output": row.actual_output,
                    "correctness_score": _fmt_optional_float(row.correctness_score),
                    "correctness_reason": row.correctness_reason,
                    "relevancy_score": _fmt_optional_float(row.relevancy_score),
                    "relevancy_reason": row.relevancy_reason,
                    "guardrail_score": _fmt_optional_float(row.guardrail_score),
                    "guardrail_reason": row.guardrail_reason,
                    "passed": "PASS" if row.passed else "FAIL",
                    "latency_ms": f"{row.latency_ms:.1f}",
                    "error": row.error,
                }
            )


def _build_summary(rows: List[EvaluationRow]) -> Dict:
    if not rows:
        return {
            "total_cases": 0,
            "intent_accuracy": 0.0,
            "avg_correctness_score": 0.0,
            "avg_relevancy_score": 0.0,
            "avg_guardrail_score": 0.0,
            "overall_pass_rate": 0.0,
            "per_category_accuracy": {},
            "latency_ms": {"p50": 0.0, "p90": 0.0, "p99": 0.0},
        }

    intent_scored = [r for r in rows if r.intent_match is not None]
    intent_accuracy = (
        100.0 * sum(1 for r in intent_scored if r.intent_match) / len(intent_scored)
        if intent_scored
        else 0.0
    )

    per_category: Dict[str, List[EvaluationRow]] = defaultdict(list)
    for r in rows:
        per_category[r.category or "uncategorized"].append(r)

    per_category_accuracy = {
        cat: round(100.0 * sum(1 for r in rs if r.passed) / len(rs), 2)
        for cat, rs in per_category.items()
    }

    latencies = [r.latency_ms for r in rows if r.latency_ms > 0]

    return {
        "total_cases": len(rows),
        "intent_accuracy": round(intent_accuracy, 2),
        "avg_correctness_score": _avg_score(rows, "correctness_score"),
        "avg_relevancy_score": _avg_score(rows, "relevancy_score"),
        "avg_guardrail_score": _avg_score(rows, "guardrail_score"),
        "overall_pass_rate": round(
            100.0 * sum(1 for r in rows if r.passed) / len(rows), 2
        ),
        "per_category_accuracy": per_category_accuracy,
        "latency_ms": _latency_percentiles(latencies),
        "errors": sum(1 for r in rows if r.error),
    }


def _render_markdown(summary: Dict) -> str:
    lines: List[str] = []
    lines.append("# DeepEval Evaluation Summary")
    lines.append("")
    lines.append(f"- **Total cases**: {summary['total_cases']}")
    lines.append(f"- **Overall pass rate**: {summary['overall_pass_rate']}%")
    lines.append(f"- **Intent accuracy**: {summary['intent_accuracy']}%")
    lines.append(f"- **Avg correctness score**: {summary['avg_correctness_score']}")
    lines.append(f"- **Avg relevancy score**: {summary['avg_relevancy_score']}")
    lines.append(f"- **Avg guardrail score**: {summary['avg_guardrail_score']}")
    lines.append(f"- **Errors**: {summary.get('errors', 0)}")
    lines.append("")
    lines.append("## Latency (ms)")
    lat = summary.get("latency_ms", {})
    lines.append(f"- p50: {lat.get('p50', 0.0)}")
    lines.append(f"- p90: {lat.get('p90', 0.0)}")
    lines.append(f"- p99: {lat.get('p99', 0.0)}")
    lines.append("")
    lines.append("## Per-category accuracy")
    for cat, pct in summary.get("per_category_accuracy", {}).items():
        lines.append(f"- `{cat}`: {pct}%")
    lines.append("")
    return "\n".join(lines)


def _avg_score(rows: List[EvaluationRow], attr: str) -> float:
    values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
    return round(sum(values) / len(values), 2) if values else 0.0


def _latency_percentiles(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0}
    sorted_values = sorted(values)
    return {
        "p50": round(_percentile(sorted_values, 50), 1),
        "p90": round(_percentile(sorted_values, 90), 1),
        "p99": round(_percentile(sorted_values, 99), 1),
    }


def _percentile(sorted_values: List[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    # Linear interpolation; good enough for small test suites.
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def _fmt_optional_float(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.3f}"


def _fmt_optional_bool(value: Optional[bool]) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


# Compat re-export for statistics in case a caller wants raw percentiles.
__all__ = ["write_reports"]
_ = statistics  # keep import used for potential extension
