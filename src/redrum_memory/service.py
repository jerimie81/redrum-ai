"""Authenticated service boundary for memory operations.

This is a transport-neutral boundary: HTTP, gRPC, or a local IPC adapter can
authenticate once and call it.  SQLite/LanceDB paths are never part of the
request contract.
"""
from __future__ import annotations
import hmac, hashlib, json, secrets
from typing import Any
from .engine import MemoryEngine
from .policy import AccessContext, PolicyStore

class ServiceAuthenticator:
    def __init__(self, token: str):
        if len(token) < 16: raise ValueError("service token must be at least 16 characters")
        self._token = token.encode()
    def issue(self, body: Any) -> str: return hmac.new(self._token, json.dumps(body,sort_keys=True,separators=(",",":")).encode(), hashlib.sha256).hexdigest()
    def verify(self, body: Any, signature: str) -> bool: return hmac.compare_digest(self.issue(body), signature)

class MemoryService:
    def __init__(self, db_path: str, token: str):
        self._engine = MemoryEngine(db_path); self._policy = PolicyStore(db_path); self._auth = ServiceAuthenticator(token)
    def request(self, body: dict[str, Any], signature: str) -> dict[str, Any]:
        if not self._auth.verify(body, signature): raise PermissionError("invalid service authentication")
        action = body.get("action"); context = AccessContext(**body.get("context", {"principal":"service"}))
        if action == "search": return {"results": self._policy.search(str(body.get("query", "")), context, int(body.get("limit", 5)))}
        if action == "export": return self._engine.export()
        raise ValueError("unsupported memory service action")
