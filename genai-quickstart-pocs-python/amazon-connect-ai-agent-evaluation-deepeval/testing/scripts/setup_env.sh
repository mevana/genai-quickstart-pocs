#!/usr/bin/env bash
# ------------------------------------------------------------------------------
# setup_env.sh
#
# Auto-discovers the AWS resources used by the DeepEval evaluation harness:
#
#   * The Lex V2 bot that powers your Amazon Connect AI Agent (for the
#     "connect" invoker).
#   * The production Amazon Bedrock AgentCore Gateway, and an IAM-authenticated
#     evaluation twin of it (for the "gateway" invoker).
#
# Intended to be SOURCED, not executed, so that the resulting environment
# variables persist in your current shell:
#
#   source scripts/setup_env.sh
#
# The IAM evaluation gateway is named "evals-harness-iam" for easy
# identification during cleanup.
#
# WARNING: This script exports resource IDs to environment variables for
# development only. For production, use AWS Secrets Manager or AWS Systems
# Manager Parameter Store with encryption enabled, and use IAM roles for
# authentication instead of long-term credentials.
# ------------------------------------------------------------------------------

# Detect if the script is being sourced; warn the caller if it is not.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "[setup_env] WARNING: this script should be sourced so env vars persist." >&2
  echo "[setup_env]          Run:  source scripts/setup_env.sh" >&2
fi

set -u

: "${AWS_REGION:=us-east-1}"
export AWS_REGION

echo "[setup_env] Region: ${AWS_REGION}"

# ------------------------------------------------------------------------------
# 1. Discover the Lex V2 bot that powers the Connect AI Agent.
#
#    The harness calls the bot directly via `lex-runtime recognize-text`, which
#    is the same API path Amazon Connect uses internally. This bypasses the
#    Connect contact flow transport layer (which is slow and flaky for
#    programmatic chat) while still exercising intent classification, tool
#    selection, and the Amazon Q in Connect response generation.
#
#    Set LEX_BOT_NAME ahead of time to pick a specific bot. Otherwise we take
#    the first bot returned by list-bots.
# ------------------------------------------------------------------------------
if [[ -z "${LEX_BOT_ID:-}" ]]; then
  if [[ -n "${LEX_BOT_NAME:-}" ]]; then
    LEX_BOT_ID=$(aws lexv2-models list-bots \
      --region "${AWS_REGION}" \
      --query "botSummaries[?botName=='${LEX_BOT_NAME}'] | [0].botId" \
      --output text 2>/dev/null || true)
  else
    LEX_BOT_ID=$(aws lexv2-models list-bots \
      --region "${AWS_REGION}" \
      --query 'botSummaries[0].botId' \
      --output text 2>/dev/null || true)
  fi
fi
export LEX_BOT_ID
echo "[setup_env] LEX_BOT_ID=${LEX_BOT_ID:-<not-found>}"

# ------------------------------------------------------------------------------
# 2. Discover the bot alias. Prefer TSTALIASID for development; fall back to
#    the first alias.
# ------------------------------------------------------------------------------
if [[ -n "${LEX_BOT_ID:-}" && "${LEX_BOT_ID}" != "None" && -z "${LEX_BOT_ALIAS_ID:-}" ]]; then
  LEX_BOT_ALIAS_ID=$(aws lexv2-models list-bot-aliases \
    --bot-id "${LEX_BOT_ID}" \
    --region "${AWS_REGION}" \
    --query "botAliasSummaries[?botAliasId=='TSTALIASID'] | [0].botAliasId" \
    --output text 2>/dev/null || true)

  if [[ -z "${LEX_BOT_ALIAS_ID:-}" || "${LEX_BOT_ALIAS_ID}" == "None" ]]; then
    LEX_BOT_ALIAS_ID=$(aws lexv2-models list-bot-aliases \
      --bot-id "${LEX_BOT_ID}" \
      --region "${AWS_REGION}" \
      --query 'botAliasSummaries[0].botAliasId' \
      --output text 2>/dev/null || true)
  fi
fi
export LEX_BOT_ALIAS_ID
echo "[setup_env] LEX_BOT_ALIAS_ID=${LEX_BOT_ALIAS_ID:-<not-found>}"

# ------------------------------------------------------------------------------
# 3. Default the Lex locale to en_US. Override LEX_LOCALE_ID to use a different
#    locale if your bot is built for another language.
# ------------------------------------------------------------------------------
: "${LEX_LOCALE_ID:=en_US}"
export LEX_LOCALE_ID
echo "[setup_env] LEX_LOCALE_ID=${LEX_LOCALE_ID}"

# ------------------------------------------------------------------------------
# 4. Locate the production AgentCore Gateway and create an IAM-auth evaluation
#    gateway that points at the same MCP Lambda targets.
#
#    The control-plane CLI service is "bedrock-agentcore-control".
#    list-gateways returns results under the "items" key.
#    There is no clone/source-gateway flag, so we:
#      a) get the prod gateway to read its role ARN
#      b) create a new gateway with AWS_IAM auth and the same role
#      c) copy each target from the prod gateway to the new one
# ------------------------------------------------------------------------------
if [[ -z "${AGENTCORE_GATEWAY_ID:-}" ]]; then
  PROD_GATEWAY_ID=$(aws bedrock-agentcore-control list-gateways \
    --region "${AWS_REGION}" \
    --query "items[?authorizerType!='AWS_IAM'] | [0].gatewayId" \
    --output text 2>/dev/null || true)

  if [[ -n "${PROD_GATEWAY_ID:-}" && "${PROD_GATEWAY_ID}" != "None" ]]; then
    EXISTING_IAM_GATEWAY_ID=$(aws bedrock-agentcore-control list-gateways \
      --region "${AWS_REGION}" \
      --query "items[?ends_with(name, '-iam')] | [0].gatewayId" \
      --output text 2>/dev/null || true)

    if [[ -n "${EXISTING_IAM_GATEWAY_ID:-}" && "${EXISTING_IAM_GATEWAY_ID}" != "None" ]]; then
      AGENTCORE_GATEWAY_ID="${EXISTING_IAM_GATEWAY_ID}"
      echo "[setup_env] Reusing existing evaluation gateway ${AGENTCORE_GATEWAY_ID}"
    else
      echo "[setup_env] Creating IAM evaluation gateway from production gateway ${PROD_GATEWAY_ID}"

      PROD_ROLE_ARN=$(aws bedrock-agentcore-control get-gateway \
        --gateway-identifier "${PROD_GATEWAY_ID}" \
        --region "${AWS_REGION}" \
        --query 'roleArn' \
        --output text 2>/dev/null || true)

      if [[ -z "${PROD_ROLE_ARN:-}" || "${PROD_ROLE_ARN}" == "None" ]]; then
        echo "[setup_env] ERROR: could not read role ARN from production gateway." >&2
      else
        AGENTCORE_GATEWAY_ID=$(aws bedrock-agentcore-control create-gateway \
          --region "${AWS_REGION}" \
          --name "evals-harness-iam" \
          --role-arn "${PROD_ROLE_ARN}" \
          --protocol-type "MCP" \
          --authorizer-type "AWS_IAM" \
          --query 'gatewayId' \
          --output text 2>/dev/null || true)

        if [[ -n "${AGENTCORE_GATEWAY_ID:-}" && "${AGENTCORE_GATEWAY_ID}" != "None" ]]; then
          echo "[setup_env] Created evaluation gateway ${AGENTCORE_GATEWAY_ID}"

          echo "[setup_env] Waiting for gateway to become READY..."
          for _i in $(seq 1 30); do
            GW_STATUS=$(aws bedrock-agentcore-control get-gateway \
              --gateway-identifier "${AGENTCORE_GATEWAY_ID}" \
              --region "${AWS_REGION}" \
              --query 'status' \
              --output text 2>/dev/null || true)
            if [[ "${GW_STATUS}" == "READY" ]]; then
              break
            fi
            sleep 5
          done

          PROD_TARGET_IDS=$(aws bedrock-agentcore-control list-gateway-targets \
            --gateway-identifier "${PROD_GATEWAY_ID}" \
            --region "${AWS_REGION}" \
            --query 'items[].targetId' \
            --output text 2>/dev/null || true)

          for TARGET_ID in ${PROD_TARGET_IDS}; do
            if [[ -z "${TARGET_ID}" || "${TARGET_ID}" == "None" ]]; then
              continue
            fi
            echo "[setup_env] Copying target ${TARGET_ID}..."

            TARGET_JSON=$(aws bedrock-agentcore-control get-gateway-target \
              --gateway-identifier "${PROD_GATEWAY_ID}" \
              --target-id "${TARGET_ID}" \
              --region "${AWS_REGION}" \
              --output json 2>/dev/null || true)

            TARGET_NAME=$(echo "${TARGET_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('name',''))" 2>/dev/null || true)
            TARGET_DESC=$(echo "${TARGET_JSON}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('description',''))" 2>/dev/null || true)
            TARGET_CONFIG=$(echo "${TARGET_JSON}" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('targetConfiguration',{})))" 2>/dev/null || true)

            if [[ -n "${TARGET_NAME}" && "${TARGET_NAME}" != "" ]]; then
              aws bedrock-agentcore-control create-gateway-target \
                --gateway-identifier "${AGENTCORE_GATEWAY_ID}" \
                --name "${TARGET_NAME}" \
                --description "${TARGET_DESC}" \
                --target-configuration "${TARGET_CONFIG}" \
                --region "${AWS_REGION}" \
                --output text 2>/dev/null || echo "[setup_env] WARNING: failed to copy target ${TARGET_ID}"
            fi
          done
          echo "[setup_env] Target copy complete."
        else
          echo "[setup_env] ERROR: failed to create evaluation gateway." >&2
        fi
      fi
    fi
  fi
fi
export AGENTCORE_GATEWAY_ID
echo "[setup_env] AGENTCORE_GATEWAY_ID=${AGENTCORE_GATEWAY_ID:-<not-found>}"

echo "[setup_env] Done. Run: python -m src --help"
