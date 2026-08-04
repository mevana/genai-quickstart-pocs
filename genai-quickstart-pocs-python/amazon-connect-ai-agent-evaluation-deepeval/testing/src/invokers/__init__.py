"""Agent invocation strategies.

The harness decouples *how* a response is obtained from *how* it is scored.
Two invokers implement the same ``AgentInvoker`` protocol:

* :class:`~src.invokers.gateway.GatewayInvoker` — tool-level testing via
  ``bedrock-agentcore invoke-gateway``.
* :class:`~src.invokers.connect.ConnectInvoker` — end-to-end testing through
  Amazon Connect chat.
"""

from .base import AgentInvoker, InvocationResult
from .connect import ConnectInvoker
from .gateway import GatewayInvoker

__all__ = [
    "AgentInvoker",
    "ConnectInvoker",
    "GatewayInvoker",
    "InvocationResult",
    "build_invoker",
]


def build_invoker(name: str, config) -> AgentInvoker:
    """Construct an invoker by name.

    ``name`` is either ``"gateway"`` (default) or ``"connect"``.
    """
    name = (name or "gateway").lower()
    if name == "gateway":
        return GatewayInvoker(config.invoker.gateway, region=config.aws.region)
    if name == "connect":
        return ConnectInvoker(config.invoker.connect, region=config.aws.region)
    raise ValueError(f"Unknown invoker: {name!r}. Expected 'gateway' or 'connect'.")
