"""Connect invoker — end-to-end AI agent evaluation via Lex V2 runtime.

Invokes the Lex V2 bot that powers your Amazon Connect AI Agent directly via
``lex-runtime recognize-text``. This is the same API path Amazon Connect uses
internally when a customer chats with the agent, so it exercises the full AI
stack:

* intent classification
* tool selection and slot resolution
* Amazon Q in Connect response generation
* guardrail enforcement

What it deliberately skips is the Connect contact flow transport layer
(queues, routing profiles, chat session management), which produces no
observable difference in the agent's generated response and adds latency and
flakiness to automated evaluation.

For MRM teams, what matters is what the agent says — not how the message
was delivered. This invoker isolates that concern.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

import boto3

from .base import InvocationResult

logger = logging.getLogger("evals_workshop_deepeval")


class ConnectInvoker:
    def __init__(self, config, region: str, lex_client=None):
        self._config = config
        self._region = region
        self._lex = lex_client or boto3.client("lexv2-runtime", region_name=region)

    @property
    def bot_id(self) -> Optional[str]:
        return os.environ.get(self._config.bot_id_env)

    @property
    def bot_alias_id(self) -> Optional[str]:
        return os.environ.get(self._config.bot_alias_id_env)

    @property
    def locale_id(self) -> str:
        return os.environ.get(self._config.locale_id_env, "en_US")

    def invoke(self, user_input: str) -> InvocationResult:
        bot_id = self.bot_id
        alias_id = self.bot_alias_id
        if not bot_id or not alias_id:
            raise RuntimeError(
                f"{self._config.bot_id_env} and {self._config.bot_alias_id_env} "
                "must be set. Run scripts/setup_env.sh (or setup_env.ps1) first."
            )

        session_id = f"deepeval-{uuid.uuid4()}"

        start = time.perf_counter()
        response = self._lex.recognize_text(
            botId=bot_id,
            botAliasId=alias_id,
            localeId=self.locale_id,
            sessionId=session_id,
            text=user_input,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0

        # Concatenate all returned messages into a single response string.
        messages = response.get("messages") or []
        actual_output = "\n".join(
            (m.get("content") or "").strip() for m in messages if m.get("content")
        ).strip()

        # Lex returns the detected intent in sessionState.intent.name.
        session_state = response.get("sessionState") or {}
        intent = (session_state.get("intent") or {}).get("name", "") or ""

        logger.debug(
            "Lex response: intent=%s state=%s messages=%d",
            intent,
            (session_state.get("intent") or {}).get("state", ""),
            len(messages),
        )

        return InvocationResult(
            actual_output=actual_output,
            detected_intent=intent,
            latency_ms=latency_ms,
            raw={
                "session_id": session_id,
                "session_state": session_state,
                "messages": messages,
            },
        )

    def close(self) -> None:  # pragma: no cover - clients are stateless
        return None
