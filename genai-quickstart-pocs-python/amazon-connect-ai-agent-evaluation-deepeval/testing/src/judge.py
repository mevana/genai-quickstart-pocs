"""Amazon Bedrock LLM judge configuration.

All DeepEval metrics in this harness share a single Amazon Bedrock judge so
that evaluation inference stays inside the customer's AWS account, subject to
their existing security controls, VPC configurations, and data residency
policies. This matters when test inputs contain banking-domain data because
no evaluation payload leaves the environment to reach an external API.
"""

from __future__ import annotations

from functools import lru_cache

try:  # pragma: no cover - DeepEval is a runtime dependency of the harness.
    from deepeval.models import AmazonBedrockModel
except ImportError:  # pragma: no cover
    AmazonBedrockModel = None  # type: ignore[assignment]


@lru_cache(maxsize=4)
def get_bedrock_judge(model_id: str, region: str):
    """Return a cached ``AmazonBedrockModel`` instance for the given model id.

    A single cached instance is reused across metrics and test cases to avoid
    creating redundant boto3 clients.
    """
    if AmazonBedrockModel is None:
        raise ImportError(
            "deepeval is not installed. Run `pip install -r requirements.txt`."
        )
    return AmazonBedrockModel(model=model_id, region=region)
