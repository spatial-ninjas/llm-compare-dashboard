import streamlit as st
from dotenv import load_dotenv


APP_VERSION = "v0.2.1"

load_dotenv()

from dashboard.db import init_db  # noqa: E402
from dashboard.views.general import render_general_view  # noqa: E402
from dashboard.views.route_finding import render_route_finding_view  # noqa: E402
from dashboard.views.route_history import render_route_history_view  # noqa: E402


st.set_page_config(
    page_title="OpenAI vs Gemini Comparator",
    layout="wide",
)

init_db()

st.title("OpenAI vs Gemini Comparator")

st.sidebar.caption(f"Version: {APP_VERSION}")

mode = st.sidebar.radio(
    "Mode",
    [
        "General prompt comparison",
        "Route finding",
        "Route evaluation history",
    ],
)

if mode == "General prompt comparison":
    st.caption(
        "Send the same prompt to both APIs, compare outputs, and persist history in SQLite."
    )
    render_general_view()

elif mode == "Route evaluation history":
    st.caption(
        "Review saved route evaluations, inspect previous runs, and export route-history data."
    )
    render_route_history_view()

else:
    st.caption(
        "Generate route-finding prompts and evaluate model routes against SSAL-native ground truth."
    )
    render_route_finding_view()
