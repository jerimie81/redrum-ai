# redrum-ai Product Requirements

## Product Promise

`redrum-ai` is a local, privacy-respecting AI work partner that helps Redrum plan, execute, review, remember, and hand off technical work with explicit safety boundaries and durable project memory.

## Primary Personas

1. Solo technical operator: uses the assistant for coding, operations, troubleshooting, and repeatable task execution.
2. Project director: uses structured tasks, plans, status notes, and handoff reports to keep work moving across sessions.
3. Security-conscious power user: needs local-first execution, inspectable memory, explicit approvals, and reproducible diagnostics.

## Core Workflows

1. Chat: ask a direct question and receive a concise answer.
2. Planning: turn a goal into ordered tasks with acceptance criteria.
3. Execution: run a guarded plan/act/observe loop using registered tools.
4. Review: audit tool outputs, diffs, and completion criteria.
5. Handoff: summarize status, evidence, remaining risk, and next action.
6. Memory: store, search, export, review, and delete scoped knowledge.

## v1 Must-Haves

1. Installable CLI with stable command taxonomy.
2. SQLite-backed memory with migrations and backup guidance.
3. Plugin-facing capability contract with version negotiation.
4. Tool registry with typed schemas, permissions, and safety policy.
5. Local model runtime abstraction with Ollama support.
6. Structured task intake, update, list, and handoff.
7. JSON automation output for core commands.
8. Diagnostics, metrics, and bug-report export.
9. Product, architecture, security, data, and operations documentation.
10. Deterministic tests for non-model-dependent behavior.

## Non-Goals for v1

1. Unattended destructive system administration.
2. Remote hosted memory or telemetry.
3. Multi-user server deployment.
4. Arbitrary plugin execution without a permission manifest.
5. Guaranteed correctness of model-generated plans without review.

## Success Metrics

1. Task completion rate for real pilot tasks.
2. Percentage of blocked tasks with actionable next steps.
3. User intervention rate per executed task.
4. Failed tool-call rate.
5. Recovery rate after interrupted sessions.
6. Median startup, retrieval, and prompt assembly latency.

## v1 Acceptance Criteria

1. A fresh install can run `health`, `bootstrap`, `task intake`, `memory insert`, `memory search`, and `bug-report`.
2. Every mutating tool has an explicit permission scope and dry-run behavior.
3. Memory can be exported, reviewed, and deleted by ID.
4. Model runtime failures return actionable errors.
5. A real-task pilot produces a gap list and no unresolved critical safety findings.
