"""Versioned contracts shared by tools, planners, hosts, and automation.

The module is deliberately dependency-free: a host can validate a manifest and
result envelope before importing the rest of redrum-ai.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class ToolContract:
    name: str
    version: str
    description: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    permissions: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    risk: str = "low"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["permissions"] = list(self.permissions)
        value["side_effects"] = list(self.side_effects)
        return value


def result_envelope(tool: str, *, status: str = "success", output: Any = "",
                    exit_code: int = 0, request_id: str = "",
                    citations: list[dict[str, Any]] | None = None,
                    error: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the stable result shape consumed by chat, planning, and hosts."""
    now = datetime.now(timezone.utc).isoformat()
    value: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION, "tool": tool,
        "status": status, "exit_code": int(exit_code), "output": output,
        "request_id": request_id, "created_at": now,
        "citations": citations or [], "metadata": metadata or {},
    }
    if error:
        value["error"] = error
    return value


def validate_result(value: dict[str, Any]) -> list[str]:
    required = {"contract_version", "tool", "status", "exit_code", "output", "citations", "metadata"}
    errors = [f"missing field: {key}" for key in sorted(required - value.keys())]
    if value.get("contract_version", "").split(".")[0] != CONTRACT_VERSION.split(".")[0]:
        errors.append("incompatible result contract major version")
    if value.get("status") not in {"success", "error", "denied", "pending"}:
        errors.append("invalid status")
    if not isinstance(value.get("exit_code"), int):
        errors.append("exit_code must be an integer")
    return errors


def check_compatibility(caller_version: str, tool_version: str) -> dict[str, Any]:
    caller_major, tool_major = caller_version.split(".")[0], tool_version.split(".")[0]
    compatible = caller_major == tool_major
    return {"compatible": compatible, "caller_version": caller_version,
            "tool_version": tool_version,
            "reason": "major versions match" if compatible else "major versions differ"}


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()

