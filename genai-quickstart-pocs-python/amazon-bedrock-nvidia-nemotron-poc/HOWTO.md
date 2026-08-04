# HOWTO — Amazon Bedrock NVIDIA Nemotron POC

Step-by-step instructions to set up, configure, run, and tear down this POC.

## 1. Enable Amazon Bedrock model access

In the AWS console, go to **Amazon Bedrock → Model access** in your target
region and request/enable access to:

- **Amazon Titan Text Embeddings V2** (`amazon.titan-embed-text-v2:0`)
- **NVIDIA Nemotron 3 Super** (`nvidia.nemotron-super-3-120b`) — confirm the
  exact model ID shown in the console for your region. If it is not available in
  your region, override the generation model with `BEDROCK_MODEL_ID` (for
  example `anthropic.claude-3-haiku-20240307-v1:0`).

See the [Bedrock model access guide](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html).
Model access can take a few minutes to activate.

## 2. Configure AWS credentials

```bash
aws configure          # or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_SESSION_TOKEN
export AWS_REGION=us-east-1
```

The credentials must allow `bedrock:InvokeModel` and `bedrock:Converse`.

## 3. Install dependencies

```bash
cd amazon-bedrock-nvidia-nemotron-poc
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> This installs **NeMo Guardrails** (`nemoguardrails`) and `langchain-aws`,
> which provide the guardrail engine on top of Amazon Bedrock. If NeMo
> Guardrails cannot initialize in your environment, the app automatically falls
> back to the equivalent rails in `guardrails.py`; the active engine is shown in
> the sidebar.

## 4. (Optional) Configure the app

Override any defaults with environment variables:

```bash
export BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0   # a different generation model
export RAG_TOP_K=6                                                  # retrieve more passages
```

## 5. Run the app

```bash
streamlit run app.py
```

Open the printed URL (default http://localhost:8501). On the first question the
app embeds the local knowledge base once (a few seconds) and caches it.

Try:
- "What is the CTR filing threshold under the BSA?"
- "When must a SAR be filed?"
- Include a fake SSN like `123-45-6789` to see the PII guardrail mask it.
- Ask something off-topic (e.g. "What's a good pasta recipe?") to see the topic
  guardrail decline.

## 6. Extend the knowledge base (optional)

Add lines to `knowledge_base.jsonl`. Each record is one JSON object:

```json
{"id": "my_001", "domain": "banking", "citation": "12 CFR 100.1", "text": "..."}
```

Restart the app (or clear the Streamlit resource cache) to re-index.

## 7. Clean up

This POC provisions no AWS resources — it only calls Amazon Bedrock on demand.
To clean up:

- Stop the Streamlit process (Ctrl+C).
- Deactivate/remove the virtual environment: `deactivate && rm -rf .venv`.
- Optionally disable the Bedrock model access you enabled in step 1.

There are no persistent resources (no S3 buckets, endpoints, or vector stores)
to delete, so there are no ongoing charges beyond per-request Bedrock usage
while the app is running.
