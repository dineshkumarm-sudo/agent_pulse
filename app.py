import streamlit as st
import pandas as pd
import re
import datetime
import plotly.express as px

from src.gsheets_client import get_gsheet_client, analyze_project_productivity
from src.agent_logic import ask_agent_pulse, collate_coo_report
from src.project_config import PROJECT_SHEETS, PROJECT_NAMES, PRODUCTIVITY_ALERT_THRESHOLDS


st.set_page_config(page_title="Agent Pulse", page_icon="⚡", layout="wide")



# ============================================================
# HELPERS
# ============================================================

def normalize_column_name(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def find_column(df, candidates):
    normalized = {normalize_column_name(col): col for col in df.columns}
    for candidate in candidates:
        key = normalize_column_name(candidate)
        if key in normalized:
            return normalized[key]
    return None


def parse_productivity(series):
    return pd.to_numeric(
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


def parse_date_series(series):
    """Parse tracker dates such as '6-Oct-2025' consistently."""
    # dayfirst=True correctly handles dates like 6-Oct-2025 and 06/10/2025.
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def parse_count(series):
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("hours", "", case=False, regex=False)
        .str.replace("hrs", "", case=False, regex=False)
        .str.strip(),
        errors="coerce",
    )


def find_hours_column(df):
    """Use the exact source column specified for Superbreakers."""
    return find_column(df, ["SB Hrs Worked"])


def calculate_productivity(df):
    """
    Productivity is the sum of each activity's target achievement, adjusted
    for actual hours worked. Targets double for every additional 4 hours.
    Formula: ((New Listings / 20) + (Listing Update / 25)) / (Hours / 4) * 100.
    """
    result = df.copy()

    # These are the exact column headers confirmed for this tracker.
    new_col = find_column(result, ["New Listings"])
    existing_col = find_column(result, ["Listing Update"])
    hours_col = find_hours_column(result)

    missing = []
    if new_col is None:
        missing.append("New Listings")
    if existing_col is None:
        missing.append("Listing Update")
    if hours_col is None:
        missing.append("Hours worked column")

    if missing:
        available = ", ".join(str(c) for c in result.columns)
        return (
            result,
            False,
            "Could not calculate productivity. Missing: "
            + ", ".join(missing)
            + ". Available sheet columns: "
            + available,
        )

    new_count = parse_count(result[new_col])
    existing_count = parse_count(result[existing_col])
    hours = parse_count(result[hours_col])

    valid_counts = new_count.notna() & existing_count.notna()
    valid_hours = hours.notna() & hours.gt(0)

    total_target_achievement = (new_count / 20) + (existing_count / 25)
    productivity = total_target_achievement * (4 / hours.where(valid_hours)) * 100
    productivity = productivity.where(valid_counts & valid_hours)

    result["Productivity (%)"] = productivity.round(2)

    return (
        result,
        True,
        f"Calculated using New Listings: {new_col}; Listing Update: "
        f"{existing_col}; Hours: {hours_col}.",
    )


def productivity_cell_style(value):
    try:
        percentage = float(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(percentage):
        return ""
    if percentage < 90:
        return "background-color: #FDE2E2; color: #B91C1C; font-weight: bold;"
    if percentage < 100:
        return "background-color: #FFEDD5; color: #9A3412; font-weight: bold;"
    return ""


def style_productivity_table(df):
    if df is None or df.empty or "Productivity (%)" not in df.columns:
        return df
    return (
        df.style
        .format({"Productivity (%)": "{:.2f}%"}, na_rep="N/A")
        .map(productivity_cell_style, subset=["Productivity (%)"])
    )


def dataframe_for_download(df):
    result = df.copy()
    if "Productivity (%)" in result.columns:
        result["Productivity (%)"] = result["Productivity (%)"].apply(
            lambda value: "N/A" if pd.isna(value) else f"{float(value):.2f}%"
        )
    return result


def fetch_sheet_safely(url, sheet_name="Daily_Tracker"):
    client = get_gsheet_client()
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    sheet = client.open_by_key(match.group(1)) if match else client.open_by_url(url)
    try:
        worksheet = sheet.worksheet(sheet_name)
    except Exception:
        worksheet = sheet.get_worksheet(0)
    return pd.DataFrame(worksheet.get_all_records())


def get_last_week_data(df, date_col):
    dates = parse_date_series(df[date_col])
    today = pd.Timestamp.today().normalize()
    this_monday = today - pd.Timedelta(days=today.weekday())
    previous_monday = this_monday - pd.Timedelta(days=7)
    mask = (dates >= previous_monday) & (dates < this_monday)
    result = df.loc[mask].copy()
    note = (
        f"Previous calendar week: {previous_monday:%d %b %Y} to "
        f"{this_monday - pd.Timedelta(days=1):%d %b %Y}."
    )
    return result, note


def build_productivity_chart(df, alert_threshold=90):
    if "Productivity (%)" not in df.columns:
        st.warning("Productivity chart is unavailable until the source columns are identified.")
        return

    date_col = find_column(df, ["Date", "Work Date", "Log Date"])
    task_col = find_column(df, [
        "Task", "Task Type", "Activity", "Activity Type", "Work Type",
        "Listing Type", "Task Name", "Process",
    ])

    chart_df = df.copy()
    chart_df["_productivity"] = parse_productivity(chart_df["Productivity (%)"])
    if date_col:
        chart_df["_date"] = parse_date_series(chart_df[date_col])
        chart_df = chart_df.dropna(subset=["_date"])
        x_col, x_title = "_date", "Date"
    else:
        chart_df["_record"] = range(1, len(chart_df) + 1)
        x_col, x_title = "_record", "Record"

    chart_df = chart_df.dropna(subset=["_productivity"])
    if chart_df.empty:
        st.info("No valid productivity values are available for the chart. Rows with zero/missing hours show N/A.")
        return

    chart_df["_task"] = chart_df[task_col].fillna("Not specified").astype(str) if task_col else "Combined / task not specified"
    new_col = find_column(df, ["New Listings"])
    existing_col = find_column(df, ["Listing Update"])
    hours_col = find_hours_column(df)

    chart_df["_new"] = parse_count(chart_df[new_col]) if new_col else float("nan")
    chart_df["_existing"] = parse_count(chart_df[existing_col]) if existing_col else float("nan")
    chart_df["_hours"] = parse_count(chart_df[hours_col]) if hours_col else float("nan")
    chart_df["_date_label"] = chart_df[x_col].astype(str) if x_col == "_record" else chart_df[x_col].dt.strftime("%d %b %Y")

    fig = px.line(
        chart_df, x=x_col, y="_productivity", color="_task", markers=True,
        custom_data=["_date_label", "_task", "_new", "_existing", "_hours"],
        labels={x_col: x_title, "_productivity": "Productivity (%)", "_task": "Task Type"},
        title="Calculated Productivity by Date",
    )
    fig.update_traces(
        hovertemplate=(
            "<b>Productivity: %{y:.2f}%</b><br>Date: %{customdata[0]}<br>"
            "Task: %{customdata[1]}<br>New Listings: %{customdata[2]}<br>"
            "Listing Update: %{customdata[3]}<br>Hours Worked: %{customdata[4]}<extra></extra>"
        )
    )
    fig.add_hline(y=alert_threshold, line_dash="dash", annotation_text=f"{alert_threshold}% alert threshold")
    fig.update_layout(
        xaxis_title=x_title, yaxis_title="Productivity (%)",
        hovermode="closest", legend_title="Task Type",
        margin=dict(l=20, r=20, t=60, b=20),
    )
    st.subheader("Productivity Trend Chart")
    st.plotly_chart(fig, use_container_width=True)


def build_daily_alerts(df, threshold=90):
    if df.empty or "Productivity (%)" not in df.columns:
        return pd.DataFrame()
    numeric = parse_productivity(df["Productivity (%)"])
    alerts = df.loc[numeric.notna() & (numeric < threshold)].copy()
    if not alerts.empty:
        alerts["Productivity (%)"] = numeric.loc[alerts.index].round(2)
    return alerts


# ============================================================
# SIDEBAR, PROJECT DIRECTORY AND NOTIFICATION SETTINGS
# ============================================================


st.sidebar.title("⚡ Agent Pulse")
st.sidebar.caption("TRACKER OPERATIONS INTELLIGENCE")

with st.sidebar.expander("🗂️  Project Directory", expanded=True):
    st.caption("Select a connected project below. More project trackers can be connected as their sheet URLs are added.")
    for project_name in PROJECT_NAMES:
        if project_name in PROJECT_SHEETS:
            if st.button(f"🟢  {project_name}", key=f"project_pick_{project_name}", use_container_width=True):
                st.session_state["selected_project"] = project_name
        else:
            st.markdown(f"⚪ **{project_name}**")
            st.caption("Tracker connection pending")

if "selected_project" not in st.session_state or st.session_state["selected_project"] not in PROJECT_SHEETS:
    st.session_state["selected_project"] = list(PROJECT_SHEETS.keys())[0]

selected_project = st.session_state["selected_project"]
sheet_url = PROJECT_SHEETS[selected_project]

df_raw = pd.DataFrame()
sheet_error = None
try:
    df_raw = fetch_sheet_safely(sheet_url)
except Exception as exc:
    sheet_error = f"{type(exc).__name__}: {exc}"


# ============================================================
# DASHBOARD FILTERS
# ============================================================

st.subheader("Dashboard Filters")
if sheet_error:
    st.error(f"Google Sheets error: {sheet_error}")

if not df_raw.empty:
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    date_col = find_column(df_raw, ["Date", "Work Date", "Log Date"])
    month_col = find_column(df_raw, ["Month"])
    week_col = find_column(df_raw, ["Week"])

    # The Date column is the source of truth for year filtering. Do not rely on
    # a separate Year field, which may be missing, stale, or incorrectly filled.
    parsed_dates = parse_date_series(df_raw[date_col]) if date_col else pd.Series(pd.NaT, index=df_raw.index)
    date_years = sorted(parsed_dates.dropna().dt.year.unique().tolist())
    years = ["All"] + [str(year) for year in date_years]
    months = ["All"] + sorted(df_raw[month_col].dropna().astype(str).unique()) if month_col else ["All"]
    weeks = ["All"] + sorted(df_raw[week_col].dropna().astype(str).unique()) if week_col else ["All"]

    with filter_col1:
        selected_year = st.selectbox("Year", years)
    with filter_col2:
        selected_month = st.selectbox("Month", months)
    with filter_col3:
        selected_week = st.selectbox("Week", weeks)

    df_filtered = df_raw.copy()
    if selected_year != "All":
        if date_col:
            # Match the selected year against the parsed Date column.
            df_filtered = df_filtered.loc[parsed_dates.dt.year == int(selected_year)].copy()
        else:
            st.warning("A Date column was not found, so the year filter cannot be applied.")
    if month_col and selected_month != "All":
        df_filtered = df_filtered[df_filtered[month_col].astype(str) == selected_month]
    if week_col and selected_week != "All":
        df_filtered = df_filtered[df_filtered[week_col].astype(str) == selected_week]
else:
    df_filtered = pd.DataFrame()


# ============================================================
# AGENT PULSE AI CHAT
# ============================================================

st.markdown("""
<style>
.block-container {padding-top: 3rem; padding-bottom: 2rem; max-width: 1500px;}
[data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.18);}
.ap-hero {
  padding: 1.7rem 1.8rem; border-radius: 22px; margin: .2rem 0 1.2rem 0;
  color: white; background:
  linear-gradient(110deg, rgba(13,27,52,.96) 0%, rgba(24,67,101,.92) 58%, rgba(16,125,129,.82) 100%),
  url('https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=1600&q=85');
  background-size: cover; background-position: center;
  box-shadow: 0 12px 32px rgba(15,45,70,.18);
}
.ap-eyebrow {font-size:.76rem; letter-spacing:.16em; text-transform:uppercase; opacity:.8; font-weight:700;}
.ap-hero h1 {font-size:2.2rem; line-height:1.12; margin:.45rem 0 .55rem 0; color:#fff;}
.ap-hero p {font-size:1rem; margin:0; opacity:.9; max-width:680px;}
.ap-pill {display:inline-block; margin-top:1rem; padding:.35rem .7rem; border:1px solid rgba(255,255,255,.35); border-radius:999px; font-size:.8rem;}
div[data-testid="stMetric"] {border:1px solid rgba(128,128,128,.18); padding:1rem 1.1rem; border-radius:16px; background:rgba(128,128,128,.035);}
div[data-testid="stExpander"] {border-radius:14px;}
</style>
<div class="ap-hero">
  <div class="ap-eyebrow">Operations intelligence · Live tracker</div>
  <h1>Agent Pulse</h1>
  <p>A clearer view of productivity, listing activity, and project health — all in one place.</p>
  <span class="ap-pill">⚡ Active project: """ + selected_project + """</span>
</div>
""", unsafe_allow_html=True)
st.caption("Ask questions, retrieve tracker records, compare periods, or request productivity insights.")

if "agent_pulse_messages" not in st.session_state:
    st.session_state.agent_pulse_messages = []

with st.form("agent_pulse_form", clear_on_submit=True):
    user_query = st.text_input("Ask Agent Pulse", placeholder="Bring last week's Superbreakers productivity data")
    submitted = st.form_submit_button("Ask Agent Pulse", type="primary", use_container_width=True)

if submitted:
    if not user_query.strip():
        st.warning("Please enter a question.")
    elif sheet_error:
        st.error(f"Google Sheets error: {sheet_error}")
    elif df_filtered.empty:
        st.warning("No Google Sheets records are available.")
    else:
        st.session_state.agent_pulse_messages.append({"role": "user", "content": user_query})
        query_lower = user_query.lower()
        asks_last_week = bool(re.search(r"\b(last[\s-]+weeks?|previous[\s-]+week)\b", query_lower))
        asks_for_records = bool(
            re.search(r"\b(show|bring|get|fetch|display|list|retrieve|pull)\b", query_lower)
            or re.search(r"\b(data|records|rows|table|details)\b", query_lower)
        )

        relevant_df = df_filtered.copy()
        filter_note = ""
        if asks_last_week:
            date_col = find_column(relevant_df, ["Date", "Work Date", "Log Date"])
            if date_col:
                relevant_df, filter_note = get_last_week_data(relevant_df, date_col)
            else:
                filter_note = "The sheet has no recognizable Date column, so records could not be filtered by week."

        relevant_df, calculation_ok, calculation_note = calculate_productivity(relevant_df)
        with st.spinner("Agent Pulse is checking your data..."):
            if relevant_df.empty:
                ai_response = "No records were found for the requested period. Please check the tracker dates."
            else:
                ai_response = ask_agent_pulse(
                    user_query=user_query,
                    df_data=relevant_df,
                    project_name=selected_project,
                )
            if filter_note:
                ai_response = f"{filter_note}\n\n{ai_response}"
            if not calculation_ok:
                ai_response += "\n\nProductivity calculation note: " + calculation_note

        show_table = asks_for_records or asks_last_week
        st.session_state.agent_pulse_messages.append({
            "role": "assistant",
            "content": ai_response,
            "dataframe": relevant_df.copy() if show_table and not relevant_df.empty else None,
        })

for message_index, message in enumerate(st.session_state.agent_pulse_messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        table = message.get("dataframe")
        if isinstance(table, pd.DataFrame) and not table.empty:
            st.caption("Retrieved Google Sheets records")
            st.dataframe(style_productivity_table(table), use_container_width=True, hide_index=True)
            st.download_button(
                "Download data as CSV",
                data=dataframe_for_download(table).to_csv(index=False).encode("utf-8"),
                file_name="agent_pulse_productivity_data.csv",
                mime="text/csv",
                key=f"agent_pulse_download_{message_index}",
            )

st.markdown("---")



# ============================================================
# PRODUCTIVITY CALCULATION
# ============================================================

calculation_ok = False
calculation_note = ""
if not df_filtered.empty:
    df_filtered, calculation_ok, calculation_note = calculate_productivity(df_filtered)
    if calculation_ok:
        st.caption(
            "Productivity adds target achievement for each activity: 20 New Listings "
            "and 25 Listing Updates per 4 hours. Targets scale proportionally with hours worked."
        )
    else:
        st.warning(calculation_note)


# ============================================================
# TRACKER ANALYSIS AND AUDIT
# ============================================================

if st.button("Execute Tracker Analysis", type="primary"):
    if df_filtered.empty:
        st.warning("No data matches the selected filters.")
    else:
        try:
            results = analyze_project_productivity(df_filtered)
            if not isinstance(results, dict):
                results = {"analysis_output": results}
            results["processed_df"] = df_filtered.copy()
            if calculation_ok:
                results["daily_alerts"] = build_daily_alerts(
                    df_filtered, PRODUCTIVITY_ALERT_THRESHOLDS.get(selected_project, 90)
                )
            st.session_state["analysis_results"] = results
            st.session_state["active_df"] = df_filtered.copy()
            st.success("Tracker analysis completed.")
        except Exception as exc:
            st.error(f"Analysis failed: {type(exc).__name__}: {exc}")


# ============================================================
# NOTIFICATION CENTER
# ============================================================

st.markdown("### 🔔 Notification Center")
threshold = PRODUCTIVITY_ALERT_THRESHOLDS.get(selected_project)
if not df_filtered.empty and calculation_ok and threshold is not None:
    current_prod = parse_productivity(df_filtered["Productivity (%)"])
    low_prod_rows = df_filtered.loc[current_prod.notna() & (current_prod < threshold)].copy()
    if low_prod_rows.empty:
        st.success(f"All clear — no productivity entries below {threshold}% in the currently filtered {selected_project} data.")
    else:
        st.warning(f"{len(low_prod_rows)} productivity alert(s): entries below {threshold}% for {selected_project}.")
        show_cols = [c for c in [
            find_column(low_prod_rows, ["Date", "Work Date", "Log Date"]),
            find_column(low_prod_rows, ["Name", "Agent Name", "Employee Name", "Team Member"]),
            "New Listings", "Listing Update", find_hours_column(low_prod_rows), "Productivity (%)"
        ] if c and c in low_prod_rows.columns]
        st.dataframe(style_productivity_table(low_prod_rows[show_cols]), use_container_width=True, hide_index=True)
elif threshold is None:
    st.info("Productivity alerts for this project will be configured when its tracker rules are provided.")
else:
    st.info("Load tracker data to see project notifications.")

# ============================================================
# DASHBOARD METRICS, TABLE AND CHART
# ============================================================

if not df_filtered.empty:
    if calculation_ok:
        numeric_prod = parse_productivity(df_filtered["Productivity (%)"])
        valid_prod = numeric_prod.dropna()
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Average Productivity", f"{valid_prod.mean():.2f}%" if not valid_prod.empty else "N/A")
        kpi2.metric("Total Entries", len(df_filtered))

        new_col = find_column(df_filtered, ["New Listings"])
        existing_col = find_column(df_filtered, ["Listing Update"])
        if new_col and existing_col:
            total_new = parse_count(df_filtered[new_col]).sum()
            total_existing = parse_count(df_filtered[existing_col]).sum()
            kpi3.metric("Total Listings Processed", f"{total_new + total_existing:,.0f}")
        else:
            kpi3.metric("Total Listings Processed", "N/A")

    build_productivity_chart(df_filtered, PRODUCTIVITY_ALERT_THRESHOLDS.get(selected_project, 90))
    st.subheader("Productivity Table")
    if calculation_ok:
        st.caption(
            "Red = below 95% | Orange = 95% to below 100% | No warning highlight = "
            "100% or above | N/A = zero/missing hours or missing listing counts."
        )
        st.dataframe(style_productivity_table(df_filtered), use_container_width=True, hide_index=True)
        st.download_button(
            "Download filtered dashboard data as CSV",
            data=dataframe_for_download(df_filtered).to_csv(index=False).encode("utf-8"),
            file_name="agent_pulse_filtered_productivity.csv",
            mime="text/csv",
            key="dashboard_productivity_download",
        )
    else:
        st.info("The tracker data is available, but productivity cannot be calculated until the required source columns are found.")
        st.dataframe(df_filtered, use_container_width=True, hide_index=True)

    with st.expander("View raw filtered tracker data"):
        st.dataframe(df_raw, use_container_width=True, hide_index=True)
else:
    st.info("Select a project and adjust the filters to view the dashboard.")


st.sidebar.markdown("---")
st.sidebar.subheader("Google Sheets Audit")
if "analysis_results" in st.session_state:
    results = st.session_state["analysis_results"]
    daily_alerts = results.get("daily_alerts", pd.DataFrame())
    if isinstance(daily_alerts, pd.DataFrame) and not daily_alerts.empty:
        for _, row in daily_alerts.iterrows():
            name_col = find_column(pd.DataFrame(columns=row.index), ["Name", "Agent Name", "Employee Name", "Team Member"])
            date_col = find_column(pd.DataFrame(columns=row.index), ["Date", "Work Date", "Log Date"])
            name_val = row.get(name_col, "Team Member") if name_col else "Team Member"
            date_val = row.get(date_col, "N/A") if date_col else "N/A"
            score_val = row.get("Productivity (%)", "N/A")
            score_display = f"{float(score_val):.2f}%" if pd.notna(score_val) else "N/A"
            st.sidebar.error(
                f"Low Productivity Flag\n\nUser: {name_val}\n\nDate: {date_val}\n\n"
                f"Calculated Productivity: {score_display}"
            )
    else:
        st.sidebar.success(f"No productivity alerts below {PRODUCTIVITY_ALERT_THRESHOLDS.get(selected_project, 90)}% were reported.")
else:
    st.sidebar.info("Execute tracker analysis to view audit flags.")
