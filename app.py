import streamlit as st
import pandas as pd
import re
import datetime
import plotly.express as px

from src.gsheets_client import get_gsheet_client, analyze_project_productivity
from src.agent_logic import ask_agent_pulse, collate_coo_report


st.set_page_config(page_title="Agent Pulse", page_icon="⚡", layout="wide")

PROJECT_SHEETS = {
    "Superbreakers": (
        "https://docs.google.com/spreadsheets/d/"
        "15hpOWzz9oK6idTrKq0HEaVIwAf-C-5yy_f2fC5Mhtfc/"
        "edit?gid=547444785#gid=547444785"
    )
}


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
    """Find common hours headers, then cautiously detect less common ones."""
    candidates = [
        "Total Hours Worked", "Total Hours", "Hours Worked",
        "Total Working Hours", "Working Hours", "Production Hours",
        "Hours", "Total Hrs Worked", "Total Hrs", "Hrs Worked",
        "Hrs", "Hours Spent", "Total Hours Spent", "Time Spent (Hours)",
        "Time Spent Hours", "Hours Utilized", "Hours Utilised",
        "Actual Hours", "Work Hours", "Total Time (Hours)",
        "Total Time Spent", "Time Taken (Hours)", "Effort Hours",
        "Productive Hours", "Daily Hours", "Logged Hours",
    ]
    col = find_column(df, candidates)
    if col:
        return col

    # Handles headers such as "Total Hrs - Daily" or "Hours (Actual)".
    for column in df.columns:
        normalized = normalize_column_name(column)
        has_hour_unit = "hour" in normalized or "hrs" in normalized
        time_like = any(word in normalized for word in ("worked", "spent", "total", "actual", "productive", "logged", "utilized", "utilised", "production"))
        if has_hour_unit and time_like:
            return column
    return None


def calculate_productivity(df):
    """
    Normalized productivity:
    ((New Listings / 20) + (Listing Update / 25)) / 2 * (4 / Hours) * 100.
    Meeting both targets proportionally over 4 hours equals 100%.
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

    average_target_achievement = ((new_count / 20) + (existing_count / 25)) / 2
    productivity = average_target_achievement * (4 / hours.where(valid_hours)) * 100
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
    if percentage < 95:
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
    dates = pd.to_datetime(df[date_col], errors="coerce", dayfirst=True)
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


def build_productivity_chart(df):
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
        chart_df["_date"] = pd.to_datetime(chart_df[date_col], errors="coerce", dayfirst=True)
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
    fig.add_hline(y=95, line_dash="dash", annotation_text="95% threshold")
    fig.update_layout(
        xaxis_title=x_title, yaxis_title="Productivity (%)",
        hovermode="closest", legend_title="Task Type",
        margin=dict(l=20, r=20, t=60, b=20),
    )
    st.subheader("Productivity Trend Chart")
    st.plotly_chart(fig, use_container_width=True)


def build_daily_alerts(df):
    if df.empty or "Productivity (%)" not in df.columns:
        return pd.DataFrame()
    numeric = parse_productivity(df["Productivity (%)"])
    alerts = df.loc[numeric.notna() & (numeric < 95)].copy()
    if not alerts.empty:
        alerts["Productivity (%)"] = numeric.loc[alerts.index].round(2)
    return alerts


# ============================================================
# SIDEBAR AND GOOGLE SHEETS
# ============================================================

st.sidebar.title("⚡ Agent Pulse")
st.sidebar.caption("Tracker Operations Intelligence")
selected_project = st.sidebar.selectbox("Select Active Project", options=list(PROJECT_SHEETS.keys()))
sheet_url = PROJECT_SHEETS[selected_project]

df_raw = pd.DataFrame()
sheet_error = None
try:
    df_raw = fetch_sheet_safely(sheet_url)
except Exception as exc:
    sheet_error = f"{type(exc).__name__}: {exc}"


# ============================================================
# AGENT PULSE AI CHAT
# ============================================================

st.title("⚡ Agent Pulse")
st.caption(f"AI Operations Assistant | Active Project: {selected_project}")
st.markdown("Ask questions, retrieve tracker records, compare periods, or request productivity insights.")

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
    elif df_raw.empty:
        st.warning("No Google Sheets records are available.")
    else:
        st.session_state.agent_pulse_messages.append({"role": "user", "content": user_query})
        query_lower = user_query.lower()
        asks_last_week = bool(re.search(r"\b(last[\s-]+weeks?|previous[\s-]+week)\b", query_lower))
        asks_for_records = bool(
            re.search(r"\b(show|bring|get|fetch|display|list|retrieve|pull)\b", query_lower)
            or re.search(r"\b(data|records|rows|table|details)\b", query_lower)
        )

        relevant_df = df_raw.copy()
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
# DASHBOARD FILTERS
# ============================================================

st.subheader("Dashboard Filters")
if sheet_error:
    st.error(f"Google Sheets error: {sheet_error}")

if not df_raw.empty:
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    current_year = datetime.datetime.now().year
    default_years = [str(year) for year in range(2025, current_year + 1)]
    year_col = find_column(df_raw, ["Year"])
    month_col = find_column(df_raw, ["Month"])
    week_col = find_column(df_raw, ["Week"])

    if year_col:
        sheet_years = [str(value) for value in df_raw[year_col].dropna().unique() if str(value).strip()]
        combined_years = sorted(set(default_years + sheet_years))
    else:
        combined_years = default_years
    years = ["All"] + combined_years
    months = ["All"] + sorted(df_raw[month_col].dropna().astype(str).unique()) if month_col else ["All"]
    weeks = ["All"] + sorted(df_raw[week_col].dropna().astype(str).unique()) if week_col else ["All"]

    with filter_col1:
        selected_year = st.selectbox("Year", years)
    with filter_col2:
        selected_month = st.selectbox("Month", months)
    with filter_col3:
        selected_week = st.selectbox("Week", weeks)

    df_filtered = df_raw.copy()
    if year_col and selected_year != "All":
        df_filtered = df_filtered[df_filtered[year_col].astype(str) == selected_year]
    if month_col and selected_month != "All":
        df_filtered = df_filtered[df_filtered[month_col].astype(str) == selected_month]
    if week_col and selected_week != "All":
        df_filtered = df_filtered[df_filtered[week_col].astype(str) == selected_week]
else:
    df_filtered = pd.DataFrame()


# ============================================================
# PRODUCTIVITY CALCULATION
# ============================================================

calculation_ok = False
calculation_note = ""
if not df_filtered.empty:
    df_filtered, calculation_ok, calculation_note = calculate_productivity(df_filtered)
    if calculation_ok:
        st.caption(
            "Productivity uses normalized target achievement: 20 New Listings and "
            "25 Listing Updates per 4 hours. Meeting both targets proportionally equals 100%."
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
                results["daily_alerts"] = build_daily_alerts(df_filtered)
            st.session_state["analysis_results"] = results
            st.session_state["active_df"] = df_filtered.copy()
            st.success("Tracker analysis completed.")
        except Exception as exc:
            st.error(f"Analysis failed: {type(exc).__name__}: {exc}")


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

    build_productivity_chart(df_filtered)
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
        st.sidebar.success("No productivity alerts below 95% were reported.")
else:
    st.sidebar.info("Execute tracker analysis to view audit flags.")
