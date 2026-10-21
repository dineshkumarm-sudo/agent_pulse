from openai import OpenAI
import streamlit as st

def collate_coo_report(tl_updates_raw: str, project_metrics_summary: str) -> str:
    """Uses NVIDIA API to collate raw TL updates into a structured email for the COO."""
    
    # Initialize OpenAI client with NVIDIA's Base URL and API key
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

    # Call NVIDIA-hosted Llama model using standard completion interface
    response = client.chat.completions.create(
        model="meta/llama-3.1-70b-instruct",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    return response.choices[0].message.content