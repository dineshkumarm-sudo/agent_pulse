
import streamlit as st
import pandas as pd
import re
import datetime
import plotly.express as px

from src.gsheets_client import (
    get_gsheet_client,
    analyze_project_productivity,
)
from src.agent_logic import ask_agent_pulse, collate_coo_report


st.set_page_config(
    page_title="Agent Pulse",
    page_icon="⚡",
    layout="wide",
)

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
    """Normalize column names for reliable matching."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def find_column(df, candidates):
    """Find a column even if capitalization or spacing differs."""
    normalized = {
        normalize_column_name(col): col
        for col in df.columns
    }

    for candidate in candidates:
        key = normalize_column_name(candidate)
        if key in normalized:
            return normalized[key]

    return None


def parse_productivity(series):
    """Convert values such as '90%' or 90 into numeric percentages."""
    return pd.to_numeric(
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


def parse_count(series):
    """Convert production counts and hours into numeric values."""
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


def calculate_productivity(df):
    """
    Calculate normalized productivity.

    Formula:
      Average of:
        New Listings Count / 20
        Existing Listings Count / 25

      Adjusted for hours worked:
        Average achievement * (4 / hours) * 100

    Meeting both targets for 4 hours = 100%.
    Zero or missing hours = N/A.
    """

    result = df.copy()

 new_col = find_column(
    result,
    ["New Listings"],
)

    existing_col = find_column(
    result,
    ["Listing Update"],
)

    hours_col = find_column(
        result,
        [
            "Total Hours Worked",
            "Total Hours",
            "Hours Worked",
            "Total Working Hours",
            "Working Hours",
            "Production Hours",
            "Hours",
            "Total Hrs Worked",
            "Total Hrs",
        ],
    )

    missing = []

    if new_col is None:
        missing.append("New Listings Count")

    if existing_col is None:
        missing.append("Existing Listings Count")

    if hours_col is None:
        missing.append("Total Hours Worked")

    if missing:
        return (
            result,
            False,
            "Could not calculate productivity. Missing recognizable "
            "column(s): " + ", ".join(missing),
        )

    new_count = parse_count(result[new_col])
    existing_count = parse_count(result[existing_col])
    hours = parse_count(result[hours_col])

    # Do not treat missing production counts as zero.
    valid_counts = new_count.notna() & existing_count.notna()
    valid_hours = hours.notna() & hours.gt(0)

    # Average the two target-achievement ratios.
    average_target_achievement = (
        (new_count / 20) + (existing_count / 25)
    ) / 2

    productivity = (
        average_target_achievement
        * (4 / hours.where(valid_hours))
        * 100
    )

    # Productivity cannot be calculated if either count is missing
    # or if hours are missing/zero.
    productivity = productivity.where(valid_counts & valid_hours)

    result["Productivity (%)"] = productivity.round(2)

    return result, True, (
        f"Calculated using New Listings: {new_col}, "
        f"Existing Listings: {existing_col}, Hours: {hours_col}."
    )


def productivity_cell_style(value):
    """Red below 95%; orange from 95% to below 100%."""
    try:
        percentage = float(value)
    except (TypeError, ValueError):
        return ""

    if pd.isna(percentage):
        return ""

    if percentage < 95:
        return (
            "background-color: #FDE2E2; "
            "color: #B91C1C; font-weight: bold;"
        )

    if percentage < 100:
        return (
            "background-color: #FFEDD5; "
            "color: #9A3412; font-weight: bold;"
        )

    return ""


def style_productivity_table(df):
    """Format productivity as a percentage and highlight thresholds."""
    if df is None or df.empty:
        return df

    if "Productivity (%)" not in df.columns:
        return df

    return (
        df.style
        .format(
            {"Productivity (%)": "{:.2f}%"},
            na_rep="N/A",
        )
        .map(
            productivity_cell_style,
            subset=["Productivity (%)"],
        )
    )


def dataframe_for_download(df):
    """Make unavailable productivity explicit in downloaded CSV files."""
    result = df.copy()

    if "Productivity (%)" in result.columns:
        result["Productivity (%)"] = result[
            "Productivity (%)"
        ].apply(
            lambda value: (
                "N/A"
                if pd.isna(value)
                else f"{float(value):.2f}%"
            )
        )

    return result


def fetch_sheet_safely(
    url: str,
    sheet_name: str = "Daily_Tracker",
) -> pd.DataFrame:
    client = get_gsheet_client()
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)

    if match:
        sheet = client.open_by_key(match.group(1))
    else:
        sheet = client.open_by_url(url)

    try:
        worksheet = sheet.worksheet(sheet_name)
    except Exception:
        worksheet = sheet.get_worksheet(0)

    return pd.DataFrame(worksheet.get_all_records())


def get_last_week_data(df, date_col):
    """Return previous calendar week's rows, Monday through Sunday."""
    dates = pd.to_datetime(
        df[date_col],
        errors="coerce",
        dayfirst=True,
    )

    today = pd.Timestamp.today().normalize()
    this_monday = today - pd.Timedelta(days=today.weekday())
    previous_monday = this_monday - pd.Timedelta(days=7)

    mask = (dates >= previous_monday) & (dates < this_monday)

    result = df.loc[mask].copy()

    note = (
        f"Previous calendar week: {previous_monday:%d %b %Y} "
        f"to {this_monday - pd.Timedelta(days=1):%d %b %Y}."
    )

    return result, note


def build_productivity_chart(df):
    """Plot calculated productivity and show useful details on hover."""

    productivity_col = find_column(
        df,
        ["Productivity (%)", "Productivity", "Productivity Percent"],
    )

    date_col = find_column(
        df,
        ["Date", "Work Date", "Log Date"],
    )

    new_col = find_column(
        df,
        [
            "New Listings Count",
            "New Listing Count",
            "New Listings",
            "New Listing",
            "New Listings Completed",
        ],
    )

    existing_col = find_column(
        df,
        [
            "Existing Listings Count",
            "Existing Listing Count",
            "Existing Listings",
            "Existing Listing",
            "Listing Updates Count",
            "Listing Update Count",
            "Existing Listings Completed",
        ],
    )

    hours_col = find_column(
        df,
        [
            "Total Hours Worked",
            "Total Hours",
            "Hours Worked",
            "Total Working Hours",
            "Working Hours",
            "Production Hours",
            "Hours",
            "Total Hrs Worked",
        ],
    )

    task_col = find_column(
        df,
        [
            "Task",
            "Task Type",
            "Activity",
            "Activity Type",
            "Work Type",
            "Listing Type",
            "Task Name",
            "Process",
        ],
    )

    if productivity_col is None:
        st.warning(
            "Productivity is unavailable because the required source "
            "columns could not be identified. Check the column names "
            "and calculation status above."
        )
        return

    chart_df = df.copy()
    chart_df["_chart_productivity"] = parse_productivity(
        chart_df[productivity_col]
    )

    if date_col:
        chart_df["_chart_date"] = pd.to_datetime(
            chart_df[date_col],
            errors="coerce",
            dayfirst=True,
        )
        chart_df = chart_df.dropna(subset=["_chart_date"])
        x_col = "_chart_date"
        x_title = "Date"
    else:
        chart_df["_chart_index"] = range(1, len(chart_df) + 1)
        x_col = "_chart_index"
        x_title = "Record"

    chart_df = chart_df.dropna(subset=["_chart_productivity"])

    if chart_df.empty:
        st.info(
            "No valid productivity values are available for the chart. "
            "Rows with zero or missing hours show N/A and are excluded."
        )
        return

    if task_col:
        chart_df["_chart_task"] = (
            chart_df[task_col].fillna("Not specified").astype(str)
        )
    else:
        chart_df["_chart_task"] = "Combined / task not specified"

    chart_df["_chart_date_label"] = (
        chart_df[x_col].astype(str)
        if x_col == "_chart_index"
        else chart_df[x_col].dt.strftime("%d %b %Y")
    )

    custom_data = [
        "_chart_date_label",
        "_chart_task",
    ]

    chart_df["_chart_new_count"] = (
        parse_count(chart_df[new_col])
        if new_col
        else float("nan")
    )
    chart_df["_chart_existing_count"] = (
        parse_count(chart_df[existing_col])
        if existing_col
        else float("nan")
    )
    chart_df["_chart_hours"] = (
        parse_count(chart_df[hours_col])
        if hours_col
        else float("nan")
    )

    custom_data.extend(
        [
            "_chart_new_count",
            "_chart_existing_count",
            "_chart_hours",
        ]
    )

    st.subheader("Productivity Trend Chart")

    fig = px.line(
        chart_df,
        x=x_col,
        y="_chart_productivity",
        color="_chart_task",
        markers=True,
        custom_data=custom_data,
        labels={
            x_col: x_title,
            "_chart_productivity": "Productivity (%)",
            "_chart_task": "Task Type",
        },
        title="Calculated Productivity by Date",
    )

    fig.update_traces(
        hovertemplate=(
            "<b>Productivity: %{y:.2f}%</b><br>"
            "Date: %{customdata[0]}<br>"
            "Task: %{customdata[1]}<br>"
            "New Listings: %{customdata[2]}<br>"
            "Existing Listings: %{customdata[3]}<br>"
            "Hours Worked: %{customdata[4]}"
            "<extra></extra>"
        )
    )

    fig.add_hline(
        y=95,
        line_dash="dash",
        annotation_text="95% threshold",
    )

    fig.update_layout(
        xaxis_title=x_title,
        yaxis_title="Productivity (%)",
        hovermode="closest",
        legend_title="Task Type",
        margin=dict(l=20, r=20, t=60, b=20),
    )

    st.plotly_chart(fig, use_container_width=True)


def build_daily_alerts(df):
    """Build audit alerts from the same calculated productivity."""
    if df.empty or "Productivity (%)" not in df.columns:
        return pd.DataFrame()

    numeric = parse_productivity(df["Productivity (%)"])
    alerts = df.loc[numeric.notna() & (numeric < 95)].copy()

    if alerts.empty:
        return alerts

    alerts["Productivity (%)"] = numeric.loc[alerts.index].round(2)

    return alerts


# ============================================================
# SIDEBAR: MANUAL PROJECT SELECTION
# ============================================================

st.sidebar.title("⚡ Agent Pulse")
st.sidebar.caption("Tracker Operations Intelligence")

selected_project = st.sidebar.selectbox(
    "Select Active Project",
    options=list(PROJECT_SHEETS.keys()),
)

sheet_url = PROJECT_SHEETS[selected_project]


# ============================================================
# LOAD GOOGLE SHEETS
# ============================================================

df_raw = pd.DataFrame()
sheet_error = None

try:
    df_raw = fetch_sheet_safely(sheet_url)
except Exception as exc:
    sheet_error = f"{type(exc).__name__}: {exc}"


# ============================================================
# AGENT PULSE CHAT AT THE TOP
# ============================================================

st.title("⚡ Agent Pulse")
st.caption(
    f"AI Operations Assistant | Active Project: {selected_project}"
)

st.markdown(
    "Ask questions, retrieve tracker records, compare periods, "
    "or request productivity insights."
)

if "agent_pulse_messages" not in st.session_state:
    st.session_state.agent_pulse_messages = []

with st.form("agent_pulse_form", clear_on_submit=True):
    user_query = st.text_input(
        "Ask Agent Pulse",
        placeholder="Bring last week's Superbreakers productivity data",
    )

    submitted = st.form_submit_button(
        "Ask Agent Pulse",
        type="primary",
        use_container_width=True,
    )

if submitted:
    if not user_query.strip():
        st.warning("Please enter a question.")
    elif sheet_error:
        st.error(f"Google Sheets error: {sheet_error}")
    elif df_raw.empty:
        st.warning("No Google Sheets records are available.")
    else:
        st.session_state.agent_pulse_messages.append(
            {"role": "user", "content": user_query}
        )

        query_lower = user_query.lower()

        asks_last_week = bool(
            re.search(
                r"\b(last[\s-]+weeks?|previous[\s-]+week)\b",
                query_lower,
            )
        )

        asks_for_records = bool(
            re.search(
                r"\b(show|bring|get|fetch|display|list|retrieve|pull)\b",
                query_lower,
            )
            or re.search(
                r"\b(data|records|rows|table|details)\b",
                query_lower,
            )
        )

        relevant_df = df_raw.copy()
        filter_note = ""

        if asks_last_week:
            date_col = find_column(
                relevant_df,
                ["Date", "Work Date", "Log Date"],
            )

            if date_col:
                relevant_df, filter_note = get_last_week_data(
                    relevant_df,
                    date_col,
                )
            else:
                filter_note = (
                    "The sheet has no recognizable Date column, "
                    "so records could not be filtered by week."
                )

        # Calculate productivity before sending records to the AI
        # or showing them in the chat's retrieved-data table.
        relevant_df, calculation_ok, calculation_note = (
            calculate_productivity(relevant_df)
        )

        with st.spinner("Agent Pulse is checking your data..."):
            if relevant_df.empty:
                ai_response = (
                    "No records were found for the requested period. "
                    "Please check the tracker dates."
                )
            else:
                ai_response = ask_agent_pulse(
                    user_query=user_query,
                    df_data=relevant_df,
                    project_name=selected_project,
                )

            if filter_note:
                ai_response = f"{filter_note}\n\n{ai_response}"

            if not calculation_ok:
                ai_response += (
                    "\n\nProductivity calculation note: "
                    + calculation_note
                )

        show_table = asks_for_records or asks_last_week

        st.session_state.agent_pulse_messages.append(
            {
                "role": "assistant",
                "content": ai_response,
                "dataframe": (
                    relevant_df.copy()
                    if show_table and not relevant_df.empty
                    else None
                ),
            }
        )


for message_index, message in enumerate(
    st.session_state.agent_pulse_messages
):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

        table = message.get("dataframe")

        if isinstance(table, pd.DataFrame) and not table.empty:
            st.caption("Retrieved Google Sheets records")

            st.dataframe(
                style_productivity_table(table),
                use_container_width=True,
                hide_index=True,
            )

            download_df = dataframe_for_download(table)

            st.download_button(
                "Download data as CSV",
                data=download_df.to_csv(index=False).encode("utf-8"),
                file_name="agent_pulse_productivity_data.csv",
                mime="text/csv",
                key=f"agent_pulse_download_{message_index}",
            )

st.markdown("---")


# ============================================================
# MANUAL FILTERS: YEAR, MONTH AND WEEK
# ============================================================

st.subheader("Dashboard Filters")

if sheet_error:
    st.error(f"Google Sheets error: {sheet_error}")

if not df_raw.empty:
    filter_col1, filter_col2, filter_col3 = st.columns(3)

    current_year = datetime.datetime.now().year

    default_years = [
        str(year) for year in range(2025, current_year + 1)
    ]

    year_col = find_column(df_raw, ["Year"])
    month_col = find_column(df_raw, ["Month"])
    week_col = find_column(df_raw, ["Week"])

    if year_col:
        sheet_years = [
            str(value)
            for value in df_raw[year_col].dropna().unique()
            if str(value).strip()
        ]
        combined_years = sorted(set(default_years + sheet_years))
    else:
        combined_years = default_years

    years = ["All"] + combined_years

    months = (
        ["All"] + sorted(
            df_raw[month_col].dropna().astype(str).unique()
        )
        if month_col
        else ["All"]
    )

    weeks = (
        ["All"] + sorted(
            df_raw[week_col].dropna().astype(str).unique()
        )
        if week_col
        else ["All"]
    )

    with filter_col1:
        selected_year = st.selectbox("Year", years)

    with filter_col2:
        selected_month = st.selectbox("Month", months)

    with filter_col3:
        selected_week = st.selectbox("Week", weeks)

    df_filtered = df_raw.copy()

    if year_col and selected_year != "All":
        df_filtered = df_filtered[
            df_filtered[year_col].astype(str) == selected_year
        ]

    if month_col and selected_month != "All":
        df_filtered = df_filtered[
            df_filtered[month_col].astype(str) == selected_month
        ]

    if week_col and selected_week != "All":
        df_filtered = df_filtered[
            df_filtered[week_col].astype(str) == selected_week
        ]

else:
    df_filtered = pd.DataFrame()


# ============================================================
# CALCULATE PRODUCTIVITY FOR ALL FILTERED DASHBOARD RECORDS
# ============================================================

calculation_ok = False
calculation_note = ""

if not df_filtered.empty:
    df_filtered, calculation_ok, calculation_note = (
        calculate_productivity(df_filtered)
    )

if not df_filtered.empty:
    if calculation_ok:
        st.caption(
            "Productivity uses normalized target achievement: "
            "20 New Listings and 25 Existing Listings per 4 hours. "
            "Meeting both targets proportionally equals 100%."
        )
    else:
        st.warning(calculation_note)


# ============================================================
# RUN TRACKER ANALYSIS
# ============================================================

if st.button("Execute Tracker Analysis", type="primary"):
    if df_filtered.empty:
        st.warning("No data matches the selected filters.")
    else:
        try:
            results = analyze_project_productivity(df_filtered)

            if not isinstance(results, dict):
                results = {"analysis_output": results}

            # Ensure audit and dashboard use the same productivity formula.
            results["processed_df"] = df_filtered.copy()

            if calculation_ok:
                results["daily_alerts"] = build_daily_alerts(
                    df_filtered
                )

            st.session_state["analysis_results"] = results
            st.session_state["active_df"] = df_filtered.copy()

            st.success("Tracker analysis completed.")
        except Exception as exc:
            st.error(
                f"Analysis failed: {type(exc).__name__}: {exc}"
            )


# ============================================================
# DASHBOARD METRICS, TABLE AND CHART
# ============================================================

if not df_filtered.empty:
    if calculation_ok:
        numeric_prod = parse_productivity(
            df_filtered["Productivity (%)"]
        )
        valid_prod = numeric_prod.dropna()

        kpi1, kpi2, kpi3 = st.columns(3)

        if not valid_prod.empty:
            kpi1.metric(
                "Average Productivity",
                f"{valid_prod.mean():.2f}%",
            )
        else:
            kpi1.metric("Average Productivity", "N/A")

        kpi2.metric("Total Entries", len(df_filtered))

        new_col = find_column(
            df_filtered,
            [
                "New Listings Count",
                "New Listing Count",
                "New Listings",
                "New Listing",
                "New Listings Completed",
            ],
        )

        existing_col = find_column(
            df_filtered,
            [
                "Existing Listings Count",
                "Existing Listing Count",
                "Existing Listings",
                "Existing Listing",
                "Listing Updates Count",
                "Listing Update Count",
                "Existing Listings Completed",
            ],
        )

        if new_col and existing_col:
            total_new = parse_count(df_filtered[new_col]).sum()
            total_existing = parse_count(
                df_filtered[existing_col]
            ).sum()

            kpi3.metric(
                "Total Listings Processed",
                f"{total_new + total_existing:,.0f}",
            )
        else:
            kpi3.metric("Total Listings Processed", "N/A")

    build_productivity_chart(df_filtered)

    st.subheader("Productivity Table")

    if calculation_ok:
        st.caption(
            "Red = below 95% | Orange = 95% to below 100% | "
            "No warning highlight = 100% or above | N/A = "
            "zero/missing hours or missing listing counts."
        )

        st.dataframe(
            style_productivity_table(df_filtered),
            use_container_width=True,
            hide_index=True,
        )

        st.download_button(
            "Download filtered dashboard data as CSV",
            data=dataframe_for_download(
                df_filtered
            ).to_csv(index=False).encode("utf-8"),
            file_name="agent_pulse_filtered_productivity.csv",
            mime="text/csv",
            key="dashboard_productivity_download",
        )
    else:
        st.info(
            "The tracker data is available, but productivity cannot "
            "be calculated until the required source columns are found."
        )
        st.dataframe(
            df_filtered,
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("View raw filtered tracker data"):
        st.dataframe(
            df_raw,
            use_container_width=True,
            hide_index=True,
        )

else:
    st.info(
        "Select a project and adjust the filters to view the dashboard."
    )


# ============================================================
# AUDIT SIDEBAR
# ============================================================

st.sidebar.markdown("---")
st.sidebar.subheader("Google Sheets Audit")

if "analysis_results" in st.session_state:
    results = st.session_state["analysis_results"]
    daily_alerts = results.get("daily_alerts", pd.DataFrame())

    if isinstance(daily_alerts, pd.DataFrame) and not daily_alerts.empty:
        for _, row in daily_alerts.iterrows():
            name_col = find_column(
                pd.DataFrame(columns=row.index),
                ["Name", "Agent Name", "Employee Name", "Team Member"],
            )
            date_col = find_column(
                pd.DataFrame(columns=row.index),
                ["Date", "Work Date", "Log Date"],
            )

            name_val = row.get(name_col, "Team Member") if name_col else "Team Member"
            date_val = row.get(date_col, "N/A") if date_col else "N/A"
            score_val = row.get("Productivity (%)", "N/A")

            if pd.notna(score_val):
                score_display = f"{float(score_val):.2f}%"
            else:
                score_display = "N/A"

            st.sidebar.error(
                f"Low Productivity Flag\n\n"
                f"User: {name_val}\n\n"
                f"Date: {date_val}\n\n"
                f"Calculated Productivity: {score_display}"
            )
    else:
        st.sidebar.success(
            "No productivity alerts below 95% were reported."
        )
else:
    st.sidebar.info(
        "Execute tracker analysis to view audit flags."
    )
