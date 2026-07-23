import datetime
import hashlib
import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Generator

REQUIRED_TABLES = {
    "conversations",
    "knowledge_bases",
    "user_preferences",
    "tasks",
    "conversation_summaries",
    "work_events",
    "memory_facts",
    "memory_reviews",
    "memory_sessions",
}

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't",
    "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have",
    "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself",
    "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is",
    "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should",
    "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we",
    "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"
}


class DatabaseHealth:
    def __init__(self, ok: bool, messages: list[str]):
        self.ok = ok
        self.messages = messages


@contextmanager
def db_session(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row["name"] for row in rows}


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if table not in fetch_table_names(conn):
        return []
    return [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return column in _table_columns(conn, table)


def _normalize_scope(project_slug: str = "unknown", workspace_path: str = "", user_id: str = "") -> tuple[str, str, str]:
    return (project_slug or "unknown", workspace_path or "", user_id or "")


def _now_utc() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def _parse_timestamp(value: Any) -> datetime.datetime:
    if value is None:
        return _now_utc()
    if isinstance(value, datetime.datetime):
        return value.replace(tzinfo=None)
    text = str(value)
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return _now_utc()


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def normalize_text(text: str) -> list[str]:
    words = re.findall(r"\b\w+\b", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def check_database(db_path: str) -> DatabaseHealth:
    messages: list[str] = []

    if not os.path.exists(db_path):
        return DatabaseHealth(False, [f"Database not found: {db_path}"])

    try:
        with db_session(db_path) as conn:
            tables = fetch_table_names(conn)
            missing_tables = sorted(REQUIRED_TABLES - tables)
            if missing_tables:
                messages.append(f"Missing database tables: {', '.join(missing_tables)}")

            if "knowledge_bases" in tables:
                if not _has_column(conn, "knowledge_bases", "source_uri"):
                    messages.append("Missing knowledge_bases.source_uri column")
                if not _has_column(conn, "knowledge_bases", "source_type"):
                    messages.append("Missing knowledge_bases.source_type column")
                if not _has_column(conn, "knowledge_bases", "confidence"):
                    messages.append("Missing knowledge_bases.confidence column")
    except sqlite3.Error as exc:
        return DatabaseHealth(False, [f"Database check failed: {exc}"])

    if messages:
        return DatabaseHealth(False, messages)

    return DatabaseHealth(True, [f"Database ready: {db_path}"])


def get_user_preferences(db_path: str) -> dict[str, str]:
    with db_session(db_path) as conn:
        if "user_preferences" not in fetch_table_names(conn):
            return {}
        rows = conn.execute("SELECT key, value FROM user_preferences ORDER BY key").fetchall()
    return {row["key"]: row["value"] for row in rows if row["key"] is not None}


def list_knowledge_entries(db_path: str, limit: int = 50, project_slug: str = "unknown") -> list[dict]:
    with db_session(db_path) as conn:
        if "knowledge_bases" not in fetch_table_names(conn):
            return []
        rows = conn.execute(
            """
            SELECT id, name, content, timestamp, tags, source_uri, source_type, confidence, salience_score, review_state
            FROM knowledge_bases
            WHERE (? = 'unknown' OR tags LIKE ? OR tags IS NULL)
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (project_slug, f"%{project_slug}%", limit),
        ).fetchall()
    return [dict(row) for row in rows]


def list_memory_facts(
    db_path: str,
    limit: int = 100,
    project_slug: str = "unknown",
    workspace_path: str = "",
    user_id: str = "",
    status: str | None = None,
) -> list[dict]:
    with db_session(db_path) as conn:
        if "memory_facts" not in fetch_table_names(conn):
            return []
        clauses = ["1 = 1"]
        params: list[Any] = []
        if project_slug != "unknown":
            clauses.append("(project_slug = ? OR project_slug IS NULL)")
            params.append(project_slug)
        if workspace_path:
            clauses.append("(workspace_path = ? OR workspace_path IS NULL)")
            params.append(workspace_path)
        if user_id:
            clauses.append("(user_id = ? OR user_id IS NULL)")
            params.append(user_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT *
            FROM memory_facts
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(last_accessed_at, updated_at, created_at) DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def delete_knowledge_entry(db_path: str, entry_id: int) -> bool:
    with db_session(db_path) as conn:
        if "knowledge_bases" not in fetch_table_names(conn):
            return False
        result = conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (entry_id,))
        return result.rowcount > 0


def delete_memory_fact(db_path: str, fact_id: int) -> bool:
    with db_session(db_path) as conn:
        if "memory_facts" not in fetch_table_names(conn):
            return False
        result = conn.execute("DELETE FROM memory_facts WHERE id = ?", (fact_id,))
        return result.rowcount > 0


def _scope_clause(project_slug: str, workspace_path: str, user_id: str) -> tuple[str, list[Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if project_slug != "unknown":
        clauses.append("(project_slug = ? OR project_slug IS NULL)")
        params.append(project_slug)
    if workspace_path:
        clauses.append("(workspace_path = ? OR workspace_path IS NULL)")
        params.append(workspace_path)
    if user_id:
        clauses.append("(user_id = ? OR user_id IS NULL)")
        params.append(user_id)
    return " AND ".join(clauses), params


def _rank_record(
    *,
    name: str,
    content: str,
    tags: str,
    timestamp_str: str | None,
    project_slug: str,
    workspace_path: str,
    query_terms: list[str],
    salience_score: float,
    confidence: float,
    query_embedding: list[float] | None,
    embedding_text: str = "",
    source_uri: str = "",
    source_type: str = "",
) -> dict[str, Any] | None:
    now = _now_utc().replace(tzinfo=None)
    dt = _parse_timestamp(timestamp_str).replace(tzinfo=None)
    age_days = max(0.0, (now - dt).total_seconds() / 86400.0)

    scope_score = 0.0
    if workspace_path and source_uri.startswith(workspace_path):
        scope_score += 2.0
    if project_slug and project_slug != "unknown" and project_slug in (tags or "").split(","):
        scope_score += 2.0

    combined_text = f"{name} {content} {tags}".lower()
    match_count = 0.0
    for term in query_terms:
        if term in combined_text:
            match_count += 1.0
            if term in name.lower():
                match_count += 0.5

    embedding_bonus = 0.0
    if query_embedding and embedding_text:
        try:
            stored_embedding = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?(?:e[-+]?\d+)?", embedding_text, re.I)]
            if stored_embedding and len(stored_embedding) == len(query_embedding):
                dot = sum(a * b for a, b in zip(query_embedding, stored_embedding))
                query_norm = math.sqrt(sum(a * a for a in query_embedding))
                stored_norm = math.sqrt(sum(a * a for a in stored_embedding))
                if query_norm > 0 and stored_norm > 0:
                    embedding_bonus = max(0.0, dot / (query_norm * stored_norm))
        except Exception:
            embedding_bonus = 0.0

    if match_count == 0 and scope_score == 0 and embedding_bonus == 0:
        return None

    half_life_days = 30.0 * ((max(1.0, salience_score) / 5.0) ** 2)
    recency_weight = math.pow(2.0, -age_days / half_life_days)
    final_score = (match_count + scope_score + embedding_bonus) * recency_weight * max(0.2, confidence)

    return {
        "name": name,
        "content": content,
        "source_uri": source_uri,
        "timestamp": timestamp_str,
        "tags": tags,
        "source_type": source_type,
        "confidence": confidence,
        "salience_score": salience_score,
        "score": final_score,
    }


def _parse_embedding_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def get_relevant_knowledge(
    db_path: str,
    query: str,
    limit: int = 5,
    project_slug: str = "unknown",
    workspace_path: str = "",
    query_embedding: list[float] | None = None,
    candidate_filter: Any | None = None,
) -> list[dict]:
    with db_session(db_path) as conn:
        tables = fetch_table_names(conn)
        if "knowledge_bases" not in tables and "memory_facts" not in tables:
            return []

        query_terms = normalize_text(query)
        if not query_terms:
            query_terms = [w for w in re.findall(r"\b\w+\b", query.lower()) if len(w) > 0]

        candidates: list[dict[str, Any]] = []

        if "knowledge_bases" in tables:
            cols = _table_columns(conn, "knowledge_bases")
            select_cols = ["id", "name", "content", "source_uri", "timestamp", "tags"]
            for extra in ("embedding", "salience_score", "confidence", "source_type"):
                if extra in cols:
                    select_cols.append(extra)
            rows = conn.execute(f"SELECT {', '.join(select_cols)} FROM knowledge_bases").fetchall()
            for row in rows:
                if candidate_filter is not None and not candidate_filter("knowledge_base", dict(row)):
                    continue
                ranked = _rank_record(
                    name=_stringify(row["name"]),
                    content=_stringify(row["content"]),
                    tags=_stringify(row["tags"]),
                    timestamp_str=row["timestamp"],
                    project_slug=project_slug,
                    workspace_path=workspace_path,
                    query_terms=query_terms,
                    salience_score=float(row["salience_score"]) if "salience_score" in row.keys() and row["salience_score"] is not None else 5.0,
                    confidence=float(row["confidence"]) if "confidence" in row.keys() and row["confidence"] is not None else 0.75,
                    query_embedding=query_embedding,
                    embedding_text=_parse_embedding_text(row["embedding"]) if "embedding" in row.keys() else "",
                    source_uri=_stringify(row["source_uri"]),
                    source_type=_stringify(row["source_type"]) if "source_type" in row.keys() else "manual",
                )
                if ranked:
                    ranked["id"] = row["id"]
                    ranked["memory_type"] = "knowledge_base"
                    candidates.append(ranked)

        if "memory_facts" in tables:
            rows = conn.execute(
                """
                SELECT id, memory_key, memory_value, canonical_key, source_type, source_uri, project_slug, workspace_path,
                       user_id, confidence, salience_score, status, created_at, updated_at, last_accessed_at
                FROM memory_facts
                WHERE status = 'active'
                """
            ).fetchall()
            for row in rows:
                if candidate_filter is not None and not candidate_filter("memory_fact", dict(row)):
                    continue
                tags = ",".join(
                    filter(
                        None,
                        [
                            _stringify(row["canonical_key"]),
                            _stringify(row["project_slug"]),
                            _stringify(row["workspace_path"]),
                            _stringify(row["user_id"]),
                        ],
                    )
                )
                ranked = _rank_record(
                    name=_stringify(row["memory_key"]),
                    content=_stringify(row["memory_value"]),
                    tags=tags,
                    timestamp_str=row["last_accessed_at"] or row["updated_at"] or row["created_at"],
                    project_slug=project_slug,
                    workspace_path=workspace_path,
                    query_terms=query_terms,
                    salience_score=float(row["salience_score"]) if row["salience_score"] is not None else 5.0,
                    confidence=float(row["confidence"]) if row["confidence"] is not None else 0.75,
                    query_embedding=query_embedding,
                    source_uri=_stringify(row["source_uri"]),
                    source_type=_stringify(row["source_type"]) or "user",
                )
                if ranked:
                    ranked["id"] = row["id"]
                    ranked["memory_type"] = "memory_fact"
                    ranked["canonical_key"] = row["canonical_key"]
                    ranked["status"] = row["status"]
                    candidates.append(ranked)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:limit]


def get_recent_conversations(
    db_path: str,
    limit: int = 6,
    project_slug: str = "unknown",
    workspace_path: str = "",
    user_id: str = "",
) -> list[sqlite3.Row]:
    with db_session(db_path) as conn:
        if "conversations" not in fetch_table_names(conn):
            return []
        columns = _table_columns(conn, "conversations")
        where_clauses = ["role IN ('user', 'agent', 'system')"]
        params: list[Any] = []
        if "project_slug" in columns and project_slug and project_slug != "unknown":
            where_clauses.append("(project_slug = ? OR project_slug IS NULL)")
            params.append(project_slug)
        if "workspace_path" in columns and workspace_path:
            where_clauses.append("(workspace_path = ? OR workspace_path IS NULL)")
            params.append(workspace_path)
        if "user_id" in columns and user_id:
            where_clauses.append("(user_id = ? OR user_id IS NULL)")
            params.append(user_id)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT id, role, content
            FROM conversations
            WHERE {' AND '.join(where_clauses)}
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return list(reversed(rows))


def get_unsummarized_conversations(
    db_path: str,
    project_slug: str = "unknown",
    before_last_n: int = 6,
) -> list[sqlite3.Row]:
    with db_session(db_path) as conn:
        tables = fetch_table_names(conn)
        if "conversations" not in tables or "conversation_summaries" not in tables:
            return []

        cutoff_row = conn.execute(
            """
            SELECT id FROM conversations
            WHERE project_slug = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT 1 OFFSET ?
            """,
            (project_slug, before_last_n - 1),
        ).fetchone()
        if not cutoff_row:
            return []

        cutoff_id = cutoff_row["id"]
        rows = conn.execute(
            """
            SELECT id, role, content
            FROM conversations
            WHERE project_slug = ?
              AND id <= ?
              AND id NOT IN (
                SELECT c.id FROM conversations c
                JOIN conversation_summaries s ON c.id >= s.start_conversation_id AND c.id <= s.end_conversation_id
                WHERE s.project_slug = ?
              )
            ORDER BY id ASC
            """,
            (project_slug, cutoff_id, project_slug),
        ).fetchall()
        return list(rows)


def _extract_preference_candidates(text: str) -> list[tuple[str, str, float]]:
    lowered = text.lower().strip()
    candidates: list[tuple[str, str, float]] = []

    patterns = [
        (r"my preferred (?P<key>[\w\s/-]+?) is (?P<value>.+)", 0.95),
        (r"i prefer (?P<value>.+?) for (?P<key>[\w\s/-]+)", 0.9),
        (r"i usually use (?P<value>.+)", 0.82),
        (r"i like (?P<value>.+)", 0.78),
        (r"please remember (?P<key>[\w\s/-]+?) is (?P<value>.+)", 0.95),
    ]
    for pattern, confidence in patterns:
        match = re.search(pattern, lowered)
        if match:
            key = match.groupdict().get("key", "preference")
            value = match.groupdict().get("value", "").strip(" .")
            canonical_key = re.sub(r"[^a-z0-9_]+", "_", key.strip().lower()).strip("_")
            if canonical_key:
                candidates.append((canonical_key, value, confidence))
    return candidates


def upsert_memory_fact(
    db_path: str,
    memory_key: str,
    memory_value: str,
    *,
    source_type: str = "user",
    source_uri: str = "",
    project_slug: str = "unknown",
    workspace_path: str = "",
    user_id: str = "",
    confidence: float = 0.75,
    salience_score: float = 5.0,
    status: str = "active",
) -> dict[str, Any]:
    canonical_key = re.sub(r"[^a-z0-9_]+", "_", memory_key.strip().lower()).strip("_")
    if not canonical_key:
        canonical_key = "memory_fact"

    project_slug, workspace_path, user_id = _normalize_scope(project_slug, workspace_path, user_id)
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
    with db_session(db_path) as conn:
        if "memory_facts" not in fetch_table_names(conn):
            raise RuntimeError("memory_facts table is missing")
        existing = conn.execute(
            """
            SELECT id
            FROM memory_facts
            WHERE canonical_key = ?
              AND memory_value = ?
              AND project_slug = ?
              AND workspace_path = ?
              AND user_id = ?
            LIMIT 1
            """,
            (canonical_key, memory_value, project_slug, workspace_path, user_id),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE memory_facts
                SET source_type = ?, source_uri = ?, confidence = ?, salience_score = ?, status = ?, updated_at = ?, last_accessed_at = ?
                WHERE id = ?
                """,
                (source_type, source_uri, confidence, salience_score, status, now, now, existing["id"]),
            )
            fact_id = existing["id"]
        else:
            conn.execute(
                """
                INSERT INTO memory_facts (
                    memory_key, memory_value, canonical_key, source_type, source_uri,
                    project_slug, workspace_path, user_id, confidence, salience_score, status,
                    created_at, updated_at, last_accessed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_key,
                    memory_value,
                    canonical_key,
                    source_type,
                    source_uri,
                    project_slug,
                    workspace_path,
                    user_id,
                    confidence,
                    salience_score,
                    status,
                    now,
                    now,
                    now,
                ),
            )
            fact_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    return {
        "status": "success",
        "id": fact_id,
        "memory_key": memory_key,
        "memory_value": memory_value,
        "canonical_key": canonical_key,
        "project_slug": project_slug,
        "workspace_path": workspace_path,
        "user_id": user_id,
    }


def get_recent_summaries(
    db_path: str,
    limit: int = 3,
    project_slug: str = "unknown",
) -> list[dict]:
    with db_session(db_path) as conn:
        if "conversation_summaries" not in fetch_table_names(conn):
            return []
        rows = conn.execute(
            """
            SELECT summary, timestamp
            FROM conversation_summaries
            WHERE project_slug = ?
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (project_slug, limit),
        ).fetchall()
        return [{"summary": row["summary"], "timestamp": row["timestamp"]} for row in rows]


def save_conversation_summary(
    db_path: str,
    summary: str,
    start_id: int,
    end_id: int,
    project_slug: str = "unknown",
    workspace_path: str = "",
) -> None:
    with db_session(db_path) as conn:
        if "conversation_summaries" not in fetch_table_names(conn):
            return
        conn.execute(
            """
            INSERT INTO conversation_summaries (summary, start_conversation_id, end_conversation_id, project_slug, workspace_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (summary, start_id, end_id, project_slug, workspace_path),
        )


def _store_user_memory_signals(
    db_path: str,
    content: str,
    *,
    project_slug: str,
    workspace_path: str,
    user_id: str,
    source_uri: str,
) -> None:
    candidates = _extract_preference_candidates(content)
    for key, value, confidence in candidates:
        try:
            upsert_memory_fact(
                db_path,
                key,
                value,
                source_type="user",
                source_uri=source_uri,
                project_slug=project_slug,
                workspace_path=workspace_path,
                user_id=user_id,
                confidence=confidence,
                salience_score=8.0,
            )
        except Exception:
            pass


def save_conversation_turn(
    db_path: str,
    role: str,
    content: str,
    project_slug: str = "unknown",
    workspace_path: str = "",
    user_id: str = "",
    source_uri: str = "",
) -> None:
    project_slug, workspace_path, user_id = _normalize_scope(project_slug, workspace_path, user_id)
    with db_session(db_path) as conn:
        if "conversations" in fetch_table_names(conn):
            columns = _table_columns(conn, "conversations")
            if "project_slug" in columns:
                conn.execute(
                    """
                    INSERT INTO conversations (role, content, project_slug, workspace_path, user_id, source_uri)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (role, content, project_slug, workspace_path, user_id, source_uri),
                )
            else:
                conn.execute("INSERT INTO conversations (role, content) VALUES (?, ?)", (role, content))

    if role == "user":
        _store_user_memory_signals(
            db_path,
            content,
            project_slug=project_slug,
            workspace_path=workspace_path,
            user_id=user_id,
            source_uri=source_uri,
        )


def prune_memories(
    db_path: str,
    max_turns: int = 100,
    project_slug: str = "unknown",
    workspace_path: str = "",
    user_id: str = "",
) -> int:
    deleted = 0
    with db_session(db_path) as conn:
        tables = fetch_table_names(conn)
        if "conversations" in tables and _has_column(conn, "conversations", "project_slug"):
            total = conn.execute(
                """
                SELECT COUNT(*)
                FROM conversations
                WHERE (? = 'unknown' OR project_slug = ?)
                  AND (? = '' OR workspace_path = ?)
                  AND (? = '' OR user_id = ?)
                """,
                (project_slug, project_slug, workspace_path, workspace_path, user_id, user_id),
            ).fetchone()[0]
            if total > max_turns:
                excess = total - max_turns
                threshold_row = conn.execute(
                    """
                    SELECT id
                    FROM conversations
                    WHERE (? = 'unknown' OR project_slug = ?)
                      AND (? = '' OR workspace_path = ?)
                      AND (? = '' OR user_id = ?)
                    ORDER BY timestamp ASC, id ASC
                    LIMIT 1 OFFSET ?
                    """,
                    (project_slug, project_slug, workspace_path, workspace_path, user_id, user_id, excess - 1),
                ).fetchone()
                if threshold_row:
                    result = conn.execute(
                        """
                        DELETE FROM conversations
                        WHERE id <= ?
                          AND (? = 'unknown' OR project_slug = ?)
                          AND (? = '' OR workspace_path = ?)
                          AND (? = '' OR user_id = ?)
                        """,
                        (
                            threshold_row["id"],
                            project_slug,
                            project_slug,
                            workspace_path,
                            workspace_path,
                            user_id,
                            user_id,
                        ),
                    )
                    deleted += result.rowcount

        if "memory_facts" in tables:
            result = conn.execute(
                """
                DELETE FROM memory_facts
                WHERE status = 'archived'
                   OR (status = 'active' AND salience_score <= 1.0 AND datetime(created_at) < datetime('now', '-365 days'))
                """,
            )
            deleted += result.rowcount

    return deleted


def save_task(
    db_path: str,
    title: str,
    description: str = "",
    status: str = "backlog",
    priority: str = "medium",
    due_date: str | None = None,
    project_slug: str = "unknown",
    workspace_path: str = "",
    acceptance_criteria: str = "",
    session_notes: str = "",
) -> None:
    with db_session(db_path) as conn:
        if "tasks" not in fetch_table_names(conn):
            return
        cols = _table_columns(conn, "tasks")
        if "acceptance_criteria" in cols:
            conn.execute(
                """
                INSERT INTO tasks (title, description, status, priority, due_date, project_slug, workspace_path, acceptance_criteria, session_notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title, description, status, priority, due_date, project_slug, workspace_path, acceptance_criteria, session_notes),
            )
        else:
            conn.execute(
                """
                INSERT INTO tasks (title, description, status, priority, due_date, project_slug, workspace_path)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, description, status, priority, due_date, project_slug, workspace_path),
            )


def get_active_tasks(db_path: str, project_slug: str = "unknown") -> list[dict]:
    with db_session(db_path) as conn:
        if "tasks" not in fetch_table_names(conn):
            return []
        cols = _table_columns(conn, "tasks")
        if "acceptance_criteria" in cols:
            rows = conn.execute(
                """
                SELECT id, title, description, status, priority, due_date, acceptance_criteria, session_notes
                FROM tasks
                WHERE project_slug = ? AND status != 'done'
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        ELSE 3
                    END,
                    due_date IS NULL,
                    due_date ASC,
                    id ASC
                """,
                (project_slug,),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "description": row["description"],
                    "status": row["status"],
                    "priority": row["priority"],
                    "due_date": row["due_date"],
                    "acceptance_criteria": row["acceptance_criteria"],
                    "session_notes": row["session_notes"],
                }
                for row in rows
            ]
        rows = conn.execute(
            """
            SELECT id, title, description, status, priority, due_date
            FROM tasks
            WHERE project_slug = ? AND status != 'done'
            ORDER BY
                CASE priority
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    ELSE 3
                END,
                due_date IS NULL,
                due_date ASC,
                id ASC
            """,
            (project_slug,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "status": row["status"],
                "priority": row["priority"],
                "due_date": row["due_date"],
                "acceptance_criteria": "",
                "session_notes": "",
            }
            for row in rows
        ]


def get_recent_memory_reviews(
    db_path: str,
    limit: int = 25,
    memory_type: str | None = None,
) -> list[dict]:
    with db_session(db_path) as conn:
        if "memory_reviews" not in fetch_table_names(conn):
            return []
        if memory_type:
            rows = conn.execute(
                """
                SELECT *
                FROM memory_reviews
                WHERE memory_type = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (memory_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT *
                FROM memory_reviews
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]


def record_memory_review(
    db_path: str,
    memory_type: str,
    memory_id: int,
    action: str,
    reviewer: str = "",
    note: str = "",
) -> None:
    with db_session(db_path) as conn:
        if "memory_reviews" not in fetch_table_names(conn):
            return
        conn.execute(
            """
            INSERT INTO memory_reviews (memory_type, memory_id, action, reviewer, note)
            VALUES (?, ?, ?, ?, ?)
            """,
            (memory_type, memory_id, action, reviewer, note),
        )


def get_anti_patterns(db_path: str, project_slug: str = "unknown") -> list[dict]:
    with db_session(db_path) as conn:
        if "anti_patterns" not in fetch_table_names(conn):
            return []
        rows = conn.execute(
            "SELECT pattern, reason FROM anti_patterns WHERE project_slug = ?",
            (project_slug,),
        ).fetchall()
        return [{"pattern": row["pattern"], "reason": row["reason"]} for row in rows]


def export_memory(db_path: str, project_slug: str = "unknown") -> dict:
    with db_session(db_path) as conn:
        tables = fetch_table_names(conn)
        payload: dict[str, Any] = {
            "project_slug": project_slug,
            "preferences": {},
            "knowledge": [],
            "facts": [],
            "tasks": [],
            "summaries": [],
            "reviews": [],
            "sessions": [],
        }
        if "user_preferences" in tables:
            rows = conn.execute("SELECT key, value, last_updated FROM user_preferences ORDER BY key").fetchall()
            payload["preferences"] = {
                row["key"]: {"value": row["value"], "last_updated": row["last_updated"]}
                for row in rows
            }
        if "knowledge_bases" in tables:
            rows = conn.execute(
                """
                SELECT id, name, content, timestamp, tags, source_uri, source_type, confidence, salience_score, review_state, last_accessed_at
                FROM knowledge_bases
                WHERE (? = 'unknown' OR tags LIKE ? OR tags IS NULL)
                ORDER BY timestamp DESC, id DESC
                """,
                (project_slug, f"%{project_slug}%"),
            ).fetchall()
            payload["knowledge"] = [dict(row) for row in rows]
        if "memory_facts" in tables:
            rows = conn.execute(
                """
                SELECT *
                FROM memory_facts
                WHERE (? = 'unknown' OR project_slug = ? OR project_slug IS NULL)
                ORDER BY COALESCE(last_accessed_at, updated_at, created_at) DESC, id DESC
                """,
                (project_slug, project_slug),
            ).fetchall()
            payload["facts"] = [dict(row) for row in rows]
        if "tasks" in tables:
            rows = conn.execute(
                """
                SELECT *
                FROM tasks
                WHERE (? = 'unknown' OR project_slug = ?)
                ORDER BY updated_at DESC, id DESC
                """,
                (project_slug, project_slug),
            ).fetchall()
            payload["tasks"] = [dict(row) for row in rows]
        if "conversation_summaries" in tables:
            rows = conn.execute(
                """
                SELECT *
                FROM conversation_summaries
                WHERE (? = 'unknown' OR project_slug = ?)
                ORDER BY timestamp DESC, id DESC
                """,
                (project_slug, project_slug),
            ).fetchall()
            payload["summaries"] = [dict(row) for row in rows]
        if "memory_reviews" in tables:
            rows = conn.execute(
                """
                SELECT *
                FROM memory_reviews
                ORDER BY created_at DESC, id DESC
                """,
            ).fetchall()
            payload["reviews"] = [dict(row) for row in rows]
        if "memory_sessions" in tables:
            rows = conn.execute(
                """
                SELECT *
                FROM memory_sessions
                WHERE (? = 'unknown' OR project_slug = ?)
                ORDER BY started_at DESC, id DESC
                """,
                (project_slug, project_slug),
            ).fetchall()
            payload["sessions"] = [dict(row) for row in rows]
    return payload


def get_memory_stats(db_path: str, project_slug: str = "unknown") -> dict[str, Any]:
    stats = {
        "project_slug": project_slug,
        "conversations": 0,
        "knowledge_bases": 0,
        "memory_facts": 0,
        "tasks": 0,
        "summaries": 0,
        "reviews": 0,
        "sessions": 0,
        "fact_status": {},
        "scope": {},
    }
    with db_session(db_path) as conn:
        tables = fetch_table_names(conn)
        if "conversations" in tables:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM conversations WHERE (? = 'unknown' OR project_slug = ?)",
                (project_slug, project_slug),
            ).fetchone()
            stats["conversations"] = row["count"] if row else 0
        if "knowledge_bases" in tables:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM knowledge_bases WHERE (? = 'unknown' OR tags LIKE ? OR tags IS NULL)",
                (project_slug, f"%{project_slug}%"),
            ).fetchone()
            stats["knowledge_bases"] = row["count"] if row else 0
        if "memory_facts" in tables:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM memory_facts WHERE (? = 'unknown' OR project_slug = ? OR project_slug IS NULL)",
                (project_slug, project_slug),
            ).fetchone()
            stats["memory_facts"] = row["count"] if row else 0
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM memory_facts
                WHERE (? = 'unknown' OR project_slug = ? OR project_slug IS NULL)
                GROUP BY status
                """,
                (project_slug, project_slug),
            ).fetchall()
            stats["fact_status"] = {row["status"]: row["count"] for row in rows}
        if "tasks" in tables:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM tasks WHERE (? = 'unknown' OR project_slug = ?)",
                (project_slug, project_slug),
            ).fetchone()
            stats["tasks"] = row["count"] if row else 0
        if "conversation_summaries" in tables:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM conversation_summaries WHERE (? = 'unknown' OR project_slug = ?)",
                (project_slug, project_slug),
            ).fetchone()
            stats["summaries"] = row["count"] if row else 0
        if "memory_reviews" in tables:
            row = conn.execute("SELECT COUNT(*) AS count FROM memory_reviews").fetchone()
            stats["reviews"] = row["count"] if row else 0
        if "memory_sessions" in tables:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM memory_sessions WHERE (? = 'unknown' OR project_slug = ?)",
                (project_slug, project_slug),
            ).fetchone()
            stats["sessions"] = row["count"] if row else 0
    return stats


def hybrid_search(db_path: str, query: str, *, limit: int = 10, project_slug: str = "unknown", workspace_path: str = "") -> list[dict[str, Any]]:
    """Hybrid lexical/semantic-compatible retrieval with reciprocal-rank fusion.

    Optional embeddings are accepted by the existing scorer; this function
    provides a deterministic lexical rank and fuses it with that result so it
    remains useful when LanceDB or an embedding model is unavailable.
    """
    lexical = get_relevant_knowledge(db_path, query, limit=max(limit * 3, 20), project_slug=project_slug, workspace_path=workspace_path)
    terms = set(normalize_text(query))
    ranked = []
    for item in lexical:
        text = f"{item.get('name','')} {item.get('content','')} {item.get('tags','')}".lower()
        lexical_rank = sum(term in text for term in terms)
        ranked.append((item, lexical_rank))
    ranked.sort(key=lambda pair: (pair[1], float(pair[0].get("score", 0))), reverse=True)
    results = []
    for index, (item, _) in enumerate(ranked[:limit * 2], 1):
        item = dict(item)
        item["retrieval"] = {"method": "rrf", "lexical_rank": index, "confidence": min(1.0, max(.1, float(item.get("confidence", .5))))}
        item["score"] = 1.0 / (60 + index) + float(item.get("score", 0))
        results.append(item)
    results.sort(key=lambda value: value["score"], reverse=True)
    return results[:limit]


def record_memory_metric(db_path: str, metric: str, value: float, project_slug: str = "unknown") -> None:
    with db_session(db_path) as conn:
        if "memory_metrics" in fetch_table_names(conn):
            conn.execute("INSERT INTO memory_metrics(metric,value,project_slug) VALUES(?,?,?)", (metric, value, project_slug))


def save_session_checkpoint(db_path: str, session_id: str, state: dict[str, Any], project_slug: str = "unknown", workspace_path: str = "") -> None:
    with db_session(db_path) as conn:
        conn.execute("INSERT INTO session_checkpoints(session_id,project_slug,workspace_path,state_json) VALUES(?,?,?,?)", (session_id, project_slug, workspace_path, json.dumps(state, sort_keys=True)))


def restore_session_checkpoint(db_path: str, session_id: str, project_slug: str = "unknown", workspace_path: str = "") -> dict[str, Any] | None:
    with db_session(db_path) as conn:
        row = conn.execute("SELECT state_json FROM session_checkpoints WHERE session_id=? AND project_slug=? AND workspace_path=? ORDER BY id DESC LIMIT 1", (session_id, project_slug, workspace_path)).fetchone()
    return json.loads(row[0]) if row else None


def consolidate_memory(
    db_path: str,
    project_slug: str = "unknown",
    workspace_path: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    deduped = 0
    summarized = 0
    with db_session(db_path) as conn:
        tables = fetch_table_names(conn)
        if "memory_facts" in tables:
            rows = conn.execute(
                """
                SELECT id, canonical_key, memory_value, source_type, source_uri, project_slug, workspace_path, user_id,
                       confidence, salience_score, status, created_at, updated_at, last_accessed_at
                FROM memory_facts
                WHERE (? = 'unknown' OR project_slug = ? OR project_slug IS NULL)
                  AND (? = '' OR workspace_path = ? OR workspace_path IS NULL)
                  AND (? = '' OR user_id = ? OR user_id IS NULL)
                ORDER BY canonical_key, memory_value, confidence DESC, salience_score DESC, updated_at DESC
                """,
                (project_slug, project_slug, workspace_path, workspace_path, user_id, user_id),
            ).fetchall()
            seen: set[tuple[str, str, str, str, str]] = set()
            for row in rows:
                key = (
                    _stringify(row["canonical_key"]),
                    _stringify(row["memory_value"]).strip().lower(),
                    _stringify(row["project_slug"]),
                    _stringify(row["workspace_path"]),
                    _stringify(row["user_id"]),
                )
                if key in seen:
                    conn.execute("DELETE FROM memory_facts WHERE id = ?", (row["id"],))
                    deduped += 1
                    continue
                seen.add(key)
                conn.execute(
                    "UPDATE memory_facts SET last_accessed_at = COALESCE(last_accessed_at, updated_at), updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (row["id"],),
                )

        if "conversation_summaries" in tables:
            rows = conn.execute(
                """
                SELECT id, summary
                FROM conversation_summaries
                WHERE (? = 'unknown' OR project_slug = ?)
                ORDER BY timestamp DESC, id DESC
                LIMIT 10
                """,
                (project_slug, project_slug),
            ).fetchall()
            summarized = len(rows)

    return {
        "status": "success",
        "project_slug": project_slug,
        "workspace_path": workspace_path,
        "user_id": user_id,
        "deduplicated_facts": deduped,
        "recent_summaries_considered": summarized,
    }
