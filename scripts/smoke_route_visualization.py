"""Smoke-test the reusable route visualization interface.

Run from the repository root:

    python scripts/smoke_route_visualization.py

The script writes route_visualization_test.html, which can be opened in a
browser. The default map uses no online base-map tiles, so the route overlay can
be inspected without relying on OpenStreetMap tile servers.
"""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from dashboard.route_visualization import Coordinate, RouteVisualization


node_coordinates: dict[str, Coordinate] = {
    # Laivurinkatu vertical segment
    "1379551695": (24.94153, 60.15873),
    "1379551742": (24.94107, 60.15831),
    "1011022232": (24.94105, 60.15828),
    "6485238714": (24.94104, 60.15825),
    "6485238715": (24.94107, 60.15831),

    # Laivurinkatu / nearby continuation
    "1011022165": (24.94207, 60.15925),
    "1011021999": (24.94212, 60.15938),
    "1011022077": (24.94211, 60.15942),
    "1011022138": (24.94211, 60.15942),
    "250658336": (24.94204, 60.15993),

    # Tehtaankatu segment
    "151033339": (24.94100, 60.15803),
    "6485510974": (24.94056, 60.15801),
    "1379511287": (24.94056, 60.15801),
    "941399511": (24.93982, 60.15798),

    # Merimiehenkatu / nearby comparison points
    "1007051492": (24.94269, 60.16201),
    "1007051348": (24.94277, 60.16207),
    "1377940914": (24.94290, 60.16213),
    "434463660": (24.94322, 60.16224),
    "1377940920": (24.94332, 60.16228),
}


def main() -> None:
    output_path = Path("route_visualization_test.html")

    viz = RouteVisualization(
        node_coordinates=node_coordinates,
        metadata={
            "network_id": "southern-helsinki-slimmed-cropped",
            "network_name": "Southern Helsinki slimmed cropped network",
            "description": "Small visualization subset from actual SSAL node coordinates",
            "gpkg_name": "osm_southern_helsinki_slimmed_cropped.gpkg",
            "crs": "EPSG:4326",
        },
    )

    viz.add_route(
        route=[
            "1379551695",
            "1379551742",
            "1011022232",
            "6485238714",
        ],
        color="blue",
        metadata={
            "label": "Example route 1: basic route drawing",
            "source": "example",
            "origin": "1379551695",
            "destination": "6485238714",
            "note": "Visualization-only example. Edge validity is not guaranteed.",
        },
    )

    viz.add_route(
        route=[
            "1011021999",
            "1011022077",
            "1011022138",
            "250658336",
        ],
        ground_truth=[
            "1011021999",
            "1011022165",
            "1011022232",
            "6485238715",
            "250658336",
        ],
        color="purple",
        ground_truth_color="green",
        metadata={
            "label": "Example route 2: comparison overlay test",
            "source": "example",
            "origin": "1011021999",
            "destination": "250658336",
            "note": "Model and ground-truth routes are intentionally different.",
        },
    )

    viz.add_route(
        route=[
            "151033339",
            "6485510974",
            "1379511287",
            "941399511",
        ],
        color="darkred",
        metadata={
            "label": "Example route 3: multi-route overlay test",
            "source": "example",
            "origin": "151033339",
            "destination": "941399511",
            "note": "Visualization-only example for testing multiple routes.",
        },
    )

    viz.add_route(
        route=[
            "1007051492",
            "1007051348",
            "1377940914",
            "434463660",
            "1377940920",
        ],
        ground_truth=[
            "1007051492",
            "1377940914",
            "1377940920",
        ],
        color="orange",
        ground_truth_color="green",
        metadata={
            "label": "Example route 4: distant comparison route",
            "source": "example",
            "origin": "1007051492",
            "destination": "1377940920",
            "note": "Used for testing route separation and labels.",
        },
    )

    # Missing coordinates should not crash by default. A warning marker is
    # added at the first resolvable route coordinate.
    viz.add_route(
        route=[
            "1379551695",
            "UNKNOWN_NODE",
            "1011022232",
        ],
        color="gray",
        metadata={
            "label": "Example route 5: missing coordinate handling",
            "source": "example",
            "note": "UNKNOWN_NODE should be reported but should not crash rendering.",
        },
    )

    viz.render(save_path=str(output_path))
    print(f"Map saved to {output_path}")


if __name__ == "__main__":
    main()
