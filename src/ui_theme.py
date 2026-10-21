import streamlit as st

def apply_nexus_theme():
    """Injects custom CSS to build the Nexus AI dark graphite aesthetic."""
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

        /* Global Resets */
        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif;
            background-color: #0B0F19 !important;
            color: #E2E8F0 !important;
        }

        /* Sidebar Styling */
        section[data-testid="stSidebar"] {
            background-color: #0d121f !important;
            border-right: 1px solid rgba(255, 255, 255, 0.08) !important;
        }

        /* Graphite Card Glassmorphism */
        .nexus-card {
            background: rgba(17, 24, 39, 0.7);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
            transition: all 0.3s ease;
        }

        .nexus-card:hover {
            border-color: rgba(0, 240, 255, 0.3);
            box-shadow: 0 8px 32px 0 rgba(0, 240, 255, 0.1);
        }

        /* Futuristic Section Header */
        .nexus-header {
            font-size: 1.5rem;
            font-weight: 600;
            letter-spacing: -0.02em;
            background: linear-gradient(135deg, #FFFFFF 0%, #00F0FF 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 1rem;
        }

        /* Metric Pill Badge */
        .nexus-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }

        .badge-cyan {
            background: rgba(0, 240, 255, 0.1);
            color: #00F0FF;
            border: 1px solid rgba(0, 240, 255, 0.3);
        }

        .badge-amber {
            background: rgba(245, 158, 11, 0.1);
            color: #F59E0B;
            border: 1px solid rgba(245, 158, 11, 0.3);
        }

        .badge-green {
            background: rgba(16, 185, 129, 0.1);
            color: #10B981;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        /* Vertical Execution Timeline */
        .timeline-item {
            position: relative;
            padding-left: 28px;
            margin-bottom: 20px;
            border-left: 2px solid rgba(255, 255, 255, 0.1);
        }

        .timeline-item.active {
            border-left: 2px solid #00F0FF;
        }

        .timeline-item.completed {
            border-left: 2px solid #10B981;
        }

        .timeline-status {
            position: absolute;
            left: -7px;
            top: 0;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #0B0F19;
            border: 2px solid rgba(255, 255, 255, 0.3);
        }

        .timeline-item.active .timeline-status {
            background: #00F0FF;
            border-color: #00F0FF;
            box-shadow: 0 0 10px #00F0FF;
        }

        .timeline-item.completed .timeline-status {
            background: #10B981;
            border-color: #10B981;
        }

        /* Streamlit Input Customization */
        .stButton > button {
            background: linear-gradient(135deg, rgba(0, 240, 255, 0.15) 0%, rgba(59, 130, 246, 0.15) 100%) !important;
            border: 1px solid rgba(0, 240, 255, 0.4) !important;
            color: #00F0FF !important;
            border-radius: 8px !important;
            font-weight: 500 !important;
            transition: all 0.3s ease !important;
        }

        .stButton > button:hover {
            background: linear-gradient(135deg, rgba(0, 240, 255, 0.3) 0%, rgba(59, 130, 246, 0.3) 100%) !important;
            box-shadow: 0 0 15px rgba(0, 240, 255, 0.4) !important;
            color: #FFFFFF !important;
        }

        /* Hide Default Streamlit Chrome */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        </style>
    """, unsafe_allow_html=True)


def render_sidebar():
    """Renders the collapsible left sidebar navigation."""
    with st.sidebar:
        st.markdown("""
            <div style="display: flex; align-items: center; gap: 12px; padding: 10px 0 20px 0;">
                <div style="width: 36px; height: 36px; border-radius: 8px; background: linear-gradient(135deg, #00F0FF, #3B82F6); display: flex; align-items: center; justify-content: center; font-weight: bold; color: #000; font-size: 18px;">N</div>
                <div>
                    <div style="font-weight: 700; font-size: 16px; letter-spacing: 0.05em; color: #FFF;">NEXUS AI</div>
                    <div style="font-size: 11px; color: #00F0FF;">OPERATIONS AGENT</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        selected = st.radio(
            "Navigation",
            [
                "Dashboard",
                "Task History",
                "Active Tasks",
                "Automations",
                "Tools & Integrations",
                "Reports & Insights",
                "Settings"
            ],
            label_visibility="collapsed"
        )

        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("""
            <div class="nexus-card" style="padding: 12px;">
                <div style="display: flex; align-items: center; justify-content: space-between;">
                    <span style="font-size: 12px; color: #94A3B8;">System Connection</span>
                    <span class="nexus-badge badge-green">ACTIVE</span>
                </div>
                <div style="font-size: 11px; color: #64748B; margin-top: 6px;">Connected to Enterprise Core</div>
            </div>
        """, unsafe_allow_html=True)

        return selected