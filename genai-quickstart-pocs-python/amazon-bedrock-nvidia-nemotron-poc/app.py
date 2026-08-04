"""
Streamlit frontend for the Amazon Bedrock NVIDIA Nemotron POC.

Flow: NeMo Guardrails (input rails -> Bedrock RAG -> output rails), with a
plain-Python rail fallback. All business logic lives in compliance_rag.py,
guardrails.py, and compliance_guardrails.py; this file only handles the UI.

Run:  streamlit run app.py
"""

import streamlit as st

from compliance_guardrails import ComplianceGuardrails

st.set_page_config(page_title="Bedrock Nemotron Compliance Assistant", page_icon="⚖️", layout="wide")


@st.cache_resource(show_spinner="Initializing guardrails, knowledge base, and index...")
def get_assistant() -> ComplianceGuardrails:
    return ComplianceGuardrails()


assistant = get_assistant()

st.title("⚖️ Amazon Bedrock NVIDIA Nemotron Compliance Assistant")
st.caption(
    "A retrieval-augmented compliance assistant on the NVIDIA stack: NVIDIA "
    "Nemotron 3 Super on Amazon Bedrock, guarded by NeMo Guardrails. Educational "
    "sample — not legal or compliance advice."
)

with st.sidebar:
    st.header("About")
    st.markdown(
        "- **Guardrails:** NeMo Guardrails (jailbreak, PII, topic, fact-check, "
        "citation rails)\n"
        "- **Retrieval:** Amazon Titan Text Embeddings V2 over a local regulatory "
        "knowledge base\n"
        "- **Generation:** NVIDIA Nemotron 3 Super on Amazon Bedrock\n\n"
        "Ask about SEC, FINRA, OCC, FinCEN, or CFPB rules."
    )
    st.info(f"Guardrail engine: **{assistant.engine}**")
    st.divider()
    st.caption("Sample questions")
    for q in [
        "What is the CTR filing threshold under the BSA?",
        "When must a Suspicious Activity Report be filed?",
        "What are the Form 10-K filing deadlines?",
    ]:
        st.markdown(f"- {q}")

question = st.text_input(
    "Ask a compliance question",
    placeholder="e.g. What are the capital adequacy requirements for national banks?",
)

if st.button("Ask", type="primary") and question:
    with st.spinner("Applying guardrails, retrieving context, and generating answer..."):
        res = assistant.run(question)

    if res["blocked"]:
        st.warning(res["answer"])
    else:
        st.subheader("Answer")
        st.markdown(res["answer"])

        cols = st.columns(2)
        cols[0].metric("Grounded in context", "Yes" if res["grounded"] else "Review")
        cols[1].metric("Citation present", "Yes" if res["cited"] else "No")
        if res["rails_fired"]:
            st.info(f"Guardrails fired: {', '.join(res['rails_fired'])}")

        if res["sources"]:
            st.subheader("Retrieved sources")
            for s in res["sources"]:
                with st.expander(f"{s['citation']}  ·  {s['domain']}"):
                    st.write(s["text"])
