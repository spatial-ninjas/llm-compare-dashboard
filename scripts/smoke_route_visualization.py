"""Smoke-test the reusable route visualization interface.

Run from the repository root:

    python scripts/smoke_route_visualization.py

The script writes route_visualization_test.html, which can be opened in a
browser. The default map uses no online base-map tiles, so the route overlay can
be inspected without relying on OpenStreetMap tile servers.

This smoke test uses synthetic coordinates rather than real Helsinki nodes so
that route overlays and segment highlights are visually easy to inspect.
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dashboard.route_visualization import Coordinate, RouteVisualization


node_coordinates: dict[str, Coordinate] = {
    # Main reference corridor
    "A": (24.9400, 60.1600),
    "B": (24.9410, 60.1600),
    "C": (24.9420, 60.1600),
    "D": (24.9430, 60.1600),

    # Candidate detour below the reference corridor
    "E": (24.9410, 60.1592),
    "F": (24.9420, 60.1592),

    # Separate route to verify multiple layers
    "G": (24.9400, 60.1582),
    "H": (24.9410, 60.1580),
    "I": (24.9420, 60.1582),

    # One endpoint used for a missing-coordinate highlight
    "J": (24.9430, 60.1580),
}


def main() -> None:
    output_path = Path("route_visualization_test.html")

    reference_route = ["A", "B", "C", "D"]
    candidate_detour = ["A", "B", "E", "F", "C", "D"]

    viz = RouteVisualization(
        node_coordinates=node_coordinates,
        metadata={
            "network_id": "toy-route-visualization-smoke-test",
            "description": "Synthetic route layout for testing overlays and highlights",
            "crs": "EPSG:4326",
            "tiles": "disabled",
        },
    )

    # Main comparison: candidate route leaves the reference route and rejoins it.
    viz.add_route(
        route=candidate_detour,
        ground_truth=reference_route,
        color="blue",
        ground_truth_color="green",
        metadata={
            "label": "Candidate detour vs reference",
            "source": "smoke test",
            "origin": "A",
            "destination": "D",
            "note": "Candidate route diverges from the reference at B and rejoins at C.",
        },
    )

    # A separate short route to verify multiple route layers and layer toggling.
    viz.add_route(
        route=["G", "H", "I"],
        color="purple",
        metadata={
            "label": "Separate route layer",
            "source": "smoke test",
            "origin": "G",
            "destination": "I",
            "note": "Separate nearby route used to verify multiple overlays.",
        },
    )

    # Missing coordinates should not crash by default. The missing node should
    # produce a warning marker near the first resolvable point.
    viz.add_route(
        route=["J", "UNKNOWN_NODE"],
        color="gray",
        metadata={
            "label": "Missing-coordinate route",
            "source": "smoke test",
            "origin": "J",
            "destination": "UNKNOWN_NODE",
            "note": "UNKNOWN_NODE should be reported but should not crash rendering.",
        },
    )

    # Highlight the candidate detour as extra/diverging segments.
    for from_node, to_node in [("B", "E"), ("E", "F"), ("F", "C")]:
        viz.add_segment_highlight(
            from_node=from_node,
            to_node=to_node,
            status="extra_segment",
            color="orange",
            dash_array="8",
            metadata={
                "notes": "Smoke test: candidate segment outside reference route",
            },
        )

    # Highlight a missing directed edge on top of an otherwise visible segment.
    viz.add_segment_highlight(
        from_node="G",
        to_node="H",
        status="missing_edge",
        color="red",
        metadata={
            "notes": "Smoke test: missing directed edge highlight",
        },
    )

    # Highlight an unknown endpoint. This should render as a marker because only
    # one endpoint has coordinates.
    viz.add_segment_highlight(
        from_node="J",
        to_node="UNKNOWN_NODE",
        status="unknown_to_node",
        color="red",
        dash_array="6",
        metadata={
            "notes": "Smoke test: one endpoint is missing, should render as marker",
        },
    )

    viz.render(save_path=str(output_path))
    print(f"Map saved to {output_path}")


if __name__ == "__main__":
    main()
