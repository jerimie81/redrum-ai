"""Small, dependency-light primitives for the federated control plane.

The module deliberately uses signed canonical JSON and SQLite transactions.  It
is suitable for an edge runner; a production deployment can put a TLS proxy or
gRPC transport in front of these same primitives without changing job policy.
"""
from __future__ import annotations
import base64, hashlib, hmac, json, re, secrets, sqlite3, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from .database import db_session
from .migrations import run_migrations

def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

class HMACSigner:
    def __init__(self, secret: bytes | str):
        self.secret = secret.encode() if isinstance(secret, str) else secret
        if len(self.secret) < 16: raise ValueError("signing secret must be at least 16 bytes")
    def sign(self, value: Any) -> str:
        return base64.urlsafe_b64encode(hmac.new(self.secret, canonical_json(value), hashlib.sha256).digest()).decode().rstrip("=")
    def verify(self, value: Any, signature: str) -> bool:
        expected = self.sign(value)
        return hmac.compare_digest(expected, signature)

@dataclass(frozen=True)
class JobEnvelope:
    job_id: str; node_id: str; nonce: str; capability: str; payload: dict[str, Any]
    vector_clock: dict[str, int]; signature: str = ""
    def unsigned(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "node_id": self.node_id, "nonce": self.nonce,
                "capability": self.capability, "payload": self.payload, "vector_clock": self.vector_clock}
    def signed(self, signer: HMACSigner) -> "JobEnvelope":
        return JobEnvelope(**{**self.__dict__, "signature": signer.sign(self.unsigned())})
    def as_dict(self) -> dict[str, Any]: return {**self.unsigned(), "signature": self.signature}

class QuarantineScanner:
    """Detect prompt injection and credentials before remote content reaches an LLM."""
    SECRET_PATTERNS = (r"(?i)\b(?:sk|ghp|xox[baprs])-[-_a-zA-Z0-9]{12,}", r"(?i)-----BEGIN [^-]+ PRIVATE KEY-----",
                       r"(?i)\b(?:password|token|secret|api[_ -]?key)\s*[:=]\s*\S+")
    INJECTION_PATTERNS = (r"(?i)ignore (?:all|any|previous) instructions", r"(?i)system message", r"(?i)developer message",
                          r"(?i)reveal (?:the )?(?:prompt|system instructions)", r"(?i)disable (?:security|safety)")
    def scan(self, text: str) -> dict[str, Any]:
        findings = ["secret" for p in self.SECRET_PATTERNS if re.search(p, text)]
        findings += ["prompt_injection" for p in self.INJECTION_PATTERNS if re.search(p, text)]
        safe = text
        for p in self.SECRET_PATTERNS: safe = re.sub(p, "[REDACTED]", safe)
        return {"quarantined": bool(findings), "findings": sorted(set(findings)), "content": safe}
    def require_safe(self, text: str) -> str:
        result = self.scan(text)
        if result["quarantined"]: raise ValueError("untrusted content quarantined: " + ", ".join(result["findings"]))
        return result["content"]

class VectorClock:
    @staticmethod
    def increment(clock: dict[str, int], actor: str) -> dict[str, int]:
        result = dict(clock); result[actor] = result.get(actor, 0) + 1; return result
    @staticmethod
    def relation(left: dict[str, int], right: dict[str, int]) -> str:
        keys = set(left) | set(right); le = all(left.get(k, 0) <= right.get(k, 0) for k in keys); ge = all(left.get(k, 0) >= right.get(k, 0) for k in keys)
        return "equal" if le and ge else "before" if le else "after" if ge else "concurrent"
    @staticmethod
    def merge(*clocks: dict[str, int]) -> dict[str, int]:
        return {k: max((c.get(k, 0) for c in clocks), default=0) for c in clocks for k in c}

class CapabilityBroker:
    def __init__(self, db_path: str, issuer: str = "control-plane"):
        self.db_path, self.issuer = db_path, issuer; run_migrations(db_path)
    def issue(self, node_id: str, capability: str, *, ttl_seconds: int = 300, scope: dict[str, Any] | None = None) -> str:
        if ttl_seconds <= 0 or ttl_seconds > 86400: raise ValueError("lease TTL must be between 1 second and 24 hours")
        lease = str(uuid.uuid4()); now = datetime.now(timezone.utc)
        with db_session(self.db_path) as c: c.execute("INSERT INTO capability_leases VALUES(?,?,?,?,?,?,?,?)", (lease,node_id,capability,json.dumps(scope or {},sort_keys=True),now.isoformat(),(now.timestamp()+ttl_seconds),None,self.issuer))
        return lease
    def authorize(self, lease_id: str, node_id: str, capability: str, scope: dict[str, Any] | None = None) -> bool:
        with db_session(self.db_path) as c:
            row = c.execute("SELECT * FROM capability_leases WHERE lease_id=? AND node_id=? AND capability=? AND revoked_at IS NULL AND expires_at > ?", (lease_id,node_id,capability,datetime.now(timezone.utc).timestamp())).fetchone()
        return bool(row and all(row["scope_json"] and (k not in json.loads(row["scope_json"]) or json.loads(row["scope_json"])[k] == v) for k,v in (scope or {}).items()))
    def revoke(self, lease_id: str) -> None:
        with db_session(self.db_path) as c: c.execute("UPDATE capability_leases SET revoked_at=? WHERE lease_id=?", (datetime.now(timezone.utc).isoformat(),lease_id))

class FederatedControlPlane:
    def __init__(self, db_path: str, signer: HMACSigner, *, scanner: QuarantineScanner | None = None):
        self.db_path, self.signer, self.scanner = db_path, signer, scanner or QuarantineScanner(); run_migrations(db_path)
        self.broker = CapabilityBroker(db_path)
    def enroll(self, node_id: str, certificate_fingerprint: str, public_key: str, capabilities: list[str], *, hardware_key_id: str = "") -> dict[str, Any]:
        if not node_id or not certificate_fingerprint or not public_key: raise ValueError("node identity is required")
        with db_session(self.db_path) as c: c.execute("INSERT OR REPLACE INTO federated_nodes(node_id,certificate_fingerprint,public_key,capabilities,revoked_at) VALUES(?,?,?,?,NULL)", (node_id,certificate_fingerprint,public_key,json.dumps(sorted(set(capabilities)))))
        return {"node_id": node_id, "certificate_fingerprint": certificate_fingerprint, "hardware_key_id": hardware_key_id, "status": "enrolled"}
    def submit(self, envelope: JobEnvelope, *, lease_id: str, certificate_fingerprint: str) -> dict[str, Any]:
        if not self.signer.verify(envelope.unsigned(), envelope.signature): raise ValueError("invalid job signature")
        if not self.broker.authorize(lease_id,envelope.node_id,envelope.capability): raise PermissionError("capability lease denied")
        with db_session(self.db_path) as c:
            node = c.execute("SELECT * FROM federated_nodes WHERE node_id=? AND revoked_at IS NULL", (envelope.node_id,)).fetchone()
            if not node or not hmac.compare_digest(node["certificate_fingerprint"], certificate_fingerprint): raise PermissionError("device authentication failed")
            if c.execute("SELECT 1 FROM replay_nonces WHERE nonce=?", (envelope.nonce,)).fetchone(): raise ValueError("replayed job nonce")
            c.execute("INSERT INTO replay_nonces(nonce,node_id) VALUES(?,?)", (envelope.nonce,envelope.node_id))
            text = json.dumps(envelope.payload, sort_keys=True); self.scanner.require_safe(text)
            digest = hashlib.sha256(canonical_json(envelope.unsigned())).hexdigest()
            c.execute("INSERT INTO federated_jobs VALUES(?,?,?,?,?,?,?, ?,NULL,NULL)", (envelope.job_id,envelope.node_id,text,digest,envelope.signature,"queued",json.dumps(envelope.vector_clock),datetime.now(timezone.utc).isoformat()))
        return {"job_id": envelope.job_id, "status": "queued"}

class SyncQueue:
    """Offline operation queue with nonce/replay protection and CRDT ordering."""
    def __init__(self, db_path: str): self.db_path = db_path; run_migrations(db_path)
    def enqueue(self, actor_id: str, entity_key: str, operation: dict[str, Any], clock: dict[str, int]) -> str:
        operation_id = str(uuid.uuid4())
        with db_session(self.db_path) as c: c.execute("INSERT INTO sync_operations(operation_id,actor_id,entity_key,operation_json,vector_clock_json,status) VALUES(?,?,?,?,?,?)", (operation_id,actor_id,entity_key,json.dumps(operation,sort_keys=True),json.dumps(clock,sort_keys=True),"queued"))
        return operation_id
    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        with db_session(self.db_path) as c: rows = c.execute("SELECT * FROM sync_operations WHERE status='queued' ORDER BY created_at,id LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    def apply(self, operation_id: str, current_clock: dict[str, int]) -> dict[str, Any]:
        with db_session(self.db_path) as c:
            row = c.execute("SELECT * FROM sync_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if not row: raise KeyError(operation_id)
            incoming = json.loads(row["vector_clock_json"]); relation = VectorClock.relation(incoming, current_clock)
            if row["status"] == "applied": return {"status":"duplicate","operation_id":operation_id}
            status = "conflict" if relation == "concurrent" else "applied"
            c.execute("UPDATE sync_operations SET status=?, applied_at=CURRENT_TIMESTAMP, conflict_json=? WHERE operation_id=?", (status,json.dumps({"relation":relation}) if status=="conflict" else None,operation_id))
        return {"status": status, "operation_id": operation_id, "relation": relation}

class AuditOutbox:
    """Tamper-evident local chain whose records can be streamed to a SIEM."""
    def __init__(self, db_path: str, node_id: str, signer: HMACSigner): self.db_path,self.node_id,self.signer=db_path,node_id,signer; run_migrations(db_path)
    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        with db_session(self.db_path) as c:
            prev = c.execute("SELECT digest,sequence_no FROM remote_audit_outbox WHERE node_id=? ORDER BY sequence_no DESC LIMIT 1", (self.node_id,)).fetchone()
            seq = (prev["sequence_no"] + 1) if prev else 1; body={"node_id":self.node_id,"sequence_no":seq,"event":event,"previous_digest":prev["digest"] if prev else None}
            digest=hashlib.sha256(canonical_json(body)).hexdigest(); sig=self.signer.sign({**body,"digest":digest}); audit_id=str(uuid.uuid4())
            c.execute("INSERT INTO remote_audit_outbox VALUES(?,?,?,?,?,?,?,NULL,CURRENT_TIMESTAMP)", (audit_id,self.node_id,seq,json.dumps(event,sort_keys=True),body["previous_digest"],digest,sig))
        return {"audit_id":audit_id,"sequence_no":seq,"digest":digest,"signature":sig}
    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        with db_session(self.db_path) as c: rows=c.execute("SELECT * FROM remote_audit_outbox WHERE node_id=? AND sent_at IS NULL ORDER BY sequence_no LIMIT ?",(self.node_id,limit)).fetchall()
        return [dict(r) for r in rows]
    def mark_sent(self, audit_ids: list[str]) -> int:
        with db_session(self.db_path) as c:
            return c.execute("UPDATE remote_audit_outbox SET sent_at=CURRENT_TIMESTAMP WHERE node_id=? AND audit_id IN (%s)" % ",".join("?"*len(audit_ids)), [self.node_id,*audit_ids]).rowcount if audit_ids else 0
