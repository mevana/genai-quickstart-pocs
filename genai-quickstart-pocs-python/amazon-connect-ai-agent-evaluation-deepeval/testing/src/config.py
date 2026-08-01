"""Configuration loading for the evaluation harness.

Reads YAML configuration files and exposes them as typed Pydantic models so
that downstream code can rely on field names and default values rather than
poking at nested dictionaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class AwsConfig(BaseModel):
    region: str = "us-east-1"
    bedrock_model_id: str = "global.anthropic.claude-sonnet-4-6"


class GatewayInvokerConfig(BaseModel):
    gateway_id_env: str = "AGENTCORE_GATEWAY_ID"
    timeout_seconds: int = 30


class ConnectInvokerConfig(BaseModel):
    bot_id_env: str = "LEX_BOT_ID"
    bot_alias_id_env: str = "LEX_BOT_ALIAS_ID"
    locale_id_env: str = "LEX_LOCALE_ID"
    response_timeout_seconds: int = 30


class InvokerConfig(BaseModel):
    default: str = "gateway"
    gateway: GatewayInvokerConfig = Field(default_factory=GatewayInvokerConfig)
    connect: ConnectInvokerConfig = Field(default_factory=ConnectInvokerConfig)


class MetricsConfig(BaseModel):
    correctness_threshold: float = 0.5
    relevancy_threshold: float = 0.7
    guardrail_threshold: float = 0.7


class TestCasesConfig(BaseModel):
    path: str = "data/test_cases.csv"


class ReportsConfig(BaseModel):
    output_dir: str = "reports"


class HarnessConfig(BaseModel):
    aws: AwsConfig = Field(default_factory=AwsConfig)
    invoker: InvokerConfig = Field(default_factory=InvokerConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    test_cases: TestCasesConfig = Field(default_factory=TestCasesConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)


def load_config(path: Optional[str] = None) -> HarnessConfig:
    """Load YAML config from ``path`` (or ``config/default.yaml`` if unset)."""
    config_path = Path(path) if path else Path("config") / "default.yaml"
    if not config_path.exists():
        # Fall back to defaults if no file is present — useful in --dry-run
        # scenarios where the user only wants to validate code paths.
        return HarnessConfig()
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return HarnessConfig(**raw)
