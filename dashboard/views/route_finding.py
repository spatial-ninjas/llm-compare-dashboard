"""Route-finding evaluation view."""

from __future__ import annotations

import streamlit as st

from dashboard.network import load_route_network_bundle


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

    st.subheader("Network")
    st.write(f"GeoPackage: `{bundle.gpkg_path}`")
    st.write(f"Edges layer: `{bundle.edges_layer}`")
    st.write(f"Nodes layer: `{bundle.nodes_layer}`")
    st.write(f"SSAL hash: `{bundle.ssal_hash}`")
    st.write(f"Node count: `{len(nodes)}`")

    with st.expander("SSAL preview"):
        preview = "\n".join(bundle.ssal_text.splitlines()[:40])
        st.code(preview, language="text")
