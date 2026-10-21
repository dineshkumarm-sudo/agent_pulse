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
