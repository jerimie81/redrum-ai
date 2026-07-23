# Security Review

## Tools
All shell and file-modifying tools are sandboxed and require explicit argument allowlists. Path traversal is mitigated by enforcing absolute paths within `workspace_path` bounds.

## Approvals
Destructive actions (e.g., `git push --force`, `rm -rf`) require an explicit user prompt.

## Plugins
Plugins run with least privilege. The capability negotiation protocol requires strict schema validation before any payload is parsed.

## Model Output
Model output is treated as untrusted and is validated before execution.
