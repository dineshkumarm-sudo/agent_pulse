from openai import OpenAI
import streamlit as st
import pandas as pd
import requests

def get_active_nvidia_model(client: OpenAI) -> str:
    """Dynamically fetches active models from NVIDIA API to avoid hardcoded deprecation errors."""
    try:
        # Fetch the live list of models directly from NVIDIA
        models = client.models.list()
        available_ids = [m.id for m in models.data]
        
        # Priority list of preferred general-purpose chat/instruct models
        preferred_substrings = [
            "llama",
            "nemotron",
            "deepseek",
            "mistral",
            "qwen"
        ]
        
        # Search for the first matching preferred model ID
        for pref in preferred_substrings:
            for model_id in available_ids:
                if pref in model_id.lower() and "embed" not in model_id.lower() and "rerank" not in model_id.lower():
                    return model_id
                    
        # Fallback to the first available non-embedding model ID
        for model_id in available_ids:
            if "embed" not in model_id.lower() and "rerank" not in model_id.lower():
                return model_id

    except Exception:
        pass
    
    # Static fallback if model listing is restricted
    return "nvidia/nemotron-3.5-super-vl-120b-a12b"


def ask_nvidia_agent(user_query: str, df_data: pd.DataFrame) -> str:
    """Uses active NVIDIA model to answer questions based on sheet productivity data."""
    if df_data.empty:
        return "No data is currently loaded to perform analysis."

    records_summary = df_data[["Date", "Week", "Month", "Year", "Productivity (%)"]].to_string(index=False) if "Productivity (%)" in df_data.columns else df_data.to_string(index=False)

    try:
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=st.secrets["nvidia"]["api_key"]
        )

        active_model = get_active_nvidia_model(client)

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

        return f"*(Model used: `{active_model}`)*\n\n" + response.choices[0].message.content

    except Exception as e:
        return f"❌ **NVIDIA API Error:** {type(e).__name__} - {str(e)}"


def collate_coo_report(tl_updates_raw: str, project_metrics_summary: str) -> str:
    """Uses NVIDIA API to collate raw TL updates into a structured email for the COO."""
    try:
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=st.secrets["nvidia"]["api_key"]
        )

        active_model = get_active_nvidia_model(client)

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
