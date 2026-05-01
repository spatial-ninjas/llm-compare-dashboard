"""Prompt builders for route-finding evaluation mode."""

from __future__ import annotations


DEFAULT_SSAL_PROFILE_NAME = "default_length_name_oneway_coords"

DEFAULT_SSAL_SCHEMA_DESCRIPTION = """
Node_ID:
  Neighbor_ID {length, street_name, direction_flag, from_x=..., from_y=..., to_x=..., to_y=...}

Fields:
- length: edge length / traversal cost
- street_name: display/debug name for the edge.
- direction_flag: "1w" means one-way; "2w" means two-way in the source road data.
- from_x/from_y and to_x/to_y: endpoint coordinates for spatial context only.
""".strip()

DEFAULT_ROUTE_PROMPT_TEMPLATE = """
You are a precise navigation engine. Your task is to calculate the shortest path between two nodes using the provided SSAL (Simplified Semantic Adjacency List) network data.

Input data:
The SSAL network data is included below. It contains the network topology where each node lists its outgoing connections in this format:

Node_ID:
  Neighbor_ID {{length, street_name, direction_flag, from_x=..., from_y=..., to_x=..., to_y=...}}

Fields:
- length: edge length / traversal cost. Minimize the sum of these values.
- street_name: display/debug name for the edge.
- direction_flag: "1w" means one-way; "2w" means two-way in the source road data.
- from_x/from_y and to_x/to_y: endpoint coordinates for spatial context only.

Task:
Find the optimal route from Origin Node ID: {origin} to Destination Node ID: {destination}.

Constraints:
- Only use connections explicitly listed in the SSAL data.
- Respect directed edges exactly as listed.
- Even if an edge is marked "2w", only use the direction that is explicitly listed under the current node.
- Minimize the total length.
- Use coordinates only as supporting spatial context; do not invent edges from coordinate proximity.
- Output the result strictly as a JSON object.
- Do not include any conversational text, explanation, Markdown, or code fences.

Output format:
{{
  "origin": "{origin}",
  "destination": "{destination}",
  "total_length": 123.4,
  "route": [
    {{"node": "{origin}", "edge_name": "start"}},
    {{"node": "...", "edge_name": "[STREET NAME]"}},
    {{"node": "{destination}", "edge_name": "[STREET NAME]"}}
  ],
  "status": "success"
}}

SSAL:
{ssal_text}
""".strip()


def build_route_prompt(
    *,
    ssal_text: str,
    origin: str,
    destination: str,
    template: str = DEFAULT_ROUTE_PROMPT_TEMPLATE,
) -> str:
    """Build a route-finding prompt from SSAL text and selected endpoints.

    The template must use Python str.format() placeholders for origin,
    destination, and ssal_text.

    Literal JSON braces inside the template must be escaped as {{ and }}.
    """
    return template.format(
        origin=origin,
        destination=destination,
        ssal_text=ssal_text,
    )
