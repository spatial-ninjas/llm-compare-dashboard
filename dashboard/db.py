"""Persistence helpers for the dashboard.

The dashboard stores four related kinds of data:

- runs stores one row per OpenAI/Gemini API call.
- route_prompt_templates stores reusable user-defined route prompt templates.
- route_tasks stores one route-finding task, including origin, destination,
  SSAL hash, prompt template snapshot, prompt template name, SSAL profile name,
  and Dijkstra ground truth.
- route_evaluations stores evaluator metrics for one provider response on one
  route task.

SQLite remains the default local backend. SQLAlchemy engine helpers are being
introduced incrementally so the same persistence API can later support
DATABASE_URL-configured managed backends such as PostgreSQL.

Route-specific evaluation rows link back to generic provider calls through
run_id and to route tasks through task_id. This keeps the general
prompt-comparison history reusable while route evaluation can add structured
metrics without overloading the runs table.

Reusable prompt templates are intentionally separate from route tasks. A route
task stores a snapshot of the actual prompt template text and metadata used for
that run, so old experiments remain reproducible even if a saved template is
later edited, renamed, or deleted.
"""

import os
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st
from collections.abc import Iterator
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, Connection

import pandas as pd


APP_DIR = Path(__file__).resolve().parents[1]
DB_PATH = APP_DIR / "history.db"


def get_database_url() -> str:
    """Return configured database URL, defaulting to local SQLite."""
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        return database_url

    return f"sqlite:///{DB_PATH}"


@st.cache_resource
def get_engine() -> Engine:
    """Create and cache the SQLAlchemy engine."""
    return create_engine(
        get_database_url(),
        future=True,
        pool_pre_ping=True,
    )


def get_database_backend_name() -> str:
    """Return active SQLAlchemy database backend name."""
    return get_engine().dialect.name


@contextmanager
def db_transaction() -> Iterator[Connection]:
    """Open a database transaction."""
    with get_engine().begin() as conn:
        yield conn


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


def _bool_to_int(value: Any) -> int | None:
    """Convert optional bool-like values to SQLite integer flags."""
    if value is None:
        return None

    return 1 if bool(value) else 0


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ensure_column(
    conn: Connection,
    *,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    """Add a SQLite column if it does not already exist.

    This helper is used by the SQLite schema initializer for lightweight
    compatibility with older local history.db files.
    """
    existing_columns = {
        row["name"]
        for row in conn.execute(
            text(f"PRAGMA table_info({table_name})")
        ).mappings()
    }

    if column_name not in existing_columns:
        conn.execute(
            text(
                f"ALTER TABLE {table_name} "
                f"ADD COLUMN {column_name} {column_definition}"
            )
        )


def _ensure_columns(
    conn: Connection,
    *,
    table_name: str,
    columns: dict[str, str],
) -> None:
    """Add missing SQLite columns for an existing table."""
    for column_name, column_definition in columns.items():
        _ensure_column(
            conn,
            table_name=table_name,
            column_name=column_name,
            column_definition=column_definition,
        )


def init_db() -> None:
    """Create or migrate the local dashboard database.

    Existing runs rows are preserved. Missing generic-history columns are
    added with lightweight SQLite migrations, while route-specific tables are
    created if they do not already exist.
    """
    with db_transaction() as conn:
        conn.execute(
            text(
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
        )

        _ensure_columns(
            conn,
            table_name="runs",
            columns={
                "thinking_mode": "TEXT",
                "thinking_budget": "INTEGER",
                "thoughts_tokens": "INTEGER",
                "attempts": "INTEGER",
            },
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS route_prompt_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    template_text TEXT NOT NULL,
                    ssal_profile_name TEXT,
                    is_builtin INTEGER NOT NULL DEFAULT 0
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS route_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    ssal_hash TEXT NOT NULL,
                    prompt_template TEXT NOT NULL,
                    prompt_template_name TEXT,
                    ssal_profile_name TEXT,
                    ground_truth_path_json TEXT,
                    ground_truth_length REAL
                )
                """
            )
        )


        _ensure_column(
            conn,
            table_name="route_tasks",
            column_name="prompt_template_name",
            column_definition="TEXT",
        )

        _ensure_column(
            conn,
            table_name="route_tasks",
            column_name="ssal_profile_name",
            column_definition="TEXT",
        )

        conn.execute(
            text(
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
        )

        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_route_evaluations_task_id
                ON route_evaluations(task_id)
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_route_evaluations_run_id
                ON route_evaluations(run_id)
                """
            )
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
                _now(),
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



def list_route_prompt_templates() -> list[dict[str, Any]]:
    """Return saved route prompt templates.

    The built-in default prompt is currently kept in route_prompts.py rather
    than seeded into SQLite, so this normally returns only locally saved
    user-defined templates. The is_builtin column is kept for future migration
    flexibility.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                created_at,
                updated_at,
                name,
                description,
                template_text,
                ssal_profile_name,
                is_builtin
            FROM route_prompt_templates
            ORDER BY is_builtin DESC, updated_at DESC, name ASC
            """
        ).fetchall()

    return [dict(row) for row in rows]


def load_route_prompt_template(template_id: int) -> dict[str, Any] | None:
    """Load one saved route prompt template by ID."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                id,
                created_at,
                updated_at,
                name,
                description,
                template_text,
                ssal_profile_name,
                is_builtin
            FROM route_prompt_templates
            WHERE id = ?
            """,
            (template_id,),
        ).fetchone()

    if row is None:
        return None

    return dict(row)


def create_route_prompt_template(
    *,
    name: str,
    template_text: str,
    description: str | None = None,
    ssal_profile_name: str | None = None,
    is_builtin: bool = False,
) -> int:
    """Create one saved route prompt template and return its ID."""
    timestamp = _now()

    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO route_prompt_templates (
                created_at,
                updated_at,
                name,
                description,
                template_text,
                ssal_profile_name,
                is_builtin
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                timestamp,
                name,
                description,
                template_text,
                ssal_profile_name,
                _bool_to_int(is_builtin) or 0,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_route_prompt_template(
    *,
    template_id: int,
    name: str | None = None,
    template_text: str | None = None,
    description: str | None = None,
    ssal_profile_name: str | None = None,
) -> None:
    """Update an existing saved route prompt template.

    Omitted fields are left unchanged. Passing ``description=None`` or
    ``ssal_profile_name=None`` preserves the current value.
    """
    assignments: list[str] = ["updated_at = ?"]
    values: list[Any] = [_now()]

    if name is not None:
        assignments.append("name = ?")
        values.append(name)

    if description is not None:
        assignments.append("description = ?")
        values.append(description)

    if template_text is not None:
        assignments.append("template_text = ?")
        values.append(template_text)

    if ssal_profile_name is not None:
        assignments.append("ssal_profile_name = ?")
        values.append(ssal_profile_name)

    values.append(template_id)

    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE route_prompt_templates
            SET {", ".join(assignments)}
            WHERE id = ?
            """,
            values,
        )
        conn.commit()


def duplicate_route_prompt_template(
    *,
    template_id: int,
    name: str,
) -> int:
    """Duplicate a saved route prompt template under a new name."""
    source = load_route_prompt_template(template_id)

    if source is None:
        raise ValueError(f"Route prompt template not found: {template_id}")

    return create_route_prompt_template(
        name=name,
        description=source.get("description"),
        template_text=source["template_text"],
        ssal_profile_name=source.get("ssal_profile_name"),
        is_builtin=False,
    )


def delete_route_prompt_template(template_id: int) -> None:
    """Delete one saved user-defined route prompt template.

    Built-in templates are protected by the is_builtin flag.
    """
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM route_prompt_templates WHERE id = ? AND is_builtin = 0",
            (template_id,),
        )
        conn.commit()


def save_route_task(
    *,
    origin: str,
    destination: str,
    ssal_hash: str,
    prompt_template: str,
    prompt_template_name: str | None = None,
    ssal_profile_name: str | None = None,
    ground_truth_path: list[str],
    ground_truth_length: float | None,
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
                prompt_template_name,
                ssal_profile_name,
                ground_truth_path_json,
                ground_truth_length
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                origin,
                destination,
                ssal_hash,
                prompt_template,
                prompt_template_name,
                ssal_profile_name,
                json.dumps(ground_truth_path),
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
                _now(),
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
    """Load recent route evaluation rows for dashboard display.

    The main history table uses compact metric columns, while selected-row
    detail views can use the saved path/raw JSON fields for segment inspection.
    """
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
                rt.prompt_template_name,
                rt.ssal_profile_name,

                re.valid_json,
                re.valid_path,
                re.exact_path_match,

                re.candidate_path_json,
                COALESCE(
                    re.ground_truth_path_json,
                    rt.ground_truth_path_json
                ) AS ground_truth_path_json,

                re.candidate_declared_length,
                re.candidate_computed_length,
                re.ground_truth_length,

                re.absolute_length_error,
                re.relative_length_error,
                re.declared_length_absolute_error,
                re.declared_length_relative_error,

                re.node_overlap,
                re.edge_overlap,

                re.error_text,
                re.raw_evaluation_json
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
                rt.ssal_hash,
                rt.prompt_template_name,
                rt.ssal_profile_name
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
            "prompt_template_name": row["prompt_template_name"],
            "ssal_profile_name": row["ssal_profile_name"],
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
