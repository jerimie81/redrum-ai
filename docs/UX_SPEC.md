# redrum-ai UX Specification

## Command Taxonomy

1. `query`: direct assistant interaction.
2. `capabilities`: plugin contract and negotiation.
3. `health`: readiness and dependency checks.
4. `tool`: direct guarded tool invocation.
5. `memory`: long-term knowledge operations.
6. `task`: task lifecycle and handoff.
7. `metrics`: local usage and failure metrics.
8. `bug-report`: reproducible diagnostic bundle.
9. `bootstrap`: first-run onboarding.

## Output Modes

1. Human mode is concise and readable.
2. JSON mode is stable for scripts and host integrations.
3. Quiet mode suppresses nonessential status text.
4. No-color mode is available for terminals and log captures.

## Error Message Standard

Each professional error should include:

1. Cause: what failed.
2. Impact: what could not continue.
3. Next action: exact command or setting to fix it.

## TTY Policy

Interactive prompts are allowed only when stdin is a TTY. Noninteractive sessions must reject approval-required actions with an explicit error.

## Day-One Workflow

1. `redrum-ai health --skip-ollama-check`
2. `redrum-ai bootstrap`
3. `redrum-ai task intake "Describe the first concrete task"`
4. `redrum-ai --mode planning "Plan that task"`
5. `redrum-ai task handoff`

## Text UI Direction

A future TUI should expose four panes: sessions, active tasks, memory search/review, and diagnostics. The CLI remains the source of truth for automation.
