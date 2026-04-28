"""Route-finding evaluation view."""

from __future__ import annotations

import streamlit as st

from dashboard.network import load_route_network_bundle
from dashboard.route_prompts import (
    DEFAULT_ROUTE_PROMPT_TEMPLATE,
    build_route_prompt,
)


def render_route_finding_view() -> None:
    """Render the route-finding evaluation view."""
    st.header("Route-finding evaluation")
    st.caption(
        "Load the SSAL-native route network and prepare route-finding evaluation."
    )

    try:
        bundle = load_route_network_bundle()
    except Exception as exc:
        st.error(f"Failed to load route network: {exc}")
        st.info(
            "Check NETWORK_GPKG_PATH, NETWORK_EDGES_LAYER, and "
            "NETWORK_NODES_LAYER in your .env file."
        )
        return

    nodes = bundle.graph.nodes()

    st.subheader("Route task")

    col1, col2 = st.columns(2)

    with col1:
        origin = st.selectbox("Origin node", nodes, index=0)

    with col2:
        destination_index = 1 if len(nodes) > 1 else 0
        destination = st.selectbox(
            "Destination node",
            nodes,
            index=destination_index,
        )

    if origin == destination:
        st.warning("Origin and destination should be different.")
        return

    st.subheader("Prompt template")

    template = st.text_area(
        "Route prompt template",
        value=DEFAULT_ROUTE_PROMPT_TEMPLATE,
        height=360,
        help=(
            "Available placeholders: {origin}, {destination}, {ssal_text}. "
            "Escape literal JSON braces as {{ and }}."
        ),
    )

    try:
        prompt = build_route_prompt(
            ssal_text=bundle.ssal_text,
            origin=origin,
            destination=destination,
            template=template,
        )
    except KeyError as exc:
        st.error(f"Prompt template is missing or has an unknown placeholder: {exc}")
        return
    except ValueError as exc:
        st.error(f"Prompt template formatting failed: {exc}")
        return

    st.subheader("Generated prompt")

    st.caption(
        "This is the full prompt that will be sent to the models in the next stage."
    )

    st.text_area(
        "Generated route prompt",
        value=prompt,
        height=420,
    )

    st.download_button(
        "Download generated prompt",
        data=prompt,
        file_name=f"route_prompt_{origin}_to_{destination}.txt",
        mime="text/plain",
        width="stretch",
    )

    st.subheader("Network")
    st.write(f"GeoPackage: `{bundle.gpkg_path}`")
    st.write(f"Edges layer: `{bundle.edges_layer}`")
    st.write(f"Nodes layer: `{bundle.nodes_layer}`")
    st.write(f"SSAL hash: `{bundle.ssal_hash}`")
    st.write(f"Node count: `{len(nodes)}`")

    with st.expander("SSAL preview"):
        preview = "\n".join(bundle.ssal_text.splitlines()[:40])
        st.code(preview, language="text")
