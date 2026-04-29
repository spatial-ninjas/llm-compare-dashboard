from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.db import export_route_history_json, load_route_evaluations


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


def _parse_path(value: Any) -> list[str]:
    """Parse a saved JSON path value into node IDs."""
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


def _parse_json_object(value: Any) -> dict[str, Any]:
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


def _path_to_segments(path: list[str]) -> list[tuple[str, str]]:
    """Convert a node path into ordered directed route segments."""
    return list(zip(path, path[1:]))


def _missing_edge_set(candidate_validation: dict[str, Any]) -> set[tuple[str, str]]:
    """Return evaluator-reported missing edges as directed segment tuples."""
    missing_edges: set[tuple[str, str]] = set()

    for edge in candidate_validation.get("missing_edges") or []:
        if isinstance(edge, (list, tuple)) and len(edge) == 2:
            source, target = edge
            missing_edges.add((str(source), str(target)))

    return missing_edges


def _build_segment_rows_from_evaluation(
    *,
    candidate_path: list[str],
    ground_truth_path: list[str],
    candidate_validation: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build display-only segment rows from saved evaluator output.

    This intentionally does not re-validate the route against the graph. Raw
    route parsing, graph validation, and missing-edge detection remain owned by
    research.evaluation. This helper only formats the saved evaluator output
    for dashboard inspection.
    """
    reference_segments = set(_path_to_segments(ground_truth_path))
    unknown_nodes = {str(node) for node in candidate_validation.get("unknown_nodes") or []}
    missing_edges = _missing_edge_set(candidate_validation)

    rows: list[dict[str, Any]] = []

    for index, (from_node, to_node) in enumerate(_path_to_segments(candidate_path)):
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


def _render_segment_inspection(selected_row: dict[str, Any]) -> None:
    """Render segment inspection for one selected saved evaluation row."""
    st.subheader("Route segment inspection")

    candidate_path = _parse_path(selected_row.get("candidate_path_json"))
    ground_truth_path = _parse_path(selected_row.get("ground_truth_path_json"))
    raw_evaluation = _parse_json_object(selected_row.get("raw_evaluation_json"))
    candidate_validation = raw_evaluation.get("candidate_validation") or {}

    if len(candidate_path) < 2:
        st.info("No inspectable candidate route segments were saved for this evaluation.")
        return

    if len(ground_truth_path) < 2:
        st.info("No inspectable ground-truth route segments were saved for this evaluation.")
        return

    segment_rows = _build_segment_rows_from_evaluation(
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


def render_route_history_view() -> None:
    st.header("Route evaluation history")

    history_df = load_route_evaluations()

    if history_df.empty:
        st.info("No saved route evaluations yet. Run a route evaluation first.")
        return

    with st.expander("Filters", expanded=True):
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

    st.dataframe(
        table_df[existing_columns],
        width="stretch",
        hide_index=True,
    )

    st.download_button(
        "Download route history JSON",
        data=export_route_history_json(),
        file_name="route_history_export.json",
        mime="application/json",
        width="stretch",
    )

    st.subheader("Inspect selected evaluation")

    selected_index = st.number_input(
        "Row number",
        min_value=0,
        max_value=len(display_df) - 1,
        value=0,
        step=1,
    )

    selected_row = display_df.iloc[int(selected_index)].to_dict()

    with st.expander("Available saved evaluation fields"):
        st.write(list(selected_row.keys()))

    with st.expander("Raw selected evaluation row"):
        st.json(selected_row)

    _render_segment_inspection(selected_row)
