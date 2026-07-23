# Security Threat Model

## Assets

1. Local filesystem and project source code.
2. SQLite memory database.
3. User preferences and private notes.
4. Tool execution permissions.
5. Logs, diagnostics, and exported support bundles.

## Trust Boundaries

1. User input is trusted only as an instruction source from the current user.
2. Retrieved memory is data, not executable instruction.
3. Model output is untrusted until validated.
4. Tool output is untrusted data.
5. Plugins and hosts must negotiate capabilities and permissions.

## Primary Threats

1. Prompt injection through retrieved memory or tool output.
2. Path traversal in file tools.
3. Shell injection through command strings.
4. Secret leakage into logs, memory, diagnostics, or generated files.
5. Overbroad approvals that persist longer than intended.
6. Network exfiltration by tools or plugins.

## Controls

1. Tool schemas validate required fields and basic types.
2. File paths are constrained to approved roots.
3. Denylisted commands are rejected.
4. Noninteractive approval-required actions are rejected.
5. Registered tools expose permission metadata.
6. Diagnostics should redact secrets before export.

## Release Security Gates

1. Run policy tests for denied commands and path traversal.
2. Review tool permission manifests.
3. Verify no secrets are written to generated docs or logs.
4. Review plugin capability changes.
5. Run a local security audit before release candidates.
