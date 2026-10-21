import streamlit as st
import pandas as pd
import requests

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Prioritize native NVIDIA-hosted models first for maximum stability
NVIDIA_MODELS = [
    "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "nvidia/llama-3.1-nemotron-70b-instruct",
    "meta/llama-3.3-70b-instruct",
    "deepseek-ai/deepseek-r1"
]

def call_nvidia_api(messages: list) -> str:
    """Sends a direct POST request to NVIDIA's API endpoint with fast failover."""
    api_key = st.secrets["nvidia"]["api_key"].strip()
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    last_error = None
    for model_name in NVIDIA_MODELS:
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1024
        }
        
        try:
            # Enforce 12-second timeout per model so hanging third-party models fail fast
            response = requests.post(NVIDIA_API_URL, headers=headers, json=payload, timeout=12)
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return f"*(Active Model: `{model_name}`)*\n\n" + content
            else:
                last_error = f"Status {response.status_code} ({model_name}): {response.text}"
        except requests.exceptions.Timeout:
            last_error = f"Request timed out on {model_name}."
            continue
        except Exception as e:
            last_error = str(e)
            continue
            
    return f"❌ **NVIDIA API Error Details:** {last_error}"


def ask_nvidia_agent(user_query: str, df_data: pd.DataFrame) -> str:
    """Uses NVIDIA API to answer productivity queries from Google Sheet data."""
    if df_data.empty:
        return "No data is currently loaded to perform analysis."

    records_summary = df_data[["Date", "Week", "Month", "Year", "Productivity (%)"]].to_string(index=False) if "Productivity (%)" in df_data.columns else df_data.to_string(index=False)

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

    messages = [{"role": "user", "content": prompt}]
    return call_nvidia_api(messages)


def collate_coo_report(tl_updates_raw: str, project_metrics_summary: str) -> str:
    """Uses NVIDIA API to collate raw TL updates into a structured email for the COO."""
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

    messages = [{"role": "user", "content": prompt}]
    return call_nvidia_api(messages)
