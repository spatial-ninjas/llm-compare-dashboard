"""Network loading helpers for route-finding mode."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
from research.network_loader import (
    fetch_or_reuse_cached_file,
    load_network_bundle_from_gpkg,
)


DEFAULT_GPKG_FILENAME = "network.gpkg"
DEFAULT_EDGES_LAYER = "slimmed_cropped_edges"
DEFAULT_NODES_LAYER = "slimmed_cropped_nodes"
DEFAULT_CACHE_DIR = ".cache/network"


def get_network_config() -> dict[str, str]:
    """Return route-finding network configuration from environment variables."""
    return {
        "gpkg_path": os.getenv("NETWORK_GPKG_PATH", ""),
        "gpkg_url": os.getenv("NETWORK_GPKG_URL", ""),
        "gpkg_sha256": os.getenv("NETWORK_GPKG_SHA256", ""),
        "cache_dir": os.getenv("NETWORK_CACHE_DIR", DEFAULT_CACHE_DIR),
        "edges_layer": os.getenv("NETWORK_EDGES_LAYER", DEFAULT_EDGES_LAYER),
        "nodes_layer": os.getenv("NETWORK_NODES_LAYER", DEFAULT_NODES_LAYER),
    }


def resolve_network_gpkg_path(config: dict[str, str]) -> Path:
    """Resolve the GeoPackage path from local config or remote cache."""
    gpkg_path_value = config["gpkg_path"]

    if gpkg_path_value:
        gpkg_path = Path(gpkg_path_value)
        if gpkg_path.exists():
            return gpkg_path

    gpkg_url = config["gpkg_url"]
    if gpkg_url:
        cache_path = build_network_cache_path(
            url=gpkg_url,
            cache_dir=config["cache_dir"],
            configured_path=gpkg_path_value,
        )

        expected_sha256 = config["gpkg_sha256"] or None

        try:
            return fetch_or_reuse_cached_file(
                url=gpkg_url,
                cache_path=cache_path,
                expected_sha256=expected_sha256,
            )
        except ValueError as error:
            raise RuntimeError(
                "Failed to fetch remote GeoPackage because checksum verification failed. "
                f"{error}"
            ) from error
        except Exception as error:
            raise RuntimeError(
                "Failed to fetch or reuse remote GeoPackage from NETWORK_GPKG_URL. "
                f"URL: {gpkg_url}. Error: {error}"
            ) from error

    if gpkg_path_value:
        raise RuntimeError(
            "NETWORK_GPKG_PATH is configured but does not exist, and "
            "NETWORK_GPKG_URL is not configured. "
            f"Missing local file: {gpkg_path_value}"
        )

    raise RuntimeError(
        "Route network is not configured. Set NETWORK_GPKG_PATH to an existing "
        "local GeoPackage file, or set NETWORK_GPKG_URL for remote loading."
    )



def build_network_cache_path(
    url: str,
    cache_dir: str,
    configured_path: str,
) -> Path:
    """Return the local cache path for a remotely fetched GeoPackage."""
    if configured_path:
        filename = Path(configured_path).name
    else:
        filename = Path(urlparse(url).path).name

    if not filename:
        filename = DEFAULT_GPKG_FILENAME

    return Path(cache_dir) / filename


@st.cache_resource
def load_route_network_bundle():
    """Load and cache the route-finding NetworkBundle."""
    config = get_network_config()
    gpkg_path = resolve_network_gpkg_path(config)

    return load_network_bundle_from_gpkg(
        gpkg_path=gpkg_path,
        edges_layer=config["edges_layer"],
        nodes_layer=config["nodes_layer"],
    )
