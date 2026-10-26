import streamlit as st


def apply_agent_pulse_theme():
    """Apply Agent Pulse's light, colorful corporate UI styling."""
    st.markdown(
        """
        <style>
        :root {
            --ap-indigo: #20264B;
            --ap-blue: #3977ED;
            --ap-green: #16A875;
            --ap-purple: #A16AE8;
            --ap-coral: #F97360;
            --ap-ink: #202642;
            --ap-muted: #68718A;
            --ap-border: #E5E9F2;
            --ap-surface: #FFFFFF;
            --ap-canvas: #F5F7FC;
        }

        html, body, [data-testid="stAppViewContainer"] {
            color: var(--ap-ink);
            background: var(--ap-canvas);
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }
        [data-testid="stHeader"] { background: rgba(245,247,252,.92); }
        [data-testid="stMainBlockContainer"] {
            max-width: 1500px;
            padding-top: 1.7rem;
            padding-bottom: 2.5rem;
        }
        h1, h2, h3, h4 { color: var(--ap-indigo); letter-spacing: -0.025em; }
        h2, h3 { margin-top: .5rem; }
        p, label, [data-testid="stCaptionContainer"] { color: var(--ap-muted); }

        /* Indigo navigation rail */
        section[data-testid="stSidebar"] {
            background: var(--ap-indigo);
            border-right: 1px solid rgba(255,255,255,.12);
        }
        section[data-testid="stSidebar"] > div {
            background: var(--ap-indigo);
        }
        section[data-testid="stSidebar"] * {
            color: #F7F8FF !important;
            -webkit-text-fill-color: currentColor;
        }
        section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
        section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {
            color: #B8C0DF !important;
            -webkit-text-fill-color: #B8C0DF;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary,
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary *,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] *,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] label * {
            color: #F7F8FF !important;
            -webkit-text-fill-color: #F7F8FF;
        }
        section[data-testid="stSidebar"] [data-testid="stExpander"] {
            background: rgba(255,255,255,.055);
            border: 1px solid rgba(255,255,255,.12);
            border-radius: 14px;
        }
        /* Keep the expander header tinted like the sidebar so its label stays readable. */
        section[data-testid="stSidebar"] [data-testid="stExpander"] details,
        section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
            background: rgba(255,255,255,.055) !important;
            color: #F7F8FF !important;
            -webkit-text-fill-color: #F7F8FF !important;
        }
        section[data-testid="stSidebar"] .stButton > button {
            background: rgba(255,255,255,.08) !important;
            color: #FFFFFF !important;
            border: 1px solid rgba(255,255,255,.14) !important;
            text-align: left;
        }
        section[data-testid="stSidebar"] .stButton > button:hover {
            background: rgba(57,119,237,.38) !important;
            border-color: rgba(255,255,255,.35) !important;
            animation: ap-project-bounce .42s ease;
        }
        /* Hide Streamlit's image hover toolbar, which appears as a white square over project logos. */
        section[data-testid="stSidebar"] [data-testid="stImage"] button,
        section[data-testid="stSidebar"] [data-testid="stImage"] [data-testid*="Toolbar"],
        section[data-testid="stSidebar"] [data-testid="stImage"] [data-testid*="toolbar"] {
            display: none !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }
        /* Subtle bounce on project hover and a purple glow for the active project. */
        @keyframes ap-project-bounce {
            0%, 100% { transform: translateY(0); }
            45% { transform: translateY(-4px); }
            70% { transform: translateY(1px); }
        }
        @keyframes ap-purple-glow {
            0%, 100% { box-shadow: 0 0 0 1px rgba(161,106,232,.7), 0 0 8px rgba(161,106,232,.35); }
            50% { box-shadow: 0 0 0 2px rgba(201,151,255,1), 0 0 15px rgba(161,106,232,.75); }
        }
        section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
            background: rgba(161,106,232,.22) !important;
            border: 1px solid #C49AFF !important;
            color: #FFFFFF !important;
            animation: ap-purple-glow 2s ease-in-out infinite;
        }
        @media (prefers-reduced-motion: reduce) {
            section[data-testid="stSidebar"] .stButton > button:hover,
            section[data-testid="stSidebar"] .stButton > button[kind="primary"] {
                animation: none !important;
            }
        }

        /* Main cards and KPI tiles */
        div[data-testid="stMetric"] {
            background: var(--ap-surface);
            border: 1px solid var(--ap-border);
            border-radius: 16px;
            padding: 1rem 1.15rem;
            box-shadow: 0 3px 12px rgba(32,38,75,.045);
        }
        div[data-testid="stMetric"] label {
            color: var(--ap-muted);
            font-weight: 600;
        }
        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: var(--ap-indigo);
            font-weight: 750;
        }
        div[data-testid="stExpander"] {
            background: var(--ap-surface);
            border: 1px solid var(--ap-border);
            border-radius: 14px;
        }
        div[data-testid="stDataFrame"], div[data-testid="stTable"] {
            border: 1px solid var(--ap-border);
            border-radius: 12px;
            overflow: hidden;
        }
        div[data-testid="stAlert"] { border-radius: 12px; }
        div[data-testid="stDownloadButton"] button,
        div[data-testid="stFormSubmitButton"] button {
            border-radius: 10px;
            font-weight: 600;
        }
        .stButton > button {
            border-radius: 10px;
            font-weight: 600;
            transition: background-color .15s ease, border-color .15s ease;
        }
        .stButton > button[kind="primary"] {
            background: var(--ap-blue) !important;
            border-color: var(--ap-blue) !important;
            color: #FFFFFF !important;
        }
        [data-testid="stSelectbox"] > div > div,
        [data-testid="stMultiSelect"] > div > div,
        [data-testid="stDateInput"] > div > div {
            border-radius: 10px;
            border-color: #D9DFEC;
        }
        hr { border-color: var(--ap-border); }
        #MainMenu { visibility: hidden; }
        footer { visibility: hidden; }

        @media (max-width: 768px) {
            [data-testid="stMainBlockContainer"] {
                padding-top: 1rem;
                padding-left: 1rem;
                padding-right: 1rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
