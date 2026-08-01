"""Gateway invoker — tool-level testing via Amazon Bedrock AgentCore Gateway.

Sends MCP JSON-RPC payloads to the gateway's ``/mcp`` endpoint using SigV4-
signed HTTP requests. This exercises gateway routing, MCP Lambda processing,
and business logic execution. It does *not* exercise intent classification or
LLM response generation — for that, use the Connect invoker.

Gateway tests are fast and produce stable, repeatable results, which makes
them a good fit for CI pre-merge gates.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Optional
from urllib.parse import urlparse

import boto3
import botocore.auth
import botocore.awsrequest
import botocore.credentials
import requests as http_requests

from .base import InvocationResult

logger = logging.getLogger("evals_workshop_deepeval")


class GatewayInvoker:
    def __init__(self, config, region: str):
        self._config = config
        self._region = region
        self._session = boto3.Session(region_name=region)
        self._credentials = self._session.get_credentials()
        self._control_client = self._session.client(
            "bedrock-agentcore-control", region_name=region
        )
        self._gateway_url: Optional[str] = None

    @property
    def gateway_id(self) -> Optional[str]:
        return os.environ.get(self._config.gateway_id_env)

    def _resolve_gateway_url(self) -> str:
        """Look up the gateway URL from the control plane if not cached.

        The returned URL is the full MCP endpoint (including the ``/mcp``
        path) ready to POST to directly.
        """
        if self._gateway_url:
            return self._gateway_url

        # Allow the user to set the URL directly to skip the describe call.
        url_from_env = os.environ.get("AGENTCORE_GATEWAY_URL")
        if url_from_env:
            self._gateway_url = url_from_env.rstrip("/")
            return self._gateway_url

        gateway_id = self.gateway_id
        if not gateway_id:
            raise RuntimeError(
                f"Environment variable {self._config.gateway_id_env} is not set. "
                "Run scripts/setup_env.sh (or setup_env.ps1) first."
            )

        resp = self._control_client.get_gateway(gatewayIdentifier=gateway_id)
        url = resp.get("gatewayUrl", "")
        if not url:
            raise RuntimeError(
                f"Gateway {gateway_id} has no gatewayUrl. "
                "Is the gateway in READY status?"
            )
        # gatewayUrl from the API already includes the /mcp path.
        # Ensure it ends with /mcp; append only if missing.
        url = url.rstrip("/")
        if not url.endswith("/mcp"):
            url = f"{url}/mcp"
        self._gateway_url = url
        logger.info("Resolved gateway URL: %s", self._gateway_url)
        return self._gateway_url

    def _sign_request(self, method: str, url: str, body: str) -> dict:
        """Return SigV4-signed headers for the given request."""
        parsed = urlparse(url)
        headers = {
            "Content-Type": "application/json",
            "Host": parsed.hostname,
        }
        request = botocore.awsrequest.AWSRequest(
            method=method, url=url, data=body, headers=headers
        )
        credentials = self._credentials.get_frozen_credentials()
        signer = botocore.auth.SigV4Auth(
            credentials, "bedrock-agentcore", self._region
        )
        signer.add_auth(request)
        return dict(request.headers)

    def invoke(self, user_input: str) -> InvocationResult:
        mcp_endpoint = self._resolve_gateway_url()

        # MCP JSON-RPC envelope — the Gateway routes this to the appropriate
        # MCP Lambda target based on the tool name embedded in the payload.
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": "handle_user_utterance",
                "arguments": {"input": user_input},
            },
        }
        body = json.dumps(payload)
        signed_headers = self._sign_request("POST", mcp_endpoint, body)

        start = time.perf_counter()
        response = http_requests.post(
            mcp_endpoint,
            data=body,
            headers=signed_headers,
            timeout=self._config.timeout_seconds,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0

        if response.status_code != 200:
            raise RuntimeError(
                f"Gateway returned HTTP {response.status_code}: {response.text}"
            )

        parsed: dict = {}
        try:
            parsed = response.json() if response.text else {}
        except json.JSONDecodeError:
            parsed = {"raw": response.text}

        logger.debug("Gateway raw response: %s", json.dumps(parsed, indent=2))

        actual_output = (
            parsed.get("result", {}).get("content", [{}])[0].get("text")
            or parsed.get("output")
            or parsed.get("raw")
            or ""
        )
        detected_intent = (
            parsed.get("result", {}).get("meta", {}).get("intent", "")
            or parsed.get("intent", "")
        )

        return InvocationResult(
            actual_output=str(actual_output),
            detected_intent=str(detected_intent),
            latency_ms=latency_ms,
            raw=parsed,
        )

    def close(self) -> None:
        return None
