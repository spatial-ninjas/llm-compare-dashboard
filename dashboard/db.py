import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


APP_DIR = Path(__file__).resolve().parents[1]
DB_PATH = APP_DIR / "history.db"


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
