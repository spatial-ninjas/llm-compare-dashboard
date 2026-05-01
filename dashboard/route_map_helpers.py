from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import streamlit as st

from dashboard.route_visualization import RouteVisualization


SEGMENT_HIGHLIGHT_STYLES = {
    "missing_edge": {
        "color": "red",
        "dash_array": None,
    },
    "unknown_from_node": {
        "color": "red",
        "dash_array": "6",
    },
    "unknown_to_node": {
        "color": "red",
        "dash_array": "6",
    },
    "extra_segment": {
        "color": "orange",
        "dash_array": "8",
    },
}


def parse_path(value: Any) -> list[str]:
    """Parse a JSON/list path value into node IDs."""
    if value is None:
        return []

    if isinstance(value, list):
        return [str(node) for node in value]

    if isinstance(value, tuple):
        return [str(node) for node in value]

    if isinstance(value, str):
        if not value.strip():
            return []

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []

        if isinstance(parsed, list):
            return [str(node) for node in parsed]

    return []


def parse_json_object(value: Any) -> dict[str, Any]:
    """Parse a saved JSON object value into a dictionary."""
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        if not value.strip():
            return {}

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}

        if isinstance(parsed, dict):
            return parsed

    return {}


def path_to_segments(path: list[str]) -> list[tuple[str, str]]:
    """Convert a node path into ordered directed route segments."""
    return list(zip(path, path[1:]))


def missing_edge_set(candidate_validation: dict[str, Any]) -> set[tuple[str, str]]:
    """Return evaluator-reported missing edges as directed segment tuples."""
    missing_edges: set[tuple[str, str]] = set()

    for edge in candidate_validation.get("missing_edges") or []:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            source, target = edge
            missing_edges.add((str(source), str(target)))

    return missing_edges


def build_segment_rows_from_evaluation(
    *,
    candidate_path: list[str],
    ground_truth_path: list[str],
    candidate_validation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build display-only segment rows from evaluator output.

    This does not validate graph edges. It formats evaluator-produced validation
    data for dashboard display and map highlighting.
    """
    reference_segments = set(path_to_segments(ground_truth_path))
    unknown_nodes = {
        str(node)
        for node in candidate_validation.get("unknown_nodes") or []
    }
    missing_edges = missing_edge_set(candidate_validation)

    rows: list[dict[str, Any]] = []

    for index, (from_node, to_node) in enumerate(path_to_segments(candidate_path)):
        segment = (from_node, to_node)
        in_reference_route = segment in reference_segments

        if from_node in unknown_nodes:
            segment_status = "unknown_from_node"
            notes = "Source node was reported as unknown by the evaluator."
        elif to_node in unknown_nodes:
            segment_status = "unknown_to_node"
            notes = "Target node was reported as unknown by the evaluator."
        elif segment in missing_edges:
            segment_status = "missing_edge"
            notes = "Evaluator reported that this directed edge is missing."
        elif in_reference_route:
            segment_status = "ok"
            notes = "Matches the reference route."
        else:
            segment_status = "extra_segment"
            notes = "Valid candidate segment, but not part of the reference route."

        rows.append(
            {
                "index": index,
                "from_node": from_node,
                "to_node": to_node,
                "in_reference_route": in_reference_route,
                "segment_status": segment_status,
                "notes": notes,
            }
        )

    return rows


def add_segment_highlights_to_map(
    *,
    viz: RouteVisualization,
    segment_rows: list[dict[str, Any]],
) -> int:
    """Add invalid/diverging segment overlays to the route map.

    Returns the number of highlights added.
    """
    highlight_count = 0

    for row in segment_rows:
        status = row.get("segment_status")

        if status not in SEGMENT_HIGHLIGHT_STYLES:
            continue

        style = SEGMENT_HIGHLIGHT_STYLES[status]

        viz.add_segment_highlight(
            from_node=str(row.get("from_node")),
            to_node=str(row.get("to_node")),
            status=str(status),
            color=style["color"],
            dash_array=style["dash_array"],
            metadata={
                "notes": row.get("notes", ""),
                "in_reference_route": row.get("in_reference_route"),
            },
        )
        highlight_count += 1

    return highlight_count


def render_highlight_summary(highlight_count: int) -> None:
    """Render a compact explanation for map segment highlights."""
    if highlight_count:
        st.warning(
            f"{highlight_count} invalid or diverging candidate segment(s) "
            "are highlighted on the map."
        )
        st.caption(
            "Map highlighting: red = invalid segment, "
            "red dashed = unknown-node segment, "
            "orange dashed = candidate segment outside the reference route."
        )
    else:
        st.success("No invalid or diverging candidate segments were highlighted on the map.")


def render_map_html_file(
    *,
    html_path: Path,
    height: int = 560,
) -> None:
    """Embed a saved HTML map through st.iframe using a data URL."""
    html_text = html_path.read_text(encoding="utf-8")
    encoded_html = base64.b64encode(html_text.encode("utf-8")).decode("ascii")

    st.iframe(
        f"data:text/html;base64,{encoded_html}",
        height=height,
    )


def safe_map_token(value: Any) -> str:
    """Return a conservative token for temporary map filenames."""
    text = str(value or "unknown")
    return "".join(char if char.isalnum() else "_" for char in text)


def network_edges_from_bundle(bundle: Any) -> list[tuple[str, str, dict[str, Any]]]:
    """Extract drawable graph edges from a loaded NetworkBundle.

    Returned edges are display-only. Route validity remains owned by the
    research evaluator and graph utilities.
    """
    edges: list[tuple[str, str, dict[str, Any]]] = []

    for source, outgoing_edges in bundle.graph.adjacency.items():
        for edge in outgoing_edges:
            attrs = edge.attrs or {}

            edges.append(
                (
                    str(source),
                    str(edge.target),
                    {
                        "edge_name": attrs.get("edge_name") or attrs.get("name") or "",
                        "length": attrs.get("length") or attrs.get("distance") or "",
                    },
                )
            )

    return edges
