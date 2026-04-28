import streamlit as st
from dotenv import load_dotenv


load_dotenv()

from dashboard.db import init_db  # noqa: E402
from dashboard.views.general import render_general_view  # noqa: E402
from dashboard.views.route_finding import render_route_finding_view  # noqa: E402


st.set_page_config(
    page_title="OpenAI vs Gemini Comparator",
    layout="wide",
)

init_db()

st.title("OpenAI vs Gemini Comparator")

mode = st.sidebar.radio(
    "Mode",
    [
        "General prompt comparison",
        "Route-finding evaluation",
    ],
)

if mode == "General prompt comparison":
    st.caption(
        "Send the same prompt to both APIs, compare outputs, and persist history in SQLite."
    )
    render_general_view()
else:
    st.caption(
        "Generate route-finding prompts and evaluate model routes against SSAL-native ground truth."
    )
    render_route_finding_view()
