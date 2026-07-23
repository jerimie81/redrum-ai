from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from redrum_ai import __version__
from redrum_ai.tools import registry

PLUGIN_API_VERSION = "1.0.0"
PLUGIN_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class Capability:
    name: str
    version: str
    command: str
    description: str


CAPABILITIES = [
    Capability("chat", "1.0.0", "query", "Single-turn local assistant interaction."),
    Capability("planning", "1.0.0", "query --mode planning", "Turn goals into ordered plans."),
    Capability("execution", "1.0.0", "query --mode execution", "Run guarded plan/act/observe loops."),
    Capability("review", "1.0.0", "query --mode review", "Review completed work and tool output."),
    Capability("memory.search", "1.0.0", "memory search", "Search scoped long-term memory."),
    Capability("memory.insert", "1.0.0", "memory insert", "Insert sourced long-term memory."),
    Capability("memory.review", "1.0.0", "memory review", "Review stored memory records by ID and source."),
    Capability("memory.export", "1.0.0", "memory export", "Export scoped memory, tasks, and summaries."),
    Capability("memory.delete", "1.0.0", "memory delete", "Delete an incorrect or stale memory record."),
    Capability("memory.stats", "1.0.0", "memory stats", "Summarize memory health and counts for the current scope."),
    Capability("memory.consolidate", "1.0.0", "memory consolidate", "Deduplicate and consolidate durable memory records."),
    Capability("model.profiles", "1.0.0", "model profiles", "Inspect configured model profiles."),
    Capability("task.intake", "1.0.0", "task intake", "Convert a request into a structured task."),
    Capability("task.list", "1.0.0", "task list", "List active or completed tasks."),
    Capability("task.handoff", "1.0.0", "task handoff", "Emit a ready-for-handoff task report."),
    Capability("tools.list", "1.0.0", "tools list", "List registered tools with categories and risk levels."),
    Capability("tools.manifest", "1.0.0", "tools manifest", "Print the full tool manifest."),
    Capability("tools.invoke", "1.0.0", "tool", "Invoke registered guarded tools."),
    Capability("observability.metrics", "1.0.0", "metrics", "Report local usage and failure metrics."),
    Capability("observability.bug_report", "1.0.0", "bug-report", "Capture reproducible diagnostics."),
    Capability("bootstrap", "1.0.0", "bootstrap", "Run first-run onboarding and seed memory."),
    Capability("tools.route", "1.0.0", "tool-router", "Select the smallest safe tool set for an intent."),
    Capability("memory.hybrid_search", "1.0.0", "memory search", "Fuse lexical, semantic, recency, and scope ranking."),
    Capability("memory.graph", "1.0.0", "memory graph", "Store and query scoped entities and relationships."),
    Capability("session.restore", "1.0.0", "session restore", "Checkpoint and restore interrupted work."),
    Capability("security.dlp", "1.0.0", "security scan", "Redact secrets and PII before context or memory writes."),
    Capability("security.audit", "1.0.0", "audit", "Produce chained tamper-evident local audit records."),
    Capability("developer.lsp", "1.0.0", "lsp", "Request diagnostics and navigation from language servers."),
    Capability("developer.patch", "1.0.0", "patch", "Generate and validate deterministic unified patches."),
    Capability("sre.forensics", "1.0.0", "forensics", "Build incident timelines from local logs."),
    Capability("sre.runbook", "1.0.0", "runbook", "Validate human-confirmed runbooks with rollback requirements."),
    Capability("offline.bundle", "1.0.0", "bundle", "Describe self-contained offline deployment artifacts."),
]


def build_contract() -> dict[str, Any]:
    return {
        "manifest_version": PLUGIN_CONTRACT_VERSION,
        "api_version": PLUGIN_API_VERSION,
        "companion_version": __version__,
        "auth": {
            "type": "local_process",
            "external_services": ["huggingface"],
            "required": False,
            "notes": "No remote plugin authentication is required. The local runtime downloads a GGUF model from Hugging Face on first use if needed.",
        },
        "capabilities": [asdict(capability) for capability in CAPABILITIES],
        "negotiable_features": {
            "response_formats": ["concise", "plan", "report"],
            "modes": ["chat", "planning", "execution", "review"],
            "task_statuses": ["backlog", "ready", "in_progress", "blocked", "needs_review", "done"],
        },
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
                "permissions": tool.get("permissions", []),
                "returns": {
                    "type": "object|string",
                    "description": "Tool-specific result. CLI wrapper normalizes results to exit_code/output JSON.",
                },
                "version": tool.get("version", "1.0"),
                "inputs": tool.get("inputs", tool["parameters"]),
                "outputs": tool.get("outputs", {"type": "object"}),
            }
            for tool in registry.list_tools()
        ],
        "commands": {
            "capabilities": {"args": ["--host-api-version"], "output": "contract JSON"},
            "health": {"args": ["--skip-ollama-check"], "output": "diagnostic JSON"},
            "tool": {"args": ["--name", "--args"], "output": "tool result JSON"},
            "tools": {"args": ["list|manifest"], "output": "tool manifest JSON"},
            "memory": {"args": ["search|insert|review|export|delete|stats|consolidate|reflect"], "output": "memory JSON"},
            "model": {"args": ["profiles"], "output": "model profile JSON"},
            "task": {"args": ["intake|list|update|handoff"], "output": "task JSON"},
            "metrics": {"args": [], "output": "metrics JSON"},
            "bug-report": {"args": [], "output": "diagnostic JSON"},
            "bootstrap": {"args": [], "output": "onboarding report"},
        },
    }


def negotiate_capabilities(host_api_version: str | None = None) -> dict[str, Any]:
    contract = build_contract()
    host_api_version = host_api_version or PLUGIN_API_VERSION
    compatible = host_api_version.split(".")[0] == PLUGIN_API_VERSION.split(".")[0]
    contract["negotiation"] = {
        "host_api_version": host_api_version,
        "compatible": compatible,
        "reason": "major versions match" if compatible else "host and companion API major versions differ",
    }
    return contract
