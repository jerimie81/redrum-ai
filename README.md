# redrum-ai

`redrum-ai` is a local-first AI engineering partner for coding, project work, operations, research, and long-lived workspace memory.

It combines a guarded tool runtime, SQLite-backed memory, configurable language-model providers, structured task workflows, plugin capability negotiation, and an optional web interface. The system is designed to remain useful offline while making security, provenance, and human approval explicit parts of the architecture.

## Status

The project is suitable for local development, private workspaces, experimentation, and controlled operator environments. Remote multi-user deployment is an architectural direction, not a claim that the current web surface is safe to expose directly to the public internet.

## Capabilities

- Local chat, planning, execution, review, and task handoff workflows.
- Scoped SQLite memory for conversations, facts, preferences, tasks, summaries, entities, and relationships.
- Hybrid-style retrieval combining lexical matching, scope, recency, confidence, salience, and optional embeddings.
- Guarded filesystem, process, Git, network, and inspection tools.
- Versioned tool manifests, structured result envelopes, permission metadata, risk levels, and approval requirements.
- Secret/PII redaction, prompt-injection-resistant context wrappers, confirmation gates, and audit primitives.
- Session checkpoints, workspace isolation, memory export, retention, review, correction, and purge operations.
- Hardware scanning and constrained-edge recommendations for local model execution.
- Optional local and hosted model providers with offline fallback responses.
- Developer and SRE helpers for patches, LSP requests, TDD loops, CI diagnosis, incident timelines, runbooks, drift reports, and offline bundle manifests.

## Architecture

```text
CLI / web interface
        │
        ▼
Application orchestration and context assembly
        │
        ├── Model provider abstraction
        ├── Tool registry and policy checks
        ├── Task and session workflows
        └── Memory engine
                ├── SQLite relational memory
                ├── Scoped facts and provenance
                ├── Retrieval and citations
                └── Entities, relations, reviews, and checkpoints
```

The intended future remote architecture is federated: a remote control plane authenticates users and routes approved work to enrolled local agents. Local agents should remain the authority for sensitive filesystem, process, credential, and workspace operations.

## Installation

The recommended installer performs a hardware scan, selects a sensible default profile, creates a virtual environment, writes configuration, and supports offline fallback:

```bash
cd ~/.gemini/redrum-ai
./install.sh
```

Verify the installation:

```bash
.venv/bin/redrum-ai --version
.venv/bin/redrum-ai health --skip-ollama-check
```

Inspect hardware without installing:

```bash
./install.sh --hardware-only
```

For unattended installation:

```bash
./install.sh --non-interactive \
  --provider ollama \
  --model qwen2.5:7b
```

For a constrained-edge GGUF installation, provide the model explicitly. The
installer records the path and verifies whether `vmtouch` is available without
writing API secrets into the configuration:

```bash
./install.sh --non-interactive \
  --provider llama_server \
  --model gemma-2-2b \
  --api-base http://127.0.0.1:8080 \
  --model-path "$HOME/usb-ai/AI/models/gemma-2-2b-it-Q4_K_M.gguf"
```

To configure the OS memlock limit required to pin a large model in RAM, run
the privileged edge setup once, then start a new login session:

```bash
sudo ./setup_edge_optimizations.sh
```

The installer stores configuration and hardware information under:

```text
~/.config/redrum-ai/config.json
~/.config/redrum-ai/hardware.json
```

Manual editable installation is also supported when build tooling is available:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## Model providers

Supported providers are:

| Provider | Typical use |
| --- | --- |
| `ollama` | Local models through Ollama |
| `llama_cpp` | Direct GGUF inference through `llama-cpp-python` |
| `llama_server` | Local OpenAI-compatible llama-server endpoint |
| `openai` | OpenAI API |
| `openai_compatible` | LM Studio, vLLM, Groq, Together, and compatible endpoints |
| `anthropic` | Anthropic Messages API |
| `google_gemini` | Google Gemini API |

Examples:

```bash
./install.sh --non-interactive \
  --provider openai \
  --model gpt-4o-mini

./install.sh --non-interactive \
  --provider openai_compatible \
  --api-base http://127.0.0.1:1234/v1 \
  --model local-model
```

API keys are read from environment variables and are not written to the generated configuration:

```bash
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export GOOGLE_API_KEY="..."
```

Inspect the available provider presets and active model profiles:

```bash
redrum-ai model profiles
```

## Common workflows

Start interactive chat:

```bash
redrum-ai chat
```

Run a one-shot request:

```bash
redrum-ai "Summarize the current project state"
```

Use structured modes:

```bash
redrum-ai query --mode planning "Plan a safe database migration"
redrum-ai query --mode execution "Run the approved verification steps"
redrum-ai query --mode review "Review the implementation for regressions"
```

Create and manage tasks:

```bash
redrum-ai task intake "Audit the backup process" --priority high
redrum-ai task list
redrum-ai task update --id 1 --status needs_review
redrum-ai task handoff --id 1
```

Inspect tools and capabilities:

```bash
redrum-ai tools list
redrum-ai tools manifest
redrum-ai capabilities --host-api-version 1.0.0
```

Manage memory:

```bash
redrum-ai memory search "preferred language"
redrum-ai memory review --type knowledge
redrum-ai memory export
redrum-ai memory stats
redrum-ai memory consolidate
```

Inspect diagnostics:

```bash
redrum-ai health --skip-ollama-check
redrum-ai metrics
redrum-ai bug-report
```

## Memory model

Memory is scoped by project, workspace, and user where available. Durable records carry source information, confidence, salience, timestamps, and review state.

The repository supports distinct categories of durable state, including:

- Conversations and rolling summaries.
- User preferences and inferred signals.
- Facts and knowledge entries.
- Tasks, checkpoints, dependencies, and handoff state.
- Entities and relationships.
- Corrections, reviews, anti-patterns, and consolidation jobs.

Memory writes derived from tool output should be reviewed or explicitly confirmed before promotion to durable facts. Secrets and sensitive content are filtered before ingestion. Use workspace and project scopes carefully; they are the primary boundary against cross-project retrieval leakage.

Standalone memory operations are available through:

```bash
PYTHONPATH=src python -m redrum_memory DB_PATH search "query"
PYTHONPATH=src python -m redrum_memory DB_PATH export
```

## Security model

The system follows a local-first, least-privilege model:

- Paths are validated against approved workspace roots.
- Commands use structured argv execution where supported.
- Dangerous commands are denied by default or require approval.
- Mutating file operations use backups and atomic replacement.
- Tool results use structured envelopes and injection-resistant context wrappers.
- Secrets and PII are redacted before memory promotion and logging.
- Network fetches support domain allowlists and provenance hashes.
- Memory and tool operations include project/workspace scope metadata.
- Audit primitives support chained integrity digests.

Do not expose the current Express or development web surface directly to the public internet. A production remote deployment requires authentication, authorization, tenant isolation, encrypted transport, key management, rate limiting, replay protection, independent audit storage, and a local-agent job boundary.

## Configuration

Configuration may be supplied through the generated JSON file, `--config`, or environment variables. Common variables include:

| Variable | Purpose |
| --- | --- |
| `REDRUM_AI_CONFIG_FILE` | Configuration JSON path |
| `REDRUM_AI_DB_PATH` | SQLite database path |
| `REDRUM_AI_MODEL_PROVIDER` | Active provider |
| `REDRUM_AI_MODEL` | Active model name |
| `REDRUM_AI_API_BASE_URL` | Hosted or OpenAI-compatible API base |
| `REDRUM_AI_API_KEY_ENV` | Environment variable containing the API key |
| `REDRUM_AI_OLLAMA_URL` | Ollama endpoint |
| `REDRUM_AI_LLAMA_SERVER_URL` | llama-server endpoint |
| `REDRUM_AI_RUNTIME_PROFILE` | `standard`, `constrained-edge`, or `quality` |
| `REDRUM_AI_TIMEOUT` | Model request timeout in seconds |
| `REDRUM_AI_MAX_TOKENS` | Maximum generated tokens |
| `REDRUM_AI_CONFIG_DIR` | Configuration directory |
| `REDRUM_AI_STATE_DIR` | Logs and local state directory |
| `REDRUM_AI_CACHE_DIR` | Local cache directory |

## Project layout

```text
src/redrum_ai/       Application, CLI, tools, providers, security, and workflows
src/redrum_memory/   SQLite memory engine, migrations, retrieval, privacy, and CLI
tests/                Regression and property tests
docs/                 Architecture, security, privacy, UX, operations, and support docs
server.ts             Local web server
src/App.tsx           Web interface
install.sh            Hardware-aware installer
```

## Development

Run Python syntax checks:

```bash
python3 -m compileall -q src
```

Run tests when development dependencies are installed:

```bash
python -m pip install -e '.[dev]'
pytest
```

Run the web type check and build when Node dependencies are installed:

```bash
npm install
npm run lint
npm run build
```

Schema changes belong in `src/redrum_memory/migrations.py` and should remain idempotent. Provider changes should preserve the fallback provider behavior and avoid placing credentials in source files, configuration JSON, logs, prompts, or memory.

## Operational guidance

Before changing a production database or model configuration:

1. Back up the SQLite database.
2. Run `redrum-ai health --skip-ollama-check`.
3. Review `redrum-ai capabilities` and `redrum-ai tools manifest`.
4. Run the relevant migration, safety, and memory regression tests.
5. Validate the selected model provider independently.
6. Record rollback and recovery steps.

## License and contribution

Add the project license and contribution policy before distributing this repository beyond its current private or controlled-use context. Security issues should be reported privately rather than disclosed in public issues.
