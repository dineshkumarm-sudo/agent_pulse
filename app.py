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


@st.cache_data(ttl=300, show_spinner=False)
def fetch_sheet_safely(url, sheet_name="Daily_Tracker"):
    """Read a tracker once and reuse it for five minutes to avoid Sheets API quota spikes."""
    client = get_gsheet_client()
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    sheet = client.open_by_key(match.group(1)) if match else client.open_by_url(url)

    # Prefer the exact worksheet tab named in the URL, when supplied.
    gid_match = re.search(r"(?:[?&#])gid=(\d+)", url)
    if gid_match:
        worksheet = sheet.get_worksheet_by_id(int(gid_match.group(1)))
    else:
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


def build_productivity_chart(df, alert_threshold=90, period_label="Selected period"):
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
        title=f"Calculated Productivity · {period_label}",
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


def render_our_shopee_dashboard(df):
    """Render file-based production tracking, ageing alerts, and period summaries."""
    st.markdown("### Our Shopee · File Delivery Dashboard")
    st.caption("Track input files, production deadlines, delivered volumes, and ageing work in progress.")

    if df.empty:
        st.warning("The Our Shopee tracker returned no records. Check the worksheet and service-account access.")
        return

    def get_col(candidates):
        return find_column(df, candidates)

    aliases = {
        "supplier": ["Supplier Name", "Supplier"],
        "file": ["Client File Name", "Client Filename", "File Name", "Client File"],
        "received": ["Input Received Date", "Received Date", "Input Date"],
        "input_skus": ["Input SKU Count", "Input SKUs", "SKU Count", "Received SKU Count"],
        "start": ["Production Start Date", "Production Started Date", "Start Date"],
        "delivery": ["Delivery Date", "Delivered Date", "Date Delivered"],
        "delivered_skus": ["Delivered SKU Count", "Delivered SKUs", "SKU Delivered", "Output SKU Count"],
        "remarks": ["Remarks", "Remark", "Comments", "Notes"],
    }
    cols = {key: get_col(options) for key, options in aliases.items()}
    required = ["file", "received", "input_skus", "start", "delivered_skus"]
    missing = [aliases[key][0] for key in required if cols[key] is None]
    if missing:
        st.error("Some required columns could not be identified: " + ", ".join(missing))
        st.write("Columns found in the tracker:", list(df.columns))
        st.info("Rename the columns to match the requested labels, or share the exact header names so the mapping can be adjusted.")
        st.dataframe(df, use_container_width=True, hide_index=True)
        return

    work = pd.DataFrame(index=df.index)
    for key, col in cols.items():
        work[key] = df[col] if col is not None else ""
    for key in ["received", "start", "delivery"]:
        work[key] = pd.to_datetime(work[key], errors="coerce", dayfirst=True)
    for key in ["input_skus", "delivered_skus"]:
        work[key] = pd.to_numeric(
            work[key].astype(str).str.replace(",", "", regex=False).str.strip(),
            errors="coerce"
        ).fillna(0)
    work["file"] = work["file"].fillna("").astype(str).str.strip()
    work["supplier"] = work["supplier"].fillna("").astype(str).str.strip()
    work["remarks"] = work["remarks"].fillna("").astype(str)
    work["remaining_skus"] = (work["input_skus"] - work["delivered_skus"]).clip(lower=0)
    work["target_days"] = (work["input_skus"] / 100).apply(lambda value: int(value) if value == int(value) else int(value) + 1)
    # The delivery clock starts from Production Start Date, not Input Received Date.
    work["due_date"] = work["start"] + pd.to_timedelta(work["target_days"], unit="D")
    today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()

    def status_for(row):
        # A recorded delivery date means the file has been delivered/closed,
        # even when the delivered SKU count is lower because of duplicates or paused SKUs.
        if pd.notna(row["delivery"]):
            return "Delivered (delivery recorded)"
        if row["input_skus"] > 0 and row["delivered_skus"] >= row["input_skus"]:
            return "Delivered"
        if pd.isna(row["start"]):
            return "Awaiting production start"
        if pd.notna(row["due_date"]) and row["due_date"] < today:
            return "Overdue"
        return "In progress"

    work["Status"] = work.apply(status_for, axis=1)
    work["Days Until Due"] = work["due_date"].apply(
        lambda value: (value - today).days if pd.notna(value) else pd.NA
    )
    work["due_date_display"] = work["due_date"].dt.strftime("%d %b %Y").fillna("—")
    work["received_week"] = work["received"].dt.to_period("W-SUN").dt.start_time
    work["delivered_week"] = work["delivery"].dt.to_period("W-SUN").dt.start_time
    # Use plain YYYY-MM strings to avoid Period/NaT comparison issues in Streamlit Cloud.
    work["received_month"] = work["received"].dt.strftime("%Y-%m").fillna("")
    work["delivered_month"] = work["delivery"].dt.strftime("%Y-%m").fillna("")

    total_inputs = int(work["input_skus"].sum())
    total_delivered = int(work["delivered_skus"].sum())
    overdue = work[work["Status"] == "Overdue"]
    open_work = work[work["Status"].isin(["Overdue", "In progress", "Awaiting production start"])]

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Input Files", int((work["file"] != "").sum()))
    k2.metric("Input SKU Volume", f"{total_inputs:,}")
    k3.metric("Delivered SKU Volume", f"{total_delivered:,}")
    k4.metric("Overdue Files", len(overdue))

    st.markdown("#### 🔔 Delivery Alerts")
    if not overdue.empty:
        st.warning(f"{len(overdue)} file(s) are past their target delivery date and are not fully delivered.")
        alert_view = overdue[["supplier", "file", "input_skus", "delivered_skus", "remaining_skus", "start", "due_date_display", "remarks"]].copy()
        for sku_col in ["input_skus", "delivered_skus", "remaining_skus"]:
            alert_view[sku_col] = alert_view[sku_col].fillna(0).astype(int)
        alert_view["start"] = pd.to_datetime(alert_view["start"], errors="coerce").dt.strftime("%d %b %Y").fillna("")
        alert_view.columns = ["Supplier Name", "Client File Name", "Input SKU Count", "Delivered SKU Count", "Remaining SKUs", "Production Start Date", "Target Delivery Date", "Remarks"]
        st.dataframe(
            alert_view.style.map(
                lambda _: "background-color: #FDE2E2; color: #991B1B; font-weight: bold;"
            , subset=["Client File Name"]),
            use_container_width=True, hide_index=True
        )
    else:
        st.success("No overdue files based on the current tracker data.")
    st.markdown("#### 📊 Inputs & Deliveries")
    st.caption("Filter by year, month, and week. Weeks run Monday through Sunday. Inputs are counted by Input Received Date; deliveries by Delivery Date.")

    year_values = sorted(
        set(work["received"].dropna().dt.year.astype(int).tolist())
        | set(work["delivery"].dropna().dt.year.astype(int).tolist()),
        reverse=True,
    )
    f1, f2, f3 = st.columns(3)
    selected_year = f1.selectbox("Year", ["All"] + year_values, index=0, key="os_summary_year")
    month_options = ["All"] + [f"{m:02d} - {pd.Timestamp(2000, m, 1):%B}" for m in range(1, 13)]
    selected_month = f2.selectbox("Month", month_options, index=0, key="os_summary_month")
    available_week_starts = sorted(
        set(work["received_week"].dropna().tolist())
        | set(work["delivered_week"].dropna().tolist()),
        reverse=True,
    )
    week_options = ["All"] + [
        f"{week:%d %b %Y} – {(week + pd.Timedelta(days=6)):%d %b %Y}"
        for week in available_week_starts
    ]
    selected_week = f3.selectbox("Week (Mon–Sun)", week_options, index=0, key="os_summary_week")

    period_type = st.radio("Summary view", ["Monthly", "Weekly"], horizontal=True, key="os_summary_period_type")
    selected_work = work.copy()
    if selected_year != "All":
        selected_work = selected_work[
            selected_work["received"].dt.year.eq(selected_year)
            | selected_work["delivery"].dt.year.eq(selected_year)
        ]
    if selected_month != "All":
        month_number = int(selected_month[:2])
        selected_work = selected_work[
            selected_work["received"].dt.month.eq(month_number)
            | selected_work["delivery"].dt.month.eq(month_number)
        ]
    if selected_week != "All":
        selected_week_start = available_week_starts[week_options.index(selected_week) - 1]
        selected_work = selected_work[
            selected_work["received_week"].eq(selected_week_start)
            | selected_work["delivered_week"].eq(selected_week_start)
        ]

    if period_type == "Monthly":
        period_keys = sorted(
            set(selected_work["received_month"].loc[selected_work["received_month"] != ""])
            | set(selected_work["delivered_month"].loc[selected_work["delivered_month"] != ""])
        )
        summary_rows = []
        for period in period_keys:
            inputs = selected_work[selected_work["received_month"] == period]
            outputs = selected_work[selected_work["delivered_month"] == period]
            summary_rows.append({
                "Period": pd.to_datetime(period + "-01").strftime("%B %Y"),
                "Input Files": int((inputs["file"] != "").sum()),
                "Input SKU Count": int(inputs["input_skus"].sum()),
                "Delivered Files": int((outputs["delivered_skus"] > 0).sum()),
                "Delivered SKU Count": int(outputs["delivered_skus"].sum()),
                "_sort": period,
            })
    else:
        period_keys = sorted(
            set(selected_work["received_week"].dropna().tolist())
            | set(selected_work["delivered_week"].dropna().tolist())
        )
        summary_rows = []
        for period in period_keys:
            inputs = selected_work[selected_work["received_week"] == period]
            outputs = selected_work[selected_work["delivered_week"] == period]
            summary_rows.append({
                "Period": f"{period:%d %b %Y} – {(period + pd.Timedelta(days=6)):%d %b %Y}",
                "Input Files": int((inputs["file"] != "").sum()),
                "Input SKU Count": int(inputs["input_skus"].sum()),
                "Delivered Files": int((outputs["delivered_skus"] > 0).sum()),
                "Delivered SKU Count": int(outputs["delivered_skus"].sum()),
                "_sort": period,
            })
    if summary_rows:
        summary = pd.DataFrame(summary_rows).sort_values("_sort").drop(columns="_sort")
        total_row = pd.DataFrame([{
            "Period": "TOTAL",
            "Input Files": int(summary["Input Files"].sum()),
            "Input SKU Count": int(summary["Input SKU Count"].sum()),
            "Delivered Files": int(summary["Delivered Files"].sum()),
            "Delivered SKU Count": int(summary["Delivered SKU Count"].sum()),
        }])
        st.dataframe(pd.concat([summary, total_row], ignore_index=True), use_container_width=True, hide_index=True)
    else:
        st.info("No input or delivery records match the selected filters.")

    st.markdown("#### ✨ Monthly Highlights")
    highlight_candidates = selected_work[selected_work["delivery"].notna() & (selected_work["delivered_skus"] > 0)].copy()
    if not highlight_candidates.empty:
        top_delivery = highlight_candidates.sort_values(
            ["delivered_skus", "delivery"], ascending=[False, True]
        ).iloc[0]
        h1, h2 = st.columns(2)
        with h1:
            with st.container(border=True):
                st.caption("🏆 Highest delivery")
                st.markdown(f"**{top_delivery['file'] or 'Unnamed file'}**")
                st.metric("Delivered SKUs", f"{int(top_delivery['delivered_skus']):,}")
                st.caption(pd.Timestamp(top_delivery["delivery"]).strftime("%d %b %Y"))
        highlight_candidates["delivery_days"] = (
            highlight_candidates["delivery"].dt.normalize()
            - highlight_candidates["start"].dt.normalize()
        ).dt.days
        quickest_candidates = highlight_candidates[
            highlight_candidates["start"].notna()
            & highlight_candidates["delivery"].notna()
            & (highlight_candidates["delivery_days"] >= 0)
        ].copy()
        if not quickest_candidates.empty:
            quickest = quickest_candidates.sort_values(
                ["delivery_days", "delivery", "delivered_skus"],
                ascending=[True, True, False],
            ).iloc[0]
            with h2:
                with st.container(border=True):
                    st.caption("⚡ Quickest delivery")
                    st.markdown(f"**{quickest['file'] or 'Unnamed file'}**")
                    duration = int(quickest["delivery_days"])
                    st.metric("Turnaround", "Same day" if duration == 0 else f"{duration} day(s)")
                    st.caption(
                        f"Started {quickest['start']:%d %b %Y} · Delivered {quickest['delivery']:%d %b %Y}"
                    )
        else:
            with h2:
                with st.container(border=True):
                    st.caption("⚡ Quickest delivery")
                    st.info("No valid production start and delivery date pairs are available yet.")
    else:
        st.info("Monthly highlights will appear once files have delivery dates and delivered SKU counts.")

    # Keep open files as compact individual file cards at the bottom of the page.
    st.markdown("#### 📂 View All Open Files")
    if not open_work.empty:
        st.caption(f"{len(open_work)} file(s) are still in progress or awaiting a production start.")
        for _, row in open_work.sort_values(["due_date", "received"], na_position="last").iterrows():
            with st.container(border=True):
                title = str(row["file"]).strip() or "Unnamed client file"
                st.markdown(f"**{title}**")
                card1, card2 = st.columns(2)
                card1.caption("Input Received Date")
                card1.write(row["received"].strftime("%d %b %Y") if pd.notna(row["received"]) else "—")
                card2.caption("SKUs · Input / Delivered")
                card2.write(f"{int(row['input_skus']):,} / {int(row['delivered_skus']):,}")
                st.caption("Remarks")
                remarks = str(row["remarks"]).strip()
                st.write(remarks if remarks else "No remarks")
    else:
        st.success("No open files at the moment.")


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


if selected_project == "Our Shopee":
    if sheet_error:
        st.error(f"Google Sheets connection error: {sheet_error}")
    render_our_shopee_dashboard(df_raw)
    # Continue into the shared Agent Pulse banner and AI chat below.


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
if not df_filtered.empty and threshold is not None:
    notification_df = df_raw.copy() if selected_project == "Superbreakers" else df_filtered.copy()
    notification_df, notification_calculation_ok, _ = calculate_productivity(notification_df)
    notification_date_col = find_column(notification_df, ["Date", "Work Date", "Log Date"])
    if selected_project == "Superbreakers" and notification_date_col:
        notification_dates = parse_date_series(notification_df[notification_date_col])
        now_local = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
        month_start = now_local.replace(day=1)
        next_month_start = month_start + pd.offsets.MonthBegin(1)
        notification_df = notification_df.loc[
            (notification_dates >= month_start) & (notification_dates < next_month_start)
        ].copy()
    if not notification_calculation_ok:
        st.info("Productivity alerts are unavailable until the required source columns are found.")
    else:
        current_prod = parse_productivity(notification_df["Productivity (%)"])
        low_prod_rows = notification_df.loc[current_prod.notna() & (current_prod < threshold)].copy()
        if low_prod_rows.empty:
            if selected_project == "Superbreakers":
                st.success(f"All clear — no productivity entries below {threshold}% for {datetime.datetime.now().strftime('%B %Y')}.")
            else:
                st.success(f"All clear — no productivity entries below {threshold}% in the currently filtered {selected_project} data.")
        else:
            period_note = f" for {datetime.datetime.now().strftime('%B %Y')}" if selected_project == "Superbreakers" else f" for {selected_project}"
            st.warning(f"{len(low_prod_rows)} productivity alert(s): entries below {threshold}%{period_note}.")
            show_cols = [c for c in [
                find_column(low_prod_rows, ["Date", "Work Date", "Log Date"]),
                find_column(low_prod_rows, ["Name", "Agent Name", "Employee Name", "Team Member"]),
                find_column(low_prod_rows, ["New Listings", "New Listing"]),
                find_column(low_prod_rows, ["Listing Update"]), find_hours_column(low_prod_rows), "Productivity (%)"
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
    dashboard_df = df_filtered.copy()
    dashboard_date_col = find_column(dashboard_df, ["Date", "Work Date", "Log Date"])
    productivity_period = "Week"

    if selected_project == "Superbreakers" and dashboard_date_col:
        productivity_period = st.radio(
            "Productivity period", ["Week", "Month"],
            horizontal=True, index=0, key="sb_productivity_period",
        )
        dashboard_dates = parse_date_series(dashboard_df[dashboard_date_col])
        now_local = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
        if productivity_period == "Week":
            period_start = now_local - pd.Timedelta(days=now_local.weekday())
            period_end = period_start + pd.Timedelta(days=7)
            period_caption = f"Current week · {period_start:%d %b}–{(period_end - pd.Timedelta(days=1)):%d %b %Y}"
        else:
            period_start = now_local.replace(day=1)
            period_end = period_start + pd.offsets.MonthBegin(1)
            period_caption = f"Current month · {period_start:%B %Y}"
        dashboard_df = dashboard_df.loc[
            (dashboard_dates >= period_start) & (dashboard_dates < period_end)
        ].copy()
        st.caption(period_caption)

    dashboard_df, dashboard_calculation_ok, dashboard_calculation_note = calculate_productivity(dashboard_df)
    if dashboard_df.empty:
        st.info(f"No records are available for the selected {productivity_period.lower()} period.")
    elif dashboard_calculation_ok:
        build_productivity_chart(
            dashboard_df, PRODUCTIVITY_ALERT_THRESHOLDS.get(selected_project, 90),
            period_label=productivity_period,
        )
        numeric_prod = parse_productivity(dashboard_df["Productivity (%)"])
        valid_prod = numeric_prod.dropna()
        kpi1, kpi2, kpi3 = st.columns(3)
        kpi1.metric("Average Productivity", f"{valid_prod.mean():.2f}%" if not valid_prod.empty else "N/A")
        kpi2.metric("Total Entries", len(dashboard_df))
        new_col = find_column(dashboard_df, ["New Listings", "New Listing"])
        existing_col = find_column(dashboard_df, ["Listing Update"])
        if new_col and existing_col:
            total_new = parse_count(dashboard_df[new_col]).sum()
            total_existing = parse_count(dashboard_df[existing_col]).sum()
            kpi3.metric("Total Listings Processed", f"{total_new + total_existing:,.0f}")
        else:
            kpi3.metric("Total Listings Processed", "N/A")

        st.subheader("Productivity Table")
        st.caption(
            "Red = below 90% | Orange = 90% to below 100% | No warning highlight = "
            "100% or above | N/A = zero/missing hours or missing listing counts."
        )
        st.dataframe(style_productivity_table(dashboard_df), use_container_width=True, hide_index=True)
        st.download_button(
            "Download dashboard data as CSV",
            data=dataframe_for_download(dashboard_df).to_csv(index=False).encode("utf-8"),
            file_name="agent_pulse_productivity.csv",
            mime="text/csv", key="dashboard_productivity_download",
        )
    else:
        st.info(
            "The tracker data is available, but productivity cannot be calculated until the required source columns are found. "
            + dashboard_calculation_note
        )
        st.dataframe(dashboard_df, use_container_width=True, hide_index=True)

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
