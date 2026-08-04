"""Invoker protocol and result types shared by Gateway and Connect invokers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class InvocationResult:
    """Structured result of invoking the agent for a single test case."""

    actual_output: str
    detected_intent: str = ""
    latency_ms: float = 0.0
    raw: dict = field(default_factory=dict)


class AgentInvoker(Protocol):
    """Minimal protocol for an agent invocation strategy."""

    def invoke(self, user_input: str) -> InvocationResult:
        """Send ``user_input`` to the agent and return its response."""

    def close(self) -> None:
        """Release any underlying resources (e.g., chat sessions)."""
