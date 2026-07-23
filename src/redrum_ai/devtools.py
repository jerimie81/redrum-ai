"""Dependency-free developer experience helpers (LSP, patches, TDD, CI)."""
from __future__ import annotations
import difflib, json, os, re, subprocess
from pathlib import Path
from typing import Any

def lsp_request(command: list[str], method: str, params: dict[str, Any], *, cwd: str = "", timeout: int = 10) -> dict[str, Any]:
    """Perform a bounded JSON-RPC request against an installed language server."""
    if not command or any("\x00" in x for x in command): return {"status":"error", "error":"invalid command"}
    try:
        proc = subprocess.Popen(command, cwd=cwd or None, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        payload = json.dumps({"jsonrpc":"2.0", "id":1, "method":method, "params":params})
        stdout, stderr = proc.communicate(payload, timeout=timeout)
        return {"status":"success", "response":stdout, "stderr":stderr}
    except Exception as exc: return {"status":"error", "error":str(exc)}

def unified_patch(path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=path, tofile=path))

def validate_patch(patch: str) -> dict[str, Any]:
    lines = patch.splitlines()
    return {"valid": bool(patch and any(x.startswith("@@") for x in lines)), "files": [x[4:] for x in lines if x.startswith("+++ ")], "hunks": sum(x.startswith("@@") for x in lines)}

def monorepo_map(roots: list[str]) -> dict[str, Any]:
    packages = []
    for root in roots:
        path = Path(root).resolve()
        if path.exists():
            for manifest in path.rglob("pyproject.toml"):
                packages.append({"path": str(manifest.parent), "manifest": manifest.name, "ecosystem": "python"})
            for manifest in path.rglob("package.json"):
                packages.append({"path": str(manifest.parent), "manifest": manifest.name, "ecosystem": "node"})
    return {"roots": [str(Path(x).resolve()) for x in roots], "packages": packages}

def tdd_loop(command: list[str], *, cwd: str = "", max_attempts: int = 3) -> dict[str, Any]:
    attempts = []
    for index in range(max_attempts):
        proc = subprocess.run(command, cwd=cwd or None, capture_output=True, text=True)
        attempts.append({"attempt": index + 1, "exit_code": proc.returncode, "output": proc.stdout + proc.stderr})
        if proc.returncode == 0: break
    return {"success": attempts[-1]["exit_code"] == 0 if attempts else False, "attempts": attempts}

def ci_log_diagnosis(log: str) -> dict[str, Any]:
    failures = [line.strip() for line in log.splitlines() if re.search(r"(?i)(error|failed|failure|traceback)", line)]
    return {"failure_count": len(failures), "findings": failures[:20], "suggestion": "Inspect the first failure; later errors may be cascading." if failures else "No obvious failure marker found."}

