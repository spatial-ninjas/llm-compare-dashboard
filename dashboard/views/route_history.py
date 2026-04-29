from __future__ import annotations

import json
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.db import export_route_history_json, load_route_evaluations


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


def _path_to_segments(path: list[str]) -> list[tuple[str, str]]:
    """Convert a node path into ordered node-to-node route segments."""
    return list(zip(path, path[1:]))


def _build_segment_rows(
    *,
    candidate_path: list[str],
    ground_truth_path: list[str],
) -> list[dict[str, Any]]:
    """Build graph-agnostic segment inspection rows."""
    reference_segments = set(_path_to_segments(ground_truth_path))

    rows: list[dict[str, Any]] = []

    for index, (from_node, to_node) in enumerate(_path_to_segments(candidate_path)):
        in_reference_route = (from_node, to_node) in reference_segments

        rows.append(
            {
                "index": index,
                "from_node": from_node,
                "to_node": to_node,
                "in_reference_route": in_reference_route,
                "segment_status": "ok" if in_reference_route else "extra_segment",
                "notes": (
                    "Matches reference route"
                    if in_reference_route
                    else "Candidate segment is not in the reference route"
                ),
            }
        )

    return rows


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
        max_value=max(len(display_df) - 1, 0),
        value=0,
        step=1,
    )

    selected_row = display_df.iloc[int(selected_index)].to_dict()

    with st.expander("Available saved evaluation fields"):
        st.write(list(selected_row.keys()))

    with st.expander("Raw selected evaluation row"):
        st.json(selected_row)

    st.subheader("Route segment inspection")

    candidate_path = _parse_path(selected_row.get("candidate_path_json"))
    ground_truth_path = _parse_path(selected_row.get("ground_truth_path_json"))

    if len(candidate_path) < 2:
        st.info("No inspectable candidate route segments were saved for this evaluation.")
        return

    if len(ground_truth_path) < 2:
        st.info("No inspectable ground-truth route segments were saved for this evaluation.")
        return

    segment_rows = _build_segment_rows(
        candidate_path=candidate_path,
        ground_truth_path=ground_truth_path,
    )

    segment_df = pd.DataFrame(segment_rows)

    review_count = int((segment_df["segment_status"] != "ok").sum())

    if review_count == 0:
        st.success("All candidate segments match the reference route.")
    else:
        st.warning(f"{review_count} candidate segment(s) are not in the reference route.")

    display_segment_df = segment_df.copy()
    display_segment_df["in_reference_route"] = display_segment_df[
        "in_reference_route"
    ].apply(_format_bool)

    st.dataframe(
        display_segment_df,
        width="stretch",
        hide_index=True,
    )
