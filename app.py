import streamlit as st
import pandas as pd
import re
import datetime
import traceback
from src.gsheets_client import get_gsheet_client, analyze_project_productivity
from src.agent_logic import ask_nvidia_agent, collate_coo_report

st.set_page_config(page_title="Nexus AI", layout="wide")

PROJECT_SHEETS = {
    "Superbreakers": "https://docs.google.com/spreadsheets/d/15hpOWzz9oK6idTrKq0HEaVIwAf-C-5yy_f2fC5Mhtfc/edit?gid=547444785#gid=547444785"
}

st.title("⚡ Nexus AI — Tracker Operations")

# --- 1. PROJECT SELECTOR ---
selected_project = st.selectbox(
    "Select Active Project",
    options=list(PROJECT_SHEETS.keys()),
    index=0
)
sheet_url = PROJECT_SHEETS[selected_project]

def fetch_sheet_safely(url: str, sheet_name: str = "Daily_Tracker") -> pd.DataFrame:
    client = get_gsheet_client()
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    if match:
        spreadsheet_id = match.group(1)
        sheet = client.open_by_key(spreadsheet_id)
    else:
        sheet = client.open_by_url(url)
    
    try:
        worksheet = sheet.worksheet(sheet_name)
    except Exception:
        worksheet = sheet.get_worksheet(0)

    records = worksheet.get_all_records()
    return pd.DataFrame(records)

# --- 2. LOAD DATA ---
df_raw = pd.DataFrame()
try:
    df_raw = fetch_sheet_safely(sheet_url)
    st.success(f"Connected to **{selected_project}**")
except Exception as e:
    st.error(f"❌ Google API Error Details: {type(e).__name__} - {str(e)}")

# --- 3. FILTER SECTION ---
st.subheader("Filter Data")
filter_col1, filter_col2, filter_col3 = st.columns(3)

current_year = datetime.datetime.now().year
default_years = [str(y) for y in range(2025, current_year + 1)]

if "Year" in df_raw.columns and not df_raw.empty:
    sheet_years = [str(y) for y in df_raw["Year"].dropna().unique() if str(y).strip() != ""]
    combined_years = sorted(list(set(default_years + sheet_years)))
else:
    combined_years = default_years

years = ["All"] + combined_years
months = ["All"] + sorted([str(m) for m in df_raw["Month"].dropna().unique()]) if "Month" in df_raw.columns and not df_raw.empty else ["All"]
weeks = ["All"] + sorted([str(w) for w in df_raw["Week"].dropna().unique()]) if "Week" in df_raw.columns and not df_raw.empty else ["All"]

with filter_col1:
    selected_year = st.selectbox("Year", years)
with filter_col2:
    selected_month = st.selectbox("Month", months)
with filter_col3:
    selected_week = st.selectbox("Week", weeks)

# Apply dynamic filters
df_filtered = df_raw.copy()
if not df_filtered.empty:
    if "Year" in df_filtered.columns and selected_year != "All":
        df_filtered = df_filtered[df_filtered["Year"].astype(str) == selected_year]
    if "Month" in df_filtered.columns and selected_month != "All":
        df_filtered = df_filtered[df_filtered["Month"].astype(str) == selected_month]
    if "Week" in df_filtered.columns and selected_week != "All":
        df_filtered = df_filtered[df_filtered["Week"].astype(str) == selected_week]

# --- 4. RUN ANALYSIS ---
if st.button("⚡ Execute Tracker Analysis", type="primary"):
    if df_filtered.empty:
        st.error("Cannot run analysis: No matching data found.")
    else:
        analysis_results = analyze_project_productivity(df_filtered)
        st.session_state["analysis_results"] = analysis_results
        st.session_state["active_df"] = analysis_results["processed_df"]
        st.success(f"Analysis completed for **{selected_project}**!")

# --- 5. DASHBOARD METRICS & CHARTS ---
if "active_df" in st.session_state:
    df_active = st.session_state["active_df"]
    
    st.markdown("---")
    
    # Summary Banner Text
    if "Productivity (%)" in df_active.columns and not df_active.empty:
        numeric_prod = pd.to_numeric(df_active["Productivity (%)"], errors="coerce")
        avg_prod = round(numeric_prod.mean(), 2)
        
        selected_week_label = selected_week if selected_week != "All" else "Selected Period"
        
        st.info(f"📊 **Summary Notice:** This week ({selected_week_label}) has an average productivity score of **{avg_prod}%**.")

        # KPI Columns
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Average Productivity", f"{avg_prod}%")
        kpi2.metric("Total Entries Logged", len(df_active))
        kpi3.metric("Flagged Alerts", len(df_active[df_active["Low_Productivity_Flag"] == True]))

        # Productivity Trend Chart
        st.subheader("Productivity Trend Chart")
        chart_df = df_active[["Date", "Productivity (%)"]].dropna() if "Date" in df_active.columns else df_active[["Productivity (%)"]].dropna()
        chart_df["Productivity (%)"] = pd.to_numeric(chart_df["Productivity (%)"], errors="coerce")
        
        if "Date" in chart_df.columns:
            st.area_chart(chart_df.set_index("Date"))
        else:
            st.area_chart(chart_df)

# --- 6. NVIDIA AI ASSISTANT CHATBOX ---
st.markdown("---")
st.subheader("🤖 Ask NVIDIA AI Assistant")
user_query = st.text_input(
    "Ask a question about project metrics:",
    placeholder="e.g., Compare week 1 and week 2 of Oct 2026 and give me key insights"
)

if st.button("Ask AI Agent"):
    if not user_query.strip():
        st.warning("Please type a question first.")
    else:
        eval_df = df_filtered if not df_filtered.empty else df_raw
        with st.spinner("NVIDIA AI is analyzing your sheet metrics..."):
            ai_response = ask_nvidia_agent(user_query, eval_df)
            st.markdown(f"### AI Analysis Response\n{ai_response}")

# --- 7. AUDIT SIDEBAR PANEL ---
st.sidebar.subheader("Google Sheets Audit")
if "analysis_results" in st.session_state:
    results = st.session_state["analysis_results"]
    daily_alerts = results.get("daily_alerts", pd.DataFrame())

    if not daily_alerts.empty:
        for idx, row in daily_alerts.iterrows():
            name_val = row.get("Name") if pd.notnull(row.get("Name")) and str(row.get("Name")).strip() != "" else "Team Member"
            date_val = row.get("Date", "N/A")
            score_val = row.get("Productivity (%)", "N/A")
            
            st.sidebar.markdown(
                f"""
                <div style="margin-bottom: 12px; padding: 10px; border-left: 4px solid #ff4b4b; background-color: #1a1c23; border-radius: 4px;">
                    <div style="font-weight: bold; color: #ff4b4b;">Low Productivity Flag</div>
                    <div style="font-size: 0.9em; margin-top: 4px; color: #ffffff;">User/Date: {name_val} - {date_val}</div>
                    <div style="font-size: 0.85em; color: #a0a0a0;">Score: {score_val}%</div>
                </div>
                """,
                unsafe_allow_html=True
            )
    else:
        st.sidebar.markdown(
            "<div style='color: #4CAF50; padding: 10px; background-color: #1a1c23; border-radius: 4px;'>All team logs met productivity thresholds.</div>",
            unsafe_allow_html=True
        )
else:
    st.sidebar.info("Execute analysis to view audit flags.")
