# ------------------------------------------------------------------------------
# setup_env.ps1
#
# PowerShell equivalent of scripts/setup_env.sh. Discovers the AWS resources
# used by the DeepEval evaluation harness:
#
#   * The Lex V2 bot that powers your Amazon Connect AI Agent (for the
#     "connect" invoker).
#   * The production Amazon Bedrock AgentCore Gateway, and an IAM-authenticated
#     evaluation twin of it (for the "gateway" invoker).
#
# Usage:
#   .\scripts\setup_env.ps1
#
# WARNING: This script exports resource IDs to environment variables for
# development only. For production, use AWS Secrets Manager or AWS Systems
# Manager Parameter Store with encryption enabled, and use IAM roles for
# authentication instead of long-term credentials.
# ------------------------------------------------------------------------------

$ErrorActionPreference = "Continue"

if (-not $env:AWS_REGION) {
    $env:AWS_REGION = "us-east-1"
}

Write-Host "[setup_env] Region: $($env:AWS_REGION)"

# ------------------------------------------------------------------------------
# 1. Discover the Lex V2 bot that powers the Connect AI Agent.
#
#    The harness calls the bot directly via `lex-runtime recognize-text`, which
#    is the same API path Amazon Connect uses internally. This bypasses the
#    Connect contact flow transport layer (which is slow and flaky for
#    programmatic chat) while still exercising intent classification, tool
#    selection, and the Amazon Q in Connect response generation.
#
#    Set $env:LEX_BOT_NAME ahead of time to pick a specific bot. Otherwise we
#    take the first bot returned by list-bots.
# ------------------------------------------------------------------------------
if (-not $env:LEX_BOT_ID) {
    if ($env:LEX_BOT_NAME) {
        $env:LEX_BOT_ID = (aws lexv2-models list-bots `
            --region $env:AWS_REGION `
            --query "botSummaries[?botName=='$($env:LEX_BOT_NAME)'] | [0].botId" `
            --output text) 2>$null
    } else {
        $env:LEX_BOT_ID = (aws lexv2-models list-bots `
            --region $env:AWS_REGION `
            --query "botSummaries[0].botId" `
            --output text) 2>$null
    }
}
Write-Host "[setup_env] LEX_BOT_ID=$($env:LEX_BOT_ID)"

# ------------------------------------------------------------------------------
# 2. Discover the bot alias. Prefer TSTALIASID for development; fall back to
#    the first alias.
# ------------------------------------------------------------------------------
if ($env:LEX_BOT_ID -and $env:LEX_BOT_ID -ne "None" -and -not $env:LEX_BOT_ALIAS_ID) {
    $env:LEX_BOT_ALIAS_ID = (aws lexv2-models list-bot-aliases `
        --bot-id $env:LEX_BOT_ID `
        --region $env:AWS_REGION `
        --query "botAliasSummaries[?botAliasId=='TSTALIASID'] | [0].botAliasId" `
        --output text) 2>$null

    if (-not $env:LEX_BOT_ALIAS_ID -or $env:LEX_BOT_ALIAS_ID -eq "None") {
        $env:LEX_BOT_ALIAS_ID = (aws lexv2-models list-bot-aliases `
            --bot-id $env:LEX_BOT_ID `
            --region $env:AWS_REGION `
            --query "botAliasSummaries[0].botAliasId" `
            --output text) 2>$null
    }
}
Write-Host "[setup_env] LEX_BOT_ALIAS_ID=$($env:LEX_BOT_ALIAS_ID)"

# ------------------------------------------------------------------------------
# 3. Default the Lex locale to en_US.
# ------------------------------------------------------------------------------
if (-not $env:LEX_LOCALE_ID) {
    $env:LEX_LOCALE_ID = "en_US"
}
Write-Host "[setup_env] LEX_LOCALE_ID=$($env:LEX_LOCALE_ID)"

# ------------------------------------------------------------------------------
# 4. Locate the production AgentCore Gateway and create an IAM-auth evaluation
#    gateway pointed at the same MCP Lambda targets.
#
#    The control-plane CLI service is "bedrock-agentcore-control".
#    list-gateways returns results under the "items" key.
#    There is no clone/source-gateway flag, so we:
#      a) get the prod gateway to read its role ARN
#      b) create a new gateway with AWS_IAM auth and the same role
#      c) copy each target from the prod gateway to the new one
# ------------------------------------------------------------------------------
if (-not $env:AGENTCORE_GATEWAY_ID) {
    $prodGatewayId = (aws bedrock-agentcore-control list-gateways `
        --region $env:AWS_REGION `
        --query "items[?authorizerType!='AWS_IAM'] | [0].gatewayId" `
        --output text) 2>$null

    if ($prodGatewayId -and $prodGatewayId -ne "None") {
        $existingIamGatewayId = (aws bedrock-agentcore-control list-gateways `
            --region $env:AWS_REGION `
            --query "items[?ends_with(name, '-iam')] | [0].gatewayId" `
            --output text) 2>$null

        if ($existingIamGatewayId -and $existingIamGatewayId -ne "None") {
            $env:AGENTCORE_GATEWAY_ID = $existingIamGatewayId
            Write-Host "[setup_env] Reusing existing evaluation gateway $env:AGENTCORE_GATEWAY_ID"
        } else {
            Write-Host "[setup_env] Creating IAM evaluation gateway from production gateway $prodGatewayId"

            $prodRoleArn = (aws bedrock-agentcore-control get-gateway `
                --gateway-identifier $prodGatewayId `
                --region $env:AWS_REGION `
                --query "roleArn" `
                --output text) 2>$null

            if (-not $prodRoleArn -or $prodRoleArn -eq "None") {
                Write-Host "[setup_env] ERROR: could not read role ARN from production gateway."
            } else {
                $env:AGENTCORE_GATEWAY_ID = (aws bedrock-agentcore-control create-gateway `
                    --region $env:AWS_REGION `
                    --name "evals-harness-iam" `
                    --role-arn $prodRoleArn `
                    --protocol-type "MCP" `
                    --authorizer-type "AWS_IAM" `
                    --query "gatewayId" `
                    --output text) 2>$null

                if ($env:AGENTCORE_GATEWAY_ID -and $env:AGENTCORE_GATEWAY_ID -ne "None") {
                    Write-Host "[setup_env] Created evaluation gateway $env:AGENTCORE_GATEWAY_ID"

                    Write-Host "[setup_env] Waiting for gateway to become READY..."
                    for ($i = 0; $i -lt 30; $i++) {
                        $gwStatus = (aws bedrock-agentcore-control get-gateway `
                            --gateway-identifier $env:AGENTCORE_GATEWAY_ID `
                            --region $env:AWS_REGION `
                            --query "status" `
                            --output text) 2>$null
                        if ($gwStatus -eq "READY") { break }
                        Start-Sleep -Seconds 5
                    }

                    $prodTargetIds = (aws bedrock-agentcore-control list-gateway-targets `
                        --gateway-identifier $prodGatewayId `
                        --region $env:AWS_REGION `
                        --query "items[].targetId" `
                        --output text) 2>$null

                    if ($prodTargetIds -and $prodTargetIds -ne "None") {
                        foreach ($targetId in $prodTargetIds -split "\s+") {
                            if (-not $targetId -or $targetId -eq "None") { continue }
                            Write-Host "[setup_env] Copying target $targetId..."

                            $targetJson = (aws bedrock-agentcore-control get-gateway-target `
                                --gateway-identifier $prodGatewayId `
                                --target-id $targetId `
                                --region $env:AWS_REGION `
                                --output json) 2>$null

                            if ($targetJson) {
                                $target = $targetJson | ConvertFrom-Json
                                $targetName = $target.name
                                $targetDesc = if ($target.description) { $target.description } else { "" }
                                $targetConfig = ($target.targetConfiguration | ConvertTo-Json -Depth 10 -Compress)

                                aws bedrock-agentcore-control create-gateway-target `
                                    --gateway-identifier $env:AGENTCORE_GATEWAY_ID `
                                    --name $targetName `
                                    --description $targetDesc `
                                    --target-configuration $targetConfig `
                                    --region $env:AWS_REGION `
                                    --output text 2>$null

                                if ($LASTEXITCODE -ne 0) {
                                    Write-Host "[setup_env] WARNING: failed to copy target $targetId"
                                }
                            }
                        }
                    }
                    Write-Host "[setup_env] Target copy complete."
                } else {
                    Write-Host "[setup_env] ERROR: failed to create evaluation gateway."
                }
            }
        }
    }
}
Write-Host "[setup_env] AGENTCORE_GATEWAY_ID=$($env:AGENTCORE_GATEWAY_ID)"

Write-Host "[setup_env] Done. Run: python -m src --help"
