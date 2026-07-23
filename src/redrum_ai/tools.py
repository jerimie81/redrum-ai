from __future__ import annotations

import difflib
import hashlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from redrum_memory.database import db_session
from redrum_ai.contracts import CONTRACT_VERSION, result_envelope
from redrum_ai.security import redact_sensitive

PERMISSIONS_CONFIG_PATH = os.path.expanduser("~/.config/redrum-ai/permissions.json")

COMMAND_ALLOWLIST = {
    "git",
    "ls",
    "grep",
    "cat",
    "echo",
    "pwd",
    "whoami",
    "find",
    "python3",
    "pytest",
    "pip",
    "black",
    "flake8",
    "curl",
    "wget",
    "ping",
    "netstat",
    "ip",
    "nslookup",
    "dig",
    "nc",
    "nmap",
}

COMMAND_DENYLIST = {
    "rm",
    "dd",
    "mkfs",
    "format",
    "reboot",
    "shutdown",
    "ssh",
    "sudo",
    "chmod",
    "chown",
}

COMMAND_TEMPLATES: dict[str, tuple[str, ...]] = {
    "pytest": ("pytest", "-q"),
    "git_status": ("git", "status", "--short", "--branch"),
    "git_diff": ("git", "diff", "--stat", "--patch", "--minimal"),
    "python_check": ("python3", "-m", "compileall"),
}

SECRET_PATTERNS = ("api_key", "apikey", "token", "secret", "password", "private_key")
TOOL_API_VERSION = "1.0.0"


def load_permissions_config() -> dict[str, Any]:
    default_config: dict[str, Any] = {
        "allowed_directories": [],
        "allow_internet_search": False,
        "allow_internet_fetch": False,
        "allowed_domains": [],
        "command_allowlist": list(COMMAND_ALLOWLIST),
        "command_denylist": list(COMMAND_DENYLIST),
    }
    if os.path.exists(PERMISSIONS_CONFIG_PATH):
        try:
            with open(PERMISSIONS_CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            default_config.update(user_config)
        except Exception as exc:
            print(f"Warning: failed to read permissions config: {exc}", file=sys.stderr)
    return default_config


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _domain_allowed(url: str) -> bool:
    config = load_permissions_config()
    allowed_domains = config.get("allowed_domains") or []
    if not allowed_domains:
        return True
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def validate_path(path: str, workspace_path: str) -> str:
    abs_path = os.path.realpath(_normalize_path(path))
    config = load_permissions_config()
    allowed_roots = [os.path.realpath(_normalize_path(root)) for root in config.get("allowed_directories", [])]
    if workspace_path and workspace_path not in allowed_roots:
        allowed_roots.append(os.path.realpath(_normalize_path(workspace_path)))

    for root in allowed_roots:
        root_real = os.path.realpath(root)
        try:
            common = os.path.commonpath([abs_path, root_real])
        except ValueError:
            continue
        if common == root_real:
            return abs_path

    raise PermissionError(f"Path is outside approved workspaces: {path}")


def backup_file(path: str) -> None:
    if os.path.exists(path) and os.path.isfile(path):
        shutil.copy2(path, path + ".bak")


def _atomic_write(path: str, content: str) -> None:
    """Write via a sibling temporary file, then atomically replace the target."""
    import tempfile
    directory = os.path.dirname(path) or "."
    fd, temporary = tempfile.mkstemp(prefix=".redrum-write-", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = redacted.replace(pattern, "[REDACTED]")
        redacted = redacted.replace(pattern.upper(), "[REDACTED]")
    return redacted


def detect_secret_text(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in SECRET_PATTERNS)


def log_tool_invocation(
    db_path: str,
    command: str,
    directory: str,
    exit_code: int,
    output: str,
    *,
    tool_name: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        with db_session(db_path) as conn:
            if "command_history" not in {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
                return
            conn.execute(
                """
                INSERT INTO command_history (command_str, working_directory, exit_code, output_summary)
                VALUES (?, ?, ?, ?)
                """,
                (
                    command,
                    directory,
                    exit_code,
                    redact_secrets(output)[:500] + ("..." if len(output) > 500 else ""),
                ),
            )
            if "work_events" in {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
                conn.execute(
                    """
                    INSERT INTO work_events (session_id, task_id, event_type, severity, message, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "",
                        None,
                        "tool.invocation",
                        "info" if exit_code == 0 else "error",
                        f"{tool_name or command} exited with {exit_code}",
                        json.dumps(metadata or {}, sort_keys=True),
                    ),
                )
    except Exception:
        pass


def request_approval(action_description: str) -> bool:
    if not sys.stdin.isatty():
        print(f"[REJECTED] Non-interactive mode block: {action_description}", file=sys.stderr)
        return False

    print(f"\n⚠️  [APPROVAL REQUIRED]: {action_description}", flush=True)
    try:
        return input("Do you approve and want to proceed? (y/N): ").strip().lower() == "y"
    except Exception:
        return False


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def read_file(path: str, workspace_path: str) -> str:
    try:
        safe_path = validate_path(path, workspace_path)
        if not os.path.exists(safe_path):
            return f"Error: File not found: {path}"
        if os.path.isdir(safe_path):
            return f"Error: Path is a directory, not a file: {path}"
        return _read_text_file(safe_path)
    except Exception as exc:
        return f"Error: {exc}"


def inspect_file(path: str, workspace_path: str, max_bytes: int = 12000) -> str:
    try:
        safe_path = validate_path(path, workspace_path)
        if not os.path.exists(safe_path):
            return f"Error: File not found: {path}"
        if os.path.isdir(safe_path):
            return f"Error: Path is a directory, not a file: {path}"

        suffix = Path(safe_path).suffix.lower()
        raw = Path(safe_path).read_bytes()[:max_bytes]
        text = raw.decode("utf-8", errors="ignore")
        payload: dict[str, Any] = {
            "path": safe_path,
            "size": os.path.getsize(safe_path),
            "modified_time": datetime.fromtimestamp(os.path.getmtime(safe_path)).isoformat(),
            "type": suffix or "text",
        }

        if suffix == ".json":
            try:
                payload["parsed"] = json.loads(text)
            except Exception:
                payload["preview"] = text
        elif suffix in {".toml"}:
            try:
                if tomllib is None:
                    raise ImportError("TOML parsing requires 'tomli' package on Python < 3.11")
                payload["parsed"] = tomllib.loads(text)
            except Exception:
                payload["preview"] = text
        elif suffix in {".yml", ".yaml"}:
            try:
                import yaml  # type: ignore

                payload["parsed"] = yaml.safe_load(text)
            except Exception:
                payload["preview"] = text
        else:
            payload["preview"] = text
        return json.dumps(payload, indent=2, default=str)
    except Exception as exc:
        return f"Error: {exc}"


def list_directory(path: str, workspace_path: str) -> str:
    try:
        safe_path = validate_path(path, workspace_path)
        if not os.path.exists(safe_path):
            return f"Error: Directory not found: {path}"
        if not os.path.isdir(safe_path):
            return f"Error: Path is not a directory: {path}"
        files = os.listdir(safe_path)
        lines = []
        for entry in sorted(files):
            fp = os.path.join(safe_path, entry)
            is_dir = os.path.isdir(fp)
            size = os.path.getsize(fp) if not is_dir else 0
            lines.append(f"{'[DIR] ' if is_dir else '[FILE]'} {entry} ({size} bytes)")
        return "\n".join(lines) or "(empty directory)"
    except Exception as exc:
        return f"Error: {exc}"


def find_files(
    root: str,
    query: str,
    workspace_path: str,
    include_content: bool = False,
    max_results: int = 50,
) -> str:
    try:
        safe_root = validate_path(root, workspace_path)
        if not os.path.exists(safe_root):
            return f"Error: Path not found: {root}"
        matches: list[dict[str, Any]] = []
        lowered = query.lower()
        for current_root, _, files in os.walk(safe_root):
            for filename in files:
                candidate = os.path.join(current_root, filename)
                rel = os.path.relpath(candidate, safe_root)
                if lowered in filename.lower() or lowered in rel.lower():
                    matches.append({"path": candidate, "reason": "name"})
                elif include_content:
                    try:
                        text = _read_text_file(candidate)
                    except Exception:
                        continue
                    if lowered in text.lower():
                        matches.append({"path": candidate, "reason": "content"})
                if len(matches) >= max_results:
                    return json.dumps(matches, indent=2)
        return json.dumps(matches, indent=2)
    except Exception as exc:
        return f"Error: {exc}"


def diff_files(path_a: str, path_b: str, workspace_path: str) -> str:
    try:
        safe_a = validate_path(path_a, workspace_path)
        safe_b = validate_path(path_b, workspace_path)
        if not os.path.exists(safe_a):
            return f"Error: File not found: {path_a}"
        if not os.path.exists(safe_b):
            return f"Error: File not found: {path_b}"
        a_lines = _read_text_file(safe_a).splitlines()
        b_lines = _read_text_file(safe_b).splitlines()
        diff = difflib.unified_diff(a_lines, b_lines, fromfile=safe_a, tofile=safe_b, lineterm="")
        return "\n".join(diff) or "No differences found."
    except Exception as exc:
        return f"Error: {exc}"


def patch_file(path: str, search_text: str, replace_text: str, workspace_path: str, dry_run: bool = False) -> str:
    try:
        safe_path = validate_path(path, workspace_path)
        if not os.path.exists(safe_path):
            return f"Error: File not found: {path}"
        if detect_secret_text(replace_text):
            return "Error: Refusing to write content that appears to contain a secret. Remove or redact secrets first."
        original = _read_text_file(safe_path)
        if search_text not in original:
            return f"Error: Search text not found in {path}"
        updated = original.replace(search_text, replace_text, 1)
        if dry_run:
            return f"[DRY-RUN] Would patch {path}."
        action = f"Patch file {path}"
        if not request_approval(action):
            return f"Action rejected: {action}"
        backup_file(safe_path)
        _atomic_write(safe_path, updated)
        return f"Success: File patched at {path}"
    except Exception as exc:
        return f"Error: {exc}"


def write_file(path: str, content: str, workspace_path: str, dry_run: bool = False) -> str:
    try:
        safe_path = validate_path(path, workspace_path)
        if dry_run:
            return f"[DRY-RUN] Would write to {path}:\n{content[:100]}..."
        if detect_secret_text(content):
            return "Error: Refusing to write content that appears to contain a secret. Remove or redact secrets first."
        action = f"Write/overwrite file {path}"
        if not request_approval(action):
            return f"Action rejected: {action}"
        backup_file(safe_path)
        os.makedirs(os.path.dirname(safe_path) or ".", exist_ok=True)
        _atomic_write(safe_path, content)
        return f"Success: File written to {path}"
    except Exception as exc:
        return f"Error: {exc}"


def _run_git_command(cmd: list[str], workspace_path: str) -> tuple[int, str]:
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=workspace_path if os.path.exists(workspace_path) else None,
        timeout=30,
    )
    return res.returncode, (res.stdout + res.stderr).strip()


def _current_git_branch(workspace_path: str) -> str:
    code, output = _run_git_command(["git", "branch", "--show-current"], workspace_path)
    if code == 0 and output:
        return output.strip()
    return "unknown"


def _build_pr_draft(branch_name: str, status_text: str, diff_text: str, commit_text: str) -> str:
    changed_files = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git a/") and " b/" in line:
            changed_files.append(line.split(" b/", 1)[1])

    unique_files = list(dict.fromkeys(changed_files))
    file_list = ", ".join(unique_files[:8]) if unique_files else "none"
    summary_lines = [
        "Pull Request Draft",
        f"- Branch: {branch_name}",
        f"- Created: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%SZ')}",
        "",
        "Summary:",
        "This branch is ready for review and handoff.",
        "",
        "Changed files:",
        file_list,
        "",
        "Commit:",
        commit_text or "No commit recorded yet.",
        "",
        "Status snapshot:",
        status_text or "(clean)",
    ]
    return "\n".join(summary_lines).strip()


def execute_argv(argv: list[str], workspace_path: str, db_path: str, dry_run: bool = False) -> dict[str, Any]:
    if not argv:
        return {"tool": "execute_argv", "status": "error", "exit_code": 1, "output": "Error: Empty argv"}

    base_cmd = os.path.basename(argv[0]).lower()
    config = load_permissions_config()

    if base_cmd in config.get("command_denylist", []):
        return {
            "tool": "execute_argv",
            "status": "error",
            "exit_code": 1,
            "output": f"Permission Error: Command '{base_cmd}' is blocked by safety policy.",
        }

    if base_cmd not in config.get("command_allowlist", []):
        action = f"Run un-allowlisted command: {shlex.join(argv)}"
        if not request_approval(action):
            return {
                "tool": "execute_argv",
                "status": "error",
                "exit_code": 1,
                "output": f"Permission Error: Command rejected by human: {shlex.join(argv)}",
            }

    if dry_run:
        return {
            "tool": "execute_argv",
            "status": "success",
            "exit_code": 0,
            "output": f"[DRY-RUN] Would execute: {shlex.join(argv)}",
        }

    try:
        res = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            cwd=workspace_path if os.path.exists(workspace_path) else None,
            timeout=60,
        )
        output = res.stdout + res.stderr
        log_tool_invocation(
            db_path,
            shlex.join(argv),
            workspace_path,
            res.returncode,
            output,
            tool_name="execute_argv",
            metadata={"argv": argv},
        )
        return {
            "tool": "execute_argv",
            "status": "success" if res.returncode == 0 else "error",
            "exit_code": res.returncode,
            "output": output,
            "metadata": {"argv": argv},
        }
    except Exception as exc:
        log_tool_invocation(
            db_path,
            shlex.join(argv),
            workspace_path,
            1,
            str(exc),
            tool_name="execute_argv",
            metadata={"argv": argv},
        )
        return {"tool": "execute_argv", "status": "error", "exit_code": 1, "output": f"Execution Error: {exc}"}


def execute_shell(cmd_str: str, workspace_path: str, db_path: str, dry_run: bool = False) -> dict[str, Any]:
    try:
        parts = shlex.split(cmd_str)
    except ValueError as exc:
        return {"tool": "execute_shell", "status": "error", "exit_code": 1, "output": f"Error: Could not parse command arguments: {exc}"}
    return execute_argv(parts, workspace_path=workspace_path, db_path=db_path, dry_run=dry_run)


def command_template(name: str, args: list[str] | None = None) -> dict[str, Any]:
    """Expand a known-safe command template into argv without shell parsing."""
    template = COMMAND_TEMPLATES.get(name)
    if template is None:
        return {"status": "error", "error": f"Unknown command template: {name}"}
    values = list(template) + list(args or [])
    return {"status": "success", "template": name, "argv": values}


def registry_introspection(category: str | None = None) -> dict[str, Any]:
    tools = registry.list_tools()
    if category:
        tools = [tool for tool in tools if tool.get("category") == category]
    return {"api_version": TOOL_API_VERSION, "contract_version": CONTRACT_VERSION,
            "categories": sorted({tool["category"] for tool in tools}), "tools": tools}


def git_tool(action: str, args: list[str] | None = None, workspace_path: str = "") -> str:
    try:
        allowed_actions = {"status", "diff", "branch", "commit", "add", "log", "checkout", "workflow", "prepare_pr"}
        if action not in allowed_actions:
            return f"Error: Git action '{action}' is not allowed or supported."

        safe_args = []
        for arg in args or []:
            if any(token in arg for token in [";", "&&", "||", "|"]):
                return f"Error: Command injection character found in argument: {arg}"
            safe_args.append(arg)

        if action in {"status", "diff", "branch", "commit", "add", "log", "checkout"}:
            cmd = ["git", action, *safe_args]
            code, output = _run_git_command(cmd, workspace_path)
            return output or f"git {action} completed with exit code {code}."

        if action == "prepare_pr":
            branch_name = safe_args[0] if safe_args else _current_git_branch(workspace_path)
            status_code, status_text = _run_git_command(["git", "status", "--short", "--branch"], workspace_path)
            diff_code, diff_text = _run_git_command(["git", "diff", "--stat", "--patch", "--minimal"], workspace_path)
            commit_code, commit_text = _run_git_command(["git", "log", "-1", "--oneline"], workspace_path)
            if status_code != 0 and diff_code != 0 and commit_code != 0:
                return "Error: Unable to prepare PR draft from the current repository state."
            return _build_pr_draft(branch_name, status_text, diff_text, commit_text)

        if action == "workflow":
            branch_name = safe_args[0] if len(safe_args) >= 1 else f"redrum/{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}"
            commit_message = safe_args[1] if len(safe_args) >= 2 else f"chore: update {branch_name}"
            paths = safe_args[2:] if len(safe_args) > 2 else ["."]

            existing_branch_code, existing_branch_text = _run_git_command(["git", "branch", "--list", branch_name], workspace_path)
            if existing_branch_code != 0:
                return existing_branch_text or "Error: Unable to inspect branches."

            checkout_cmd = ["git", "checkout", branch_name] if existing_branch_text.strip() else ["git", "checkout", "-b", branch_name]
            checkout_code, checkout_text = _run_git_command(checkout_cmd, workspace_path)
            if checkout_code != 0:
                return checkout_text or f"Error: Unable to switch to branch '{branch_name}'."

            add_code, add_text = _run_git_command(["git", "add", *paths], workspace_path)
            if add_code != 0:
                return add_text or "Error: git add failed."

            commit_code, commit_text = _run_git_command(["git", "commit", "-m", commit_message], workspace_path)
            if commit_code != 0:
                return commit_text or "Error: git commit failed."

            status_code, status_text = _run_git_command(["git", "status", "--short", "--branch"], workspace_path)
            diff_code, diff_text = _run_git_command(["git", "diff", "HEAD~1..HEAD"], workspace_path)
            branch_text = _current_git_branch(workspace_path)
            report = [
                "Git workflow complete.",
                f"Branch: {branch_text}",
                f"Commit: {commit_text.strip() or commit_message}",
                "",
                _build_pr_draft(branch_text, status_text if status_code == 0 else "", diff_text if diff_code == 0 else "", commit_text),
            ]
            return "\n".join(report).strip()

        return f"Error: Git action '{action}' is not implemented."
    except Exception as exc:
        return f"Error executing git command: {exc}"


def dns_lookup(hostname: str) -> dict[str, Any]:
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, None)})
        return {"hostname": hostname, "addresses": addresses, "status": "success"}
    except Exception as exc:
        return {"hostname": hostname, "status": "error", "error": str(exc)}


def tcp_check(hostname: str, port: int, timeout: int = 5) -> dict[str, Any]:
    try:
        with socket.create_connection((hostname, port), timeout=timeout):
            return {"hostname": hostname, "port": port, "status": "success", "reachable": True}
    except Exception as exc:
        return {"hostname": hostname, "port": port, "status": "error", "reachable": False, "error": str(exc)}


def fetch_url(url: str, max_bytes: int = 20000) -> dict[str, Any]:
    config = load_permissions_config()
    if not config.get("allow_internet_fetch", True):
        return {"status": "error", "error": "Permission Error: Internet fetch is disabled in configuration."}
    if not _domain_allowed(url):
        return {"status": "error", "error": f"Permission Error: Domain not allowed: {urllib.parse.urlparse(url).hostname or url}"}

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "redrum-ai/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read(max_bytes)
            body = raw.decode("utf-8", errors="ignore")
            sha256 = hashlib.sha256(raw).hexdigest()
            return {
                "status": "success",
                "url": url,
                "content_hash": sha256,
                "content_type": response.headers.get_content_type(),
                "retrieved_at": datetime.now().astimezone().isoformat(),
                "body": body,
            }
    except Exception as exc:
        return {"status": "error", "url": url, "error": str(exc)}


def web_search(query: str, workspace_path: str = "") -> str:
    config = load_permissions_config()
    if not config.get("allow_internet_search", True):
        return "Permission Error: Internet search is disabled in configuration."

    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        if not _domain_allowed(url):
            return "Permission Error: Search domain not allowed."
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8")
            snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
            clean = [re.sub(r"<[^>]+>", "", snippet).strip() for snippet in snippets]
            return "\n".join(clean[:5]) or "No results found."
    except Exception as e:
        return f"Search failed: {e}"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any]
    permissions: list[str] = field(default_factory=list)
    category: str = "general"
    risk: str = "low"
    side_effects: list[str] = field(default_factory=list)
    version: str = CONTRACT_VERSION
    outputs: dict[str, Any] = field(default_factory=lambda: {"type": "object", "required": ["status", "exit_code", "output"]})


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        func: Callable[..., Any],
        permissions: list[str] | None = None,
        *,
        category: str = "general",
        risk: str = "low",
        side_effects: list[str] | None = None,
        version: str = CONTRACT_VERSION,
        outputs: dict[str, Any] | None = None,
    ):
        self._tools[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
            permissions=permissions or [],
            category=category,
            risk=risk,
            side_effects=side_effects or [],
            version=version,
            outputs=outputs or {"type": "object", "required": ["status", "exit_code", "output"]},
        )

    def get_tool(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [self._tool_to_dict(tool) for tool in self._tools.values()]

    def manifest(self) -> dict[str, Any]:
        return {"api_version": TOOL_API_VERSION, "tool_count": len(self._tools), "tools": self.list_tools()}

    @staticmethod
    def _tool_to_dict(tool: ToolSpec) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "permissions": tool.permissions,
            "category": tool.category,
            "risk": tool.risk,
            "side_effects": tool.side_effects,
            "version": tool.version,
            "inputs": tool.parameters,
            "outputs": tool.outputs,
        }


registry = ToolRegistry()

registry.register(
    name="read_file",
    description="Read contents of a text file inside an approved workspace path.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    func=read_file,
    permissions=["filesystem.read"],
    category="filesystem",
)

registry.register(
    name="inspect_file",
    description="Inspect a file and return metadata plus parsed content when possible.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_bytes": {"type": "integer"},
        },
        "required": ["path"],
    },
    func=inspect_file,
    permissions=["filesystem.read"],
    category="filesystem",
)

registry.register(
    name="write_file",
    description="Create or overwrite a file with approval before mutating.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["path", "content"],
    },
    func=write_file,
    permissions=["filesystem.write", "approval.required"],
    category="filesystem",
    risk="high",
    side_effects=["mutates files"],
)

registry.register(
    name="patch_file",
    description="Apply a targeted search-and-replace patch to a file with approval.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "search_text": {"type": "string"},
            "replace_text": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["path", "search_text", "replace_text"],
    },
    func=patch_file,
    permissions=["filesystem.write", "approval.required"],
    category="filesystem",
    risk="high",
    side_effects=["mutates files"],
)

registry.register(
    name="list_directory",
    description="List contents of a directory.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    func=list_directory,
    permissions=["filesystem.read"],
    category="filesystem",
)

registry.register(
    name="find_files",
    description="Recursively search for file names or content matches.",
    parameters={
        "type": "object",
        "properties": {
            "root": {"type": "string"},
            "query": {"type": "string"},
            "include_content": {"type": "boolean"},
            "max_results": {"type": "integer"},
        },
        "required": ["root", "query"],
    },
    func=find_files,
    permissions=["filesystem.read"],
    category="filesystem",
)

registry.register(
    name="diff_files",
    description="Show a unified diff between two files.",
    parameters={
        "type": "object",
        "properties": {
            "path_a": {"type": "string"},
            "path_b": {"type": "string"},
        },
        "required": ["path_a", "path_b"],
    },
    func=diff_files,
    permissions=["filesystem.read"],
    category="filesystem",
)

registry.register(
    name="execute_argv",
    description="Execute a structured argv command without shell interpolation.",
    parameters={
        "type": "object",
        "properties": {
            "argv": {"type": "array", "items": {"type": "string"}},
            "dry_run": {"type": "boolean"},
        },
        "required": ["argv"],
    },
    func=execute_argv,
    permissions=["process.execute", "approval.conditional"],
    category="process",
    risk="high",
    side_effects=["executes a subprocess"],
)

registry.register(
    name="execute_shell",
    description="Execute command line shell commands via safe argv parsing.",
    parameters={
        "type": "object",
        "properties": {"cmd_str": {"type": "string"}, "dry_run": {"type": "boolean"}},
        "required": ["cmd_str"],
    },
    func=execute_shell,
    permissions=["process.execute", "approval.conditional"],
    category="process",
    risk="high",
    side_effects=["executes a subprocess"],
)

registry.register(
    name="git_tool",
    description="Execute Git commands and helper workflows.",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "args": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["action"],
    },
    func=git_tool,
    permissions=["process.execute", "vcs.git"],
    category="vcs",
    risk="medium",
)

registry.register(
    name="web_search",
    description="Search the web for current events, news, or factual information.",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    func=web_search,
    permissions=["network.web"],
    category="network",
    risk="medium",
)

registry.register(
    name="web_fetch",
    description="Fetch a URL and return content plus a content hash.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "max_bytes": {"type": "integer"},
        },
        "required": ["url"],
    },
    func=fetch_url,
    permissions=["network.web"],
    category="network",
)

registry.register(
    name="dns_lookup",
    description="Resolve a hostname to IP addresses.",
    parameters={"type": "object", "properties": {"hostname": {"type": "string"}}, "required": ["hostname"]},
    func=dns_lookup,
    permissions=["network.local"],
    category="network",
)

registry.register(
    name="tcp_check",
    description="Check TCP reachability for a host and port.",
    parameters={
        "type": "object",
        "properties": {
            "hostname": {"type": "string"},
            "port": {"type": "integer"},
            "timeout": {"type": "integer"},
        },
        "required": ["hostname", "port"],
    },
    func=tcp_check,
    permissions=["network.local"],
    category="network",
)


def validate_tool_args(tool_name: str, args: dict) -> None:
    tool_entry = registry.get_tool(tool_name)
    if not tool_entry:
        raise ValueError(f"Tool '{tool_name}' not found in registry.")

    parameters = tool_entry.parameters or {}
    required = parameters.get("required", [])
    properties = parameters.get("properties", {})

    for req in required:
        if req not in args:
            raise TypeError(f"Missing required argument: '{req}'")

    for key, val in args.items():
        if key not in properties:
            raise ValueError(f"Unexpected argument: '{key}'")

        prop_def = properties[key]
        expected_type = prop_def.get("type")
        if expected_type == "string" and not isinstance(val, str):
            raise TypeError(f"Argument '{key}' must be a string (got {type(val).__name__})")
        if expected_type == "array" and not isinstance(val, list):
            raise TypeError(f"Argument '{key}' must be a list (got {type(val).__name__})")
        if expected_type == "object" and not isinstance(val, dict):
            raise TypeError(f"Argument '{key}' must be a dictionary (got {type(val).__name__})")
        if expected_type == "integer" and not isinstance(val, int):
            raise TypeError(f"Argument '{key}' must be an integer (got {type(val).__name__})")
        if expected_type == "boolean" and not isinstance(val, bool):
            raise TypeError(f"Argument '{key}' must be a boolean (got {type(val).__name__})")

    # Common safety constraints.  These are applied in addition to the JSON
    # schema so malformed paths and command injection attempts fail early.
    for key, val in args.items():
        if key in {"path", "path_a", "path_b", "root"} and ("\x00" in val or os.path.isabs(val) and val.startswith("/proc/")):
            raise ValueError(f"Unsafe path argument: '{key}'")
        if key in {"argv"} and any("\x00" in item for item in val):
            raise ValueError("NUL bytes are not valid command arguments")


def _invoke_function(tool_name: str, args: dict, workspace_path: str, db_path: str, dry_run: bool = False) -> Any:
    tool_entry = registry.get_tool(tool_name)
    if not tool_entry:
        return {"tool": tool_name, "status": "error", "exit_code": 1, "output": f"Error: Tool '{tool_name}' not found in registry."}

    func = tool_entry.func
    import inspect

    sig = inspect.signature(func)
    kwargs = {}
    for p_name in sig.parameters:
        if p_name in args:
            kwargs[p_name] = args[p_name]
        elif p_name == "workspace_path":
            kwargs["workspace_path"] = workspace_path
        elif p_name == "db_path":
            kwargs["db_path"] = db_path
        elif p_name == "dry_run":
            kwargs["dry_run"] = dry_run
    try:
        return func(**kwargs)
    except Exception as exc:
        return {"tool": tool_name, "status": "error", "exit_code": 1, "output": f"Execution Error: {exc}"}


def invoke_tool(tool_name: str, args: dict, workspace_path: str, db_path: str, dry_run: bool = False) -> dict[str, Any]:
    try:
        validate_tool_args(tool_name, args)
    except Exception as exc:
        return {
            "contract_version": CONTRACT_VERSION,
            "tool": tool_name,
            "status": "error",
            "exit_code": 1,
            "output": f"Schema Validation Error: {exc}",
            "metadata": {"tool_name": tool_name},
        }

    result = _invoke_function(tool_name, args, workspace_path, db_path, dry_run=dry_run)
    tool_entry = registry.get_tool(tool_name)
    metadata = {
        "tool_name": tool_name,
        "category": tool_entry.category if tool_entry else "unknown",
        "permissions": tool_entry.permissions if tool_entry else [],
    }

    if isinstance(result, dict):
        envelope = {
            "contract_version": CONTRACT_VERSION,
            "tool": tool_name,
            "status": result.get("status", "success" if result.get("exit_code", 0) == 0 else "error"),
            "exit_code": result.get("exit_code", 0),
            "output": result.get("output", ""),
            "metadata": {**metadata, **result.get("metadata", {})},
        }
        if "url" in result:
            envelope["metadata"]["url"] = result["url"]
        if "content_hash" in result:
            envelope["metadata"]["content_hash"] = result["content_hash"]
        envelope.setdefault("citations", [])
        envelope.setdefault("created_at", datetime.now().astimezone().isoformat())
        return envelope

    output = str(result)
    exit_code = 0 if not output.startswith("Error") and not output.startswith("Permission Error") else 1
    return {
        "contract_version": CONTRACT_VERSION,
        "tool": tool_name,
        "status": "success" if exit_code == 0 else "error",
        "exit_code": exit_code,
        "output": output,
        "metadata": metadata,
        "citations": [],
        "created_at": datetime.now().astimezone().isoformat(),
    }
