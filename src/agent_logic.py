
import streamlit as st
import pandas as pd
import requests

# NVIDIA API settings
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Start with one model verified in NVIDIA's official catalog.
NVIDIA_MODEL = "z-ai/glm-5.3-flash"


def call_nvidia_api(messages: list) -> str:
    """Send a request to NVIDIA and return the AI response."""

    # Read the API key from Streamlit Secrets
    try:
        api_key = st.secrets["nvidia"]["api_key"].strip()
    except (KeyError, AttributeError, TypeError):
        return (
            "NVIDIA API key is missing. "
            "Please check your Streamlit Secrets settings."
        )

    if not api_key:
        return "NVIDIA API key is empty. Please check Streamlit Secrets."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "model": NVIDIA_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1024,
        "stream": False,
    }

    try:
        response = requests.post(
            NVIDIA_API_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )

        # Successful API request
        if response.status_code == 200:
            data = response.json()
            content = data["choices"][0]["message"]["content"]

            if not content:
                return "NVIDIA returned an empty response. Please try again."

            return f"**AI Model:** `{NVIDIA_MODEL}`\n\n{content}"

        # Explain common API errors
        if response.status_code == 401:
            return (
                "NVIDIA rejected the API key (401 Unauthorized). "
                "Check that your NVIDIA API key is correct."
            )

        if response.status_code == 403:
            return (
                "Access denied (403 Forbidden). "
                "Check your NVIDIA account permissions and model access."
            )

        if response.status_code == 404:
            return (
                f"NVIDIA returned 404 for model `{NVIDIA_MODEL}`.\n\n"
                "The model or endpoint may not be available to your account. "
                "Check the model in NVIDIA's official catalog and confirm "
                "that its API endpoint is available."
            )

        if response.status_code == 429:
            return (
                "NVIDIA rate limit reached (429). "
                "Please wait a little and try again."
            )

        return (
            f"NVIDIA API Error: HTTP {response.status_code}\n\n"
            f"Details: {response.text[:1500]}"
        )

    except requests.exceptions.Timeout:
        return (
            "The NVIDIA API request timed out. "
            "Please try again in a moment."
        )

    except requests.exceptions.RequestException as exc:
        return f"Network error while contacting NVIDIA: {exc}"

    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return f"Could not read NVIDIA's response: {exc}"


def ask_nvidia_agent(user_query: str, df_data: pd.DataFrame) -> str:
    """Answer productivity questions using Google Sheets data."""

    if df_data is None or df_data.empty:
        return "No data is currently loaded to perform analysis."

    # Use the relevant columns when they are available
    preferred_columns = [
        "Date",
        "Week",
        "Month",
        "Year",
        "Productivity (%)",
    ]

    if "Productivity (%)" in df_data.columns:
        available_columns = [
            column
            for column in preferred_columns
            if column in df_data.columns
        ]
        records_summary = df_data[available_columns].to_string(
            index=False
        )
    else:
        records_summary = df_data.to_string(index=False)

    prompt = f"""
You are Nexus AI, an Operations and Productivity Intelligence Assistant.

Answer the user's question using the provided dataset.

DATASET:
{records_summary[:12000]}

USER QUESTION:
{user_query}

INSTRUCTIONS:
- Give a direct, concise, executive-ready answer.
- Use bullet points where helpful.
- When comparing weeks or months, calculate average productivity
  and numerical differences when the available data supports it.
- Do not invent figures or claim calculations that you have not made.
- Clearly mention when the dataset does not contain enough information.
"""

    messages = [
        {
            "role": "user",
            "content": prompt,
        }
    ]

    return call_nvidia_api(messages)


def collate_coo_report(
    tl_updates_raw: str,
    project_metrics_summary: str,
) -> str:
    """Generate an executive-ready weekly report for the COO."""

    prompt = f"""
You are Nexus AI, an Executive Assistant.

Draft a professional weekly summary email for the COO using
the project metrics and team lead updates below.

PROJECT METRICS:
{project_metrics_summary}

TEAM LEAD UPDATES:
{tl_updates_raw}

REQUIREMENTS:
- Use a professional, concise, executive-ready tone.
- Include these three sections:
  1. Executive Overview & Key Accomplishments
  2. Project Productivity & Operational Health
  3. Key Blockers & Focus Areas for Next Week
- Use clear Markdown headings and bullet points.
- Preserve reported figures, dates, and project statuses.
- Do not invent missing information.
- Clearly highlight blockers and next steps when stated in the inputs.
- Return the report content ready for review and editing.
"""

    messages = [
        {
            "role": "user",
            "content": prompt,
        }
    ]

    return call_nvidia_api(messages)
