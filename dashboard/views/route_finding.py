"""Route-finding evaluation view."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd
import streamlit as st
from research.evaluation import evaluate_route_response
from research.graph import dijkstra_shortest_path

from dashboard.api_clients import call_gemini, call_openai
from dashboard.db import (
    create_route_prompt_template,
    list_route_prompt_templates,
    save_route_evaluation,
    save_route_task,
    save_run,
    update_route_prompt_template,
)
from dashboard.network import load_route_network_bundle
from dashboard.route_map_helpers import (
    add_segment_highlights_to_map,
    build_segment_rows_from_evaluation,
    network_edges_from_bundle,
    render_highlight_summary,
    render_map_html_file,
    safe_map_token,
)
from dashboard.route_prompts import (
    DEFAULT_ROUTE_PROMPT_TEMPLATE,
    DEFAULT_ROUTE_PROMPT_TEMPLATE_NAME,
    DEFAULT_SSAL_PROFILE_NAME,
    build_route_prompt,
    get_ssal_profile,
    list_ssal_profiles,
    validate_route_prompt_template,
)
from dashboard.route_visualization import (
    RouteVisualization,
    node_coordinates_from_network_bundle,
)


DEFAULT_ORIGIN_NODE = "1004552350"
DEFAULT_DESTINATION_NODE = "9713069615"


def _format_metric(value: Any, digits: int = 3) -> str:
    """Format route evaluation metrics for display."""
    if value is None:
        return "—"

    if isinstance(value, float):
        return f"{value:.{digits}f}"

    return str(value)


def _format_bool(value: Any) -> str:
    """Format optional boolean values for compact UI display."""
    if value is True:
        return "✅ Yes"
    if value is False:
        return "⚠️ No"
    return "—"



def _format_metric_value(value: Any, digits: int = 3) -> str:
    """Format optional numeric metric values for compact display."""
    if value is None or pd.isna(value):
        return "—"

    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"

    return str(value)


def _metric_cell(label: str, value: Any) -> str:
    """Return compact HTML for one route metric cell."""
    escaped_label = html.escape(str(label))
    escaped_value = html.escape(str(value))

    return f"""
    <div style="padding: 0.35rem 0 0.2rem 0;">
        <div style="
            font-size: 0.85rem;
            color: #6b7280;
            margin-bottom: 0.15rem;
        ">
            {escaped_label}
        </div>
        <div style="
            font-size: 1.25rem;
            font-weight: 600;
            line-height: 1.2;
        ">
            {escaped_value}
        </div>
    </div>
    """


BUILTIN_TEMPLATE_OPTION_ID = "builtin"


def _load_route_prompt_template_options() -> list[dict[str, Any]]:
    """Return built-in and saved route prompt template options."""
    options = [
        {
            "id": BUILTIN_TEMPLATE_OPTION_ID,
            "name": DEFAULT_ROUTE_PROMPT_TEMPLATE_NAME,
            "description": "Built-in default template bundled with the dashboard.",
            "template_text": DEFAULT_ROUTE_PROMPT_TEMPLATE,
            "ssal_profile_name": DEFAULT_SSAL_PROFILE_NAME,
            "is_builtin": True,
        }
    ]

    for template in list_route_prompt_templates():
        options.append(
            {
                "id": str(template["id"]),
                "name": template["name"],
                "description": template.get("description"),
                "template_text": template["template_text"],
                "ssal_profile_name": template.get("ssal_profile_name"),
                "is_builtin": bool(template.get("is_builtin")),
            }
        )

    return options


def _template_option_label(option: dict[str, Any]) -> str:
    """Return a compact label for the prompt template selector."""
    if option.get("is_builtin"):
        return f"{option['name']} · built-in"

    return str(option["name"])


def _selected_template_option(
    options: list[dict[str, Any]],
    selected_id: str,
) -> dict[str, Any]:
    """Return selected template option, falling back to built-in default."""
    for option in options:
        if str(option["id"]) == str(selected_id):
            return option

    return options[0]


def _selected_template_has_unsaved_changes(
    *,
    selected_template: dict[str, Any],
    current_template_text: str,
    current_template_name: str,
    current_ssal_profile_name: str,
) -> bool:
    """Return whether the editor differs from the selected template option."""
    return (
        current_template_text != selected_template["template_text"]
        or current_template_name != selected_template["name"]
        or current_ssal_profile_name
        != (selected_template.get("ssal_profile_name") or DEFAULT_SSAL_PROFILE_NAME)
    )


def render_ground_truth_summary(
    *,
    origin: str,
    destination: str,
    ground_truth_path: list[str],
    ground_truth_length: float | None,
) -> None:
    """Render a compact summary card for the selected reference route."""
    ground_truth_edges = max(len(ground_truth_path) - 1, 0)

    with st.container(border=True):
        st.markdown("**Selected reference route**")
        st.markdown(f"Route: `{origin}` → `{destination}`")

        metric_col1, metric_col2 = st.columns(2)

        with metric_col1:
            st.markdown(
                _metric_cell(
                    "Ground-truth length",
                    _format_metric_value(ground_truth_length, digits=1),
                ),
                unsafe_allow_html=True,
            )

        with metric_col2:
            st.markdown(
                _metric_cell("Ground-truth edges", str(ground_truth_edges)),
                unsafe_allow_html=True,
            )


def _node_default_index(
    nodes: list[str],
    preferred_node: str,
    fallback_index: int,
) -> int:
    """Return the selectbox index for a preferred node, with a safe fallback."""
    try:
        return nodes.index(preferred_node)
    except ValueError:
        return min(fallback_index, max(len(nodes) - 1, 0))


def _evaluation_status_label(evaluation: dict[str, Any]) -> str:
    """Return a compact human-readable evaluation status label."""
    if _is_satisfactory_evaluation(evaluation):
        return "✅ Satisfactory"

    if evaluation.get("status") == "evaluated":
        return "⚠️ Needs review"

    reason = evaluation.get("reason")
    if reason:
        return f"⚠️ {reason}"

    return str(evaluation.get("status") or "—")


def _get_response_text(api_result: dict[str, Any]) -> str:
    """Return provider response text from an API result."""
    return str(api_result.get("text") or "")


def _get_result_model(api_result: dict[str, Any], fallback: str) -> str:
    """Return model name from API result metadata."""
    metadata = api_result.get("metadata") or {}
    return str(metadata.get("model") or fallback)


def _ground_truth_length(ground_truth: dict[str, Any]) -> float | None:
    """Return ground-truth length from known Dijkstra result keys."""
    value = ground_truth.get("total_length", ground_truth.get("length"))

    if value is None:
        return None

    return float(value)


def _provider_error_evaluation(api_result: dict[str, Any]) -> dict[str, Any]:
    """Build a route-evaluation-like row for failed provider calls."""
    return {
        "status": "skipped",
        "reason": "provider_call_failed",
        "valid_json": None,
        "valid_path": None,
        "exact_path_match": None,
        "candidate_path": None,
        "candidate_declared_length": None,
        "candidate_computed_length": None,
        "ground_truth_path": None,
        "ground_truth_length": None,
        "absolute_length_error": None,
        "relative_length_error": None,
        "declared_length_absolute_error": None,
        "declared_length_relative_error": None,
        "node_overlap": None,
        "edge_overlap": None,
        "error_text": api_result.get("error") or "Provider call failed.",
    }


def _provider_status_message(
    *,
    provider: str,
    api_result: dict[str, Any],
) -> str:
    """Return a compact provider call status message."""
    attempts = (api_result.get("metadata") or {}).get("attempts")
    outcome = "finished" if api_result.get("ok") else "failed"

    if attempts:
        return f"{provider} call {outcome} after {attempts} attempt(s)."

    return f"{provider} call {outcome}."


def _is_satisfactory_evaluation(evaluation: dict[str, Any]) -> bool:
    """Return whether a route evaluation should be treated as satisfactory."""
    return (
        evaluation.get("status") == "evaluated"
        and evaluation.get("valid_json") is True
        and evaluation.get("valid_path") is True
        and evaluation.get("exact_path_match") is True
    )


def _evaluation_download_payload(
    *,
    task_id: int,
    origin: str,
    destination: str,
    ssal_hash: str,
    ssal_profile_name: str,
    prompt_template_name: str,
    openai_run_id: int,
    gemini_run_id: int,
    openai_result: dict[str, Any],
    gemini_result: dict[str, Any],
    openai_evaluation: dict[str, Any],
    gemini_evaluation: dict[str, Any],
) -> str:
    """Return a formatted JSON payload for the latest route test."""
    return json.dumps(
        {
            "task": {
                "id": task_id,
                "origin": origin,
                "destination": destination,
                "ssal_hash": ssal_hash,
                "prompt_template_name": prompt_template_name,
                "ssal_profile_name": ssal_profile_name,
            },
            "openai": {
                "run_id": openai_run_id,
                "provider_result": openai_result,
                "evaluation": openai_evaluation,
            },
            "gemini": {
                "run_id": gemini_run_id,
                "provider_result": gemini_result,
                "evaluation": gemini_evaluation,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def render_save_summary(
    *,
    task_id: int,
    openai_run_id: int,
    gemini_run_id: int,
) -> None:
    """Show a compact persistence confirmation after a route test."""
    st.success("Route test saved to local history.")

    st.caption(
        "Saved one route task, two generic provider runs, "
        "and two route evaluation rows."
    )

    with st.expander("Saved row IDs"):
        st.json(
            {
                "route_task_id": task_id,
                "openai_run_id": openai_run_id,
                "gemini_run_id": gemini_run_id,
            }
        )


def render_route_map_preview(
    *,
    bundle: Any,
    origin: str,
    destination: str,
    ground_truth_path: list[str],
) -> None:
    """Render a map preview for the selected route task."""
    node_coordinates = node_coordinates_from_network_bundle(bundle)

    if not node_coordinates:
        st.info("No node coordinates are available for map preview.")
        return

    viz = RouteVisualization(
        node_coordinates=node_coordinates,
        metadata={
            "ssal_hash": bundle.ssal_hash[:12],
            "origin": origin,
            "destination": destination,
        },
    )

    viz.add_network_layer(
        edges=network_edges_from_bundle(bundle),
        name="Full network",
        color="gray",
        weight=1,
        opacity=0.25,
        include_in_bounds=True,
    )

    viz.add_node_marker(
        node_id=str(origin),
        label="Selected origin",
        color="green",
        metadata={"role": "origin"},
    )

    viz.add_node_marker(
        node_id=str(destination),
        label="Selected destination",
        color="red",
        metadata={"role": "destination"},
    )

    viz.add_route(
        route=ground_truth_path,
        metadata={
            "label": "Dijkstra reference",
            "origin": origin,
            "destination": destination,
            "edges": max(len(ground_truth_path) - 1, 0),
        },
        color="green",
    )

    viz.add_route_node_markers(
        route=ground_truth_path,
        name="Dijkstra reference nodes",
        color="green",
        show=False,
        metadata={
            "route_type": "ground_truth",
        },
    )

    output_dir = Path(tempfile.gettempdir()) / "llm_compare_dashboard_maps"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = (
        "route_preview_"
        f"{safe_map_token(origin)}_"
        f"{safe_map_token(destination)}_"
        f"{bundle.ssal_hash[:12]}.html"
    )
    output_path = output_dir / safe_name

    viz.render(save_path=str(output_path))
    render_map_html_file(html_path=output_path, height=520)


def render_provider_route_map(
    *,
    bundle: Any,
    provider: str,
    model: str,
    origin: str,
    destination: str,
    ground_truth_path: list[str],
    evaluation: dict[str, Any],
) -> None:
    """Render one provider candidate route against the ground-truth route."""
    candidate_path = evaluation.get("candidate_path")

    if not isinstance(candidate_path, list) or len(candidate_path) < 2:
        reason = evaluation.get("reason") or evaluation.get("error_text")
        if reason:
            st.info(f"No inspectable {provider} route was extracted: {reason}")
        else:
            st.info(f"No inspectable {provider} route was extracted.")
        return

    candidate_path = [str(node) for node in candidate_path]
    ground_truth_path = [str(node) for node in ground_truth_path]

    node_coordinates = node_coordinates_from_network_bundle(bundle)

    if not node_coordinates:
        st.info("No node coordinates are available for route map rendering.")
        return

    provider_color = "blue"
    if provider.lower() == "gemini":
        provider_color = "purple"

    viz = RouteVisualization(
        node_coordinates=node_coordinates,
        metadata={
            "ssal_hash": bundle.ssal_hash[:12],
            "provider": provider,
            "model": model,
            "origin": origin,
            "destination": destination,
        },
    )

    viz.add_network_layer(
        edges=network_edges_from_bundle(bundle),
        name="Full network",
        color="gray",
        weight=1,
        opacity=0.2,
        include_in_bounds=False,
    )

    viz.add_node_marker(
        node_id=str(origin),
        label="Selected origin",
        color="green",
        metadata={"role": "origin"},
    )

    viz.add_node_marker(
        node_id=str(destination),
        label="Selected destination",
        color="red",
        metadata={"role": "destination"},
    )

    viz.add_route(
        route=candidate_path,
        ground_truth=ground_truth_path,
        metadata={
            "label": f"{provider} / {model}",
            "origin": origin,
            "destination": destination,
            "status": _evaluation_status_label(evaluation),
        },
        color=provider_color,
        ground_truth_color="green",
    )

    viz.add_route_node_markers(
        route=candidate_path,
        name=f"{provider} route nodes",
        color=provider_color,
        show=False,
        metadata={
            "route_type": "candidate",
            "provider": provider,
            "model": model,
        },
    )

    viz.add_route_node_markers(
        route=ground_truth_path,
        name="Ground truth route nodes",
        color="green",
        show=False,
        metadata={
            "route_type": "ground_truth",
        },
    )

    candidate_validation = evaluation.get("candidate_validation") or {}
    segment_rows = build_segment_rows_from_evaluation(
        candidate_path=candidate_path,
        ground_truth_path=ground_truth_path,
        candidate_validation=candidate_validation,
    )

    highlight_count = add_segment_highlights_to_map(
        viz=viz,
        segment_rows=segment_rows,
    )

    render_highlight_summary(highlight_count)

    output_dir = Path(tempfile.gettempdir()) / "llm_compare_dashboard_maps"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = (
        "route_result_"
        f"{safe_map_token(provider)}_"
        f"{safe_map_token(model)}_"
        f"{safe_map_token(origin)}_"
        f"{safe_map_token(destination)}_"
        f"{bundle.ssal_hash[:12]}.html"
    )
    output_path = output_dir / safe_name

    viz.render(save_path=str(output_path))
    render_map_html_file(html_path=output_path, height=520)


def render_route_eval_card(
    *,
    title: str,
    api_result: dict[str, Any],
    evaluation: dict[str, Any] | None,
) -> None:
    """Render one provider result and route evaluation summary."""
    st.subheader(title)

    if not api_result.get("ok"):
        st.error(api_result.get("error") or "Provider call failed.")

        with st.expander("Raw provider result"):
            st.json(api_result)

        if evaluation is not None:
            with st.expander("Saved route evaluation JSON"):
                st.json(evaluation)

        return

    if evaluation is None:
        st.warning("No route evaluation available.")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.write(f"Valid JSON: `{evaluation.get('valid_json')}`")
        st.write(f"Valid path: `{evaluation.get('valid_path')}`")
        st.write(f"Exact path match: `{evaluation.get('exact_path_match')}`")
        st.write(
            "Candidate length: "
            f"`{_format_metric(evaluation.get('candidate_computed_length'))}`"
        )

    with col2:
        st.write(
            "Ground-truth length: "
            f"`{_format_metric(evaluation.get('ground_truth_length'))}`"
        )
        st.write(
            "Relative length error: "
            f"`{_format_metric(evaluation.get('relative_length_error'))}`"
        )
        st.write(f"Node overlap: `{_format_metric(evaluation.get('node_overlap'))}`")
        st.write(f"Edge overlap: `{_format_metric(evaluation.get('edge_overlap'))}`")

    if evaluation.get("reason"):
        st.write(f"Reason: `{evaluation.get('reason')}`")

    with st.expander("Model response"):
        st.text(_get_response_text(api_result))

    with st.expander("Raw evaluation JSON"):
        st.json(evaluation)


def render_route_finding_view() -> None:
    """Render the route-finding evaluation view."""
    template_options = _load_route_prompt_template_options()

    selected_template_id = st.session_state.get(
        "route_prompt_template_id",
        BUILTIN_TEMPLATE_OPTION_ID,
    )

    selected_template = _selected_template_option(
        template_options,
        selected_template_id,
    )

    if "route_prompt_template" not in st.session_state:
        st.session_state.route_prompt_template = selected_template["template_text"]

    if "route_prompt_template_name" not in st.session_state:
        st.session_state.route_prompt_template_name = selected_template["name"]

    if "route_prompt_ssal_profile_name" not in st.session_state:
        st.session_state.route_prompt_ssal_profile_name = (
            selected_template.get("ssal_profile_name") or DEFAULT_SSAL_PROFILE_NAME
        )

    template = st.session_state.route_prompt_template
    template_name = st.session_state.route_prompt_template_name
    template_ssal_profile_name = st.session_state.route_prompt_ssal_profile_name
    ssal_profile = get_ssal_profile(template_ssal_profile_name)
    default_ssal_profile = get_ssal_profile(DEFAULT_SSAL_PROFILE_NAME)

    try:
        bundle = load_route_network_bundle(
            include_coords=ssal_profile.include_coords,
            include_direction=ssal_profile.include_direction,
            include_attrs=ssal_profile.include_attrs,
        )
        display_bundle = load_route_network_bundle(
            include_coords=default_ssal_profile.include_coords,
            include_direction=default_ssal_profile.include_direction,
            include_attrs=default_ssal_profile.include_attrs,
        )
    except Exception as exc:
        st.error(f"Failed to load route network: {exc}")
        st.info(
            "Check NETWORK_GPKG_PATH, NETWORK_GPKG_URL, "
            "NETWORK_GPKG_SHA256, NETWORK_CACHE_DIR, "
            "NETWORK_EDGES_LAYER, and NETWORK_NODES_LAYER "
            "in your .env file."
        )
        return

    nodes = bundle.graph.nodes()

    with st.sidebar:
        st.header("Route settings")

        openai_model = st.selectbox(
            "OpenAI model",
            options=[
                "gpt-5.4-mini",
                "gpt-4.1-mini",
                "gpt-5.4",
            ],
            index=0,
        )

        gemini_model = st.selectbox(
            "Gemini model",
            options=[
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-2.5-pro",
            ],
            index=0,
        )

        max_output_tokens = st.slider(
            "Max response tokens",
            min_value=256,
            max_value=8192,
            value=4096,
            step=256,
        )

        gemini_thinking_mode = st.selectbox(
            "Gemini thinking budget",
            options=[
                "off",
                "dynamic",
                "custom",
            ],
            index=0,
            help=(
                "Dynamic lets Gemini decide. Off disables thinking. "
                "Custom sets an explicit thinking token budget."
            ),
        )

        gemini_custom_thinking_budget = None
        if gemini_thinking_mode == "custom":
            gemini_custom_thinking_budget = st.slider(
                "Custom Gemini thinking budget",
                min_value=0,
                max_value=8192,
                value=1024,
                step=256,
            )

        st.divider()
        st.caption("Route network")
        st.write(f"SSAL profile: `{ssal_profile.name}`")
        st.write(f"SSAL hash: `{bundle.ssal_hash[:12]}`")
        st.write(f"Nodes: `{len(nodes)}`")

    main_col, prompt_col = st.columns([1.55, 1.0], gap="large")

    with main_col:
        st.subheader("Route task")

        route_col1, route_col2 = st.columns(2)

        with route_col1:
            origin = st.selectbox(
                "Origin node",
                nodes,
                index=_node_default_index(
                    nodes,
                    preferred_node=DEFAULT_ORIGIN_NODE,
                    fallback_index=0,
                ),
            )

        with route_col2:
            destination = st.selectbox(
                "Destination node",
                nodes,
                index=_node_default_index(
                    nodes,
                    preferred_node=DEFAULT_DESTINATION_NODE,
                    fallback_index=1,
                ),
            )

        if origin == destination:
            st.warning("Origin and destination should be different.")
            return

        ground_truth = dijkstra_shortest_path(bundle.graph, origin, destination)

        if not ground_truth.get("ok"):
            st.error(f"No Dijkstra path found: {ground_truth.get('reason')}")
            return

        ground_truth_length = _ground_truth_length(ground_truth)
        ground_truth_path = [str(node) for node in ground_truth["path"]]

        render_ground_truth_summary(
            origin=origin,
            destination=destination,
            ground_truth_path=ground_truth_path,
            ground_truth_length=ground_truth_length,
        )

        render_route_map_preview(
            bundle=display_bundle,
            origin=origin,
            destination=destination,
            ground_truth_path=ground_truth_path,
        )

        with st.expander("Ground-truth path"):
            st.code(
                json.dumps(ground_truth_path, indent=2, ensure_ascii=False),
                language="json",
            )

        with st.expander("Network debug details", expanded=False):
            st.write(f"GeoPackage: `{bundle.gpkg_path}`")
            st.write(f"Edges layer: `{bundle.edges_layer}`")
            st.write(f"Nodes layer: `{bundle.nodes_layer}`")
            st.write(f"SSAL hash: `{bundle.ssal_hash}`")
            st.write(f"Node count: `{len(nodes)}`")

            st.subheader("SSAL preview")
            preview = "\n".join(bundle.ssal_text.splitlines()[:40])
            st.code(preview, language="text")

    template_errors = validate_route_prompt_template(template)
    prompt = ""

    if not template_errors:
        try:
            prompt = build_route_prompt(
                ssal_text=bundle.ssal_text,
                origin=origin,
                destination=destination,
                template=template,
                ssal_schema_description=ssal_profile.schema_description,
            )
        except ValueError as exc:
            template_errors = [str(exc)]

    with prompt_col:
        st.subheader("Prompt template")

        st.caption(f"Current SSAL profile: `{ssal_profile.name}`")

        with st.expander("SSAL schema", expanded=False):
            st.code(ssal_profile.schema_description, language="text")

        selected_option_id = st.selectbox(
            "Saved prompt template",
            options=[str(option["id"]) for option in template_options],
            index=next(
                (
                    index
                    for index, option in enumerate(template_options)
                    if str(option["id"]) == str(selected_template_id)
                ),
                0,
            ),
            format_func=lambda option_id: _template_option_label(
                _selected_template_option(template_options, option_id)
            ),
        )

        if selected_option_id != selected_template_id:
            selected_template = _selected_template_option(
                template_options,
                selected_option_id,
            )
            st.session_state.route_prompt_template_id = selected_option_id
            st.session_state.route_prompt_template = selected_template["template_text"]
            st.session_state.route_prompt_template_name = selected_template["name"]
            st.session_state.route_prompt_ssal_profile_name = (
                selected_template.get("ssal_profile_name") or DEFAULT_SSAL_PROFILE_NAME
            )
            st.rerun()

        ssal_profiles = list_ssal_profiles()
        selected_profile_name = st.selectbox(
            "SSAL profile for this prompt template",
            options=[profile.name for profile in ssal_profiles],
            index=next(
                (
                    index
                    for index, profile in enumerate(ssal_profiles)
                    if profile.name == ssal_profile.name
                ),
                0,
            ),
            format_func=lambda name: get_ssal_profile(name).label,
            help=(
                "This controls the SSAL text inserted into {ssal_text}. "
                "It is saved with the prompt template and route task."
            ),
        )

        if selected_profile_name != ssal_profile.name:
            st.session_state.route_prompt_ssal_profile_name = selected_profile_name
            st.rerun()

        edited_template = st.text_area(
            "Route prompt template",
            value=template,
            height=520,
            help=(
                "Available placeholders: {origin}, {destination}, {ssal_text}. "
                "Escape literal JSON braces as {{ and }}."
            ),
        )

        if edited_template != template:
            st.session_state.route_prompt_template = edited_template
            st.rerun()

        selected_template = _selected_template_option(
            template_options,
            selected_template_id,
        )
        selected_template_description = selected_template.get("description") or ""
        has_unsaved_changes = _selected_template_has_unsaved_changes(
            selected_template=selected_template,
            current_template_text=template,
            current_template_name=template_name,
            current_ssal_profile_name=template_ssal_profile_name,
        )

        st.caption(f"Template name: {template_name}")
        st.caption(f"Expected SSAL profile: {template_ssal_profile_name}")

        if has_unsaved_changes:
            st.warning("The prompt editor has unsaved changes.")

        if template_errors:
            st.error("Prompt template validation failed.")
            for error in template_errors:
                st.warning(error)
            st.info(
                "Fix the template before running provider calls. "
                "Literal JSON or SSAL braces must be escaped as {{ and }}."
            )
        else:
            st.success("Prompt template validation passed.")

        with st.expander("Manage prompt template", expanded=False):
            new_template_name = st.text_input(
                "New template name",
                key="route_prompt_new_template_name",
            )
            template_description = st.text_area(
                "Template description",
                value=selected_template_description,
                height=100,
                placeholder="Optional notes about when to use this prompt.",
                key=f"route_prompt_template_description_{selected_template_id}",
            )
            description_changed = (
                template_description.strip()
                != selected_template_description.strip()
            )

            if description_changed and not selected_template.get("is_builtin", False):
                st.warning("The template description has unsaved changes.")

            save_col, update_col = st.columns(2)

            with save_col:
                save_as_new = st.button(
                    "Save as new",
                    disabled=bool(template_errors) or not new_template_name.strip(),
                    width="stretch",
                )

            with update_col:
                update_selected = st.button(
                    "Update selected",
                    disabled=(
                        bool(template_errors)
                        or selected_template.get("is_builtin", False)
                        or not (has_unsaved_changes or description_changed)
                    ),
                    width="stretch",
                )

            if save_as_new:
                try:
                    new_template_id = create_route_prompt_template(
                        name=new_template_name.strip(),
                        description=template_description.strip() or None,
                        template_text=template,
                        ssal_profile_name=template_ssal_profile_name,
                    )
                except Exception as exc:
                    st.error(f"Failed to save prompt template: {exc}")
                else:
                    st.success(f"Saved prompt template: {new_template_name.strip()}")
                    st.session_state.route_prompt_template_id = str(new_template_id)
                    st.session_state.route_prompt_template_name = new_template_name.strip()
                    st.session_state.route_prompt_template = template
                    st.session_state.route_prompt_ssal_profile_name = (
                        template_ssal_profile_name
                    )
                    st.rerun()

            if update_selected:
                try:
                    update_route_prompt_template(
                        template_id=int(selected_template_id),
                        template_text=template,
                        description=template_description.strip(),
                        ssal_profile_name=template_ssal_profile_name,
                    )
                except Exception as exc:
                    st.error(f"Failed to update prompt template: {exc}")
                else:
                    st.success(f"Updated prompt template: {template_name}")
                    st.rerun()

            st.caption(
                "Update is only available for saved templates. "
                "Use Save as new to create a variant from the current editor state."
            )

        if st.button("Reset editor to built-in default"):
            st.session_state.route_prompt_template_id = BUILTIN_TEMPLATE_OPTION_ID
            st.session_state.route_prompt_template = DEFAULT_ROUTE_PROMPT_TEMPLATE
            st.session_state.route_prompt_template_name = DEFAULT_ROUTE_PROMPT_TEMPLATE_NAME
            st.session_state.route_prompt_ssal_profile_name = DEFAULT_SSAL_PROFILE_NAME
            st.rerun()

        st.subheader("Generated prompt")

        if template_errors:
            st.info("Generated prompt preview is unavailable until the template is valid.")
        else:
            st.caption("This is the full prompt that will be sent to the models.")

            st.text_area(
                "Generated route prompt",
                value=prompt,
                height=360,
            )

            st.download_button(
                "Download generated prompt",
                data=prompt,
                file_name=f"route_prompt_{origin}_to_{destination}.txt",
                mime="text/plain",
                width="stretch",
            )

    with main_col:
        run_button = st.button(
            "Run route test",
            type="primary",
            width="stretch",
            disabled=bool(template_errors),
        )

        if not run_button:
            return

        with st.status("Running route test...", expanded=True) as status:
            st.write("Saving route task...")

            task_id = save_route_task(
                origin=origin,
                destination=destination,
                ssal_hash=bundle.ssal_hash,
                prompt_template=template,
                prompt_template_name=template_name,
                ssal_profile_name=template_ssal_profile_name,
                ground_truth_path=ground_truth_path,
                ground_truth_length=ground_truth_length,
            )

            st.write("Calling OpenAI and Gemini in parallel...")

            provider_futures = {}

            with ThreadPoolExecutor(max_workers=2) as executor:
                provider_futures[
                    executor.submit(
                        call_openai,
                        prompt=prompt,
                        model=openai_model,
                        max_output_tokens=max_output_tokens,
                    )
                ] = "OpenAI"

                provider_futures[
                    executor.submit(
                        call_gemini,
                        prompt=prompt,
                        model=gemini_model,
                        max_output_tokens=max_output_tokens,
                        thinking_mode=gemini_thinking_mode,
                        custom_thinking_budget=gemini_custom_thinking_budget,
                    )
                ] = "Gemini"

                results: dict[str, dict[str, Any]] = {}

                for future in as_completed(provider_futures):
                    provider = provider_futures[future]

                    try:
                        results[provider] = future.result()
                    except Exception as exc:
                        fallback_model = (
                            openai_model if provider == "OpenAI" else gemini_model
                        )
                        results[provider] = {
                            "ok": False,
                            "provider": provider,
                            "text": "",
                            "error": str(exc),
                            "metadata": {
                                "model": fallback_model,
                                "attempts": None,
                                "max_output_tokens": max_output_tokens,
                            },
                            "raw": None,
                        }

                    st.write(
                        _provider_status_message(
                            provider=provider,
                            api_result=results[provider],
                        )
                    )

            openai_result = results["OpenAI"]
            gemini_result = results["Gemini"]

            st.write("Saving provider runs...")
            openai_run_id = save_run(prompt, openai_result)
            gemini_run_id = save_run(prompt, gemini_result)

            st.write("Evaluating OpenAI route...")
            if openai_result.get("ok"):
                openai_evaluation = evaluate_route_response(
                    response_text=_get_response_text(openai_result),
                    graph=bundle.graph,
                    origin=origin,
                    destination=destination,
                )
            else:
                openai_evaluation = _provider_error_evaluation(openai_result)

            st.write("Evaluating Gemini route...")
            if gemini_result.get("ok"):
                gemini_evaluation = evaluate_route_response(
                    response_text=_get_response_text(gemini_result),
                    graph=bundle.graph,
                    origin=origin,
                    destination=destination,
                )
            else:
                gemini_evaluation = _provider_error_evaluation(gemini_result)

            st.write("Saving route evaluations...")
            save_route_evaluation(
                task_id=task_id,
                run_id=openai_run_id,
                provider="OpenAI",
                model=_get_result_model(openai_result, openai_model),
                evaluation=openai_evaluation,
            )

            save_route_evaluation(
                task_id=task_id,
                run_id=gemini_run_id,
                provider="Gemini",
                model=_get_result_model(gemini_result, gemini_model),
                evaluation=gemini_evaluation,
            )

            status.update(
                label="Route test completed.",
                state="complete",
                expanded=False,
            )

        render_save_summary(
            task_id=task_id,
            openai_run_id=openai_run_id,
            gemini_run_id=gemini_run_id,
        )

        st.download_button(
            "Download this route test as JSON",
            data=_evaluation_download_payload(
                task_id=task_id,
                origin=origin,
                destination=destination,
                ssal_hash=bundle.ssal_hash,
                prompt_template_name=template_name,
                ssal_profile_name=template_ssal_profile_name,
                openai_run_id=openai_run_id,
                gemini_run_id=gemini_run_id,
                openai_result=openai_result,
                gemini_result=gemini_result,
                openai_evaluation=openai_evaluation,
                gemini_evaluation=gemini_evaluation,
            ),
            file_name=f"route_evaluation_{origin}_to_{destination}.json",
            mime="application/json",
            width="stretch",
        )

        result_col1, result_col2 = st.columns(2)

        with result_col1:
            render_route_eval_card(
                title="OpenAI",
                api_result=openai_result,
                evaluation=openai_evaluation,
            )
            render_provider_route_map(
                bundle=display_bundle,
                provider="OpenAI",
                model=_get_result_model(openai_result, openai_model),
                origin=origin,
                destination=destination,
                ground_truth_path=ground_truth_path,
                evaluation=openai_evaluation,
            )

        with result_col2:
            render_route_eval_card(
                title="Gemini",
                api_result=gemini_result,
                evaluation=gemini_evaluation,
            )
            render_provider_route_map(
                bundle=display_bundle,
                provider="Gemini",
                model=_get_result_model(gemini_result, gemini_model),
                origin=origin,
                destination=destination,
                ground_truth_path=ground_truth_path,
                evaluation=gemini_evaluation,
            )
