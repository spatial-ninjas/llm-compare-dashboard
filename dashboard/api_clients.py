import json
import os
import time
from typing import Any, Dict, Optional

from google import genai
from google.genai import types
from openai import OpenAI


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


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


def get_api_key_status() -> dict[str, bool]:
    """Return whether provider API keys are available in the environment."""
    return {
        "openai": bool(OPENAI_API_KEY),
        "gemini": bool(GEMINI_API_KEY),
    }


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
