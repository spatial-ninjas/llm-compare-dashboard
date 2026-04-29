from __future__ import annotations

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

    st.json(selected_row)
