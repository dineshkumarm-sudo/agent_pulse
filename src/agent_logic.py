from openai import OpenAI
import streamlit as st
import pandas as pd

def resolve_nvidia_model(client: OpenAI) -> str:
    """Probes candidate model endpoints to resolve an active model string."""
    # List of universal hosted model endpoints on NVIDIA API Catalog
    candidate_models = [
        "nvidia/llama-3.1-nemotron-70b-instruct",
        "meta/llama-3.3-70b-instruct",
        "deepseek-ai/deepseek-r1",
        "mistralai/mistral-large-2-instruct",
        "meta/llama3-70b-instruct"
    ]

    for model_name in candidate_models:
        try:
            # Send a minimal probe call to check model status
            client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1
            )
            return model_name
        except Exception:
            continue

    # Fallback to standard catalog string if probe encounters rate limiting
    return "nvidia/llama-3.1-nemotron-70b-instruct"


def ask_nvidia_agent(user_query: str, df_data: pd.DataFrame) -> str:
    """Uses resolved NVIDIA model to answer questions based on sheet productivity data."""
    if df_data.empty:
        return "No data is currently loaded to perform analysis."

    records_summary = df_data[["Date", "Week", "Month", "Year", "Productivity (%)"]].to_string(index=False) if "Productivity (%)" in df_data.columns else df_data.to_string(index=False)

    try:
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=st.secrets["nvidia"]["api_key"]
        )

        active_model = resolve_nvidia_model(client)

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
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=st.secrets["nvidia"]["api_key"]
        )

        active_model = resolve_nvidia_model(client)

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
