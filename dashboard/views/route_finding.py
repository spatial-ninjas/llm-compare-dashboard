"""Route-finding evaluation view."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
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
    save_route_evaluation,
    save_route_task,
    save_run,
)
from dashboard.network import load_route_network_bundle
from dashboard.route_prompts import (
    DEFAULT_ROUTE_PROMPT_TEMPLATE,
    build_route_prompt,
)
from dashboard.route_visualization import (
    RouteVisualization,
    node_coordinates_from_network_bundle,
)


DEFAULT_ORIGIN_NODE = "1004552350"
DEFAULT_DESTINATION_NODE = "12143305053"


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
    st.subheader("Route map preview")

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

    viz.add_route(
        route=ground_truth_path,
        metadata={
            "label": "Dijkstra reference route",
            "origin": origin,
            "destination": destination,
            "source": "research.graph.dijkstra_shortest_path",
        },
        color="green",
    )

    output_dir = Path(tempfile.gettempdir()) / "llm_compare_dashboard_maps"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"route_preview_{origin}_{destination}_{bundle.ssal_hash[:12]}.html"
    output_path = output_dir / safe_name

    viz.render(save_path=str(output_path))

    html = output_path.read_text(encoding="utf-8")
    encoded_html = base64.b64encode(html.encode("utf-8")).decode("ascii")

    st.iframe(
        f"data:text/html;base64,{encoded_html}",
        height=520,
    )


def render_route_eval_summary_table(
    *,
    openai_evaluation: dict[str, Any],
    gemini_evaluation: dict[str, Any],
) -> None:
    """Render a compact metric-by-metric route evaluation comparison."""
    rows = [
        {
            "Metric": "Status",
            "OpenAI": _evaluation_status_label(openai_evaluation),
            "Gemini": _evaluation_status_label(gemini_evaluation),
        },
        {
            "Metric": "Valid JSON",
            "OpenAI": _format_bool(openai_evaluation.get("valid_json")),
            "Gemini": _format_bool(gemini_evaluation.get("valid_json")),
        },
        {
            "Metric": "Valid path",
            "OpenAI": _format_bool(openai_evaluation.get("valid_path")),
            "Gemini": _format_bool(gemini_evaluation.get("valid_path")),
        },
        {
            "Metric": "Exact shortest path",
            "OpenAI": _format_bool(openai_evaluation.get("exact_path_match")),
            "Gemini": _format_bool(gemini_evaluation.get("exact_path_match")),
        },
        {
            "Metric": "Candidate length",
            "OpenAI": _format_metric(openai_evaluation.get("candidate_computed_length")),
            "Gemini": _format_metric(gemini_evaluation.get("candidate_computed_length")),
        },
        {
            "Metric": "Ground-truth length",
            "OpenAI": _format_metric(openai_evaluation.get("ground_truth_length")),
            "Gemini": _format_metric(gemini_evaluation.get("ground_truth_length")),
        },
        {
            "Metric": "Relative length error",
            "OpenAI": _format_metric(openai_evaluation.get("relative_length_error")),
            "Gemini": _format_metric(gemini_evaluation.get("relative_length_error")),
        },
        {
            "Metric": "Node overlap",
            "OpenAI": _format_metric(openai_evaluation.get("node_overlap")),
            "Gemini": _format_metric(gemini_evaluation.get("node_overlap")),
        },
        {
            "Metric": "Edge overlap",
            "OpenAI": _format_metric(openai_evaluation.get("edge_overlap")),
            "Gemini": _format_metric(gemini_evaluation.get("edge_overlap")),
        },
        {
            "Metric": "Reason",
            "OpenAI": openai_evaluation.get("reason") or "—",
            "Gemini": gemini_evaluation.get("reason") or "—",
        },
    ]

    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Metric": st.column_config.TextColumn("Metric", width="medium"),
            "OpenAI": st.column_config.TextColumn("OpenAI", width="medium"),
            "Gemini": st.column_config.TextColumn("Gemini", width="medium"),
        },
    )

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

    if _is_satisfactory_evaluation(evaluation):
        st.success("Evaluation satisfactory")
    elif evaluation.get("status") == "evaluated":
        st.warning("Evaluation completed, but the route was not an exact valid match")
    else:
        st.warning(f"Evaluation status: {evaluation.get('status')}")

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
    st.header("Route-finding evaluation")
    st.caption(
        "Load the SSAL-native route network, generate a route prompt, "
        "run both models, and evaluate their routes."
    )

    try:
        bundle = load_route_network_bundle()
    except Exception as exc:
        st.error(f"Failed to load route network: {exc}")
        st.info(
            "Check NETWORK_GPKG_PATH, NETWORK_EDGES_LAYER, and "
            "NETWORK_NODES_LAYER in your .env file."
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
            value=2048,
            step=256,
        )

        gemini_thinking_mode = st.selectbox(
            "Gemini thinking budget",
            options=[
                "dynamic",
                "off",
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
        st.write(f"SSAL hash: `{bundle.ssal_hash[:12]}`")
        st.write(f"Nodes: `{len(nodes)}`")

    st.subheader("Route task")

    col1, col2 = st.columns(2)

    with col1:
        origin = st.selectbox(
            "Origin node",
            nodes,
            index=_node_default_index(
                nodes,
                preferred_node=DEFAULT_ORIGIN_NODE,
                fallback_index=0,
            ),
        )

    with col2:
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

    st.write(f"Ground-truth length: `{_format_metric(ground_truth_length, digits=1)}`")

    render_route_map_preview(
        bundle=bundle,
        origin=origin,
        destination=destination,
        ground_truth_path=ground_truth["path"],
    )

    with st.expander("Ground-truth path"):
        st.code(
            json.dumps(ground_truth["path"], indent=2, ensure_ascii=False),
            language="json",
        )

    template = st.session_state.get(
        "route_prompt_template",
        DEFAULT_ROUTE_PROMPT_TEMPLATE,
    )

    try:
        prompt = build_route_prompt(
            ssal_text=bundle.ssal_text,
            origin=origin,
            destination=destination,
            template=template,
        )
    except KeyError as exc:
        st.error(f"Prompt template is missing or has an unknown placeholder: {exc}")
        return
    except ValueError as exc:
        st.error(f"Prompt template formatting failed: {exc}")
        return

    with st.expander("Debug / prompt and network details", expanded=False):
        st.subheader("Prompt template")

        edited_template = st.text_area(
            "Route prompt template",
            value=template,
            height=360,
            help=(
                "Available placeholders: {origin}, {destination}, {ssal_text}. "
                "Escape literal JSON braces as {{ and }}."
            ),
        )

        if edited_template != template:
            st.session_state.route_prompt_template = edited_template
            st.rerun()

        st.subheader("Generated prompt")

        st.caption("This is the full prompt that will be sent to the models.")

        st.text_area(
            "Generated route prompt",
            value=prompt,
            height=420,
        )

        st.download_button(
            "Download generated prompt",
            data=prompt,
            file_name=f"route_prompt_{origin}_to_{destination}.txt",
            mime="text/plain",
            width="stretch",
        )

        st.subheader("Network")
        st.write(f"GeoPackage: `{bundle.gpkg_path}`")
        st.write(f"Edges layer: `{bundle.edges_layer}`")
        st.write(f"Nodes layer: `{bundle.nodes_layer}`")
        st.write(f"SSAL hash: `{bundle.ssal_hash}`")
        st.write(f"Node count: `{len(nodes)}`")

        st.subheader("SSAL preview")
        preview = "\n".join(bundle.ssal_text.splitlines()[:40])
        st.code(preview, language="text")

    run_button = st.button(
        "Run route test",
        type="primary",
        width="stretch",
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
            ground_truth_path=ground_truth["path"],
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

    st.subheader("Route evaluation results")

    render_route_eval_summary_table(
        openai_evaluation=openai_evaluation,
        gemini_evaluation=gemini_evaluation,
    )

    result_col1, result_col2 = st.columns(2)

    with result_col1:
        render_route_eval_card(
            title="OpenAI",
            api_result=openai_result,
            evaluation=openai_evaluation,
        )

    with result_col2:
        render_route_eval_card(
            title="Gemini",
            api_result=gemini_result,
            evaluation=gemini_evaluation,
        )
