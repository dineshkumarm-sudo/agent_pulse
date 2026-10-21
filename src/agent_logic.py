
import streamlit as st
import pandas as pd
import requests

# ============================================================
# NVIDIA API CONFIGURATION
# ============================================================

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "z-ai/glm-5.3-flash"


# ============================================================
# COMMON NVIDIA API FUNCTION
# ============================================================

def call_nvidia_api(messages: list) -> str:
    """Send a request to NVIDIA and return the AI response."""

    # Get API key from Streamlit Secrets
    try:
        api_key = st.secrets["nvidia"]["api_key"].strip()
    except Exception:
        return (
            "❌ NVIDIA API key not found.\n\n"
            "Please check Streamlit Cloud → Settings → Secrets."
        )

    if not api_key:
        return "❌ NVIDIA API key is empty. Check Streamlit Secrets."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "model": NVIDIA_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 2048,
        "stream": False,
    }

    try:
        response = requests.post(
            NVIDIA_API_URL,
            headers=headers,
            json=payload,
            timeout=90,
        )

        # Successful request
        if response.status_code == 200:
            data = response.json()
            choices = data.get("choices", [])

            if not choices:
                return (
                    "❌ NVIDIA returned a response without any choices.\n\n"
                    f"Response: {str(data)[:1000]}"
                )

            content = choices[0].get("message", {}).get("content")

            if not content or not str(content).strip():
                return (
                    "⚠️ NVIDIA returned an empty answer. "
                    "Please try asking your question again."
                )

            return (
                f"**AI Model:** `{NVIDIA_MODEL}`\n\n"
                f"{content}"
            )

        # Return clear error details
        error_details = response.text[:2000]

        if response.status_code == 400:
            return (
                f"❌ NVIDIA rejected the request (HTTP 400).\n\n"
                f"Model: `{NVIDIA_MODEL}`\n\n"
                f"Details: {error_details}"
            )

        if response.status_code == 401:
            return (
                "❌ NVIDIA rejected the API key (HTTP 401).\n\n"
                "Check that your NVIDIA API key is correct and active."
            )

        if response.status_code == 403:
            return (
                "❌ NVIDIA denied access (HTTP 403).\n\n"
                "Your account may not have permission to use this endpoint "
                "or model.\n\n"
                f"Details: {error_details}"
            )

        if response.status_code == 404:
            return (
                "❌ NVIDIA returned HTTP 404.\n\n"
                f"Configured model: `{NVIDIA_MODEL}`\n"
                f"API endpoint: `{NVIDIA_API_URL}`\n\n"
                "NVIDIA could not find the requested resource. "
                "Check model availability and account access.\n\n"
                f"Details returned by NVIDIA: {error_details}\n\n"
                "If this message mentions a different model, such as "
                "DeepSeek, the deployed app may be running older code "
                "or another file may be making the request."
            )

        if response.status_code == 429:
            return (
                "⚠️ NVIDIA rate limit or usage limit reached (HTTP 429).\n\n"
                "Wait a little before trying again.\n\n"
                f"Details: {error_details}"
            )

        return (
            f"❌ NVIDIA API Error: HTTP {response.status_code}\n\n"
            f"Model: `{NVIDIA_MODEL}`\n\n"
            f"Details: {error_details}"
        )

    except requests.exceptions.Timeout:
        return (
            "❌ NVIDIA did not respond within 90 seconds.\n\n"
            "Please try again. If this keeps happening, check NVIDIA "
            "API availability and your account access."
        )

    except requests.exceptions.RequestException as exc:
        return (
            "❌ Could not connect to NVIDIA.\n\n"
            f"Network details: {str(exc)}"
        )

    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return (
            "❌ Could not process NVIDIA's response.\n\n"
            f"Details: {str(exc)}"
        )


# ============================================================
# AI PRODUCTIVITY ANALYSIS
# ============================================================

def ask_nvidia_agent(
    user_query: str,
    df_data: pd.DataFrame,
) -> str:
    """Answer questions using the available productivity dataset."""

    if df_data is None or df_data.empty:
        return (
            "No data is currently loaded. "
            "Please load your Google Sheets data first."
        )

    if not user_query or not user_query.strip():
        return "Please enter a question."

    # Convert the data to text for the AI
    records_summary = df_data.to_string(
        index=False,
        max_rows=200,
        max_cols=30,
    )

    # Keep the request within a reasonable size
    records_summary = records_summary[:20000]

    prompt = f"""
You are Nexus AI, an Operations and Productivity Intelligence Assistant.

Your job is to help a program manager understand team productivity,
project performance, trends, risks, and operational issues.

DATASET:
{records_summary}

USER QUESTION:
{user_query}

INSTRUCTIONS:
1. Answer the user's exact question first.
2. Use only the supplied dataset for dataset-specific facts.
3. When comparing weeks or months, calculate average productivity
   from the relevant records when possible.
4. Explain numerical differences clearly, including percentage-point
   differences when comparing productivity percentages.
5. If a requested period is missing, state that clearly.
6. Do not invent values, employee details, or project statuses.
7. Use short headings and bullet points where helpful.
8. Keep the response professional and suitable for a manager.
9. If the data does not support a conclusion, explain why.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are Nexus AI. Be accurate, analytical, concise, "
                "and transparent about limitations in the supplied data."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    return call_nvidia_api(messages)


# ============================================================
# COO WEEKLY REPORT GENERATION
# ============================================================

def collate_coo_report(
    tl_updates_raw: str,
    project_metrics_summary: str,
) -> str:
    """Generate a weekly operations report for the COO."""

    if not tl_updates_raw.strip() and not project_metrics_summary.strip():
        return (
            "No team-lead updates or project metrics were provided. "
            "Please provide at least one input."
        )

    prompt = f"""
You are Nexus AI, an Executive Assistant supporting an eCommerce
Program Manager.

Prepare a professional weekly operations report for the COO using
the information provided below.

PROJECT METRICS:
{project_metrics_summary}

TEAM LEAD UPDATES:
{tl_updates_raw}

REPORT STRUCTURE:

## 1. Executive Overview & Key Accomplishments
Summarize the most important accomplishments, progress, and outcomes.

## 2. Project Productivity & Operational Health
Summarize reported productivity, delivery status, volumes, and
operational performance. Preserve the original figures.

## 3. Key Blockers & Focus Areas for Next Week
Identify reported blockers, pending activities, risks, and next steps.

RULES:
- Use a professional, concise, executive-ready tone.
- Use clear Markdown headings and bullet points.
- Do not invent figures, dates, commitments, or project statuses.
- Distinguish completed work from pending work.
- Include owners or deadlines only when supplied.
- If information is missing, state that it was not provided.
- Return the report ready for the manager to review and edit.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are Nexus AI, an executive reporting assistant. "
                "Accuracy is more important than filling every section."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    return call_nvidia_api(messages)
