"""SQLite persistence helpers for the dashboard.

The dashboard keeps generic provider calls and route-specific evaluation data
separate:

- runs stores one row per OpenAI/Gemini API call.
- route_tasks stores one route-finding task, including origin,
  destination, SSAL hash, prompt template, and Dijkstra ground truth.
- route_evaluations stores evaluator metrics for one provider response on
  one route task.

Route-specific rows link back to generic provider calls through run_id.
This lets the general prompt-comparison history stay reusable while route
evaluation can add structured metrics without overloading the runs table.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


APP_DIR = Path(__file__).resolve().parents[1]
DB_PATH = APP_DIR / "history.db"


def get_conn() -> sqlite3.Connection:
    """Open a SQLite connection with row dictionaries and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _json_dumps(value: Any) -> str | None:
    """Serialize optional JSON data for SQLite storage."""
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None) -> Any:
    """Deserialize optional JSON data from SQLite storage."""
    if not value:
        return None

    try:
        return json.loads(value)
    except Exception:
        return value


def _bool_to_int(value: Any) -> int | None:
    """Convert optional bool-like values to SQLite integer flags."""
    if value is None:
        return None

    return 1 if bool(value) else 0


def init_db() -> None:
    """Create or migrate the local dashboard database.

    Existing runs rows are preserved. Missing generic-history columns are
    added with lightweight SQLite migrations, while route-specific tables are
    created if they do not already exist.
    """
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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS route_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                ssal_hash TEXT NOT NULL,
                prompt_template TEXT NOT NULL,
                ground_truth_path_json TEXT,
                ground_truth_length REAL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS route_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                task_id INTEGER NOT NULL,
                run_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,

                valid_json INTEGER,
                valid_path INTEGER,
                exact_path_match INTEGER,

                candidate_path_json TEXT,
                candidate_declared_length REAL,
                candidate_computed_length REAL,

                ground_truth_path_json TEXT,
                ground_truth_length REAL,

                absolute_length_error REAL,
                relative_length_error REAL,
                declared_length_absolute_error REAL,
                declared_length_relative_error REAL,

                node_overlap REAL,
                edge_overlap REAL,

                error_text TEXT,
                raw_evaluation_json TEXT,

                FOREIGN KEY(task_id) REFERENCES route_tasks(id),
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_route_evaluations_task_id
            ON route_evaluations(task_id)
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_route_evaluations_run_id
            ON route_evaluations(run_id)
            """
        )

        conn.commit()


def save_run(prompt: str, result: Dict[str, Any]) -> int:
    """Save one generic provider API call and return the inserted run ID.

    This table is shared by the general prompt-comparison mode and the upcoming
    route-finding mode. Route-specific metrics should be stored separately in
    route_evaluations and linked back through the returned run_id.
    """
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
        cursor = conn.execute(
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
                _json_dumps(result.get("raw")),
                meta.get("thinking_mode"),
                meta.get("thinking_budget"),
                meta.get("thoughts_tokens"),
                meta.get("attempts"),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def load_saved_runs(limit: int = 100) -> pd.DataFrame:
    """Load recent generic provider runs for the saved-history table."""
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
    """Load one generic provider run, including parsed raw response JSON."""
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
    """Delete all generic provider runs from local history."""
    with get_conn() as conn:
        conn.execute("DELETE FROM runs")
        conn.commit()


def export_runs_json() -> str:
    """Export generic provider run history as formatted JSON text."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2)


def save_route_task(
    *,
    origin: str,
    destination: str,
    ssal_hash: str,
    prompt_template: str,
    ground_truth_path: list[str] | None = None,
    ground_truth_length: float | None = None,
) -> int:
    """Save one route-finding task and return the inserted task ID.

    The prompt template is stored without the full SSAL text to avoid
    duplicating large network data in every route task row.
    """
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO route_tasks (
                created_at,
                origin,
                destination,
                ssal_hash,
                prompt_template,
                ground_truth_path_json,
                ground_truth_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.strftime("%Y-%m-%d %H:%M:%S"),
                origin,
                destination,
                ssal_hash,
                prompt_template,
                _json_dumps(ground_truth_path),
                ground_truth_length,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def save_route_evaluation(
    *,
    task_id: int,
    run_id: int,
    provider: str,
    model: str,
    evaluation: dict[str, Any],
) -> int:
    """Save one route evaluator result and return the inserted evaluation ID.

    Compact metric columns are stored for querying and display. The complete
    evaluator result is also stored as JSON for later debugging.
    """
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO route_evaluations (
                created_at,
                task_id,
                run_id,
                provider,
                model,
                valid_json,
                valid_path,
                exact_path_match,
                candidate_path_json,
                candidate_declared_length,
                candidate_computed_length,
                ground_truth_path_json,
                ground_truth_length,
                absolute_length_error,
                relative_length_error,
                declared_length_absolute_error,
                declared_length_relative_error,
                node_overlap,
                edge_overlap,
                error_text,
                raw_evaluation_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.strftime("%Y-%m-%d %H:%M:%S"),
                task_id,
                run_id,
                provider,
                model,
                _bool_to_int(evaluation.get("valid_json")),
                _bool_to_int(evaluation.get("valid_path")),
                _bool_to_int(evaluation.get("exact_path_match")),
                _json_dumps(evaluation.get("candidate_path")),
                evaluation.get("candidate_declared_length"),
                evaluation.get("candidate_computed_length"),
                _json_dumps(evaluation.get("ground_truth_path")),
                evaluation.get("ground_truth_length"),
                evaluation.get("absolute_length_error"),
                evaluation.get("relative_length_error"),
                evaluation.get("declared_length_absolute_error"),
                evaluation.get("declared_length_relative_error"),
                evaluation.get("node_overlap"),
                evaluation.get("edge_overlap"),
                evaluation.get("error_text") or evaluation.get("reason"),
                _json_dumps(evaluation),
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def load_route_evaluations(limit: int = 100) -> pd.DataFrame:
    """Load recent route evaluation rows for dashboard display."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                re.id,
                re.created_at,
                re.task_id,
                re.run_id,
                re.provider,
                re.model,
                rt.origin,
                rt.destination,
                rt.ssal_hash,
                re.valid_json,
                re.valid_path,
                re.exact_path_match,
                re.candidate_computed_length,
                re.ground_truth_length,
                re.relative_length_error,
                re.declared_length_relative_error,
                re.node_overlap,
                re.edge_overlap,
                re.error_text
            FROM route_evaluations re
            JOIN route_tasks rt ON rt.id = re.task_id
            ORDER BY re.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame([dict(row) for row in rows])


def export_route_history_rows() -> list[dict[str, Any]]:
    """Return route-history rows compatible with research.history_evaluation."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                r.id,
                r.created_at,
                r.provider,
                r.model,
                r.finish_status,
                r.max_output_tokens,
                r.prompt,
                r.response_text,
                r.error_text,
                rt.origin,
                rt.destination,
                rt.ssal_hash
            FROM route_evaluations re
            JOIN route_tasks rt ON rt.id = re.task_id
            JOIN runs r ON r.id = re.run_id
            ORDER BY re.id DESC
            """
        ).fetchall()

    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "provider": row["provider"],
            "model": row["model"],
            "finish_status": row["finish_status"],
            "max_output_tokens": row["max_output_tokens"],
            "origin": row["origin"],
            "destination": row["destination"],
            "ssal_hash": row["ssal_hash"],
            "prompt": row["prompt"],
            "response_text": row["response_text"] or "",
            "error_text": row["error_text"],
        }
        for row in rows
    ]


def export_route_history_json() -> str:
    """Serialize route-history export rows as formatted JSON text."""
    return json.dumps(
        export_route_history_rows(),
        ensure_ascii=False,
        indent=2,
    )
