from openai import OpenAI
import streamlit as st
import pandas as pd

def get_working_nvidia_client_and_model():
    """Dynamically resolves a valid active model from NVIDIA API catalog for the current key."""
    api_key = st.secrets["nvidia"]["api_key"]
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key
    )

    # 1. Try dynamic listing from your actual account catalog
    try:
        models_page = client.models.list()
        for m in models_page.data:
            m_id = m.id.lower()
            if any(k in m_id for k in ["llama", "nemotron", "deepseek", "mistral"]) and "embed" not in m_id:
                return client, m.id
    except Exception:
        pass

    # 2. Candidate models list across NVIDIA catalog formats
    fallback_models = [
        "meta/llama3-70b-instruct",
        "deepseek-ai/deepseek-r1",
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "mistralai/mistral-large-2-instruct"
    ]

    for model_candidate in fallback_models:
        try:
            # Test ping with minimum tokens
            client.chat.completions.create(
                model=model_candidate,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1
            )
            return client, model_candidate
        except Exception:
            continue

    # Default fallback
    return client, "meta/llama3-70b-instruct"


def ask_nvidia_agent(user_query: str, df_data: pd.DataFrame) -> str:
    """Uses available NVIDIA model to answer questions based on sheet productivity data."""
    if df_data.empty:
        return "No data is currently loaded to perform analysis."

    records_summary = df_data[["Date", "Week", "Month", "Year", "Productivity (%)"]].to_string(index=False) if "Productivity (%)" in df_data.columns else df_data.to_string(index=False)

    try:
        client, active_model = get_working_nvidia_client_and_model()

        prompt = f"""
        You are Nexus AI, an Operations & Productivity Intelligence Assistant.
        Answer the user's question clearly and concisely using the provided Google Sheet dataset.

        === DATASET CONTEXT ===
        {records_summary[:4000]}

        === USER QUESTION ===
        {user_query}

        === INSTRUCTIONS ===
        - Provide a direct, executive-ready answer.
        - If comparing weeks or months, highlight numerical differences in average productivity.
        - Keep output clean, brief, and bulleted.
        """

        response = client.chat.completions.create(
            model=active_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        return f"*(Active Model: `{active_model}`)*\n\n" + response.choices[0].message.content

    except Exception as e:
        return f"❌ **NVIDIA API Error:** {type(e).__name__} - {str(e)}"


def collate_coo_report(tl_updates_raw: str, project_metrics_summary: str) -> str:
    """Uses NVIDIA API to collate raw TL updates into a structured email for the COO."""
    try:
        client, active_model = get_working_nvidia_client_and_model()

        prompt = f"""
        You are Nexus AI, an Executive Assistant. Draft a professional, executive-ready weekly summary email for the COO based on team lead inputs and project metrics.

        === PROJECT METRICS SUMMARY ===
        {project_metrics_summary}

        === RAW TEAM LEAD UPDATES ===
        {tl_updates_raw}

        === INSTRUCTIONS ===
        - Keep tone professional, concise, and structured.
        - Include 3 main sections:
          1. Executive Overview & Key Accomplishments
          2. Project Productivity & Operational Health
          3. Key Blockers & Focus Areas for Next Week
        - Format cleanly in Markdown with bullet points.
        """

        response = client.chat.completions.create(
            model=active_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"❌ **NVIDIA API Error:** {type(e).__name__} - {str(e)}"
