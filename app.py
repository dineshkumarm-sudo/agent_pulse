
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
