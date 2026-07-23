"""Safe, offline-friendly SRE and incident-response analyzers."""
from __future__ import annotations
import json, re, time
import subprocess
from pathlib import Path
from typing import Any

def forensic_timeline(text: str) -> list[dict[str, Any]]:
    events = []
    for line in text.splitlines():
        match = re.search(r"(\d{4}-\d\d-\d\d[T ][^ ]+).*?(error|warn|fail|oom|panic|timeout).*", line, re.I)
        if match: events.append({"timestamp": match.group(1), "severity": match.group(2).lower(), "message": line.strip()})
    return events

def parse_log_file(path: str, max_bytes: int = 2_000_000) -> dict[str, Any]:
    raw = Path(path).read_bytes()[:max_bytes]
    text = raw.decode("utf-8", "replace")
    return {"path": str(Path(path).resolve()), "bytes": len(raw), "events": forensic_timeline(text)}

def verify_runbook(runbook: list[dict[str, Any]]) -> dict[str, Any]:
    errors = []
    for index, step in enumerate(runbook):
        if not step.get("name") or not isinstance(step.get("argv"), list): errors.append(f"step {index}: name and argv are required")
        if step.get("rollback") is None: errors.append(f"step {index}: rollback is required")
    return {"valid": not errors, "errors": errors, "steps": len(runbook)}

def execute_runbook(runbook: list[dict[str, Any]], *, cwd: str = "", confirm: bool = False) -> dict[str, Any]:
    """Execute only a validated runbook after explicit caller confirmation."""
    check = verify_runbook(runbook)
    if not check["valid"]: return {"status": "error", "validation": check, "steps": []}
    if not confirm: return {"status": "pending_confirmation", "validation": check, "steps": []}
    completed = []
    for step in runbook:
        proc = subprocess.run(step["argv"], cwd=cwd or None, capture_output=True, text=True)
        completed.append({"name": step["name"], "exit_code": proc.returncode, "output": proc.stdout + proc.stderr})
        if proc.returncode:
            return {"status": "error", "steps": completed, "rollback_available": True}
    return {"status": "success", "steps": completed, "rollback_available": True}

def drift_report(desired: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(set(desired) | set(actual))
    changes = [{"key": key, "desired": desired.get(key), "actual": actual.get(key)} for key in keys if desired.get(key) != actual.get(key)]
    return {"drift": bool(changes), "changes": changes}

def parse_iac_state(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    resources = value.get("resources", []) if isinstance(value, dict) else []
    return {"format": "terraform", "resource_count": len(resources), "resources": resources}

def offline_bundle_manifest(root: str) -> dict[str, Any]:
    path = Path(root)
    files = [{"path": str(p.relative_to(path)), "bytes": p.stat().st_size} for p in path.rglob("*") if p.is_file()]
    return {"format": 1, "root": str(path.resolve()), "created_at": time.time(), "files": files}
