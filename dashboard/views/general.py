"""General prompt-comparison view."""

from __future__ import annotations

import json
import time
from typing import Any

import pandas as pd
import streamlit as st

from dashboard.api_clients import (
    call_gemini,
    call_openai,
    estimate_openai_cost,
    get_api_key_status,
)
from dashboard.db import (
    DB_PATH,
    export_runs_json,
    load_run_by_id,
    load_saved_runs,
    save_run,
)


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


def _metadata_caption(metadata: dict[str, Any]) -> str:
    """Return compact provider metadata for result captions."""
    parts: list[str] = []

    attempts = metadata.get("attempts")
    thinking_mode = metadata.get("thinking_mode")
    thinking_budget = metadata.get("thinking_budget")

    if attempts is not None:
        parts.append(f"Attempts: {attempts}")
    if thinking_mode:
        parts.append(f"Thinking mode: {thinking_mode}")
    if thinking_budget is not None:
        parts.append(f"Thinking budget: {thinking_budget}")

    return " | ".join(parts)


def _result_download_payload(
    *,
    prompt: str,
    openai_run_id: int,
    gemini_run_id: int,
    openai_result: dict[str, Any],
    gemini_result: dict[str, Any],
) -> str:
    """Return a formatted JSON payload for the latest comparison run."""
    return json.dumps(
        {
            "prompt": prompt,
            "openai": {
                "run_id": openai_run_id,
                "provider_result": openai_result,
            },
            "gemini": {
                "run_id": gemini_run_id,
                "provider_result": gemini_result,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


def render_save_summary(
    *,
    openai_run_id: int,
    gemini_run_id: int,
) -> None:
    """Show a compact persistence confirmation after a comparison run."""
    st.success("Comparison saved to local history.")

    st.caption("Saved two generic provider run rows.")

    with st.expander("Saved row IDs"):
        st.json(
            {
                "openai_run_id": openai_run_id,
                "gemini_run_id": gemini_run_id,
            }
        )


def render_provider_card(
    *,
    title: str,
    api_result: dict[str, Any],
    show_raw: bool,
    show_cost_estimate: bool = False,
) -> None:
    """Render one provider result card."""
    st.header(title)

    metadata = api_result.get("metadata") or {}

    if api_result.get("ok"):
        st.success("Request succeeded")
        st.write(api_result.get("text") or "")

        caption = _metadata_caption(metadata)
        if caption:
            st.caption(caption)

        if show_cost_estimate:
            cost = estimate_openai_cost(
                metadata.get("model"),
                metadata.get("input_tokens", 0),
                metadata.get("output_tokens", 0),
            )
            if cost is not None:
                st.caption(f"Rough estimated cost: ${cost:.6f}")
            else:
                st.caption("Rough estimated cost: not configured for this model")
    else:
        st.error(api_result.get("error") or "Provider call failed.")

        caption = _metadata_caption(metadata)
        if caption:
            st.caption(caption)

    with st.expander(f"{title} metadata"):
        st.json(metadata)

    if show_raw:
        with st.expander(f"Raw {title} response"):
            st.json(api_result.get("raw", api_result))


def render_saved_history(*, history_limit: int, show_raw: bool) -> None:
    """Render persistent saved-history table and inspection controls."""
    st.divider()
    st.subheader("Saved history")

    saved_df = load_saved_runs(limit=history_limit)

    st.download_button(
        "Download saved history as JSON",
        data=export_runs_json(),
        file_name="llm_compare_history.json",
        mime="application/json",
        width="stretch",
    )

    if saved_df.empty:
        st.caption("No saved history yet. Run the models once to persist data.")
        return

    st.dataframe(saved_df, width="stretch")

    run_ids = saved_df["id"].tolist()
    selected_run_id = st.selectbox(
        "Inspect saved run",
        options=run_ids,
        format_func=lambda x: f"Run #{x}",
    )

    selected_run = load_run_by_id(int(selected_run_id))
    if not selected_run:
        return

    with st.expander("Saved run details", expanded=False):
        st.json(
            {
                "id": selected_run["id"],
                "created_at": selected_run["created_at"],
                "provider": selected_run["provider"],
                "model": selected_run["model"],
                "ok": selected_run["ok"],
                "latency_ms": selected_run["latency_ms"],
                "max_output_tokens": selected_run["max_output_tokens"],
                "input_tokens": selected_run["input_tokens"],
                "output_tokens": selected_run["output_tokens"],
                "thoughts_tokens": selected_run.get("thoughts_tokens"),
                "total_tokens": selected_run["total_tokens"],
                "thinking_mode": selected_run.get("thinking_mode"),
                "thinking_budget": selected_run.get("thinking_budget"),
                "attempts": selected_run.get("attempts"),
                "finish_status": selected_run["finish_status"],
            }
        )

        st.markdown("**Prompt**")
        st.code(selected_run["prompt"] or "", language="text")

        if selected_run.get("response_text"):
            st.markdown("**Response**")
            st.write(selected_run["response_text"])

        if selected_run.get("error_text"):
            st.markdown("**Error**")
            st.error(selected_run["error_text"])

        if show_raw and selected_run.get("raw_json") is not None:
            with st.expander("Raw saved response"):
                st.json(selected_run["raw_json"])


def render_general_view() -> None:
    """Render the general prompt-comparison view."""
    with st.sidebar:
        st.header("Settings")

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
            ],
            index=0,
        )

        max_output_tokens = st.slider(
            "Max response tokens",
            min_value=32,
            max_value=2048,
            value=1024,
            step=32,
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
                max_value=2048,
                value=128,
                step=32,
            )

        history_limit = st.slider(
            "Saved rows to show",
            min_value=10,
            max_value=500,
            value=100,
            step=10,
        )

        show_raw = st.checkbox("Show raw API responses", value=False)
        show_cost_estimate = st.checkbox("Show rough OpenAI cost estimate", value=True)
        api_key_status = get_api_key_status()

        st.divider()
        st.caption("Environment key status")
        st.write(f"OpenAI key loaded: {'✅' if api_key_status['openai'] else '❌'}")
        st.write(f"Gemini key loaded: {'✅' if api_key_status['gemini'] else '❌'}")
        st.write(f"SQLite DB: `{DB_PATH.name}`")

        st.divider()
        st.caption("History export")
        st.download_button(
            "Download saved history JSON",
            data=export_runs_json(),
            file_name="llm_compare_history.json",
            mime="application/json",
            width="stretch",
        )

    default_prompt = "Is Aalto University in Otaniemi?"

    prompt = st.text_area(
        "Prompt",
        value=default_prompt,
        height=180,
        placeholder="Type a prompt here...",
    )

    run = st.button("Run both models", type="primary", width="stretch")

    if "history" not in st.session_state:
        st.session_state.history = []

    if run:
        if not prompt.strip():
            st.warning("Please enter a prompt.")
            st.stop()

        with st.status("Running comparison...", expanded=True) as status:
            st.write("Calling OpenAI...")
            openai_result = call_openai(prompt, openai_model, max_output_tokens)
            st.write(
                _provider_status_message(
                    provider="OpenAI",
                    api_result=openai_result,
                )
            )

            st.write("Calling Gemini...")
            gemini_result = call_gemini(
                prompt,
                gemini_model,
                max_output_tokens,
                thinking_mode=gemini_thinking_mode,
                custom_thinking_budget=gemini_custom_thinking_budget,
            )
            st.write(
                _provider_status_message(
                    provider="Gemini",
                    api_result=gemini_result,
                )
            )

            st.write("Saving provider runs...")
            openai_run_id = save_run(prompt, openai_result)
            gemini_run_id = save_run(prompt, gemini_result)

            status.update(
                label="Comparison completed.",
                state="complete",
                expanded=False,
            )

        st.session_state.history.insert(
            0,
            {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "prompt": prompt,
                "openai_ok": openai_result.get("ok", False),
                "gemini_ok": gemini_result.get("ok", False),
                "openai_model": openai_model,
                "gemini_model": gemini_model,
                "gemini_thinking_mode": gemini_thinking_mode,
                "gemini_thinking_budget": (
                    gemini_custom_thinking_budget
                    if gemini_thinking_mode == "custom"
                    else (0 if gemini_thinking_mode == "off" else None)
                ),
                "max_output_tokens": max_output_tokens,
                "openai_total_tokens": openai_result.get("metadata", {}).get("total_tokens"),
                "gemini_total_tokens": gemini_result.get("metadata", {}).get("total_tokens"),
            },
        )

        render_save_summary(
            openai_run_id=openai_run_id,
            gemini_run_id=gemini_run_id,
        )

        st.download_button(
            "Download this comparison as JSON",
            data=_result_download_payload(
                prompt=prompt,
                openai_run_id=openai_run_id,
                gemini_run_id=gemini_run_id,
                openai_result=openai_result,
                gemini_result=gemini_result,
            ),
            file_name="llm_comparison_result.json",
            mime="application/json",
            width="stretch",
        )

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            render_provider_card(
                title="OpenAI",
                api_result=openai_result,
                show_raw=show_raw,
                show_cost_estimate=show_cost_estimate,
            )

        with col2:
            render_provider_card(
                title="Gemini",
                api_result=gemini_result,
                show_raw=show_raw,
            )

        st.divider()
        st.subheader("Quick comparison")

        comparison_df = pd.DataFrame(
            [
                {
                    "provider": "OpenAI",
                    "model": openai_model,
                    "ok": openai_result.get("ok", False),
                    "latency_ms": openai_result.get("metadata", {}).get("latency_ms"),
                    "input_tokens": openai_result.get("metadata", {}).get("input_tokens"),
                    "output_tokens": openai_result.get("metadata", {}).get("output_tokens"),
                    "total_tokens": openai_result.get("metadata", {}).get("total_tokens"),
                    "attempts": openai_result.get("metadata", {}).get("attempts"),
                    "max_output_tokens": openai_result.get("metadata", {}).get("max_output_tokens"),
                },
                {
                    "provider": "Gemini",
                    "model": gemini_model,
                    "ok": gemini_result.get("ok", False),
                    "latency_ms": gemini_result.get("metadata", {}).get("latency_ms"),
                    "input_tokens": gemini_result.get("metadata", {}).get("input_tokens"),
                    "output_tokens": gemini_result.get("metadata", {}).get("output_tokens"),
                    "thoughts_tokens": gemini_result.get("metadata", {}).get("thoughts_tokens"),
                    "total_tokens": gemini_result.get("metadata", {}).get("total_tokens"),
                    "attempts": gemini_result.get("metadata", {}).get("attempts"),
                    "thinking_mode": gemini_result.get("metadata", {}).get("thinking_mode"),
                    "thinking_budget": gemini_result.get("metadata", {}).get("thinking_budget"),
                    "max_output_tokens": gemini_result.get("metadata", {}).get("max_output_tokens"),
                },
            ]
        )

        st.dataframe(comparison_df, width="stretch")

    st.divider()
    st.subheader("Current browser session history")

    if st.session_state.history:
        st.dataframe(pd.DataFrame(st.session_state.history), width="stretch")
    else:
        st.caption("No runs yet in this browser session.")

    render_saved_history(history_limit=history_limit, show_raw=show_raw)
