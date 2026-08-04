"""Test-case loading for CSV and JSON.

Test cases are defined with five required fields:

    test_id,input,expected_intent,expected_outcome,category

``expected_outcome`` may be empty for adversarial or out-of-scope cases where
no specific correct response is defined — only guardrail compliance is scored.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass(frozen=True)
class TestCase:
    test_id: str
    input: str
    expected_intent: str
    expected_outcome: str
    category: str


def _coerce(row: dict) -> TestCase:
    return TestCase(
        test_id=str(row["test_id"]).strip(),
        input=str(row["input"]).strip(),
        expected_intent=str(row.get("expected_intent", "")).strip(),
        expected_outcome=str(row.get("expected_outcome", "")).strip(),
        category=str(row.get("category", "")).strip(),
    )


def load_test_cases(path: str | Path) -> List[TestCase]:
    """Load test cases from a CSV or JSON file.

    The format is auto-detected from the file extension.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Test case file not found: {p}")

    if p.suffix.lower() == ".json":
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(f"{p} must contain a JSON array of test cases")
        return [_coerce(row) for row in data]

    if p.suffix.lower() == ".csv":
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            return [_coerce(row) for row in reader]

    raise ValueError(f"Unsupported test case format: {p.suffix}")


def filter_by_categories(
    cases: Iterable[TestCase], categories: Iterable[str] | None
) -> List[TestCase]:
    """Return only the cases whose category is in ``categories``.

    If ``categories`` is falsy, returns the input unchanged.
    """
    if not categories:
        return list(cases)
    wanted = {c.strip() for c in categories if c.strip()}
    return [c for c in cases if c.category in wanted]
