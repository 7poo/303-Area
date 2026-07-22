"""Run manifest and publication status shared by batch stages and agent tools."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import duckdb


def ensure_manifest(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id VARCHAR PRIMARY KEY,
            stage VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            started_at TIMESTAMP NOT NULL,
            finished_at TIMESTAMP,
            metadata JSON,
            row_counts JSON,
            error_message VARCHAR
        )
    """)


def start_run(conn: duckdb.DuckDBPyConnection, stage: str, metadata: dict[str, Any] | None = None) -> str:
    ensure_manifest(conn)
    run_id = f"{stage}-{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO pipeline_runs(run_id,stage,status,started_at,metadata) VALUES(?,?,?,?,?)",
        [run_id, stage, "running", datetime.now(timezone.utc).replace(tzinfo=None), json.dumps(metadata or {}, default=str)],
    )
    conn.commit()
    return run_id


def finish_run(
    conn: duckdb.DuckDBPyConnection,
    run_id: str,
    status: str,
    row_counts: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    if status not in {"success", "failed"}:
        raise ValueError("pipeline status must be success or failed")
    conn.execute(
        "UPDATE pipeline_runs SET status=?,finished_at=?,row_counts=?,error_message=? WHERE run_id=?",
        [status, datetime.now(timezone.utc).replace(tzinfo=None), json.dumps(row_counts or {}, default=str), error_message, run_id],
    )
    conn.commit()


def latest_successful_run(conn: duckdb.DuckDBPyConnection, stage: str) -> dict[str, Any] | None:
    try:
        row = conn.execute(
            "SELECT run_id,stage,status,started_at,finished_at,metadata,row_counts "
            "FROM pipeline_runs WHERE stage=? ORDER BY started_at DESC LIMIT 1",
            [stage],
        ).fetchone()
    except duckdb.Error:
        return None
    if not row or row[2] != "success":
        return None
    return dict(zip(["run_id", "stage", "status", "started_at", "finished_at", "metadata", "row_counts"], row))
