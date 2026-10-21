from openai import OpenAI
import streamlit as st
import pandas as pd

# Active supported models on NVIDIA API Catalog
PRIMARY_MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"
FALLBACK_MODEL = "deepseek-ai/deepseek-r1"

def ask_nvidia_agent(user_query: str, df_data: pd.DataFrame) -> str:
    """Uses active NVIDIA hosted model to answer questions based on sheet productivity data."""
    if df_data.empty:
        return "No data is currently loaded to perform analysis."

    records_summary = df_data[["Date", "Week", "Month", "Year", "Productivity (%)"]].to_string(index=False) if "Productivity (%)" in df_data.columns else df_data.to_string(index=False)

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=st.secrets["nvidia"]["api_key"]
    )

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

    # Try Primary Model; fallback if endpoint changes
    for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            return response.choices[0].message.content
        except Exception as e:
            if "410" in str(e) or "404" in str(e):
                continue  # Try next model in list
            return f"❌ **NVIDIA API Error:** {type(e).__name__} - {str(e)}"

    return "❌ All configured NVIDIA AI endpoints returned deprecation/availability errors."


def collate_coo_report(tl_updates_raw: str, project_metrics_summary: str) -> str:
    """Uses NVIDIA API to collate raw TL updates into a structured email for the COO."""
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=st.secrets["nvidia"]["api_key"]
    )

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

    for model_name in [PRIMARY_MODEL, FALLBACK_MODEL]:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            if "410" in str(e) or "404" in str(e):
                continue
            return f"❌ **NVIDIA API Error:** {type(e).__name__} - {str(e)}"

    return "❌ All configured NVIDIA AI endpoints returned deprecation/availability errors."
