from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import folium


Coordinate = tuple[float, float]  # (longitude, latitude)


@dataclass
class RouteLayer:
    route: list[str]
    route_coordinates: list[Coordinate]
    ground_truth: list[str] | None = None
    ground_truth_coordinates: list[Coordinate] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RouteVisualization:
    """Folium-based route visualization interface."""

    def __init__(
        self,
        node_coordinates: dict[str, Coordinate],
        metadata: dict[str, Any] | None = None,
    ):
        self.node_coordinates = node_coordinates
        self.metadata = metadata or {}
        self.routes: list[RouteLayer] = []

    def add_route(
        self,
        route: list[str],
        *,
        ground_truth: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        route_coordinates = self._resolve_coordinates(route, label="route")

        ground_truth_coordinates = None
        if ground_truth is not None:
            ground_truth_coordinates = self._resolve_coordinates(
                ground_truth,
                label="ground truth",
            )

        self.routes.append(
            RouteLayer(
                route=route,
                route_coordinates=route_coordinates,
                ground_truth=ground_truth,
                ground_truth_coordinates=ground_truth_coordinates,
                metadata=metadata or {},
            )
        )

    def _resolve_coordinates(
        self,
        route: list[str],
        *,
        label: str,
    ) -> list[Coordinate]:
        missing_nodes = [
            node_id for node_id in route if node_id not in self.node_coordinates
        ]

        if missing_nodes:
            raise ValueError(f"Missing coordinates for {label} nodes: {missing_nodes}")

        return [self.node_coordinates[node_id] for node_id in route]

    def _format_metadata_html(self, metadata: dict[str, Any], title: str) -> str:
        """Formats a metadata dictionary into a simple HTML table for Folium popups/tooltips."""
        if not metadata:
            return f"<b>{title}</b>"
            
        html = f"<b>{title}</b><br><table style='width: 100%; border-collapse: collapse; font-size: 12px;'>"
        for key, value in metadata.items():
            html += f"<tr><td style='padding-right: 8px; font-weight: bold;'>{key}:</td><td>{value}</td></tr>"
        html += "</table>"
        return html

    def render(self, save_path: str | None = None) -> folium.Map:
        """Renders the map with routes."""
        # All points to determine map bounds
        all_lats, all_lons = [], []
        
        for layer in self.routes:
            for lon, lat in layer.route_coordinates:
                all_lats.append(lat)
                all_lons.append(lon)
            if layer.ground_truth_coordinates:
                for lon, lat in layer.ground_truth_coordinates:
                    all_lats.append(lat)
                    all_lons.append(lon)

        # If no routes were added, use all node_coordinates
        if not all_lats and self.node_coordinates:
            all_lats = [lat for lon, lat in self.node_coordinates.values()]
            all_lons = [lon for lon, lat in self.node_coordinates.values()]

        # Initialize and fit map
        if all_lats and all_lons:
            center_lat = sum(all_lats) / len(all_lats)
            center_lon = sum(all_lons) / len(all_lons)
            m = folium.Map(location=[center_lat, center_lon], zoom_start=15)
            m.fit_bounds([[min(all_lats), min(all_lons)], [max(all_lats), max(all_lons)]])
        else:
            m = folium.Map(location=[0, 0], zoom_start=2)

        # Add network-level metadata to the map as a fixed HTML overlay
        if self.metadata:
            network_info = self._format_metadata_html(self.metadata, "Network Metadata")
            
            fixed_html = f"""
            <div style="
                position: fixed; 
                bottom: 50px; 
                left: 50px; 
                width: 250px; 
                background-color: white; 
                padding: 10px; 
                border: 2px solid black; 
                border-radius: 5px; 
                z-index: 9999; 
                opacity: 0.8;
            ">
                {network_info}
            </div>
            """            
            m.get_root().html.add_child(folium.Element(fixed_html))

        # Draw routes
        for index, layer in enumerate(self.routes, start=1):
            label = layer.metadata.get("label", f"Route {index}")
            
            # Create a FeatureGroup for toggling layers easily
            fg = folium.FeatureGroup(name=label)

            tooltip_html = self._format_metadata_html(layer.metadata, label)

            # Draw Ground Truth if present
            if layer.ground_truth_coordinates:
                # Convert (lon, lat) -> (lat, lon) for Folium
                gt_lat_lons = [(lat, lon) for lon, lat in layer.ground_truth_coordinates]
                folium.PolyLine(
                    locations=gt_lat_lons,
                    color="green",
                    weight=6,
                    opacity=0.6,
                    dash_array="10",
                    tooltip=folium.Tooltip(f"<b>Ground Truth:</b> {label}"),
                ).add_to(fg)

            # Draw Model Route
            route_lat_lons = [(lat, lon) for lon, lat in layer.route_coordinates]
            folium.PolyLine(
                locations=route_lat_lons,
                color="blue",
                weight=4,
                opacity=0.8,
                tooltip=folium.Tooltip(tooltip_html),
            ).add_to(fg)

            # Add start/end markers for the main route
            if route_lat_lons:
                folium.CircleMarker(
                    location=route_lat_lons[0],
                    radius=5,
                    color="green",
                    fill=True,
                    fill_color="green",
                    tooltip=f"Start: {layer.route[0]}"
                ).add_to(fg)
                
                folium.CircleMarker(
                    location=route_lat_lons[-1],
                    radius=5,
                    color="red",
                    fill=True,
                    fill_color="red",
                    tooltip=f"End: {layer.route[-1]}"
                ).add_to(fg)

            fg.add_to(m)

        # Add layer control to toggle specific routes on and off
        folium.LayerControl().add_to(m)

        if save_path:
            m.save(save_path)
            print(f"Map saved to {save_path}")

        return m
