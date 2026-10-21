import streamlit as st
import pandas as pd
from src.gsheets_client import fetch_daily_tracker_data, analyze_project_productivity
from src.agent_logic import collate_coo_report

st.set_page_config(page_title="Nexus AI", layout="wide")

# Map Project Names to FULL Google Sheet URLs
PROJECT_SHEETS = {
    "Superbreakers": "https://docs.google.com/spreadsheets/d/15hpOWzz9oK6idTrKq0HEaVlwAf-C-5yy_f2fC5Mh/edit"
}

st.title("Tracker Operations")

# --- 1. CLEAN PROJECT SELECTOR ---
selected_project = st.selectbox(
    "Select Active Project",
    options=list(PROJECT_SHEETS.keys()),
    index=0
)
sheet_url = PROJECT_SHEETS[selected_project]

# Fetch data using the full URL mapped to the selected project name
try:
    df_raw = fetch_daily_tracker_data(sheet_url)
except Exception as e:
    st.error(f"Error connecting to Google Sheet for **{selected_project}**. Please verify that your service account email (`agent-pulse@...`) has Viewer/Editor access to the sheet.")
    st.stop()

# --- 2. MONTH, YEAR, AND WEEK FILTERS ---
st.subheader("Filter Data")
filter_col1, filter_col2, filter_col3 = st.columns(3)

years = ["All"] + sorted([str(y) for y in df_raw["Year"].dropna().unique()]) if "Year" in df_raw.columns else ["All"]
months = ["All"] + sorted([str(m) for m in df_raw["Month"].dropna().unique()]) if "Month" in df_raw.columns else ["All"]
weeks = ["All"] + sorted([str(w) for w in df_raw["Week"].dropna().unique()]) if "Week" in df_raw.columns else ["All"]

with filter_col1:
    selected_year = st.selectbox("Year", years)
with filter_col2:
    selected_month = st.selectbox("Month", months)
with filter_col3:
    selected_week = st.selectbox("Week", weeks)

# Apply dynamic filters
df_filtered = df_raw.copy()
if "Year" in df_filtered.columns and selected_year != "All":
    df_filtered = df_filtered[df_filtered["Year"].astype(str) == selected_year]
if "Month" in df_filtered.columns and selected_month != "All":
    df_filtered = df_filtered[df_filtered["Month"].astype(str) == selected_month]
if "Week" in df_filtered.columns and selected_week != "All":
    df_filtered = df_filtered[df_filtered["Week"].astype(str) == selected_week]

# --- 3. EXECUTION BUTTON & ANALYSIS ---
if st.button("⚡ Execute Tracker Analysis", type="primary"):
    analysis_results = analyze_project_productivity(df_filtered)
    st.session_state["analysis_results"] = analysis_results
    st.success(f"Analysis completed for **{selected_project}**!")

# --- 4. RIGHT SIDE AUDIT PANEL (WITH FIXED HTML RENDERING) ---
if "analysis_results" in st.session_state:
    results = st.session_state["analysis_results"]
    daily_alerts = results.get("daily_alerts", pd.DataFrame())

    audit_html = "<div class='audit-container'>"
    if not daily_alerts.empty:
        for idx, row in daily_alerts.iterrows():
            audit_html += f"""
            <div style="margin-bottom: 12px; padding: 10px; border-left: 4px solid #ff4b4b; background-color: #1a1c23; border-radius: 4px;">
                <div style="font-weight: bold; color: #ff4b4b;">Low Productivity Flag</div>
                <div style="font-size: 0.9em; margin-top: 4px;">User/Date: {row.get('Name', 'N/A')} - {row.get('Date', 'N/A')}</div>
                <div style="font-size: 0.85em; color: #a0a0a0;">Score: {row.get('Productivity (%)', 'N/A')}%</div>
            </div>
            """
    else:
        audit_html += "<div style='color: #4CAF50;'>All team logs met productivity thresholds.</div>"
    audit_html += "</div>"

    st.sidebar.subheader("Google Sheets Audit")
    st.sidebar.markdown(audit_html, unsafe_allow_html=True)
