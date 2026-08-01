"""DeepEval-based evaluation harness for Amazon Connect AI Agents.

See the accompanying blog post:
    "Evaluating Amazon Connect AI Agents with DeepEval for Model Risk
    Management Acceptance" (Troy Dieter, Madhavi Evana, AWS).

The harness wraps a deployed Amazon Connect AI Agent with two invocation
strategies (Gateway and Amazon Connect) and three DeepEval metrics backed by
Amazon Bedrock as the LLM judge, producing structured CSV, JSON, and Markdown
reports suitable for Model Risk Management (MRM) documentation packages.
"""

__all__ = ["cli", "config", "evaluator", "metrics", "reports", "test_cases"]
