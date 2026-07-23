# redrum-ai Architecture

## Decoupled Architecture

The project has been separated into two independent, standalone projects:
1. **redrum-memory (`src/redrum_memory`)**: Standalone, independent persistence and memory engine containing the database schemas, transactional contexts, user preferences, tasks, anti-pattern records, and LanceDB semantic search capabilities.
2. **redrum-ai (`src/redrum_ai`)**: Local CLI orchestrator, planner, agent/tool executor, and model wrapper that handles interaction logic, and imports memory capabilities from `redrum_memory`.

## Module Boundaries

### redrum-memory
1. `redrum_memory/database.py`: SQLite sessions, schemas, and persistence queries.
2. `redrum_memory/migrations.py`: Schema evolution only (automated & idempotent migrations).
3. `redrum_memory/memory_core.py`: Multi-tier episodic (SQLite) and semantic (LanceDB) memory management.

### redrum-ai
1. `cli.py`: Command definitions and argument parsing only.
2. `main.py`: Command routing and compatibility wrapper for current handlers.
3. `config.py`: Configuration loading, environment overrides, and validation.
4. `model.py`: Model provider abstraction and Ollama provider.
5. `prompt.py` and `context.py`: Prompt assembly and budgeting.
6. `tools.py`: Tool registry, permission metadata, validation, and execution.
7. `plugin.py`: Host-facing capability contract.
8. `telemetry.py`: Local metrics, events, and bug-report capture.

## Service Boundary Direction

Command handlers should call service-style functions. Service functions may depend on `database`, `model`, `tools`, and `telemetry`. Lower-level modules should not import `main.py` or depend on CLI parser details.

## Durable State Layout

1. Config: `~/.config/redrum-ai/` or explicit `--config`.
2. Runtime state: SQLite database from `REDRUM_AI_DB_PATH`.
3. Logs: `~/.local/state/redrum-ai/logs/` when packaged professionally.
4. Backups: sibling database backups before migrations and exports.
5. Cache: `~/.cache/redrum-ai/` for future model/provider metadata.

## Internal Request/Response Shapes

All automation-facing commands should return dictionaries that can be serialized as JSON with:

1. `status`: `success`, `error`, or domain-specific terminal state.
2. `data` or named payload such as `task`, `results`, or `report`.
3. `errors`: list of actionable error objects when applicable.
4. `metadata`: command version, project scope, and timestamps where useful.

## Architecture Decisions

### ADR-001: Local-First Runtime

The application remains local-first for v1. Ollama is the default provider, and no remote service is required for core operation.

### ADR-002: SQLite as Durable Memory

SQLite remains the v1 persistence layer because it is inspectable, portable, transactional, and sufficient for a single-user companion.

### ADR-003: Explicit Tool Registry

All actions available to the agent must be registered with schemas and permissions. Free-form shell execution is a compatibility feature and should move toward structured argv execution.

### ADR-004: JSON as Plugin Boundary

The professional plugin surface uses JSON-compatible command output and versioned capability negotiation instead of importing Python internals directly.
