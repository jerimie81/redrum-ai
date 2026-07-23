"""Local zero-trust policy, DLP, and tamper-evident audit primitives."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path
from typing import Any

from redrum_ai.contracts import canonical_digest

SECRET_RE = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[^\s,;]+|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|-----BEGIN [^-]+ KEY-----")
PII_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")


def redact_sensitive(text: str, *, include_pii: bool = True) -> str:
    text = SECRET_RE.sub("[REDACTED_SECRET]", text)
    return PII_RE.sub("[REDACTED_PII]", text) if include_pii else text


def scan_sensitive(value: Any) -> dict[str, Any]:
    text = json.dumps(value, default=str) if not isinstance(value, str) else value
    secrets_found = SECRET_RE.findall(text)
    pii_found = PII_RE.findall(text)
    return {"safe": not secrets_found and not pii_found,
            "secret_count": len(secrets_found), "pii_count": len(pii_found),
            "redacted": redact_sensitive(text)}


class Policy:
    def __init__(self, *, allowed_roots: list[str] | None = None,
                 allowed_commands: set[str] | None = None,
                 denied_commands: set[str] | None = None):
        self.allowed_roots = [Path(p).resolve() for p in (allowed_roots or [])]
        self.allowed_commands = allowed_commands or set()
        self.denied_commands = denied_commands or {"rm", "dd", "mkfs", "shutdown", "reboot", "sudo"}

    def check_path(self, path: str) -> bool:
        candidate = Path(path).expanduser().resolve()
        return any(candidate == root or root in candidate.parents for root in self.allowed_roots)

    def check_argv(self, argv: list[str]) -> tuple[bool, str]:
        if not argv:
            return False, "empty command"
        command = Path(argv[0]).name
        if command in self.denied_commands:
            return False, f"command denied: {command}"
        if self.allowed_commands and command not in self.allowed_commands:
            return False, f"command not allowlisted: {command}"
        if any("\x00" in arg for arg in argv):
            return False, "NUL byte in argument"
        return True, "allowed"


def sandbox_argv(argv: list[str], *, cwd: str, timeout: int = 60, policy: Policy | None = None) -> dict[str, Any]:
    """Run an argv command with policy checks and a bounded process lifetime.

    Bubblewrap/Firejail is used when available and explicitly enabled; the
    portable fallback still enforces argv, cwd, timeout, and allow/deny policy.
    """
    policy = policy or Policy(allowed_roots=[cwd])
    allowed, reason = policy.check_argv(argv)
    if not allowed:
        return {"status": "denied", "exit_code": 126, "output": reason}
    wrapper = []
    if os.environ.get("REDRUM_AI_USE_SANDBOX") == "1":
        binary = shutil.which("bwrap") or shutil.which("firejail")
        if binary:
            wrapper = [binary, "--unshare-net"] if Path(binary).name == "bwrap" else [binary, "--quiet"]
    try:
        completed = subprocess.run(wrapper + argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return {"status": "success" if completed.returncode == 0 else "error",
                "exit_code": completed.returncode, "output": completed.stdout + completed.stderr}
    except subprocess.TimeoutExpired as exc:
        return {"status": "error", "exit_code": 124, "output": f"timeout after {timeout}s: {exc}"}


def audit_digest(entry: dict[str, Any], previous_digest: str = "", key: str = "") -> str:
    payload = {"previous_digest": previous_digest, "entry": entry}
    raw = canonical_digest(payload).encode()
    return hmac.new((key or "redrum-ai-local-audit").encode(), raw, hashlib.sha256).hexdigest()

