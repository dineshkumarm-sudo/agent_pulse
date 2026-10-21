import requests
import streamlit as st

def send_teams_notification(message: str) -> bool:
    """Sends a notification card/text to Teams via Webhook."""
    webhook_url = st.secrets["teams"]["webhook_url"]
    payload = {
        "text": message
    }
    response = requests.post(webhook_url, json=payload)
    return response.status_code == 200

def ping_team_leads_for_report(tl_list: list[str]) -> bool:
    """Automated Monday morning ping to TLs requesting weekly updates."""
    mentions = ", ".join(tl_list)
    msg = (
        f"📢 **Nexus AI - Weekly Report Request**\n\n"
        f"Hi {mentions},\n"
        f"Please reply with your weekly highlights, completed deliverables, and any blockers "
        f"for the upcoming COO Weekly Executive Summary."
    )
    return send_teams_notification(msg)