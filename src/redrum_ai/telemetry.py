from __future__ import annotations

import platform
import sqlite3
import time
import uuid
from typing import Any

from redrum_memory.database import db_session, fetch_table_names


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def classify_error(message: str) -> str:
    text = message.lower()
    if "ollama" in text or "model" in text:
        return "model_runtime"
    if "database" in text or "sqlite" in text or "migration" in text:
        return "database"
    if "permission" in text or "approval" in text or "blocked" in text:
        return "policy"
    if "json" in text or "schema" in text or "parse" in text:
        return "schema"
    if "timeout" in text or "unavailable" in text or "connection" in text:
        return "connectivity"
    return "unknown"


def log_event(
    db_path: str,
    event_type: str,
    message: str,
    *,
    session_id: str = "",
    task_id: int | None = None,
    severity: str = "info",
    metadata: str = "",
) -> None:
    try:
        with db_session(db_path) as conn:
            if "work_events" not in fetch_table_names(conn):
                return
            conn.execute(
                """
                INSERT INTO work_events (session_id, task_id, event_type, severity, message, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, task_id, event_type, severity, message, metadata),
            )
    except sqlite3.Error:
        pass


def collect_metrics(db_path: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "tasks": {},
        "tools": {"invocations": 0, "failures": 0},
        "events": {"total": 0, "by_type": {}, "by_severity": {}},
    }
    with db_session(db_path) as conn:
        tables = fetch_table_names(conn)
        if "tasks" in tables:
            rows = conn.execute("SELECT status, COUNT(*) AS count FROM tasks GROUP BY status").fetchall()
            metrics["tasks"] = {row["status"]: row["count"] for row in rows}
        if "command_history" in tables:
            row = conn.execute("SELECT COUNT(*) AS count FROM command_history").fetchone()
            metrics["tools"]["invocations"] = row["count"] if row else 0
            row = conn.execute("SELECT COUNT(*) AS count FROM command_history WHERE exit_code != 0").fetchone()
            metrics["tools"]["failures"] = row["count"] if row else 0
        if "work_events" in tables:
            row = conn.execute("SELECT COUNT(*) AS count FROM work_events").fetchone()
            metrics["events"]["total"] = row["count"] if row else 0
            rows = conn.execute("SELECT event_type, COUNT(*) AS count FROM work_events GROUP BY event_type").fetchall()
            metrics["events"]["by_type"] = {row["event_type"]: row["count"] for row in rows}
            rows = conn.execute("SELECT severity, COUNT(*) AS count FROM work_events GROUP BY severity").fetchall()
            metrics["events"]["by_severity"] = {row["severity"]: row["count"] for row in rows}
    return metrics


def build_bug_report(db_path: str, version: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "redrum_ai_version": version,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "database_path": db_path,
        "metrics": collect_metrics(db_path),
        "recent_events": [],
        "recent_commands": [],
    }
    with db_session(db_path) as conn:
        tables = fetch_table_names(conn)
        if "work_events" in tables:
            rows = conn.execute(
                """
                SELECT timestamp, event_type, severity, message
                FROM work_events
                ORDER BY timestamp DESC, id DESC
                LIMIT 10
                """
            ).fetchall()
            report["recent_events"] = [dict(row) for row in rows]
        if "command_history" in tables:
            rows = conn.execute(
                """
                SELECT timestamp, command_str, working_directory, exit_code, output_summary
                FROM command_history
                ORDER BY timestamp DESC, id DESC
                LIMIT 10
                """
            ).fetchall()
            report["recent_commands"] = [dict(row) for row in rows]
    return report
