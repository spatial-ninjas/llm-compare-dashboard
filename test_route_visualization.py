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


# Example route 1: basic route drawing
model_route_1 = [
    "1379551695",
    "1379551742",
    "1011022232",
    "6485238714",
]

route_metadata_1 = {
    "label": "Example route 1: basic route drawing",
    "source": "example",
    "origin": "1379551695",
    "destination": "6485238714",
    "valid_path": None,
    "exact_path_match": None,
    "is_shortest_path": None,
    "note": "Visualization-only example. Node IDs are real, but edge validity is not guaranteed.",
}


# Example route 2: route with different ground-truth overlay
model_route_2 = [
    "1011021999",
    "1011022077",
    "1011022138",
    "250658336",
]

ground_truth_route_2 = [
    "1011021999",
    "1011022165",
    "1011022232",
    "6485238715",
    "250658336",
]

route_metadata_2 = {
    "label": "Example route 2: comparison overlay test",
    "source": "example",
    "origin": "1011021999",
    "destination": "250658336",
    "valid_path": None,
    "exact_path_match": None,
    "is_shortest_path": None,
    "note": "Model and ground-truth routes are intentionally different to test overlay behavior.",
}


# Example route 3: separate nearby route for multiple overlays
model_route_3 = [
    "151033339",
    "6485510974",
    "1379511287",
    "941399511",
]

route_metadata_3 = {
    "label": "Example route 3: multi-route overlay test",
    "source": "example",
    "origin": "151033339",
    "destination": "941399511",
    "valid_path": None,
    "exact_path_match": None,
    "is_shortest_path": None,
    "note": "Visualization-only example for testing multiple route rendering.",
}


# Example route 4: distant comparison route
model_route_4 = [
    "1007051492",
    "1007051348",
    "1377940914",
    "434463660",
    "1377940920",
]

ground_truth_route_4 = [
    "1007051492",
    "1377940914",
    "1377940920",
]

route_metadata_4 = {
    "label": "Example route 4: distant comparison route",
    "source": "example",
    "origin": "1007051492",
    "destination": "1377940920",
    "valid_path": None,
    "exact_path_match": None,
    "is_shortest_path": None,
    "note": "Used for testing route separation and labels. Edge validity is not guaranteed.",
}


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
    route=model_route_1,
    metadata=route_metadata_1,
)

viz.add_route(
    route=model_route_2,
    ground_truth=ground_truth_route_2,
    metadata=route_metadata_2,
)

viz.add_route(
    route=model_route_3,
    metadata=route_metadata_3,
)

viz.add_route(
    route=model_route_4,
    ground_truth=ground_truth_route_4,
    metadata=route_metadata_4,
)

viz.render(save_path="route_visualization_test.html")
