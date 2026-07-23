"""Policy-filtered, multi-tenant memory access.

Filtering is intentionally performed while selecting candidates, before the
ranking layer sees content.  Callers receive no existence signal for denied
records.
"""
from __future__ import annotations
import hashlib, json, uuid
from dataclasses import dataclass
from enum import IntEnum
from typing import Any
from .database import db_session, get_relevant_knowledge
from .migrations import run_migrations

class Sensitivity(IntEnum): PUBLIC = 0; INTERNAL = 1; CONFIDENTIAL = 2; RESTRICTED = 3
SCOPES = ("personal", "project", "org", "sre", "session", "regulated")

@dataclass(frozen=True)
class AccessContext:
    principal: str; scope: str = "project"; project_slug: str = "unknown"; workspace_path: str = ""; max_sensitivity: int = int(Sensitivity.INTERNAL)

class PolicyStore:
    def __init__(self, db_path: str): self.db_path = db_path; run_migrations(db_path)
    def grant(self, context: AccessContext, *, effect: str = "allow") -> str:
        if context.scope not in SCOPES or effect not in {"allow", "deny"}: raise ValueError("invalid scope or effect")
        policy_id = str(uuid.uuid4())
        with db_session(self.db_path) as c: c.execute("INSERT INTO memory_access_policies VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", (policy_id,context.principal,context.scope,context.project_slug,context.workspace_path,context.max_sensitivity,effect))
        return policy_id
    def can_read(self, record: dict[str, Any], context: AccessContext) -> bool:
        sensitivity = int(record.get("sensitivity", Sensitivity.INTERNAL) or 0)
        if sensitivity > context.max_sensitivity: return False
        scope = record.get("kb_scope") or record.get("scope") or "project"
        if scope == "personal" and record.get("user_id") not in {None, "", context.principal}: return False
        if scope in {"project", "sre", "session", "regulated"} and context.project_slug != "unknown" and record.get("project_slug") not in {None, "", context.project_slug}: return False
        return scope in SCOPES
    def search(self, query: str, context: AccessContext, limit: int = 5) -> list[dict[str, Any]]:
        # Database retrieval is scoped first; policy checks happen before the
        # shared lexical/vector scorer is called for each candidate.
        with db_session(self.db_path) as c:
            rows = c.execute("SELECT id, project_slug, workspace_path, user_id, sensitivity, kb_scope FROM knowledge_bases WHERE (kb_scope IS NULL OR kb_scope=?) AND (sensitivity IS NULL OR sensitivity<=?) AND (project_slug IS NULL OR project_slug=? OR ?='unknown')", (context.scope,context.max_sensitivity,context.project_slug,context.project_slug)).fetchall()
            fact_rows = c.execute("SELECT id, project_slug, workspace_path, user_id, sensitivity, kb_scope FROM memory_facts WHERE status='active' AND (kb_scope IS NULL OR kb_scope=?) AND (sensitivity IS NULL OR sensitivity<=?) AND (project_slug IS NULL OR project_slug=? OR ?='unknown')", (context.scope,context.max_sensitivity,context.project_slug,context.project_slug)).fetchall()
        allowed_ids = {("knowledge_base", row["id"]) for row in rows if self.can_read(dict(row), context)} | {("memory_fact", row["id"]) for row in fact_rows if self.can_read(dict(row), context)}
        # The callback is evaluated inside the database retrieval loop, before
        # lexical or vector scoring, so denied rows are never ranked.
        def allowed(kind: str, row: dict[str, Any]) -> bool:
            return (kind, row.get("id")) in allowed_ids
        return get_relevant_knowledge(self.db_path, query, limit=limit, project_slug=context.project_slug, workspace_path=context.workspace_path, candidate_filter=allowed)
    def record_provenance(self, memory_type: str, memory_id: int, context: AccessContext, content: str, source_uri: str = "", sensitivity: int = 1) -> str:
        provenance_id = str(uuid.uuid4()); digest = hashlib.sha256(content.encode()).hexdigest()
        record = {"provenance_id":provenance_id,"memory_type":memory_type,"memory_id":memory_id,"scope":context.scope,"sensitivity":sensitivity,"source_uri":source_uri,"content_hash":digest}
        with db_session(self.db_path) as c: c.execute("INSERT INTO memory_provenance VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)", (provenance_id,memory_type,memory_id,context.scope,sensitivity,source_uri,digest,json.dumps(record,sort_keys=True)))
        return provenance_id
