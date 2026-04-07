import json
import os
import time
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

st.set_page_config(
    page_title="OpenAI vs Gemini Comparator",
    layout="wide",
)

st.title("OpenAI vs Gemini Comparator")
st.caption("Send the same prompt to both APIs and compare outputs, latency, and token metadata.")


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
    """
    Rough estimate only. Update if pricing changes.
    """
    pricing_per_million = {
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
        # Add more models here if you want estimates for them.
    }

    price = pricing_per_million.get(model)
    if not price:
        return None

    return (
        (input_tokens / 1_000_000) * price["input"]
        + (output_tokens / 1_000_000) * price["output"]
    )


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
            },
        }


def call_gemini(prompt: str, model: str, max_output_tokens: int) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        return {
            "ok": False,
            "provider": "Gemini",
            "error": "Missing GEMINI_API_KEY in environment.",
        }

    client = genai.Client(api_key=GEMINI_API_KEY)
    started = time.perf_counter()

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=max_output_tokens,
            ),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        response_dict = obj_to_dict(response) or {}
        text_output = safe_getattr(response, "text", None)
        if not text_output:
            text_output = json.dumps(response_dict, indent=2, ensure_ascii=False)

        usage_md = response_dict.get("usage_metadata", {}) or {}
        input_tokens = usage_md.get("prompt_token_count", 0)
        output_tokens = usage_md.get("candidates_token_count", 0)
        total_tokens = usage_md.get("total_token_count", input_tokens + output_tokens)

        finish_reason = None
        candidates = response_dict.get("candidates")
        if isinstance(candidates, list) and candidates:
            finish_reason = candidates[0].get("finish_reason")

        return {
            "ok": True,
            "provider": "Gemini",
            "text": text_output,
            "metadata": {
                "provider": "Gemini",
                "model": model,
                "latency_ms": latency_ms,
                "finish_reason": finish_reason,
                "max_output_tokens": max_output_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "usage_raw": usage_md,
            },
            "raw": response_dict,
        }

    except Exception as e:
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "ok": False,
            "provider": "Gemini",
            "error": str(e),
            "metadata": {
                "provider": "Gemini",
                "model": model,
                "latency_ms": latency_ms,
                "max_output_tokens": max_output_tokens,
            },
        }


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

    show_raw = st.checkbox("Show raw API responses", value=False)
    show_cost_estimate = st.checkbox("Show rough OpenAI cost estimate", value=True)

    st.divider()
    st.caption("Environment key status")
    st.write(f"OpenAI key loaded: {'✅' if bool(OPENAI_API_KEY) else '❌'}")
    st.write(f"Gemini key loaded: {'✅' if bool(GEMINI_API_KEY) else '❌'}")


default_prompt = "Is Oslo north of the Arctic Circle?"

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
        gemini_result = call_gemini(prompt, gemini_model, max_output_tokens)

    st.session_state.history.insert(
        0,
        {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "prompt": prompt,
            "openai_ok": openai_result.get("ok", False),
            "gemini_ok": gemini_result.get("ok", False),
            "openai_model": openai_model,
            "gemini_model": gemini_model,
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

            if show_cost_estimate:
                meta = openai_result["metadata"]
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
                st.subheader("OpenAI metadata")
                st.json(openai_result["metadata"])

    with col2:
        st.header("Gemini")
        if gemini_result["ok"]:
            st.success("Request succeeded")
            st.write(gemini_result["text"])
            st.subheader("Gemini metadata")
            st.json(gemini_result["metadata"])

            if show_raw:
                with st.expander("Raw Gemini response"):
                    st.json(gemini_result["raw"])
        else:
            st.error(gemini_result["error"])
            if "metadata" in gemini_result:
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
                "max_output_tokens": openai_result.get("metadata", {}).get("max_output_tokens"),
            },
            {
                "provider": "Gemini",
                "model": gemini_model,
                "ok": gemini_result.get("ok", False),
                "latency_ms": gemini_result.get("metadata", {}).get("latency_ms"),
                "input_tokens": gemini_result.get("metadata", {}).get("input_tokens"),
                "output_tokens": gemini_result.get("metadata", {}).get("output_tokens"),
                "total_tokens": gemini_result.get("metadata", {}).get("total_tokens"),
                "max_output_tokens": gemini_result.get("metadata", {}).get("max_output_tokens"),
            },
        ]
    )

    st.dataframe(comparison_df, use_container_width=True)

st.divider()
st.subheader("Session history")

if st.session_state.history:
    st.dataframe(pd.DataFrame(st.session_state.history), use_container_width=True)
else:
    st.caption("No runs yet.")
