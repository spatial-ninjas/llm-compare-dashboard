"""Network loading helpers for route-finding mode."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from research.network_loader import load_network_bundle_from_gpkg


DEFAULT_EDGES_LAYER = "slimmed_cropped_edges"
DEFAULT_NODES_LAYER = "slimmed_cropped_nodes"


def get_local_network_config() -> dict[str, str]:
    """Return local route-finding network config from environment variables."""
    return {
        "gpkg_path": os.getenv("NETWORK_GPKG_PATH", ""),
        "edges_layer": os.getenv("NETWORK_EDGES_LAYER", DEFAULT_EDGES_LAYER),
        "nodes_layer": os.getenv("NETWORK_NODES_LAYER", DEFAULT_NODES_LAYER),
    }


@st.cache_resource
def load_route_network_bundle():
    """Load and cache the local route-finding NetworkBundle."""
    config = get_local_network_config()

    gpkg_path_value = config["gpkg_path"]
    if not gpkg_path_value:
        raise RuntimeError("NETWORK_GPKG_PATH is not configured.")

    gpkg_path = Path(gpkg_path_value)
    if not gpkg_path.exists():
        raise RuntimeError(f"NETWORK_GPKG_PATH does not exist: {gpkg_path}")

    return load_network_bundle_from_gpkg(
        gpkg_path=gpkg_path,
        edges_layer=config["edges_layer"],
        nodes_layer=config["nodes_layer"],
    )
