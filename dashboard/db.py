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
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

import streamlit as st
from collections.abc import Iterator
from contextlib import contextmanager
from sqlalchemy import create_engine, event, text
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
    engine = create_engine(
        get_database_url(),
        future=True,
        pool_pre_ping=True,
    )

    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _set_sqlite_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

    return engine


def get_database_backend_name() -> str:
    """Return active SQLAlchemy database backend name."""
    return get_engine().dialect.name


@contextmanager
def db_transaction() -> Iterator[Connection]:
    """Open a database transaction."""
    with get_engine().begin() as conn:
        yield conn


def _json_dumps(value: Any) -> str | None:
    """Serialize optional JSON data for database storage."""
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False)


def _db_bool(value: Any) -> bool | int | None:
    """Convert optional bool-like values for the active database backend."""
    if value is None:
        return None

    if is_postgres():
        return bool(value)

    return 1 if bool(value) else 0


def _json_safe_value(value: Any) -> Any:
    """Return a JSON-serializable representation of a database value."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    return value


def _json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy of a database row mapping."""
    return {key: _json_safe_value(value) for key, value in row.items()}


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


def is_postgres() -> bool:
    """Return whether the active database backend is PostgreSQL."""
    return get_database_backend_name() == "postgresql"


def is_sqlite() -> bool:
    """Return whether the active database backend is SQLite."""
    return get_database_backend_name() == "sqlite"


def insert_returning_id(
    *,
    table_name: str,
    columns: list[str],
    values: dict[str, Any],
) -> int:
    """Insert one row and return its generated primary key.

    Table and column names must come from internal constants only. Do not pass
    user-controlled identifiers here.
    """
    column_sql = ", ".join(columns)
    placeholder_sql = ", ".join(f":{column}" for column in columns)

    if is_postgres():
        sql = text(
            f"""
            INSERT INTO {table_name} ({column_sql})
            VALUES ({placeholder_sql})
            RETURNING id
            """
        )

        with db_transaction() as conn:
            inserted_id = conn.execute(sql, values).scalar_one()

        return int(inserted_id)

    sql = text(
        f"""
        INSERT INTO {table_name} ({column_sql})
        VALUES ({placeholder_sql})
        """
    )

    with db_transaction() as conn:
        result = conn.execute(sql, values)
        inserted_id = result.lastrowid

    if inserted_id is None:
        raise RuntimeError(f"Failed to get inserted id for table: {table_name}")

    return int(inserted_id)


def fetch_all_dicts(
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Execute a SELECT query and return rows as dictionaries."""
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params or {}).mappings().all()

    return [dict(row) for row in rows]


def fetch_one_dict(
    sql: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Execute a SELECT query and return one row as a dictionary."""
    with get_engine().connect() as conn:
        row = conn.execute(text(sql), params or {}).mappings().first()

    return dict(row) if row is not None else None


def execute_statement(sql: str, params: dict[str, Any] | None = None) -> None:
    """Execute one write statement inside a transaction."""
    with db_transaction() as conn:
        conn.execute(text(sql), params or {})


def init_db() -> None:
    """Create or migrate the dashboard database for the active backend."""
    if is_postgres():
        init_postgres_db()
    elif is_sqlite():
        init_sqlite_db()
    else:
        raise RuntimeError(
            f"Unsupported database backend: {get_database_backend_name()}"
        )


def init_sqlite_db() -> None:
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


def init_postgres_db() -> None:
    """Create the dashboard database schema for PostgreSQL.

    PostgreSQL mode is intended for new deployed databases. Existing SQLite
    history.db migration remains a SQLite-only concern.
    """
    with db_transaction() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    prompt TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    ok BOOLEAN NOT NULL,
                    latency_ms DOUBLE PRECISION,
                    max_output_tokens INTEGER,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    total_tokens INTEGER,
                    finish_status TEXT,
                    response_text TEXT,
                    error_text TEXT,
                    raw_json TEXT,
                    thinking_mode TEXT,
                    thinking_budget INTEGER,
                    thoughts_tokens INTEGER,
                    attempts INTEGER
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS route_prompt_templates (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    template_text TEXT NOT NULL,
                    ssal_profile_name TEXT,
                    is_builtin BOOLEAN NOT NULL DEFAULT FALSE
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS route_tasks (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    ssal_hash TEXT NOT NULL,
                    prompt_template TEXT NOT NULL,
                    prompt_template_name TEXT,
                    ssal_profile_name TEXT,
                    ground_truth_path_json TEXT,
                    ground_truth_length DOUBLE PRECISION
                )
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS route_evaluations (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    task_id BIGINT NOT NULL,
                    run_id BIGINT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,

                    valid_json BOOLEAN,
                    valid_path BOOLEAN,
                    exact_path_match BOOLEAN,

                    candidate_path_json TEXT,
                    candidate_declared_length DOUBLE PRECISION,
                    candidate_computed_length DOUBLE PRECISION,

                    ground_truth_path_json TEXT,
                    ground_truth_length DOUBLE PRECISION,

                    absolute_length_error DOUBLE PRECISION,
                    relative_length_error DOUBLE PRECISION,
                    declared_length_absolute_error DOUBLE PRECISION,
                    declared_length_relative_error DOUBLE PRECISION,

                    node_overlap DOUBLE PRECISION,
                    edge_overlap DOUBLE PRECISION,

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

        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_route_evaluations_created_at
                ON route_evaluations(created_at DESC)
                """
            )
        )

        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_route_tasks_origin_destination
                ON route_tasks(origin, destination)
                """
            )
        )


def save_run(prompt: str, result: Dict[str, Any]) -> int:
    """Save one generic provider API call and return the inserted run ID.

    This table is shared by the general prompt-comparison mode and route-finding
    mode. Route-specific metrics are stored separately in route_evaluations and
    linked back through the returned run_id.
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

    columns = [
        "created_at",
        "prompt",
        "provider",
        "model",
        "ok",
        "latency_ms",
        "max_output_tokens",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "finish_status",
        "response_text",
        "error_text",
        "raw_json",
        "thinking_mode",
        "thinking_budget",
        "thoughts_tokens",
        "attempts",
    ]
    values = {
        "created_at": _now(),
        "prompt": prompt,
        "provider": result.get("provider"),
        "model": meta.get("model"),
        "ok": _db_bool(result.get("ok", False)),
        "latency_ms": meta.get("latency_ms"),
        "max_output_tokens": meta.get("max_output_tokens"),
        "input_tokens": meta.get("input_tokens"),
        "output_tokens": meta.get("output_tokens"),
        "total_tokens": meta.get("total_tokens"),
        "finish_status": finish_status,
        "response_text": result.get("text"),
        "error_text": result.get("error"),
        "raw_json": _json_dumps(result.get("raw")),
        "thinking_mode": meta.get("thinking_mode"),
        "thinking_budget": meta.get("thinking_budget"),
        "thoughts_tokens": meta.get("thoughts_tokens"),
        "attempts": meta.get("attempts"),
    }

    return insert_returning_id(
        table_name="runs",
        columns=columns,
        values=values,
    )


def load_saved_runs(limit: int = 100) -> pd.DataFrame:
    """Load recent generic provider runs for the saved-history table."""
    rows = fetch_all_dicts(
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
        LIMIT :limit
        """,
        {"limit": limit},
    )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def load_run_by_id(run_id: int) -> Optional[Dict[str, Any]]:
    """Load one generic provider run, including parsed raw response JSON."""
    data = fetch_one_dict(
        "SELECT * FROM runs WHERE id = :run_id",
        {"run_id": run_id},
    )

    if data is None:
        return None

    raw_json = data.get("raw_json")
    if raw_json:
        try:
            data["raw_json"] = json.loads(raw_json)
        except Exception:
            pass

    return data


def delete_all_runs() -> None:
    """Delete all generic provider runs from history.

    This only affects the generic runs table. Route-linked rows may prevent this
    after route evaluations have been saved, depending on foreign-key state.
    """
    execute_statement("DELETE FROM runs")


def export_runs_json() -> str:
    """Export generic provider run history as formatted JSON text."""
    rows = fetch_all_dicts("SELECT * FROM runs ORDER BY id DESC")
    return json.dumps(
        [_json_safe_row(row) for row in rows],
        ensure_ascii=False,
        indent=2,
    )


def list_route_prompt_templates() -> list[dict[str, Any]]:
    """Return saved route prompt templates.

    The built-in default prompt is currently kept in route_prompts.py rather
    than seeded into SQLite, so this normally returns only locally saved
    user-defined templates. The is_builtin column is kept for future migration
    flexibility.
    """
    return fetch_all_dicts(
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
    )


def load_route_prompt_template(template_id: int) -> dict[str, Any] | None:
    """Load one saved route prompt template by ID."""
    return fetch_one_dict(
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
        WHERE id = :template_id
        """,
        {"template_id": template_id},
    )


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
    columns = [
        "created_at",
        "updated_at",
        "name",
        "description",
        "template_text",
        "ssal_profile_name",
        "is_builtin",
    ]
    values = {
        "created_at": timestamp,
        "updated_at": timestamp,
        "name": name,
        "description": description,
        "template_text": template_text,
        "ssal_profile_name": ssal_profile_name,
        "is_builtin": _db_bool(is_builtin) or (False if is_postgres() else 0),
    }

    return insert_returning_id(
        table_name="route_prompt_templates",
        columns=columns,
        values=values,
    )


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
    assignments: list[str] = ["updated_at = :updated_at"]
    values: dict[str, Any] = {"updated_at": _now(), "template_id": template_id}

    if name is not None:
        assignments.append("name = :name")
        values["name"] = name

    if description is not None:
        assignments.append("description = :description")
        values["description"] = description

    if template_text is not None:
        assignments.append("template_text = :template_text")
        values["template_text"] = template_text

    if ssal_profile_name is not None:
        assignments.append("ssal_profile_name = :ssal_profile_name")
        values["ssal_profile_name"] = ssal_profile_name

    execute_statement(
        f"""
        UPDATE route_prompt_templates
        SET {", ".join(assignments)}
        WHERE id = :template_id
        """,
        values,
    )


def delete_route_prompt_template(template_id: int) -> None:
    """Delete one saved user-defined route prompt template.

    Built-in templates are protected by the is_builtin flag.
    """
    execute_statement(
        """
        DELETE FROM route_prompt_templates
        WHERE id = :template_id AND is_builtin = :is_builtin
        """,
        {
            "template_id": template_id,
            "is_builtin": _db_bool(False),
        },
    )


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
    columns = [
        "created_at",
        "origin",
        "destination",
        "ssal_hash",
        "prompt_template",
        "prompt_template_name",
        "ssal_profile_name",
        "ground_truth_path_json",
        "ground_truth_length",
    ]
    values = {
        "created_at": _now(),
        "origin": origin,
        "destination": destination,
        "ssal_hash": ssal_hash,
        "prompt_template": prompt_template,
        "prompt_template_name": prompt_template_name,
        "ssal_profile_name": ssal_profile_name,
        "ground_truth_path_json": _json_dumps(ground_truth_path),
        "ground_truth_length": ground_truth_length,
    }

    return insert_returning_id(
        table_name="route_tasks",
        columns=columns,
        values=values,
    )


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
    columns = [
        "created_at",
        "task_id",
        "run_id",
        "provider",
        "model",
        "valid_json",
        "valid_path",
        "exact_path_match",
        "candidate_path_json",
        "candidate_declared_length",
        "candidate_computed_length",
        "ground_truth_path_json",
        "ground_truth_length",
        "absolute_length_error",
        "relative_length_error",
        "declared_length_absolute_error",
        "declared_length_relative_error",
        "node_overlap",
        "edge_overlap",
        "error_text",
        "raw_evaluation_json",
    ]
    values = {
        "created_at": _now(),
        "task_id": task_id,
        "run_id": run_id,
        "provider": provider,
        "model": model,
        "valid_json": _db_bool(evaluation.get("valid_json")),
        "valid_path": _db_bool(evaluation.get("valid_path")),
        "exact_path_match": _db_bool(evaluation.get("exact_path_match")),
        "candidate_path_json": _json_dumps(evaluation.get("candidate_path")),
        "candidate_declared_length": evaluation.get("candidate_declared_length"),
        "candidate_computed_length": evaluation.get("candidate_computed_length"),
        "ground_truth_path_json": _json_dumps(evaluation.get("ground_truth_path")),
        "ground_truth_length": evaluation.get("ground_truth_length"),
        "absolute_length_error": evaluation.get("absolute_length_error"),
        "relative_length_error": evaluation.get("relative_length_error"),
        "declared_length_absolute_error": evaluation.get(
            "declared_length_absolute_error"
        ),
        "declared_length_relative_error": evaluation.get(
            "declared_length_relative_error"
        ),
        "node_overlap": evaluation.get("node_overlap"),
        "edge_overlap": evaluation.get("edge_overlap"),
        "error_text": evaluation.get("error_text") or evaluation.get("reason"),
        "raw_evaluation_json": _json_dumps(evaluation),
    }

    return insert_returning_id(
        table_name="route_evaluations",
        columns=columns,
        values=values,
    )


def load_route_evaluations(limit: int = 100) -> pd.DataFrame:
    """Load recent route evaluation rows for dashboard display.

    The main history table uses compact metric columns, while selected-row
    detail views can use the saved path/raw JSON fields for segment inspection.
    """
    rows = fetch_all_dicts(
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
        LIMIT :limit
        """,
        {"limit": limit},
    )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def export_route_history_rows() -> list[dict[str, Any]]:
    """Return route-history rows compatible with research.history_evaluation."""
    rows = fetch_all_dicts(
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
    )

    return [
        _json_safe_row(
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
        )
        for row in rows
    ]


def export_route_history_json() -> str:
    """Serialize route-history export rows as formatted JSON text."""
    return json.dumps(
        export_route_history_rows(),
        ensure_ascii=False,
        indent=2,
    )
