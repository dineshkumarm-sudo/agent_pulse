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
                if pref in model_id.lower()
