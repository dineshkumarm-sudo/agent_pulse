
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

def find_column(df, candidates):
    """Find a column even if its capitalization or spacing differs."""
    normalized = {
        re.sub(r"[^a-z0-9]", "", str(col).lower()): col
        for col in df.columns
    }

    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]", "", candidate.lower())
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
    """Convert production counts into numbers."""
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.strip(),
        errors="coerce",
    )


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
    """Build a chart with productivity, production count and task hover data."""

    productivity_col = find_column(
        df,
        ["Productivity (%)", "Productivity", "Productivity Percent"],
    )
    date_col = find_column(
        df,
        ["Date", "Work Date", "Log Date"],
    )
    count_col = find_column(
        df,
        [
            "Production Count",
            "Production",
            "Production Qty",
            "Production Quantity",
            "Completed Count",
            "Completed SKUs",
            "SKUs Completed",
            "SKU Count",
            "Product Count",
            "Total SKUs",
            "Quantity Completed",
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
            "The productivity chart needs a Productivity (%) column "
            "in your Google Sheet."
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
        x_col = "_chart_index"
        chart_df["_chart_index"] = range(1, len(chart_df) + 1)
        x_title = "Record"

    chart_df = chart_df.dropna(subset=["_chart_productivity"])

    if chart_df.empty:
        st.warning("No valid productivity values are available to chart.")
        return

    # Prepare production counts and task labels for hover information.
    if count_col:
        chart_df["_chart_production_count"] = parse_count(
            chart_df[count_col]
        )
        count_label = "_chart_production_count"
    else:
        count_label = None

    if task_col:
        chart_df["_chart_task"] = (
            chart_df[task_col].fillna("Not specified").astype(str)
        )
        task_label = "_chart_task"
    else:
        chart_df["_chart_task"] = "Task type not available in sheet"
        task_label = "_chart_task"

    chart_df["_chart_date_label"] = (
        chart_df[x_col].astype(str)
        if x_col == "_chart_index"
        else chart_df[x_col].dt.strftime("%d %b %Y")
    )

    st.subheader("Productivity Trend Chart")

    if not count_col:
        st.info(
            "I couldn't identify a production-count column. "
            "The chart will show productivity and task type. "
            "To display production counts on hover, your sheet needs "
            "a production-count field."
        )

    if not task_col:
        st.info(
            "I couldn't identify a task-type column. "
            "Add a column such as Task Type with values like "
            "'New Listings' and 'Listing Update' to show task details."
        )

    # One series per task type, so both activities can be distinguished.
    fig = px.line(
        chart_df,
        x=x_col,
        y="_chart_productivity",
        color=task_label,
        markers=True,
        custom_data=[
            "_chart_date_label",
            "_chart_task",
        ] + ([count_label] if count_label else []),
        labels={
            x_col: x_title,
            "_chart_productivity": "Productivity (%)",
            task_label: "Task Type",
        },
        title="Productivity by Date and Task",
    )

    if count_label:
        fig.update_traces(
            hovertemplate=(
                "<b>Productivity: %{y:.2f}%</b><br>"
                "Date: %{customdata[0]}<br>"
                "Task: %{customdata[1]}<br>"
                "Production Count: %{customdata[2]:,.0f}"
                "<extra></extra>"
            )
        )
    else:
        fig.update_traces(
            hovertemplate=(
                "<b>Productivity: %{y:.2f}%</b><br>"
                "Date: %{customdata[0]}<br>"
                "Task: %{customdata[1]}"
                "<extra></extra>"
            )
        )

    fig.update_layout(
        xaxis_title=x_title,
        yaxis_title="Productivity (%)",
        hovermode="closest",
        legend_title="Task Type",
        margin=dict(l=20, r=20, t=60, b=20),
    )

    st.plotly_chart(fig, use_container_width=True)


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
        placeholder=(
            "Bring last week's Superbreakers productivity data"
        ),
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

        # Retrieve previous-week data when explicitly requested.
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
                    "so the records could not be filtered by week."
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

        # Only attach a table for requests that ask to retrieve/show data.
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
                table,
                use_container_width=True,
                hide_index=True,
            )

            st.download_button(
                "Download data as CSV",
                data=table.to_csv(index=False).encode("utf-8"),
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

    if "Year" in df_raw.columns:
        sheet_years = [
            str(value)
            for value in df_raw["Year"].dropna().unique()
            if str(value).strip()
        ]
        combined_years = sorted(set(default_years + sheet_years))
    else:
        combined_years = default_years

    years = ["All"] + combined_years

    months = (
        ["All"] + sorted(df_raw["Month"].dropna().astype(str).unique())
        if "Month" in df_raw.columns
        else ["All"]
    )

    weeks = (
        ["All"] + sorted(df_raw["Week"].dropna().astype(str).unique())
        if "Week" in df_raw.columns
        else ["All"]
    )

    with filter_col1:
        selected_year = st.selectbox("Year", years)

    with filter_col2:
        selected_month = st.selectbox("Month", months)

    with filter_col3:
        selected_week = st.selectbox("Week", weeks)

    df_filtered = df_raw.copy()

    if "Year" in df_filtered.columns and selected_year != "All":
        df_filtered = df_filtered[
            df_filtered["Year"].astype(str) == selected_year
        ]

    if "Month" in df_filtered.columns and selected_month != "All":
        df_filtered = df_filtered[
            df_filtered["Month"].astype(str) == selected_month
        ]

    if "Week" in df_filtered.columns and selected_week != "All":
        df_filtered = df_filtered[
            df_filtered["Week"].astype(str) == selected_week
        ]

else:
    df_filtered = pd.DataFrame()


# ============================================================
# RUN TRACKER ANALYSIS
# ============================================================

if st.button("Execute Tracker Analysis", type="primary"):
    if df_filtered.empty:
        st.warning("No data matches the selected filters.")
    else:
        try:
            results = analyze_project_productivity(df_filtered)
            st.session_state["analysis_results"] = results
            st.session_state["active_df"] = results["processed_df"]
            st.success("Tracker analysis completed.")
        except Exception as exc:
            st.error(
                f"Analysis failed: {type(exc).__name__}: {exc}"
            )


# ============================================================
# DASHBOARD METRICS AND INTERACTIVE CHART
# ============================================================

if not df_filtered.empty:
    productivity_col = find_column(
        df_filtered,
        ["Productivity (%)", "Productivity", "Productivity Percent"],
    )

    if productivity_col:
        numeric_prod = parse_productivity(
            df_filtered[productivity_col]
        )
        valid_prod = numeric_prod.dropna()

        if not valid_prod.empty:
            avg_prod = valid_prod.mean()

            kpi1, kpi2, kpi3 = st.columns(3)

            kpi1.metric(
                "Average Productivity",
                f"{avg_prod:.2f}%",
            )

            kpi2.metric(
                "Total Entries",
                len(df_filtered),
            )

            count_col = find_column(
                df_filtered,
                [
                    "Production Count",
                    "Production",
                    "Production Qty",
                    "Production Quantity",
                    "Completed Count",
                    "Completed SKUs",
                    "SKUs Completed",
                    "SKU Count",
                    "Product Count",
                    "Total SKUs",
                    "Quantity Completed",
                ],
            )

            if count_col:
                total_production = parse_count(
                    df_filtered[count_col]
                ).sum()
                kpi3.metric(
                    "Total Production Count",
                    f"{total_production:,.0f}",
                )
            else:
                kpi3.metric("Total Production Count", "Column not found")

    build_productivity_chart(df_filtered)

    with st.expander("View filtered tracker data"):
        st.dataframe(
            df_filtered,
            use_container_width=True,
            hide_index=True,
        )
else:
    st.info("Select a project and adjust the filters to view the dashboard.")


# ============================================================
# AUDIT SIDEBAR
# ============================================================

st.sidebar.markdown("---")
st.sidebar.subheader("Google Sheets Audit")

if "analysis_results" in st.session_state:
    results = st.session_state["analysis_results"]
    daily_alerts = results.get("daily_alerts", pd.DataFrame())

    if not daily_alerts.empty:
        for _, row in daily_alerts.iterrows():
            name_val = row.get("Name", "Team Member")
            date_val = row.get("Date", "N/A")
            score_val = row.get("Productivity (%)", "N/A")

            st.sidebar.warning(
                f"Low Productivity Flag\n\n"
                f"User: {name_val}\n\n"
                f"Date: {date_val}\n\n"
                f"Score: {score_val}%"
            )
    else:
        st.sidebar.success("No productivity alerts were reported.")
else:
    st.sidebar.info("Execute tracker analysis to view audit flags.")
