
import streamlit as st
import pandas as pd
import requests

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Model selected for initial API testing
NVIDIA_MODELS = [
    "z-ai/glm-5.3-flash"
]


def call_nvidia_api(messages: list) -> str:
    """Send a request to NVIDIA's hosted chat completion API."""

    try:
        api_key = st.secrets["nvidia"]["api_key"].strip()
    except (KeyError, AttributeError):
        return (
            "❌ NVIDIA API key is missing. "
            "Check Streamlit Secrets configuration."
        )

    if not api_key:
        return "❌ NVIDIA API key is empty. Check Streamlit Secrets."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    last_error = None

    for model_name in NVIDIA_MODELS:
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1024,
        }

        try:
            response = requests.post(
                NVIDIA_API_URL,
                headers=headers,
                json=payload,
                timeout=60,
            )

            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]

                if not content:
                    return "⚠️ NVIDIA returned an empty response."

                return f"*(Active Model: `{model_name}`)*\n\n{content}"

            last_error = (
                f"HTTP {response.status_code} | "
                f"Model: {model_name} | "
                f"Response: {response.text[:1000]}"
            )

            # Do not retry identical requests for these errors.
            if response.status_code in (400, 401, 403, 404):
                break

        except requests.exceptions.Timeout:
            last_error = (
                f"Request timed out while calling model {model_name}. "
                "Please try again."
            )
        except requests.exceptions.RequestException as exc:
            last_error = f"Network error: {str(exc)}"
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            last_error = f"Unexpected API response: {str(exc)}"

    return (
        "❌ **NVIDIA API Error Details**\n\n"
        f"{last_error or 'Unknown error. Please try again.'}"
    )


def ask_nvidia_agent(user_query: str, df_data: pd.DataFrame) -> str:
    """Answer productivity questions using Google Sheet data."""

    if df_data is None or df_data.empty:
        return "No data is currently loaded to perform analysis."

    required_columns = [
        "Date",
        "Week",
        "Month",
        "Year",
        "Productivity (%)",
    ]

    if "Productivity (%)" in df_data.columns:
        available_columns = [
            column
            for column in required_columns
            if column in df_data.columns
        ]
        records_summary = df_data[available_columns].to_string(
            index=False
        )
    else:
        records_summary = df_data.to_string(index=False)

    prompt = f"""
You are Nexus AI, an Operations & Productivity Intelligence Assistant.

Answer the user's question clearly and concisely using the
provided Google Sheet dataset.

=== DATASET CONTEXT ===
{records_summary[:4000]}

=== USER QUESTION ===
{user_query}

=== INSTRUCTIONS ===
- Provide a direct, executive-ready answer.
- When comparing weeks or months, calculate and explain
  numerical differences in average productivity when possible.
- Do not invent figures that are absent from the data.
- Keep the output clean, brief, and bulleted.
"""

    messages = [
        {"role": "user", "content": prompt}
    ]

    return call_nvidia_api(messages)


def collate_coo_report(
    tl_updates_raw: str,
    project_metrics_summary: str,
) -> str:
    """Draft a structured weekly report email for the COO."""

    prompt = f"""
You are Nexus AI, an Executive Assistant.

Draft a professional, executive-ready weekly summary email
for the COO using the team lead updates and project metrics.

=== PROJECT METRICS SUMMARY ===
{project_metrics_summary}

=== RAW TEAM LEAD UPDATES ===
{tl_updates_raw}

=== INSTRUCTIONS ===
- Use a professional, concise, executive-ready tone.
- Include these three main sections:
  1. Executive Overview & Key Accomplishments
  2. Project Productivity & Operational Health
  3. Key Blockers & Focus Areas for Next Week
- Use clear Markdown headings and bullet points.
- Preserve all reported figures and project statuses.
- Do not invent missing information.
"""

    messages = [
        {"role": "user", "content": prompt}
    ]

    return call_nvidia_api(messages)
