"""Prompt builders for route-finding evaluation mode."""

from __future__ import annotations

from dataclasses import dataclass
from string import Formatter


DEFAULT_ROUTE_PROMPT_TEMPLATE_NAME = "Built-in default route prompt"
DEFAULT_SSAL_PROFILE_NAME = "default_length_name_oneway_coords"
REQUIRED_ROUTE_PROMPT_PLACEHOLDERS = {"origin", "destination", "ssal_text"}
OPTIONAL_ROUTE_PROMPT_PLACEHOLDERS = {"ssal_schema_description"}

DEFAULT_SSAL_SCHEMA_DESCRIPTION = """
Node_ID:
  Neighbor_ID {length, street_name, direction_flag, from_x=..., from_y=..., to_x=..., to_y=...}

Fields:
- length: edge length / traversal cost
- street_name: display/debug name for the edge.
- direction_flag: "1w" means one-way; "2w" means two-way in the source road data.
- from_x/from_y and to_x/to_y: endpoint coordinates for spatial context only.
""".strip()


NO_COORDS_SSAL_SCHEMA_DESCRIPTION = """
Node_ID:
  Neighbor_ID {length, street_name, direction_flag}

Fields:
- length: edge length / traversal cost
- street_name: display/debug name for the edge.
- direction_flag: "1w" means one-way; "2w" means two-way in the source road data.
""".strip()


@dataclass(frozen=True)
class SSALProfile:
    """Prompt-facing SSAL representation options."""

    name: str
    label: str
    description: str
    include_coords: bool = True
    include_direction: bool = False
    include_attrs: tuple[str, ...] = (
        "length",
        "name",
        "oneway",
        "from_x",
        "from_y",
        "to_x",
        "to_y",
    )
    schema_description: str = ""


SSAL_PROFILES: dict[str, SSALProfile] = {
    DEFAULT_SSAL_PROFILE_NAME: SSALProfile(
        name=DEFAULT_SSAL_PROFILE_NAME,
        label="Default: length, name, oneway, coordinates",
        description="Current default SSAL representation with endpoint coordinates.",
        include_coords=True,
        include_attrs=(
            "length",
            "name",
            "oneway",
            "from_x",
            "from_y",
            "to_x",
            "to_y",
        ),
        schema_description=DEFAULT_SSAL_SCHEMA_DESCRIPTION,
    ),
    "length_name_oneway": SSALProfile(
        name="length_name_oneway",
        label="No coordinates: length, name, oneway",
        description="Compact SSAL representation without endpoint coordinates.",
        include_coords=False,
        include_attrs=("length", "name", "oneway"),
        schema_description=NO_COORDS_SSAL_SCHEMA_DESCRIPTION,
    ),
}


def get_ssal_profile(profile_name: str | None) -> SSALProfile:
    """Return a known SSAL profile, falling back to the default profile."""
    return SSAL_PROFILES.get(
        profile_name or DEFAULT_SSAL_PROFILE_NAME,
        SSAL_PROFILES[DEFAULT_SSAL_PROFILE_NAME],
    )


def list_ssal_profiles() -> list[SSALProfile]:
    """Return SSAL profiles in a stable UI order."""
    return list(SSAL_PROFILES.values())


DEFAULT_ROUTE_PROMPT_TEMPLATE = """
You are a precise navigation engine. Your task is to calculate the shortest path between two nodes using the provided SSAL (Simplified Semantic Adjacency List) network data.

Input data:
The SSAL network data is included below. It contains the network topology where each node lists its outgoing connections in this format:

{ssal_schema_description}

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


def _base_placeholder_name(field_name: str) -> str:
    """Return the root placeholder name for a Python format field."""
    for separator in (".", "["):
        if separator in field_name:
            return field_name.split(separator, 1)[0]

    return field_name


def validate_route_prompt_template(template: str) -> list[str]:
    """Return validation errors for a route prompt template.

    Route prompt templates use Python str.format placeholders. Literal JSON
    or SSAL braces must therefore be escaped as {{ and }}.
    """
    formatter = Formatter()
    placeholders: set[str] = set()
    errors: list[str] = []

    try:
        parsed_template = list(formatter.parse(template))
    except ValueError as exc:
        return [
            "Template has malformed braces. "
            "Escape literal JSON/SSAL braces as {{ and }}. "
            f"Details: {exc}"
        ]

    for _, field_name, _, _ in parsed_template:
        if field_name is None:
            continue

        if not field_name:
            errors.append(
                "Template contains an empty placeholder. "
                "Use {origin}, {destination}, {ssal_text}, or {ssal_schema_description}."
            )
            continue

        placeholders.add(_base_placeholder_name(field_name))

    missing_placeholders = REQUIRED_ROUTE_PROMPT_PLACEHOLDERS - placeholders
    allowed_placeholders = REQUIRED_ROUTE_PROMPT_PLACEHOLDERS | OPTIONAL_ROUTE_PROMPT_PLACEHOLDERS
    unknown_placeholders = placeholders - allowed_placeholders

    for placeholder in sorted(missing_placeholders):
        errors.append(f"Template is missing required placeholder: {{{placeholder}}}")

    for placeholder in sorted(unknown_placeholders):
        errors.append(f"Template has unknown placeholder: {{{placeholder}}}")

    return errors


def route_prompt_template_is_valid(template: str) -> bool:
    """Return whether a route prompt template passes validation."""
    return not validate_route_prompt_template(template)


def build_route_prompt(
    *,
    ssal_text: str,
    origin: str,
    destination: str,
    template: str = DEFAULT_ROUTE_PROMPT_TEMPLATE,
    ssal_schema_description: str = DEFAULT_SSAL_SCHEMA_DESCRIPTION,
) -> str:
    """Build a route-finding prompt from SSAL text and selected endpoints.

    The template must use Python str.format() placeholders for origin,
    destination, and ssal_text. It may also use ssal_schema_description
    to describe the SSAL format associated with the selected profile.

    Literal JSON braces inside the template must be escaped as {{ and }}.
    """
    validation_errors = validate_route_prompt_template(template)

    if validation_errors:
        raise ValueError("; ".join(validation_errors))

    return template.format(
        origin=origin,
        destination=destination,
        ssal_text=ssal_text,
        ssal_schema_description=ssal_schema_description,
    )
