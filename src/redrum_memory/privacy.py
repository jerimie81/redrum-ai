"""Privacy, retention, and optional AES-256-GCM storage helpers."""
from __future__ import annotations
import base64, hashlib, os, sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from redrum_ai.security import redact_sensitive
from .database import db_session

class EncryptedStore:
    """Client-side AES-GCM when ``cryptography`` is installed.

    The dependency is optional to keep the offline CLI small; construction
    fails explicitly instead of silently storing plaintext when encryption is
    requested.
    """
    def __init__(self, key: bytes | str):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise RuntimeError("AES-256 encryption requires the optional 'cryptography' package") from exc
        raw = key.encode() if isinstance(key, str) else key
        self.key = hashlib.sha256(raw).digest()
        self._aes = AESGCM(self.key)
    def encrypt(self, text: str, aad: bytes = b"") -> str:
        nonce = os.urandom(12)
        return base64.b64encode(nonce + self._aes.encrypt(nonce, text.encode(), aad)).decode()
    def decrypt(self, value: str, aad: bytes = b"") -> str:
        raw = base64.b64decode(value)
        return self._aes.decrypt(raw[:12], raw[12:], aad).decode()

def privacy_filter(text: str) -> str: return redact_sensitive(text, include_pii=True)

def purge_expired(db_path: str, *, chat_days: int = 90, fact_days: int = 365, project_slug: str = "unknown") -> dict[str, int]:
    with db_session(db_path) as conn:
        conversations = conn.execute("DELETE FROM conversations WHERE project_slug=? AND datetime(timestamp) < datetime('now', ?)", (project_slug, f"-{chat_days} days")).rowcount
        facts = conn.execute("DELETE FROM memory_facts WHERE project_slug=? AND datetime(created_at) < datetime('now', ?)", (project_slug, f"-{fact_days} days")).rowcount
    return {"conversations": conversations, "facts": facts}

