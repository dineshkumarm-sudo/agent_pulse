from openai import OpenAI
import streamlit as st
import pandas as pd

def ask_nvidia_agent(user_query: str, df_data: pd.DataFrame) -> str:
    """Uses NVIDIA Llama model to answer questions based on sheet productivity data."""
    if df_data.empty:
        return "No data is currently loaded to perform analysis."

    # Convert DataFrame summary into clean context string for the LLM
    records_summary = df_data[["Date", "Week", "Month", "Year", "Productivity (%)"]].to_string(index=False) if "Productivity (%)" in df_data.columns else df_data.to_string(index=False)

    try:
        # Initialize OpenAI client pointing to NVIDIA API endpoint
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

        # Using updated NVIDIA-hosted Llama 3 model string
        response = client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"❌ **NVIDIA API Error:** {type(e).__name__} - {str(e)}"


def collate_coo_report(tl_updates_raw: str, project_metrics_summary: str) -> str:
    """Uses NVIDIA API to collate raw TL updates into a structured email for the COO."""
    try:
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

        response = client.chat.completions.create(
            model="meta/llama-3.1-70b-instruct",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )

        return response.choices[0].message.content
    except Exception as e:
        return f"❌ **NVIDIA API Error:** {type(e).__name__} - {str(e)}"
