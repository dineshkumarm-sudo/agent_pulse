import streamlit as st
import pandas as pd
import re
import datetime
import plotly.express as px
import plotly.graph_objects as go

from src.gsheets_client import get_gsheet_client, analyze_project_productivity
from src.agent_logic import ask_agent_pulse, collate_coo_report
from src.project_config import PROJECT_SHEETS, PROJECT_NAMES, PRODUCTIVITY_ALERT_THRESHOLDS, PCCG_DELIVERY_SHEET_URL
from src.ui_theme import apply_agent_pulse_theme


st.set_page_config(page_title="Agent Pulse", page_icon="⚡", layout="wide")
apply_agent_pulse_theme()

# Center cell contents and headers in Streamlit's table and dataframe views.
st.markdown("""
<style>
div[data-testid="stDataFrame"] [role="gridcell"] > *,
div[data-testid="stDataFrame"] [role="columnheader"] > *,
div[data-testid="stTable"] th,
div[data-testid="stTable"] td {
    text-align: center !important;
    justify-content: center !important;
}
div[data-testid="stDataFrame"] [role="gridcell"] {
    text-align: center !important;
}
</style>
""", unsafe_allow_html=True)



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
        .set_properties(**{"text-align": "center"})
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

@st.cache_data(ttl=300, show_spinner=False)
def fetch_pccg_delivery_safely(url):
    """Read PCCG delivery data while tolerating blank or duplicate worksheet headers."""
    client = get_gsheet_client()
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", url)
    sheet = client.open_by_key(match.group(1)) if match else client.open_by_url(url)

    gid_match = re.search(r"(?:[?&#])gid=(\d+)", url)
    worksheet = (
        sheet.get_worksheet_by_id(int(gid_match.group(1)))
        if gid_match else sheet.get_worksheet(0)
    )
    values = worksheet.get_all_values()
    if not values:
        return pd.DataFrame()

    # get_all_records() fails when the sheet has blank headers or duplicate
    # empty strings. Build the DataFrame directly and ignore blank-header columns.
    headers = [str(value).strip() for value in values[0]]
    keep_indices = [i for i, header in enumerate(headers) if header]
    clean_headers = []
    seen = {}
    for i in keep_indices:
        header = headers[i]
        seen[header] = seen.get(header, 0) + 1
        clean_headers.append(header if seen[header] == 1 else f"{header}_{seen[header]}")

    rows = []
    for row in values[1:]:
        padded = row + [""] * max(0, len(headers) - len(row))
        rows.append([padded[i] for i in keep_indices])
    return pd.DataFrame(rows, columns=clean_headers)


def summarize_pccg_deliveries(delivery_df):
    """Count delivered PCCG rows by delivery date, using all required row-level filters."""
    if delivery_df is None or delivery_df.empty:
        return pd.DataFrame(columns=["_delivery_date", "Delivered SKUs"])

    year_col = find_column(delivery_df, ["Year"])
    date_col = find_column(delivery_df, ["Delivered on"])
    completed_by_col = find_column(delivery_df, ["Completed By"])
    status_col = find_column(delivery_df, ["Status"])
    priority_col = find_column(delivery_df, ["Priority"])

    required = {
        "Year": year_col,
        "Delivered on": date_col,
        "Completed By": completed_by_col,
        "Status": status_col,
        "Priority": priority_col,
    }
    missing = [name for name, col in required.items() if col is None]
    if missing:
        raise ValueError("PCCG delivery sheet is missing required columns: " + ", ".join(missing))

    work = delivery_df.copy()
    year_values = pd.to_numeric(work[year_col], errors="coerce")
    delivery_dates = parse_date_series(work[date_col]).dt.normalize()
    completed_by = work[completed_by_col].fillna("").astype(str).str.strip().str.casefold()
    statuses = work[status_col].fillna("").astype(str).str.strip().str.casefold()

    # Check every required field on the same row; Year is an explicit filter.
    valid = (
        year_values.eq(delivery_dates.dt.year)
        & completed_by.eq("vserve")
        & statuses.eq("delivered")
        & delivery_dates.notna()
    )
    work = work.loc[valid].copy()
    work["_delivery_date"] = delivery_dates.loc[valid]
    work["_priority"] = work[priority_col].fillna("Unspecified").astype(str).str.strip()
    work.loc[work["_priority"].eq(""), "_priority"] = "Unspecified"

    if work.empty:
        return pd.DataFrame(columns=["_delivery_date", "Delivered SKUs"])

    totals = work.groupby("_delivery_date").size().rename("Delivered SKUs").reset_index()
    priority_counts = (
        work.pivot_table(
            index="_delivery_date",
            columns="_priority",
            values=year_col,
            aggfunc="size",
            fill_value=0,
        )
        .add_prefix("Priority: ")
        .reset_index()
    )
    result = totals.merge(priority_counts, on="_delivery_date", how="left")
    return result


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
    """Plot daily New Listings and Listing Updates with both counts in each hover tooltip."""
    date_col = find_column(df, ["Date", "Work Date", "Log Date"])
    new_col = find_column(df, ["New Listings", "New Listing"])
    update_col = find_column(df, ["Listing Update"])
    if not date_col or (not new_col and not update_col):
        st.warning("Activity chart needs a date column and at least one listing activity column.")
        return

    chart_df = df.copy()
    chart_df["_date"] = parse_date_series(chart_df[date_col]).dt.normalize()
    chart_df["_new"] = parse_count(chart_df[new_col]).fillna(0) if new_col else 0
    chart_df["_updates"] = parse_count(chart_df[update_col]).fillna(0) if update_col else 0
    chart_df = chart_df.dropna(subset=["_date"])
    if chart_df.empty:
        st.info("No dated activity records are available for this period.")
        return

    # Aggregate by date so the hover values represent all activity on that date.
    daily = chart_df.groupby("_date", as_index=False)[["_new", "_updates"]].sum()
    daily = daily.sort_values("_date")
    hover_data = daily[["_new", "_updates"]].to_numpy()

    fig = px.line(
        daily, x="_date", y="_new", markers=True,
        custom_data=["_new", "_updates"],
        labels={"_date": "Date", "_new": "New Listings"},
    )
    fig.update_traces(
        name="New Listings",
        hovertemplate=(
            "<b>Date: %{x|%d %b %Y}</b><br>"
            "New Listings: %{customdata[0]:,.0f}<br>"
            "Listing Updates: %{customdata[1]:,.0f}<extra></extra>"
        ),
    )
    fig.add_scatter(
        x=daily["_date"], y=daily["_updates"], mode="lines+markers",
        name="Listing Updates",
        customdata=hover_data,
        hovertemplate=(
            "<b>Date: %{x|%d %b %Y}</b><br>"
            "New Listings: %{customdata[0]:,.0f}<br>"
            "Listing Updates: %{customdata[1]:,.0f}<extra></extra>"
        ),
    )
    fig.update_layout(
        xaxis_title="Date", yaxis_title="Number of listings",
        hovermode="closest", legend_title="Activity",
        margin=dict(l=20, r=20, t=20, b=20),
    )
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

pccg_delivery_df = pd.DataFrame()
pccg_delivery_error = None
if selected_project == "PCCG":
    try:
        pccg_delivery_df = fetch_pccg_delivery_safely(PCCG_DELIVERY_SHEET_URL)
    except Exception as exc:
        pccg_delivery_error = f"{type(exc).__name__}: {exc}"

# Safe default used by AI chat and tracker analysis before dashboard filters render.
df_filtered = df_raw.copy()


# Keep general dashboard spacing and component styling without the AI hero/chat.



# ============================================================
# PRODUCTIVITY CALCULATION
# ============================================================

calculation_ok = False
calculation_note = ""
if not df_filtered.empty and selected_project not in ("Our Shopee", "PCCG"):
    df_filtered, calculation_ok, calculation_note = calculate_productivity(df_filtered)
    if not calculation_ok:
        st.warning(calculation_note)


# ============================================================
# NOTIFICATION CENTER
# ============================================================

st.markdown(f"""<div style="padding: 0 0 .5rem 0;"><div style="font-size:.78rem;font-weight:750;letter-spacing:.12em;text-transform:uppercase;color:#3977ED;">AGENT PULSE · PROJECT OVERVIEW</div><div style="font-size:2rem;font-weight:800;letter-spacing:-.04em;color:#20264B;margin-top:.15rem;">{selected_project}</div><div style="font-size:.95rem;color:#68718A;">Operational performance, delivery status, and team productivity</div></div>""", unsafe_allow_html=True)
st.markdown("### 🔔 Notification Center")

# Keep the current-month New Listings count in the Notification Center.
dashboard_date_col = find_column(df_raw, ["Date", "Work Date", "Log Date"])
all_dates = parse_date_series(df_raw[dashboard_date_col]) if dashboard_date_col else pd.Series(pd.NaT, index=df_raw.index)
month_start_now = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize().replace(day=1)
next_month_start_now = month_start_now + pd.offsets.MonthBegin(1)
current_month_df = df_raw.loc[(all_dates >= month_start_now) & (all_dates < next_month_start_now)]
current_month_new_col = find_column(current_month_df, ["New Listings", "New Listing"])
current_month_new = parse_count(current_month_df[current_month_new_col]).sum() if current_month_new_col else 0
st.caption(f"New Listings Done This Month: {current_month_new:,.0f}")

threshold = PRODUCTIVITY_ALERT_THRESHOLDS.get(selected_project)
if not df_raw.empty and threshold is not None:
    notification_df = df_raw.copy()
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

# Render the Our Shopee dashboard below the Notification Center.
if selected_project == "Our Shopee":
    if sheet_error:
        st.error(f"Google Sheets connection error: {sheet_error}")
    render_our_shopee_dashboard(df_raw)


if selected_project != "Our Shopee":
    # ============================================================
    # DASHBOARD FILTERS
    # ============================================================

    st.markdown("### 🎛️ Dashboard Filters")
    if selected_project == "PCCG":
        report_type = st.radio(
            "Report Type", ["Monthly Report", "Weekly Report"],
            index=0, horizontal=True, key="pccg_report_type",
        )
    else:
        report_type = st.selectbox("Report Type", ["Monthly Report", "Weekly Report"], index=0, key="dashboard_report_type")
    if sheet_error:
        st.error(f"Google Sheets error: {sheet_error}")

    date_col = find_column(df_raw, ["Date", "Work Date", "Log Date"])
    if not df_raw.empty and date_col:
        filter_dates = parse_date_series(df_raw[date_col])
        filter_base = df_raw.copy()
        filter_base["_AP_DATE"] = filter_dates
        valid_dates = filter_base["_AP_DATE"].dropna()
        today_local = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
        current_monday = today_local - pd.Timedelta(days=today_local.weekday())
        current_sunday_exclusive = current_monday + pd.Timedelta(days=7)

        available_years = sorted(valid_dates.dt.year.unique().tolist())
        years = [str(y) for y in available_years]
        if not years:
            years = [str(today_local.year)]
        default_year = str(today_local.year) if str(today_local.year) in years else years[-1]
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            selected_year = st.selectbox("Year", years, index=years.index(default_year), key="dashboard_year")
        months_for_year = sorted(valid_dates[valid_dates.dt.year == int(selected_year)].dt.month.unique().tolist())
        month_labels = {int(m): pd.Timestamp(year=int(selected_year), month=int(m), day=1).strftime("%B") for m in months_for_year}
        month_options = ["All"] + [month_labels[m] for m in months_for_year]
        current_month_label = today_local.strftime("%B")
        default_month = current_month_label if int(selected_year) == today_local.year and current_month_label in month_options else "All"
        with filter_col2:
            selected_month = st.selectbox("Month", month_options, index=month_options.index(default_month), key="dashboard_month")

        week_source = filter_base[filter_base["_AP_DATE"].dt.year == int(selected_year)].copy()
        if selected_month != "All":
            selected_month_number = next((m for m, label in month_labels.items() if label == selected_month), None)
            if selected_month_number is not None:
                week_source = week_source[week_source["_AP_DATE"].dt.month == selected_month_number]

        # Week 1 begins on the month's first calendar day and ends on that Sunday.
        # Each following week runs Monday through Sunday, never crossing into another month.
        week_periods = []
        week_lookup = {}
        for month_number in sorted(week_source["_AP_DATE"].dt.month.dropna().unique().tolist()):
            month_dates = week_source.loc[week_source["_AP_DATE"].dt.month == month_number, "_AP_DATE"]
            month_start = pd.Timestamp(year=int(selected_year), month=int(month_number), day=1)
            next_month_start = month_start + pd.offsets.MonthBegin(1)
            first_sunday_exclusive = month_start + pd.Timedelta(days=(6 - month_start.weekday()) % 7 + 1)
            # Generate every calendar week in the month, even if no tracker row exists for a week.
            period_starts = [month_start]
            next_period_start = first_sunday_exclusive
            while next_period_start < next_month_start:
                period_starts.append(next_period_start)
                next_period_start += pd.Timedelta(days=7)
            for week_number, period_start in enumerate(period_starts, start=1):
                period_end = min(
                    first_sunday_exclusive if week_number == 1 else period_start + pd.Timedelta(days=7),
                    next_month_start,
                )
                month_name = month_start.strftime("%B")
                label = f"Week {week_number}" if selected_month != "All" else f"{month_name} - Week {week_number}"
                week_periods.append((label, period_start, period_end, month_number))
                week_lookup[label] = (period_start, period_end)

        # PCCG already records the reporting week in its source sheet. Use that
        # field directly so selecting Week 4 cannot overlap with Week 5 date ranges.
        pccg_week_col = find_column(filter_base, ["Week"]) if selected_project == "PCCG" else None
        if pccg_week_col:
            week_source = filter_base[filter_base["_AP_DATE"].dt.year == int(selected_year)].copy()
            if selected_month != "All":
                week_source = week_source[week_source["_AP_DATE"].dt.month == selected_month_number]
            pccg_week_values = week_source[pccg_week_col].dropna().astype(str).str.strip().unique().tolist()
            def pccg_week_sort(value):
                match = re.search(r"(\\d+)", value)
                return (int(match.group(1)), value.lower()) if match else (10**6, value.lower())
            pccg_week_values = sorted(pccg_week_values, key=pccg_week_sort)
            week_options = ["All"] + pccg_week_values
            week_lookup = {}
        else:
            week_options = ["All"] + [period[0] for period in week_periods]
        current_month_start = today_local.replace(day=1)
        current_first_sunday_exclusive = current_month_start + pd.Timedelta(days=(6 - current_month_start.weekday()) % 7 + 1)
        if today_local < current_first_sunday_exclusive:
            current_period_start = current_month_start
        else:
            current_period_start = today_local - pd.Timedelta(days=today_local.weekday())
        current_week_number = 1 + sum(
            1 for _, start, _, month_number in week_periods
            if month_number == today_local.month and start < current_period_start
        )
        current_week_label = (
            f"Week {current_week_number}" if selected_month != "All"
            else f"{today_local.strftime('%B')} - Week {current_week_number}"
        )
        default_week = current_week_label if current_week_label in week_options else "All"
        with filter_col3:
            selected_week = st.selectbox("Week", week_options, index=week_options.index(default_week), key="dashboard_week")

        date_mask = filter_base["_AP_DATE"].dt.year == int(selected_year)
        if selected_month != "All":
            date_mask &= filter_base["_AP_DATE"].dt.month == selected_month_number
        if report_type == "Weekly Report" and selected_week != "All":
            if selected_project == "PCCG" and pccg_week_col:
                date_mask &= (
                    filter_base[pccg_week_col].astype(str).str.strip().str.casefold()
                    == selected_week.strip().casefold()
                )
            else:
                selected_week_start, selected_week_end = week_lookup[selected_week]
                date_mask &= (
                    (filter_base["_AP_DATE"] >= selected_week_start)
                    & (filter_base["_AP_DATE"] < selected_week_end)
                )
        df_filtered = filter_base.loc[date_mask].drop(columns=["_AP_DATE"]).copy()
        st.caption("The report type and date filters control both the productivity table and listing chart. Monthly reports use the selected year/month; weekly reports also apply the selected week.")
    elif not df_raw.empty:
        st.warning("A Date column was not found, so Year / Month / Week filters cannot be applied.")
        df_filtered = df_raw.copy()
    else:
        df_filtered = pd.DataFrame()



    # ============================================================
    # DASHBOARD METRICS, TABLE AND CHART
    # ============================================================

    if selected_project == "PCCG" and not df_filtered.empty:
        dashboard_df = df_filtered.copy()
        production_col = find_column(dashboard_df, ["Production / Image Count"])
        hours_col = find_column(dashboard_df, ["Production Hours PCCG"])
        date_display_col = find_column(dashboard_df, ["Date", "Work Date", "Log Date"])
        missing = [
            label for label, col in [
                ("Production / Image Count", production_col),
                ("Production Hours PCCG", hours_col),
                ("Date", date_display_col),
            ] if col is None
        ]
        if missing:
            st.error("PCCG productivity cannot be calculated. Missing required columns: " + ", ".join(missing))
            st.caption("Columns found: " + ", ".join(str(col) for col in dashboard_df.columns))
            st.dataframe(dashboard_df, use_container_width=True, hide_index=True)
        else:
            production = parse_count(dashboard_df[production_col])
            hours = parse_count(dashboard_df[hours_col])
            valid_hours = hours.gt(0)
            dashboard_df["Productivity (%)"] = (
                production / (hours.where(valid_hours) / 8 * 10) * 100
            ).where(production.notna() & valid_hours).round(2)

            total_volume = production.fillna(0).sum()
            total_hours = hours.fillna(0).sum()
            average_productivity = (
                total_volume / (total_hours / 8 * 10) * 100
                if total_hours > 0 else None
            )

            st.markdown("### 📋 PCCG Productivity Table")
            st.caption("Target: 10 production counts per 8 working hours. Productivity is calculated against actual hours recorded.")
            display_columns = [
                col for col in [
                    find_column(dashboard_df, ["Month"]),
                    find_column(dashboard_df, ["Week"]),
                    date_display_col,
                    production_col,
                    hours_col,
                    "Productivity (%)",
                ] if col
            ]
            table_df = dashboard_df[display_columns].copy()

            # Match delivery counts to the exact productivity-table date. Delivery
            # counts are filtered by Year, Delivered on, Completed By=Vserve,
            # and Status=Delivered on the same source row.
            if pccg_delivery_error:
                st.warning(f"PCCG delivery data could not be loaded: {pccg_delivery_error}")
            else:
                try:
                    delivery_summary = summarize_pccg_deliveries(pccg_delivery_df)
                    table_df["_match_date"] = parse_date_series(table_df[date_display_col]).dt.normalize()
                    if not delivery_summary.empty:
                        table_df = table_df.merge(
                            delivery_summary,
                            left_on="_match_date",
                            right_on="_delivery_date",
                            how="left",
                        )
                    else:
                        table_df["Delivered SKUs"] = 0
                    if "Delivered SKUs" not in table_df.columns:
                        table_df["Delivered SKUs"] = 0
                    count_cols = [
                        col for col in table_df.columns
                        if col == "Delivered SKUs" or col.startswith("Priority: ")
                    ]
                    for count_col in count_cols:
                        table_df[count_col] = pd.to_numeric(table_df[count_col], errors="coerce").fillna(0).astype(int)
                    table_df = table_df.drop(
                        columns=[col for col in ["_match_date", "_delivery_date"] if col in table_df.columns]
                    )
                    display_columns.extend(
                        col for col in ["Delivered SKUs"] + sorted(
                            c for c in table_df.columns if c.startswith("Priority: ")
                        ) if col in table_df.columns and col not in display_columns
                    )
                except Exception as exc:
                    st.warning(f"PCCG delivery counts could not be calculated: {type(exc).__name__}: {exc}")
                    table_df["Delivered SKUs"] = "N/A"

            table_df["Productivity (%)"] = table_df["Productivity (%)"].map(
                lambda value: "N/A" if pd.isna(value) else f"{value:.2f}%"
            )
            total_row = {col: "" for col in display_columns}
            total_row[date_display_col] = "TOTAL"
            total_row[production_col] = f"{total_volume:,.0f}"
            total_row[hours_col] = f"{total_hours:,.2f}".rstrip("0").rstrip(".")
            total_row["Productivity (%)"] = f"{average_productivity:.2f}%" if average_productivity is not None else "N/A"
            for count_col in [c for c in display_columns if c == "Delivered SKUs" or c.startswith("Priority: ")]:
                total_row[count_col] = f"{pd.to_numeric(table_df[count_col], errors='coerce').fillna(0).sum():,.0f}"
            table_df = pd.concat([table_df, pd.DataFrame([total_row])], ignore_index=True)
            st.dataframe(table_df, use_container_width=True, hide_index=True)
            st.download_button(
                "Download PCCG productivity as CSV",
                data=table_df.to_csv(index=False).encode("utf-8"),
                file_name="pccg_productivity.csv",
                mime="text/csv",
                key="pccg_productivity_download",
            )

            kpi1, kpi2 = st.columns(2)
            kpi1.metric("Average Productivity", f"{average_productivity:.2f}%" if average_productivity is not None else "N/A")
            kpi2.metric("Total Volume Completed", f"{total_volume:,.0f}")

    elif selected_project != "Our Shopee" and not df_filtered.empty:
        dashboard_df = df_filtered.copy()
        dashboard_df, dashboard_calculation_ok, dashboard_calculation_note = calculate_productivity(dashboard_df)
        if dashboard_df.empty:
            st.info("No records match the selected Year / Month / Week filters.")
        elif dashboard_calculation_ok:
            st.markdown("### 📋 Productivity Table")
            st.caption(
                "Red = below 90% | Orange = 90% to below 100% | No warning highlight = "
                "100% or above | N/A = zero/missing hours or missing listing counts."
            )

            # Resolve the source columns and totals before building the TOTAL row.
            new_col = find_column(dashboard_df, ["New Listings", "New Listing"])
            existing_col = find_column(dashboard_df, ["Listing Update"])
            hours_col = find_hours_column(dashboard_df)
            total_new = parse_count(dashboard_df[new_col]).sum() if new_col else 0
            total_updates = parse_count(dashboard_df[existing_col]).sum() if existing_col else 0

            # Show productivity percentage in the Superbreakers table and CSV.
            date_display_col = find_column(dashboard_df, ["Date", "Work Date", "Log Date"])
            display_columns = [col for col in [date_display_col, new_col, existing_col, hours_col] if col]
            show_productivity = selected_project == "Superbreakers"
            if show_productivity:
                display_columns.append("Productivity (%)")
            table_df = dashboard_df[display_columns].copy()
            total_row = {col: "" for col in display_columns}
            if date_display_col:
                total_row[date_display_col] = "TOTAL"
            for col in [new_col, existing_col, hours_col]:
                if col and col in table_df.columns:
                    total_row[col] = f"{parse_count(table_df[col]).sum():,.0f}"
            if show_productivity:
                total_hours = parse_count(table_df[hours_col]).sum() if hours_col else 0
                if total_hours > 0:
                    total_productivity = (
                        (total_new / 20) + (total_updates / 25)
                    ) * (4 / total_hours) * 100
                    total_row["Productivity (%)"] = f"{total_productivity:.2f}%"
                else:
                    total_row["Productivity (%)"] = "N/A"
                table_df["Productivity (%)"] = parse_productivity(
                    table_df["Productivity (%)"]
                ).map(lambda value: "N/A" if pd.isna(value) else f"{value:.2f}%")
            table_df = pd.concat([table_df, pd.DataFrame([total_row])], ignore_index=True)
            st.dataframe(
                table_df.style.set_properties(**{"text-align": "center"}),
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "Download dashboard data as CSV",
                data=table_df.to_csv(index=False).encode("utf-8"),
                file_name="agent_pulse_productivity.csv",
                mime="text/csv", key="dashboard_productivity_download",
            )

            st.markdown("### Listing Activity Chart")
            build_productivity_chart(dashboard_df, PRODUCTIVITY_ALERT_THRESHOLDS.get(selected_project, 90))

            numeric_prod = parse_productivity(dashboard_df["Productivity (%)"])
            valid_prod = numeric_prod.dropna()

            # Exactly three summary tiles below the chart, reflecting the selected filters.
            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("Average Productivity", f"{valid_prod.mean():.2f}%" if not valid_prod.empty else "N/A")
            kpi2.metric("New Listings", f"{total_new:,.0f}")
            kpi3.metric("Listing Updates", f"{total_updates:,.0f}")




        else:
            st.info(
                "The tracker data is available, but productivity cannot be calculated until the required source columns are found. "
                + dashboard_calculation_note
            )
            st.dataframe(dashboard_df, use_container_width=True, hide_index=True)
    elif selected_project != "Our Shopee":
        st.info("Select a project and adjust the filters to view the dashboard.")


