"""Standalone, SQLite-first memory engine used by redrum-ai and other agents."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from redrum_ai.security import redact_sensitive
from .database import db_session, get_relevant_knowledge
from .migrations import run_migrations


def _scope(project_slug: str = "unknown", workspace_path: str = "") -> tuple[str, str]:
    return project_slug or "unknown", workspace_path or ""


def _terms(value: str) -> set[str]:
    return {x for x in re.findall(r"[\w-]{2,}", value.lower())}


class MemoryEngine:
    """Durable memory facade with provenance, review gates, and scope isolation."""
    def __init__(self, db_path: str, *, project_slug: str = "unknown", workspace_path: str = "", user_id: str = ""):
        self.db_path, self.project_slug, self.workspace_path, self.user_id = db_path, *_scope(project_slug, workspace_path), user_id or ""
        run_migrations(db_path)

    def ingest(self, content: str, *, source_type: str = "chat", source_uri: str = "", kind: str = "fact",
               confidence: float = .75, salience: float = 5., confirmed: bool = False) -> dict[str, Any]:
        """Ingest data, redacting secrets and requiring confirmation for durable facts."""
        safe_content = redact_sensitive(content)
        digest = hashlib.sha256(safe_content.encode()).hexdigest()
        if kind == "fact" and not confirmed:
            return {"status": "pending_confirmation", "content_hash": digest, "content": safe_content}
        with db_session(self.db_path) as conn:
            source_id = conn.execute("INSERT INTO memory_sources(source_type,source_uri,content_hash,project_slug,workspace_path) VALUES(?,?,?,?,?)",
                                     (source_type, source_uri, digest, self.project_slug, self.workspace_path)).lastrowid
            if kind in {"fact", "preference"}:
                key = self._key(safe_content)
                conn.execute("INSERT INTO memory_facts(memory_key,memory_value,canonical_key,source_type,source_uri,project_slug,workspace_path,user_id,confidence,salience_score,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             (key, safe_content, key, source_type, source_uri or f"memory-source:{source_id}", self.project_slug, self.workspace_path, self.user_id, confidence, salience, "active"))
            else:
                conn.execute("INSERT OR IGNORE INTO knowledge_bases(name,content,tags,source_uri,source_type,confidence,salience_score,review_state,project_slug,workspace_path,user_id,kb_scope) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                             (digest[:16], safe_content, self.project_slug, source_uri, source_type, confidence, salience, "confirmed" if confirmed else "unreviewed", self.project_slug, self.workspace_path, self.user_id, "project"))
        return {"status": "stored", "content_hash": digest, "source_id": source_id, "kind": kind}

    @staticmethod
    def _key(content: str) -> str:
        words = list(_terms(content))
        return "memory_" + hashlib.sha1(" ".join(sorted(words)).encode()).hexdigest()[:12]

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return get_relevant_knowledge(self.db_path, query, limit=limit, project_slug=self.project_slug, workspace_path=self.workspace_path)

    def save_checkpoint(self, session_id: str, state: dict[str, Any]) -> int:
        with db_session(self.db_path) as conn:
            return int(conn.execute("INSERT INTO session_checkpoints(session_id,project_slug,workspace_path,state_json) VALUES(?,?,?,?)",
                                    (session_id, self.project_slug, self.workspace_path, json.dumps(state, sort_keys=True))).lastrowid)

    def restore(self, session_id: str) -> dict[str, Any] | None:
        with db_session(self.db_path) as conn:
            row = conn.execute("SELECT state_json FROM session_checkpoints WHERE session_id=? AND project_slug=? AND workspace_path=? ORDER BY id DESC LIMIT 1",
                               (session_id, self.project_slug, self.workspace_path)).fetchone()
        return json.loads(row[0]) if row else None

    def graph_upsert(self, subject: str, predicate: str, obj: str, *, entity_type: str = "concept", confidence: float = .75) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            ids = []
            for name in (subject, obj):
                conn.execute("INSERT OR IGNORE INTO memory_entities(canonical_name,entity_type,project_slug,workspace_path,confidence) VALUES(?,?,?,?,?)",
                             (name, entity_type, self.project_slug, self.workspace_path, confidence))
                ids.append(conn.execute("SELECT id FROM memory_entities WHERE canonical_name=? AND project_slug=? AND workspace_path=?", (name, self.project_slug, self.workspace_path)).fetchone()[0])
            conn.execute("INSERT OR IGNORE INTO memory_relations(subject_id,predicate,object_id,confidence,project_slug) VALUES(?,?,?,?,?)",
                         (ids[0], predicate, ids[1], confidence, self.project_slug))
        return {"subject": subject, "predicate": predicate, "object": obj, "confidence": confidence}

    def graph_query(self, entity: str) -> list[dict[str, Any]]:
        with db_session(self.db_path) as conn:
            rows = conn.execute("""SELECT a.canonical_name subject, r.predicate, b.canonical_name object, r.confidence
                FROM memory_relations r JOIN memory_entities a ON a.id=r.subject_id JOIN memory_entities b ON b.id=r.object_id
                WHERE (a.canonical_name=? OR b.canonical_name=?) AND r.project_slug=?""", (entity, entity, self.project_slug)).fetchall()
        return [dict(row) for row in rows]

    def export(self) -> dict[str, Any]:
        with db_session(self.db_path) as conn:
            facts = [dict(r) for r in conn.execute("SELECT * FROM memory_facts WHERE project_slug=? AND workspace_path=?", (self.project_slug, self.workspace_path))]
            conversations = [dict(r) for r in conn.execute("SELECT * FROM conversations WHERE project_slug=? AND workspace_path=? ORDER BY id", (self.project_slug, self.workspace_path))]
        return {"schema": 1, "project_slug": self.project_slug, "workspace_path": self.workspace_path, "facts": facts, "conversations": conversations}

    def purge(self, *, before: str | None = None) -> int:
        clause = "AND created_at < ?" if before else ""
        params: list[Any] = [self.project_slug, self.workspace_path] + ([before] if before else [])
        with db_session(self.db_path) as conn:
            result = conn.execute(f"DELETE FROM memory_facts WHERE project_slug=? AND workspace_path=? {clause}", params)
        return result.rowcount
