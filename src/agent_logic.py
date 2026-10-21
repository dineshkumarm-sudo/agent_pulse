from openai import OpenAI
import streamlit as st
import pandas as pd

def ask_nvidia_agent(user_query: str, df_data: pd.DataFrame) -> str:
    """Uses NVIDIA Llama model to answer questions based on sheet productivity data."""
    if df_data.empty:
        return "No data is currently loaded to perform analysis."

    # Convert DataFrame summary into clean context string for the LLM
    records_summary = df_data[["Date", "Week", "Month", "Year", "Productivity (%)"]].to_string(index=False) if "Productivity (%)" in df_data.columns else df_data.to_string(index=False)

    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=st.secrets["nvidia"]["api_key"]
    )

    prompt = f"""
    You are Nexus AI, an Operations & Productivity Intelligence Assistant.
    Answer the user's question clearly and concisely using the provided Google Sheet dataset.

    === DATASET CONTEXT ===
    {records_summary[:4000]}  # Truncated safely for context window

    === USER QUESTION ===
    {user_query}

    === INSTRUCTIONS ===
    - Provide a direct, executive-ready answer.
    - If comparing weeks
