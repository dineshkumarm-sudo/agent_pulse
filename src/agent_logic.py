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
