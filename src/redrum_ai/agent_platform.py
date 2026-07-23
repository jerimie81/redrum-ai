"""Planning, connector consent, and safe tool-result reasoning services."""
from __future__ import annotations
import json, time
from dataclasses import dataclass
from typing import Any
from redrum_ai.contracts import result_envelope
from redrum_ai.security import redact_sensitive, scan_sensitive

@dataclass(frozen=True)
class Route:
    intent: str
    tools: tuple[str, ...]
    explanation: str
    fallback: tuple[str, ...] = ()

class ToolRouter:
    RULES = (
        ("filesystem", ("file", "directory", "folder", "read", "patch", "write"), ("inspect_file",), ("find_files",)),
        ("git", ("git", "branch", "commit", "diff", "repository"), ("git_tool",), ("read_file",)),
        ("network", ("web", "url", "http", "dns", "network"), ("web_fetch",), ("dns_lookup",)),
        ("memory", ("remember", "memory", "preference", "recall"), (), ()),
        ("process", ("run", "execute", "test", "command"), ("execute_argv",), ("execute_shell",)),
    )
    def route(self, query: str, available: set[str] | None = None) -> Route:
        lowered = query.lower()
        available = available or set()
        for intent, words, preferred, fallback in self.RULES:
            if any(word in lowered for word in words):
                selected = tuple(x for x in preferred if not available or x in available)
                backup = tuple(x for x in fallback if not available or x in available)
                return Route(intent, selected, f"Matched {intent} intent with the narrowest capability.", backup)
        return Route("chat", (), "No tool is required for a conversational request.")

def summarize_tool_result(tool: str, raw: Any, *, started: float | None = None) -> dict[str, Any]:
    text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
    safe = redact_sensitive(text)
    status = raw.get("status", "success") if isinstance(raw, dict) else "success"
    code = raw.get("exit_code", 0) if isinstance(raw, dict) else 0
    findings = [line.strip() for line in safe.splitlines() if line.strip()][:8]
    return result_envelope(tool, status=status, output=safe, exit_code=code,
                           metadata={"key_findings": findings, "latency_ms": round((time.time()-(started or time.time()))*1000, 2), "sensitive_scan": scan_sensitive(text)})

class ConnectorRegistry:
    def __init__(self): self._connectors: dict[str, dict[str, Any]] = {}
    def register(self, name: str, scopes: list[str], importer: str = "") -> None:
        self._connectors[name] = {"name": name, "scopes": scopes, "importer": importer, "optional": True}
    def manifest(self) -> list[dict[str, Any]]: return list(self._connectors.values())
    def get(self, name: str) -> dict[str, Any] | None: return self._connectors.get(name)

connectors = ConnectorRegistry()
for _name in ("calendar", "task_tracker", "documentation", "issue_tracker"):
    connectors.register(_name, [f"{_name}.read"], f"import_{_name}")

