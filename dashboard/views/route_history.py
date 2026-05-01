from __future__ import annotations

import html
import json
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.db import export_route_history_json, load_route_evaluations
from dashboard.network import load_route_network_bundle
from dashboard.route_visualization import (
    RouteVisualization,
    node_coordinates_from_network_bundle,
)
from dashboard.route_map_helpers import (
    add_segment_highlights_to_map,
    build_segment_rows_from_evaluation,
    network_edges_from_bundle,
    parse_json_object,
    parse_path,
    render_highlight_summary,
    render_map_html_file,
    safe_map_token,
)


INVALID_SEGMENT_STATUSES = {
    "unknown_from_node",
    "unknown_to_node",
    "missing_edge",
}


def _format_bool(value: Any) -> str:
    if value == 1 or value is True:
        return "✅ Yes"
    if value == 0 or value is False:
        return "⚠️ No"
    return "—"


def _status_label(row: pd.Series) -> str:
    if (
        row.get("valid_json") == 1
        and row.get("valid_path") == 1
        and row.get("exact_path_match") == 1
    ):
        return "✅ Satisfactory"
    return "⚠️ Needs review"


def _selection_label(row: pd.Series) -> str:
    """Return a compact label for selecting a saved route evaluation."""
    row_id = row.get("id")
    created_at = str(row.get("created_at") or "")
    time_part = created_at.split(" ")[1] if " " in created_at else created_at
    provider = row.get("provider") or "?"
    origin = row.get("origin") or "?"
    destination = row.get("destination") or "?"

    return f"#{row_id} · {provider} · {time_part} · {origin} → {destination}"


def _format_metric_value(value: Any, digits: int = 3) -> str:
    """Format optional numeric metric values for compact display."""
    if value is None or pd.isna(value):
        return "—"

    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"

    return str(value)


def _format_error_text(value: Any) -> str:
    """Format optional error/reason text."""
    if value is None or pd.isna(value):
        return "—"

    text = str(value)
    return text if text and text.lower() != "nan" else "—"


def _metric_cell(label: str, value: Any) -> str:
    """Return compact HTML for one selected-evaluation metric cell."""
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


def _render_history_overview_table(display_df: pd.DataFrame) -> None:
    """Render a compact overview table for saved route evaluations."""
    overview_df = display_df.copy()

    overview_df["route"] = (
        overview_df["origin"].astype(str)
        + " → "
        + overview_df["destination"].astype(str)
    )

    overview_df["len_err"] = overview_df["relative_length_error"].apply(
        _format_metric_value
    )
    overview_df["node"] = overview_df["node_overlap"].apply(_format_metric_value)
    overview_df["edge"] = overview_df["edge_overlap"].apply(_format_metric_value)
    overview_df["reason"] = overview_df["error_text"].apply(_format_error_text)

    overview_columns = {
        "id": "ID",
        "created_at": "Time",
        "provider": "Provider",
        "model": "Model",
        "route": "Route",
        "status": "Status",
        "len_err": "Len err",
        "node": "Node",
        "edge": "Edge",
        "reason": "Reason",
    }

    existing_overview_columns = [
        column for column in overview_columns if column in overview_df.columns
    ]

    overview_df = overview_df[existing_overview_columns].rename(
        columns=overview_columns
    )

    st.dataframe(
        overview_df,
        width="stretch",
        hide_index=True,
        height=320,
    )


def _render_selected_evaluation_summary(selected_row: dict[str, Any]) -> None:
    """Render a compact summary card for the selected saved evaluation."""
    provider = selected_row.get("provider", "—")
    model = selected_row.get("model", "—")
    created_at = selected_row.get("created_at", "—")
    origin = selected_row.get("origin", "—")
    destination = selected_row.get("destination", "—")
    evaluation_id = selected_row.get("id", "—")

    candidate_path = parse_path(selected_row.get("candidate_path_json"))
    ground_truth_path = parse_path(selected_row.get("ground_truth_path_json"))

    candidate_edges = max(len(candidate_path) - 1, 0)
    ground_truth_edges = max(len(ground_truth_path) - 1, 0)

    candidate_length = selected_row.get("candidate_computed_length")
    ground_truth_length = selected_row.get("ground_truth_length")
    relative_length_error = selected_row.get("relative_length_error")
    node_overlap = selected_row.get("node_overlap")
    edge_overlap = selected_row.get("edge_overlap")
    error_text = _format_error_text(selected_row.get("error_text"))

    with st.container(border=True):
        st.markdown(f"**#{evaluation_id} · {provider}/{model}**")
        st.caption(str(created_at))
        st.markdown(f"Route: `{origin}` → `{destination}`")

        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)

        with metric_col1:
            st.markdown(
                _metric_cell(
                    "Candidate length",
                    _format_metric_value(candidate_length, digits=1),
                ),
                unsafe_allow_html=True,
            )

        with metric_col2:
            st.markdown(
                _metric_cell(
                    "Ground truth",
                    _format_metric_value(ground_truth_length, digits=1),
                ),
                unsafe_allow_html=True,
            )

        with metric_col3:
            st.markdown(
                _metric_cell("Candidate edges", str(candidate_edges)),
                unsafe_allow_html=True,
            )

        with metric_col4:
            st.markdown(
                _metric_cell("Reference edges", str(ground_truth_edges)),
                unsafe_allow_html=True,
            )

        metric_col5, metric_col6, metric_col7 = st.columns(3)

        with metric_col5:
            st.markdown(
                _metric_cell(
                    "Relative length error",
                    _format_metric_value(relative_length_error),
                ),
                unsafe_allow_html=True,
            )

        with metric_col6:
            st.markdown(
                _metric_cell("Node overlap", _format_metric_value(node_overlap)),
                unsafe_allow_html=True,
            )

        with metric_col7:
            st.markdown(
                _metric_cell("Edge overlap", _format_metric_value(edge_overlap)),
                unsafe_allow_html=True,
            )

        if error_text != "—":
            st.caption(f"Reason/error: {error_text}")


def _render_segment_inspection(selected_row: dict[str, Any]) -> None:
    """Render segment inspection for one selected saved evaluation row."""
    st.subheader("Route segment inspection")

    candidate_path = parse_path(selected_row.get("candidate_path_json"))
    ground_truth_path = parse_path(selected_row.get("ground_truth_path_json"))
    raw_evaluation = parse_json_object(selected_row.get("raw_evaluation_json"))
    candidate_validation = raw_evaluation.get("candidate_validation") or {}

    if len(candidate_path) < 2:
        st.info("No inspectable candidate route segments were saved for this evaluation.")
        return

    if len(ground_truth_path) < 2:
        st.info("No inspectable ground-truth route segments were saved for this evaluation.")
        return

    segment_rows = build_segment_rows_from_evaluation(
        candidate_path=candidate_path,
        ground_truth_path=ground_truth_path,
        candidate_validation=candidate_validation,
    )

    if not segment_rows:
        st.info("No inspectable candidate route segments were found.")
        return

    segment_df = pd.DataFrame(segment_rows)

    invalid_count = int(
        segment_df["segment_status"].isin(INVALID_SEGMENT_STATUSES).sum()
    )
    extra_count = int((segment_df["segment_status"] == "extra_segment").sum())

    if invalid_count:
        st.error(f"{invalid_count} invalid candidate segment(s) found.")
    elif extra_count:
        st.warning(
            f"{extra_count} valid candidate segment(s) are outside the reference route."
        )
    else:
        st.success("All candidate segments match the reference route.")

    display_segment_df = segment_df.copy()
    display_segment_df["in_reference_route"] = display_segment_df[
        "in_reference_route"
    ].apply(_format_bool)

    st.dataframe(
        display_segment_df,
        width="stretch",
        hide_index=True,
    )

    with st.expander("Raw evaluator output"):
        if raw_evaluation:
            st.json(raw_evaluation)
        else:
            st.info("No raw evaluator JSON was saved for this row.")


def _render_selected_route_map(selected_row: dict[str, Any]) -> None:
    """Render candidate/reference route map for one selected saved evaluation."""
    candidate_path = parse_path(selected_row.get("candidate_path_json"))
    ground_truth_path = parse_path(selected_row.get("ground_truth_path_json"))
    raw_evaluation = parse_json_object(selected_row.get("raw_evaluation_json"))
    candidate_validation = raw_evaluation.get("candidate_validation") or {}

    if len(candidate_path) < 2:
        st.info("No inspectable candidate route was saved for this evaluation.")
        return

    if len(ground_truth_path) < 2:
        st.info("No inspectable ground-truth route was saved for this evaluation.")
        return

    segment_rows = build_segment_rows_from_evaluation(
        candidate_path=candidate_path,
        ground_truth_path=ground_truth_path,
        candidate_validation=candidate_validation,
    )

    try:
        bundle = load_route_network_bundle()
    except Exception as exc:
        st.warning(f"Could not load route network for map rendering: {exc}")
        return

    node_coordinates = node_coordinates_from_network_bundle(bundle)

    if not node_coordinates:
        st.info("No node coordinates are available for route map rendering.")
        return

    provider = selected_row.get("provider", "provider")
    model = selected_row.get("model", "model")
    origin = selected_row.get("origin", "?")
    destination = selected_row.get("destination", "?")
    evaluation_id = selected_row.get("id", "unknown")

    provider_color = "blue"
    if str(provider).lower() == "gemini":
        provider_color = "purple"

    viz = RouteVisualization(
        node_coordinates=node_coordinates,
        metadata={
            "ssal_hash": selected_row.get("ssal_hash", bundle.ssal_hash[:12]),
            "evaluation_id": evaluation_id,
            "provider": provider,
            "model": model,
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
            "label": f"{provider} candidate route",
            "model": model,
            "origin": origin,
            "destination": destination,
            "evaluation_id": evaluation_id,
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
            "evaluation_id": evaluation_id,
        },
    )

    viz.add_route_node_markers(
        route=ground_truth_path,
        name="Ground truth route nodes",
        color="green",
        show=False,
        metadata={
            "route_type": "ground_truth",
            "evaluation_id": evaluation_id,
        },
    )

    highlight_count = add_segment_highlights_to_map(
        viz=viz,
        segment_rows=segment_rows,
    )
    render_highlight_summary(highlight_count)

    output_dir = Path(tempfile.gettempdir()) / "llm_compare_dashboard_maps"
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = (
        "route_history_"
        f"{safe_map_token(evaluation_id)}_"
        f"{safe_map_token(provider)}_"
        f"{safe_map_token(origin)}_"
        f"{safe_map_token(destination)}.html"
    )
    output_path = output_dir / safe_name

    viz.render(save_path=str(output_path))
    render_map_html_file(html_path=output_path, height=560)


def render_route_history_view() -> None:
    history_df = load_route_evaluations()

    if history_df.empty:
        st.info("No saved route evaluations yet. Run a route evaluation first.")
        return

    with st.expander("Filters", expanded=False):
        provider_options = sorted(history_df["provider"].dropna().unique())
        selected_providers = st.multiselect(
            "Provider",
            provider_options,
            default=provider_options,
        )

        status_options = ["✅ Satisfactory", "⚠️ Needs review"]
        selected_statuses = st.multiselect(
            "Status",
            status_options,
            default=status_options,
        )

    display_df = history_df.copy()
    display_df["status"] = display_df.apply(_status_label, axis=1)

    if selected_providers:
        display_df = display_df[display_df["provider"].isin(selected_providers)]

    if selected_statuses:
        display_df = display_df[display_df["status"].isin(selected_statuses)]

    if display_df.empty:
        st.info("No route evaluations match the selected filters.")
        return

    table_df = display_df.copy()

    for column in ["valid_json", "valid_path", "exact_path_match"]:
        if column in table_df.columns:
            table_df[column] = table_df[column].apply(_format_bool)

    columns = [
        "created_at",
        "provider",
        "model",
        "origin",
        "destination",
        "status",
        "valid_json",
        "valid_path",
        "exact_path_match",
        "candidate_computed_length",
        "ground_truth_length",
        "relative_length_error",
        "node_overlap",
        "edge_overlap",
        "error_text",
    ]

    existing_columns = [column for column in columns if column in table_df.columns]

    _render_history_overview_table(display_df)

    st.download_button(
        "Download route history JSON",
        data=export_route_history_json(),
        file_name="route_history_export.json",
        mime="application/json",
        width="stretch",
    )

    with st.expander("Detailed history table"):
        st.dataframe(
            table_df[existing_columns],
            width="stretch",
            hide_index=True,
        )

    st.subheader("Inspect selected evaluation")

    selection_df = display_df.reset_index(drop=True).copy()
    option_ids = selection_df["id"].tolist()

    selection_labels = {
        row["id"]: _selection_label(row)
        for _, row in selection_df.iterrows()
    }

    selected_id = st.selectbox(
        "Saved evaluation",
        options=option_ids,
        format_func=lambda row_id: selection_labels.get(row_id, str(row_id)),
    )

    selected_row = selection_df.loc[selection_df["id"] == selected_id].iloc[0].to_dict()

    _render_selected_evaluation_summary(selected_row)

    with st.expander("Map replay", expanded=True):
        _render_selected_route_map(selected_row)

    _render_segment_inspection(selected_row)
