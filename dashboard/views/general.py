import json
import time

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
    delete_all_runs,
    export_runs_json,
    load_run_by_id,
    load_saved_runs,
    save_run,
)


def render_general_view() -> None:
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
            value=300,
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
            help="Dynamic lets Gemini decide. Off disables thinking. Custom sets an explicit thinking token budget.",
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


    default_prompt = "Is Aalto University in Otaniemi?"

    prompt = st.text_area(
        "Prompt",
        value=default_prompt,
        height=180,
        placeholder="Type a prompt here...",
    )

    run = st.button("Run both models", type="primary", use_container_width=True)

    if "history" not in st.session_state:
        st.session_state.history = []

    if run:
        if not prompt.strip():
            st.warning("Please enter a prompt.")
            st.stop()

        with st.spinner("Calling both APIs..."):
            openai_result = call_openai(prompt, openai_model, max_output_tokens)
            gemini_result = call_gemini(
                prompt,
                gemini_model,
                max_output_tokens,
                thinking_mode=gemini_thinking_mode,
                custom_thinking_budget=gemini_custom_thinking_budget,
            )

        save_run(prompt, openai_result)
        save_run(prompt, gemini_result)

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

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.header("OpenAI")
            if openai_result["ok"]:
                st.success("Request succeeded")
                st.write(openai_result["text"])

                meta = openai_result["metadata"]
                attempts = meta.get("attempts", 1)
                st.caption(f"Attempts: {attempts}")

                if show_cost_estimate:
                    cost = estimate_openai_cost(
                        meta["model"],
                        meta.get("input_tokens", 0),
                        meta.get("output_tokens", 0),
                    )
                    if cost is not None:
                        st.caption(f"Rough estimated cost: ${cost:.6f}")
                    else:
                        st.caption("Rough estimated cost: not configured for this model")

                st.subheader("OpenAI metadata")
                st.json(openai_result["metadata"])

                if show_raw:
                    with st.expander("Raw OpenAI response"):
                        st.json(openai_result["raw"])
            else:
                st.error(openai_result["error"])
                if "metadata" in openai_result:
                    meta = openai_result["metadata"]
                    attempts = meta.get("attempts", 1)
                    st.caption(f"Attempts: {attempts}")
                    st.subheader("OpenAI metadata")
                    st.json(openai_result["metadata"])

        with col2:
            st.header("Gemini")
            if gemini_result["ok"]:
                st.success("Request succeeded")
                st.write(gemini_result["text"])

                meta = gemini_result["metadata"]
                parts = []
                attempts = meta.get("attempts")
                thinking_mode = meta.get("thinking_mode")
                thinking_budget = meta.get("thinking_budget")

                if attempts is not None:
                    parts.append(f"Attempts: {attempts}")
                if thinking_mode:
                    parts.append(f"Thinking mode: {thinking_mode}")
                if thinking_budget is not None:
                    parts.append(f"Thinking budget: {thinking_budget}")

                if parts:
                    st.caption(" | ".join(parts))

                st.subheader("Gemini metadata")
                st.json(gemini_result["metadata"])

                if show_raw:
                    with st.expander("Raw Gemini response"):
                        st.json(gemini_result["raw"])
            else:
                st.error(gemini_result["error"])
                if "metadata" in gemini_result:
                    meta = gemini_result["metadata"]
                    parts = []
                    attempts = meta.get("attempts")
                    thinking_mode = meta.get("thinking_mode")
                    thinking_budget = meta.get("thinking_budget")

                    if attempts is not None:
                        parts.append(f"Attempts: {attempts}")
                    if thinking_mode:
                        parts.append(f"Thinking mode: {thinking_mode}")
                    if thinking_budget is not None:
                        parts.append(f"Thinking budget: {thinking_budget}")

                    if parts:
                        st.caption(" | ".join(parts))

                    st.subheader("Gemini metadata")
                    st.json(gemini_result["metadata"])

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

        st.dataframe(comparison_df, use_container_width=True)

    st.divider()
    st.subheader("Current browser session history")

    if st.session_state.history:
        st.dataframe(pd.DataFrame(st.session_state.history), use_container_width=True)
    else:
        st.caption("No runs yet in this browser session.")

    st.divider()
    st.subheader("Saved history (persistent)")

    saved_df = load_saved_runs(limit=history_limit)

    col_a, col_b = st.columns([1, 1])
    with col_a:
        export_json = export_runs_json()
        st.download_button(
            "Download saved history as JSON",
            data=export_json,
            file_name="llm_compare_history.json",
            mime="application/json",
            use_container_width=True,
        )
    with col_b:
        if st.button("Clear saved history", type="secondary", use_container_width=True):
            delete_all_runs()
            st.success("Saved history cleared.")
            st.rerun()

    if not saved_df.empty:
        st.dataframe(saved_df, use_container_width=True)

        run_ids = saved_df["id"].tolist()
        selected_run_id = st.selectbox("Inspect saved run", options=run_ids, format_func=lambda x: f"Run #{x}")

        selected_run = load_run_by_id(int(selected_run_id))
        if selected_run:
            st.markdown("**Saved run details**")
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
    else:
        st.caption("No saved history yet. Run the models once to persist data.")
