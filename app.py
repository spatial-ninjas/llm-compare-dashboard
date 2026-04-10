import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import OpenAI


load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "history.db"

st.set_page_config(
    page_title="OpenAI vs Gemini Comparator",
    layout="wide",
)

st.title("OpenAI vs Gemini Comparator")
st.caption("Send the same prompt to both APIs, compare outputs, and persist history in SQLite.")


def safe_getattr(obj: Any, name: str, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def obj_to_dict(obj: Any) -> Any:
    if obj is None:
        return None

    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass

    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass

    if isinstance(obj, (dict, list, str, int, float, bool)) or obj is None:
        return obj

    return str(obj)


def estimate_openai_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    pricing_per_million = {
        "gpt-5.4": {"input": 2.50, "output": 15.00},
        "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    }

    price = pricing_per_million.get(model)
    if not price:
        return None

    return (
        (input_tokens / 1_000_000) * price["input"]
        + (output_tokens / 1_000_000) * price["output"]
    )


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                prompt TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                ok INTEGER NOT NULL,
                latency_ms REAL,
                max_output_tokens INTEGER,
                input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                finish_status TEXT,
                response_text TEXT,
                error_text TEXT,
                raw_json TEXT
            )
            """
        )

        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(runs)").fetchall()
        }

        extra_columns = {
            "thinking_mode": "TEXT",
            "thinking_budget": "INTEGER",
            "thoughts_tokens": "INTEGER",
            "attempts": "INTEGER",
        }

        for column_name, column_type in extra_columns.items():
            if column_name not in existing_columns:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {column_name} {column_type}")

        conn.commit()


def save_run(prompt: str, result: Dict[str, Any]) -> None:
    meta = result.get("metadata", {}) or {}
    finish_status = (
        meta.get("finish_reason")
        or meta.get("status")
        or (
            (meta.get("incomplete_details") or {}).get("reason")
            if isinstance(meta.get("incomplete_details"), dict)
            else None
        )
    )

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO runs (
                created_at,
                prompt,
                provider,
                model,
                ok,
                latency_ms,
                max_output_tokens,
                input_tokens,
                output_tokens,
                total_tokens,
                finish_status,
                response_text,
                error_text,
                raw_json,
                thinking_mode,
                thinking_budget,
                thoughts_tokens,
                attempts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.strftime("%Y-%m-%d %H:%M:%S"),
                prompt,
                result.get("provider"),
                meta.get("model"),
                1 if result.get("ok", False) else 0,
                meta.get("latency_ms"),
                meta.get("max_output_tokens"),
                meta.get("input_tokens"),
                meta.get("output_tokens"),
                meta.get("total_tokens"),
                finish_status,
                result.get("text"),
                result.get("error"),
                json.dumps(result.get("raw"), ensure_ascii=False) if result.get("raw") is not None else None,
                meta.get("thinking_mode"),
                meta.get("thinking_budget"),
                meta.get("thoughts_tokens"),
                meta.get("attempts"),
            ),
        )
        conn.commit()


def load_saved_runs(limit: int = 100) -> pd.DataFrame:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                created_at,
                provider,
                model,
                ok,
                latency_ms,
                max_output_tokens,
                input_tokens,
                output_tokens,
                total_tokens,
                finish_status,
                thinking_mode,
                thinking_budget,
                thoughts_tokens,
                attempts,
                prompt,
                response_text,
                error_text
            FROM runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([dict(row) for row in rows])


def load_run_by_id(run_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

    if row is None:
        return None

    data = dict(row)
    raw_json = data.get("raw_json")
    if raw_json:
        try:
            data["raw_json"] = json.loads(raw_json)
        except Exception:
            pass
    return data


def delete_all_runs() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM runs")
        conn.commit()


def export_runs_json() -> str:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)


def call_openai(prompt: str, model: str, max_output_tokens: int) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        return {
            "ok": False,
            "provider": "OpenAI",
            "error": "Missing OPENAI_API_KEY in environment.",
        }

    client = OpenAI(api_key=OPENAI_API_KEY)
    started = time.perf_counter()

    try:
        response = client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=max_output_tokens,
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        usage = safe_getattr(response, "usage", None)
        usage_dict = obj_to_dict(usage) or {}

        input_tokens = usage_dict.get("input_tokens") or usage_dict.get("prompt_tokens") or 0
        output_tokens = usage_dict.get("output_tokens") or usage_dict.get("completion_tokens") or 0
        total_tokens = usage_dict.get("total_tokens") or (input_tokens + output_tokens)

        request_id = safe_getattr(response, "_request_id", None) or safe_getattr(response, "request_id", None)
        status = safe_getattr(response, "status", None)
        incomplete_details = obj_to_dict(safe_getattr(response, "incomplete_details", None))

        text_output = safe_getattr(response, "output_text", None)
        if not text_output:
            text_output = json.dumps(obj_to_dict(response), indent=2, ensure_ascii=False)

        return {
            "ok": True,
            "provider": "OpenAI",
            "text": text_output,
            "metadata": {
                "provider": "OpenAI",
                "model": model,
                "latency_ms": latency_ms,
                "request_id": request_id,
                "status": status,
                "incomplete_details": incomplete_details,
                "max_output_tokens": max_output_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "attempts": 1,
                "usage_raw": usage_dict,
            },
            "raw": obj_to_dict(response),
        }

    except Exception as e:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "ok": False,
            "provider": "OpenAI",
            "error": str(e),
            "metadata": {
                "provider": "OpenAI",
                "model": model,
                "latency_ms": latency_ms,
                "max_output_tokens": max_output_tokens,
                "attempts": 1,
            },
        }


def build_gemini_thinking_config(
    thinking_mode: str,
    custom_thinking_budget: Optional[int],
) -> Optional[types.ThinkingConfig]:
    if thinking_mode == "off":
        return types.ThinkingConfig(thinking_budget=0)

    if thinking_mode == "custom":
        return types.ThinkingConfig(
            thinking_budget=custom_thinking_budget if custom_thinking_budget is not None else 128
        )

    return None


def as_int(value: Any) -> int:
    return int(value) if value is not None else 0


def call_gemini(
    prompt: str,
    model: str,
    max_output_tokens: int,
    thinking_mode: str = "dynamic",
    custom_thinking_budget: Optional[int] = None,
    max_retries: int = 4,
) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        return {
            "ok": False,
            "provider": "Gemini",
            "error": "Missing GEMINI_API_KEY in environment.",
        }

    client = genai.Client(api_key=GEMINI_API_KEY)

    thinking_config = build_gemini_thinking_config(
        thinking_mode=thinking_mode,
        custom_thinking_budget=custom_thinking_budget,
    )

    config_kwargs: Dict[str, Any] = {
        "max_output_tokens": max_output_tokens,
    }
    if thinking_config is not None:
        config_kwargs["thinking_config"] = thinking_config

    last_error = None
    started_total = time.perf_counter()

    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )

            latency_ms = round((time.perf_counter() - started_total) * 1000, 2)

            response_dict = obj_to_dict(response) or {}
            text_output = safe_getattr(response, "text", None)
            if not text_output:
                text_output = json.dumps(response_dict, indent=2, ensure_ascii=False)

            usage_md = response_dict.get("usage_metadata", {}) or {}
            input_tokens = as_int(usage_md.get("prompt_token_count"))
            output_tokens = as_int(usage_md.get("candidates_token_count"))
            thoughts_tokens = as_int(usage_md.get("thoughts_token_count"))
            total_tokens = as_int(usage_md.get("total_token_count")) or (
                input_tokens + output_tokens + thoughts_tokens
            )

            finish_reason = None
            finish_message = None
            candidates = response_dict.get("candidates")
            if isinstance(candidates, list) and candidates:
                finish_reason = candidates[0].get("finish_reason")
                finish_message = candidates[0].get("finish_message")

            effective_thinking_budget = None
            if thinking_mode == "off":
                effective_thinking_budget = 0
            elif thinking_mode == "custom":
                effective_thinking_budget = custom_thinking_budget

            return {
                "ok": True,
                "provider": "Gemini",
                "text": text_output,
                "metadata": {
                    "provider": "Gemini",
                    "model": model,
                    "latency_ms": latency_ms,
                    "finish_reason": finish_reason,
                    "finish_message": finish_message,
                    "max_output_tokens": max_output_tokens,
                    "thinking_mode": thinking_mode,
                    "thinking_budget": effective_thinking_budget,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "thoughts_tokens": thoughts_tokens,
                    "total_tokens": total_tokens,
                    "attempts": attempt + 1,
                    "usage_raw": usage_md,
                },
                "raw": response_dict,
            }

        except Exception as e:
            last_error = e
            error_text = str(e)

            is_retryable = (
                "503" in error_text
                or "UNAVAILABLE" in error_text
                or "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
            )

            if not is_retryable or attempt == max_retries:
                latency_ms = round((time.perf_counter() - started_total) * 1000, 2)
                return {
                    "ok": False,
                    "provider": "Gemini",
                    "error": error_text,
                    "metadata": {
                        "provider": "Gemini",
                        "model": model,
                        "latency_ms": latency_ms,
                        "max_output_tokens": max_output_tokens,
                        "thinking_mode": thinking_mode,
                        "thinking_budget": (
                            custom_thinking_budget if thinking_mode == "custom"
                            else 0 if thinking_mode == "off"
                            else None
                        ),
                        "attempts": attempt + 1,
                    },
                }

            sleep_seconds = min(2 ** attempt, 20)
            time.sleep(sleep_seconds)

    raise RuntimeError(f"Unexpected retry exit: {last_error}")


init_db()

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

    st.divider()
    st.caption("Environment key status")
    st.write(f"OpenAI key loaded: {'✅' if bool(OPENAI_API_KEY) else '❌'}")
    st.write(f"Gemini key loaded: {'✅' if bool(GEMINI_API_KEY) else '❌'}")
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
    