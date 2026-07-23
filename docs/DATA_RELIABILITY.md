# Data Reliability Plan

## Core Entities

1. `conversations`: raw user, agent, and system turns.
2. `conversation_summaries`: compact summaries of older turns.
3. `knowledge_bases`: long-term facts and sourced notes.
4. `user_preferences`: stable user preference facts.
5. `tasks`: structured work items and handoff notes.
6. `command_history`: shell/tool execution audit.
7. `work_events`: structured local telemetry.

## Migration Rules

1. Additive migrations are preferred.
2. Every migration must be deterministic and idempotent where practical.
3. Production migrations should run after a database backup.
4. Old database fixtures must be kept for migration tests.

## Backup and Export Policy

1. Users can export memory and tasks to JSON.
2. Database backups should be created before destructive schema changes.
3. Encrypted backups are planned for professional release hardening.

## Memory Review Policy

1. Users must be able to inspect memory records by ID.
2. Users must be able to delete incorrect or stale records.
3. Future memory confidence fields should distinguish confirmed facts from inferred facts.
4. Retention policies should differ for raw turns, summaries, tasks, and long-term facts.

## Integrity Checks

Health checks should verify required tables, required columns, readable database path, writable database directory, and SQLite integrity where practical.
