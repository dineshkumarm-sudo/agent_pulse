import streamlit as st
import pandas as pd
from src.ui_theme import apply_nexus_theme, render_sidebar
from src.gsheets_client import fetch_daily_tracker_data, analyze_project_productivity
from src.teams_client import send_teams_notification, ping_team_leads_for_report
from src.agent_logic import collate_coo_report
from src.email_client import send_email_to_coo

# Page Configuration
st.set_page_config(page_title="Nexus AI - Command Center", layout="wide", page_icon="⚡")

# Apply Nexus UI Theme
apply_nexus_theme()

# Left Sidebar Component
nav_choice = render_sidebar()

# Main Layout Architecture: Center Workspace (col1) + Right Activity Panel (col2)
col_workspace, col_activity = st.columns([2.2, 1])

# ==========================================
# CENTER WORKSPACE
# ==========================================
with col_workspace:
    st.markdown('<div class="nexus-header">Nexus Command Center</div>', unsafe_allow_html=True)
    st.markdown("""
        <div style="color: #94A3B8; font-size: 14px; margin-bottom: 24px;">
            Welcome back, System Director. Autonomous monitoring engines are active and synced with Google Drive & Teams.
        </div>
    """, unsafe_allow_html=True)

    # 1. Quick Stats Banner
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("""
            <div class="nexus-card">
                <div style="color: #94A3B8; font-size: 12px;">ACTIVE WORKFLOWS</div>
                <div style="font-size: 24px; font-weight: 700; color: #FFF; margin-top: 4px;">2 Running</div>
                <span class="nexus-badge badge-cyan" style="margin-top: 8px;">Tracker & COO Pipeline</span>
            </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
            <div class="nexus-card">
                <div style="color: #94A3B8; font-size: 12px;">SYSTEM HEALTH</div>
                <div style="font-size: 24px; font-weight: 700; color: #10B981; margin-top: 4px;">99.8%</div>
                <span class="nexus-badge badge-green" style="margin-top: 8px;">Optimal</span>
            </div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
            <div class="nexus-card">
                <div style="color: #94A3B8; font-size: 12px;">FLAGGED ALERTS</div>
                <div style="font-size: 24px; font-weight: 700; color: #F59E0B; margin-top: 4px;">Attention Needed</div>
                <span class="nexus-badge badge-amber" style="margin-top: 8px;">Threshold Monitors Active</span>
            </div>
        """, unsafe_allow_html=True)

    # 2. Main Workspace Tabs
    tab_trackers, tab_teams, tab_coo = st.tabs([
        "📊 Productivity & Trackers", 
        "📢 Teams Communication", 
        "✉️ COO Weekly Report Pipeline"
    ])

    # Tab 1: Productivity Tracker
    with tab_trackers:
        st.markdown("### Tracker Operations")
        
        sheet_url = st.text_input(
            "Google Sheet Resource URL",
            value="https://docs.google.com/spreadsheets/d/15hpOWzz9oK6idTrKq0HEaVIwAf-C-5yy_f2fC5Mhtfc/edit"
        )
        
        if st.button("⚡ Execute Tracker Analysis"):
            with st.spinner("Analyzing tracker metrics..."):
                try:
                    raw_df = fetch_daily_tracker_data(sheet_url)
                    analysis = analyze_project_productivity(raw_df, 100.0)
                    
                    st.session_state["processed_df"] = analysis["processed_df"]
                    st.session_state["daily_alerts"] = analysis["daily_alerts"]
                    st.session_state["weekly_alerts"] = analysis["weekly_alerts"]
                    st.session_state["step_tracker_completed"] = True
                    st.success("Analysis complete.")
                except Exception as e:
                    st.error(f"Execution Error: {e}")

        if "processed_df" in st.session_state:
            df = st.session_state["processed_df"]
            
            st.markdown('<div class="nexus-card">', unsafe_allow_html=True)
            st.markdown("#### Execution Summary")
            col_a, col_b = st.columns(2)
            col_a.metric("Total Rows Evaluated", len(df))
            col_b.metric("Low Productivity Records (<100%)", len(st.session_state["daily_alerts"]))
            st.markdown('</div>', unsafe_allow_html=True)

            if not st.session_state["weekly_alerts"].empty:
                st.markdown("""
                    <div class="nexus-card" style="border-color: rgba(245, 158, 11, 0.4);">
                        <span class="nexus-badge badge-amber">WARNING</span>
                        <div style="font-weight: 600; margin-top: 8px; color: #FFF;">Weekly New Listings Dropped Below 50</div>
                        <div style="color: #94A3B8; font-size: 13px;">Immediate follow-up with Team Leads recommended.</div>
                    </div>
                """, unsafe_allow_html=True)
                st.dataframe(st.session_state["weekly_alerts"], use_container_width=True)

            st.markdown("#### Primary Data Matrix")
            st.dataframe(df, use_container_width=True)

    # Tab 2: Teams Communication
    with tab_teams:
        st.markdown("### MS Teams Dispatch Center")
        st.markdown('<div class="nexus-card">', unsafe_allow_html=True)
        st.markdown("#### Request Weekly Updates from Team Leads")
        tl_names = st.text_input("Target Team Leads", "TL-Anup, TL-Vigneshwari")
        
        if st.button("🚀 Dispatch Teams Request"):
            tls = [name.strip() for name in tl_names.split(",")]
            if ping_team_leads_for_report(tls):
                st.session_state["step_teams_completed"] = True
                st.success("Notifications successfully delivered to Teams channel.")
            else:
                st.error("Delivery failed.")
        st.markdown('</div>', unsafe_allow_html=True)

    # Tab 3: COO Report Pipeline
    with tab_coo:
        st.markdown("### Monday COO Executive Email Generator")
        
        st.markdown('<div class="nexus-card">', unsafe_allow_html=True)
        raw_responses = st.text_area(
            "Raw Team Lead Inputs:",
            height=120,
            placeholder="- Anup: Delivered 40 new listings, image upload blocker resolved.\n- Vigneshwari: Updated 130 listings."
        )

        if st.button("✨ Collate Executive Email"):
            if raw_responses.strip():
                metrics_summary = "Tracker analysis available."
                if "processed_df" in st.session_state:
                    metrics_summary = f"Total logs analyzed: {len(st.session_state['processed_df'])}. Low productivity entries flagged: {len(st.session_state['daily_alerts'])}."

                with st.spinner("NEXUS AI is collating and formatting report..."):
                    draft = collate_coo_report(raw_responses, metrics_summary)
                    st.session_state["coo_report_draft"] = draft
                    st.session_state["step_draft_completed"] = True
            else:
                st.warning("Please provide input updates.")
        st.markdown('</div>', unsafe_allow_html=True)

        if "coo_report_draft" in st.session_state:
            st.markdown('<div class="nexus-card" style="border-color: rgba(0, 240, 255, 0.4);">', unsafe_allow_html=True)
            st.markdown("#### Human-in-the-Loop Approval & Review")
            final_subject = st.text_input("Email Subject", value="Weekly Operations Update - Executive Summary")
            editable_draft = st.text_area("Formatted Email Body (Editable):", value=st.session_state["coo_report_draft"], height=250)

            if st.button("🟢 Approve & Deliver to COO"):
                if send_email_to_coo(final_subject, editable_draft):
                    st.session_state["step_email_completed"] = True
                    st.success("Report successfully delivered to COO!")
                    send_teams_notification("✅ **COO Weekly Report Delivered Successfully.**")
            st.markdown('</div>', unsafe_allow_html=True)


# ==========================================
# RIGHT ACTIVITY PANEL
# ==========================================
with col_activity:
    st.markdown("""
        <div class="nexus-card" style="padding: 16px;">
            <div style="font-weight: 600; font-size: 14px; color: #FFF; margin-bottom: 4px;">Task Activity & Execution</div>
            <div style="font-size: 12px; color: #00F0FF;">Live Execution Pipeline</div>
        </div>
    """, unsafe_allow_html=True)

    # Vertical Execution Timeline Steps
    tracker_status = "completed" if st.session_state.get("step_tracker_completed") else "active"
    teams_status = "completed" if st.session_state.get("step_teams_completed") else ("active" if tracker_status == "completed" else "pending")
    draft_status = "completed" if st.session_state.get("step_draft_completed") else ("active" if teams_status == "completed" else "pending")
    email_status = "completed" if st.session_state.get("step_email_completed") else ("active" if draft_status == "completed" else "pending")

    st.markdown(f"""
        <div class="nexus-card">
            <div class="timeline-item {tracker_status}">
                <div class="timeline-status"></div>
                <div style="font-weight: 600; font-size: 13px; color: #FFF;">Google Sheets Audit</div>
                <div style="font-size: 11px; color: #94A3B8;">Analyze daily productivity & flags</div>
            </div>

            <div class="timeline-item {teams_status}">
                <div class="timeline-status"></div>
                <div style="font-weight: 600; font-size: 13px; color: #FFF;">Teams Notification</div>
                <div style="font-size: 11px; color: #94A3B8;">Gather TL weekly updates</div>
            </div>

            <div class="timeline-item {draft_status}">
                <div class="timeline-status"></div>
                <div style="font-weight: 600; font-size: 13px; color: #FFF;">AI Executive Synthesis</div>
                <div style="font-size: 11px; color: #94A3B8;">Collate and format draft</div>
            </div>

            <div class="timeline-item {email_status}">
                <div class="timeline-status"></div>
                <div style="font-weight: 600; font-size: 13px; color: #FFF;">COO Report Dispatch</div>
                <div style="font-size: 11px; color: #94A3B8;">Human approval & email send</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # System Logs Panel
    st.markdown("""
        <div class="nexus-card">
            <div style="font-weight: 600; font-size: 12px; color: #94A3B8; margin-bottom: 8px;">SYSTEM LOGS</div>
            <div style="font-family: monospace; font-size: 10px; color: #64748B; line-height: 1.6;">
                [SYS_INIT] Engine active.<br>
                [AUTH] Google Drive API connected.<br>
                [HOOK] Teams webhook ready.<br>
                [LLM] GPT-4o model ready.
            </div>
        </div>
    """, unsafe_allow_html=True)