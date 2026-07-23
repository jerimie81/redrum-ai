# Privacy Review

## Memory
All `memory.db` content is stored strictly locally. No user memory is sent to cloud APIs without explicit user configuration or override.

## Logs
Logs stored in `~/.gemini/redrum-ai/logs` may contain prompt assemblies and error states. They do not ship externally.

## Diagnostics and Exports
The `bug-report` and `metrics` commands redact secrets by default before displaying them to the user. Users must manually review exported logs before sharing them with developers.
