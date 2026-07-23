#!/usr/bin/env bash
set -euo pipefail

# redrum-ai installer.  It is intentionally dependency-light and works both
# online and on an air-gapped laptop.  Use --help for automation options.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROVIDER=""
MODEL=""
API_BASE=""
API_KEY_ENV=""
MODEL_PATH=""
PROFILE=""
CONFIG_DIR="${REDRUM_AI_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/redrum-ai}"
NONINTERACTIVE=0
HARDWARE_ONLY=0
SKIP_PIP=0
INSTALL_RUNTIME=0
SKIP_HEALTH=0

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Options:
  --provider NAME       ollama, llama_cpp, llama_server, openai, openai_compatible,
                        anthropic, google_gemini
  --model NAME          Model identifier (provider-specific)
  --model-path PATH     Local GGUF path for constrained-edge/llama runtimes
  --api-base URL        OpenAI-compatible/Anthropic/Gemini API base URL
  --api-key-env NAME    Environment variable containing the API key
  --profile NAME        standard, constrained-edge, quality
  --config-dir DIR      Configuration directory
  --non-interactive     Use defaults/arguments without prompts
  --hardware-only       Scan hardware and exit without installing
  --skip-pip            Skip Python package installation
  --install-runtime     Attempt optional runtime package installation
  --skip-health-check   Do not run the post-install health check
  -h, --help            Show this help

Examples:
  ./install.sh
  ./install.sh --non-interactive --provider ollama --model qwen2.5:7b
  ./install.sh --non-interactive --provider openai_compatible \
    --api-base http://127.0.0.1:1234/v1 --model local-model
  ./install.sh --hardware-only
EOF
}

while (($#)); do
  case "$1" in
    --provider) PROVIDER="$2"; shift 2 ;;
    --model) MODEL="$2"; shift 2 ;;
    --model-path) MODEL_PATH="$2"; shift 2 ;;
    --api-base) API_BASE="$2"; shift 2 ;;
    --api-key-env) API_KEY_ENV="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --config-dir) CONFIG_DIR="$2"; shift 2 ;;
    --non-interactive) NONINTERACTIVE=1; shift ;;
    --hardware-only) HARDWARE_ONLY=1; shift ;;
    --skip-pip) SKIP_PIP=1; shift ;;
    --install-runtime) INSTALL_RUNTIME=1; shift ;;
    --skip-health-check) SKIP_HEALTH=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

cd "$PROJECT_DIR"
mkdir -p "$CONFIG_DIR"

die() { echo "install.sh: $*" >&2; exit 2; }

valid_env_name() {
  [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]
}

valid_url() {
  "$PYTHON_BIN" - "$1" <<'PY'
import sys
from urllib.parse import urlparse
parsed = urlparse(sys.argv[1])
raise SystemExit(0 if parsed.scheme in {"http", "https"} and parsed.netloc else 1)
PY
}

discover_model_path() {
  local candidate
  local candidates=(
    "$MODEL_PATH"
    "${REDRUM_AI_MODEL_PATH:-}"
    "$HOME/.ollama/models/blobs/sha256-gemma-3-4b-it-Q4_0.gguf"
    "$HOME/usb-ai/AI/models/gemma-2-2b-it-Q4_K_M.gguf"
    "$HOME/models/gemma-2-2b-it-Q4_K_M.gguf"
  )
  for candidate in "${candidates[@]}"; do
    [[ -n "$candidate" && -f "$candidate" ]] && { realpath "$candidate"; return 0; }
  done
  return 1
}

scan_hardware() {
  PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -m redrum_ai.hardware
}

HARDWARE_JSON="$(scan_hardware)"
printf '%s\n' "$HARDWARE_JSON" > "$CONFIG_DIR/hardware.json"
echo "Hardware scan saved to $CONFIG_DIR/hardware.json"

if ((HARDWARE_ONLY)); then
  printf '%s\n' "$HARDWARE_JSON"
  exit 0
fi

recommendation() {
  PYTHONPATH="$PROJECT_DIR/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -c \
    'import json,sys; from redrum_ai.hardware import recommend_profile; print(json.dumps(recommend_profile(json.load(sys.stdin))))' \
    <<<"$HARDWARE_JSON"
}
RECOMMENDED="$(recommendation)"
DEFAULT_PROVIDER="$(printf '%s' "$RECOMMENDED" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["provider"])')"
DEFAULT_MODEL="$(printf '%s' "$RECOMMENDED" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["model"])')"
DEFAULT_PROFILE="$(printf '%s' "$RECOMMENDED" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["runtime_profile"])')"

if [[ -z "$PROVIDER" ]]; then PROVIDER="$DEFAULT_PROVIDER"; fi
if [[ -z "$MODEL" ]]; then MODEL="$DEFAULT_MODEL"; fi
if [[ -z "$PROFILE" ]]; then PROFILE="$DEFAULT_PROFILE"; fi

if [[ -t 0 && "$NONINTERACTIVE" == 0 ]]; then
  echo
  echo "Recommended: provider=$PROVIDER model=$MODEL profile=$PROFILE"
  read -r -p "Provider [ollama/llama_cpp/llama_server/openai/openai_compatible/anthropic/google_gemini] [$PROVIDER]: " answer
  [[ -n "$answer" ]] && PROVIDER="$answer"
  case "$PROVIDER" in
    ollama)
      read -r -p "Ollama model [$MODEL]: " answer; [[ -n "$answer" ]] && MODEL="$answer" ;;
    llama_cpp)
      read -r -p "GGUF model filename [$MODEL]: " answer; [[ -n "$answer" ]] && MODEL="$answer" ;;
    llama_server)
      read -r -p "Model name [$MODEL]: " answer; [[ -n "$answer" ]] && MODEL="$answer"
      read -r -p "llama-server URL [${API_BASE:-http://127.0.0.1:8080}]: " answer; [[ -n "$answer" ]] && API_BASE="$answer" ;;
    *)
      read -r -p "Model name [$MODEL]: " answer; [[ -n "$answer" ]] && MODEL="$answer"
      read -r -p "API base URL [${API_BASE:-provider default}]: " answer; [[ -n "$answer" ]] && API_BASE="$answer"
      read -r -p "API key environment variable [${API_KEY_ENV:-OPENAI_API_KEY}]: " answer; [[ -n "$answer" ]] && API_KEY_ENV="$answer" ;;
  esac
  read -r -p "Runtime profile [$PROFILE]: " answer; [[ -n "$answer" ]] && PROFILE="$answer"
fi

case "$PROVIDER" in
  ollama) [[ -z "$API_BASE" ]] && API_BASE="http://localhost:11434"; [[ -z "$API_KEY_ENV" ]] && API_KEY_ENV="" ;;
  llama_server) [[ -z "$API_BASE" ]] && API_BASE="http://127.0.0.1:8080"; [[ -z "$API_KEY_ENV" ]] && API_KEY_ENV="" ;;
  openai) [[ -z "$API_BASE" ]] && API_BASE="https://api.openai.com/v1"; [[ -z "$API_KEY_ENV" ]] && API_KEY_ENV="OPENAI_API_KEY" ;;
  anthropic) [[ -z "$API_BASE" ]] && API_BASE="https://api.anthropic.com/v1"; [[ -z "$API_KEY_ENV" ]] && API_KEY_ENV="ANTHROPIC_API_KEY" ;;
  google_gemini) [[ -z "$API_BASE" ]] && API_BASE="https://generativelanguage.googleapis.com/v1beta"; [[ -z "$API_KEY_ENV" ]] && API_KEY_ENV="GOOGLE_API_KEY" ;;
  openai_compatible) [[ -z "$API_BASE" ]] && API_BASE="http://127.0.0.1:1234/v1"; [[ -z "$API_KEY_ENV" ]] && API_KEY_ENV="OPENAI_API_KEY" ;;
  *) echo "Unsupported provider: $PROVIDER" >&2; exit 2 ;;
esac

case "$PROVIDER" in
  openai|openai_compatible|anthropic|google_gemini) [[ -z "$API_KEY_ENV" ]] && API_KEY_ENV="OPENAI_API_KEY" ;;
  *) API_KEY_ENV="" ;;
esac

case "$PROVIDER" in
  openai|openai_compatible|anthropic|google_gemini|llama_server)
    valid_url "$API_BASE" || die "invalid API base URL '$API_BASE'; expected an http(s) URL"
    ;;
esac
if [[ -n "$API_KEY_ENV" ]] && ! valid_env_name "$API_KEY_ENV"; then
  die "invalid API key environment variable '$API_KEY_ENV'; enter a variable name such as OPENAI_API_KEY, not the secret itself"
fi

if [[ -n "$MODEL_PATH" ]]; then
  MODEL_PATH="$(realpath -m "$MODEL_PATH")"
  [[ -f "$MODEL_PATH" ]] || die "model path does not exist: $MODEL_PATH"
elif [[ "$PROFILE" == "constrained-edge" && "$PROVIDER" =~ ^(llama_cpp|llama_server)$ ]]; then
  MODEL_PATH="$(discover_model_path || true)"
  [[ -n "$MODEL_PATH" ]] || echo "Warning: no local GGUF found; vmtouch and llama-server setup will remain pending."
fi

if ((SKIP_PIP == 0)); then
  "$PYTHON_BIN" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip --timeout 5 || echo "Offline: keeping installed pip."
  if python -c 'import setuptools.build_meta' >/dev/null 2>&1 && ! python -m pip install --no-build-isolation -e .; then
    echo "Packaged install unavailable; registering the local source tree."
    SITE_PACKAGES="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    printf '%s\n' "$PROJECT_DIR/src" > "$SITE_PACKAGES/redrum_ai_local.pth"
  elif ! python -c 'import setuptools.build_meta' >/dev/null 2>&1; then
    echo "Setuptools build backend unavailable; registering the local source tree."
    SITE_PACKAGES="$(python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
    printf '%s\n' "$PROJECT_DIR/src" > "$SITE_PACKAGES/redrum_ai_local.pth"
  fi
else
  VIRTUAL_ENV="$PROJECT_DIR/.venv"
  [[ -x "$VIRTUAL_ENV/bin/python" ]] || die "--skip-pip requires an existing .venv; remove --skip-pip or create the environment first"
  mkdir -p "$VIRTUAL_ENV/bin"
fi

if ((INSTALL_RUNTIME)); then
  case "$PROVIDER" in
    llama_cpp) python -m pip install llama-cpp-python || echo "Could not install llama-cpp-python; install it manually." ;;
    *) echo "Runtime package installation is not required for provider=$PROVIDER." ;;
  esac
fi

CONFIG_FILE="$CONFIG_DIR/config.json"
export CONFIG_FILE PROVIDER MODEL API_BASE API_KEY_ENV PROFILE PROJECT_DIR MODEL_PATH
"$PYTHON_BIN" - <<'PY'
import json, os
config = {
    "model_provider": os.environ["PROVIDER"],
    "model_name": os.environ["MODEL"],
    "api_base_url": os.environ["API_BASE"],
    "api_key_env": os.environ["API_KEY_ENV"],
    "runtime_profile": os.environ["PROFILE"],
    "edge_model_path": os.environ.get("MODEL_PATH", ""),
    "allow_web_access": True,
    "db_path": os.path.expanduser("~/.gemini/memory.db"),
    "ollama_url": os.environ["API_BASE"] if os.environ["PROVIDER"] == "ollama" else "http://localhost:11434",
    "llama_server_url": os.environ["API_BASE"] if os.environ["PROVIDER"] == "llama_server" else "http://127.0.0.1:8080",
}
with open(os.environ["CONFIG_FILE"], "w", encoding="utf-8") as handle:
    json.dump(config, handle, indent=2)
    handle.write("\n")
PY
chmod 600 "$CONFIG_FILE"

LAUNCHER="${VIRTUAL_ENV:-$PROJECT_DIR/.venv}/bin/redrum-ai"
mkdir -p "$(dirname "$LAUNCHER")"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
export REDRUM_AI_CONFIG_FILE="$(printf '%q' "$CONFIG_FILE")"
exec "${VIRTUAL_ENV:-$PROJECT_DIR/.venv}/bin/python" "$PROJECT_DIR/ai_partner.py" "\$@"
EOF
chmod +x "$LAUNCHER"

# Keep the convenient user-level command pointed at the generated executable,
# rather than at the repository helper whose mode may be lost by an archive
# or checkout operation.
USER_BIN_DIR="${REDRUM_AI_BIN_DIR:-$HOME/.local/bin}"
USER_COMMAND="$USER_BIN_DIR/redrum-ai"
mkdir -p "$USER_BIN_DIR"
cat > "$USER_COMMAND" <<EOF
#!/usr/bin/env bash
exec "$LAUNCHER" "\$@"
EOF
chmod +x "$USER_COMMAND"

echo "Installed redrum-ai"
echo "Provider: $PROVIDER"
echo "Model: $MODEL"
echo "Config: $CONFIG_FILE"
echo "Command: $USER_COMMAND"
if [[ -n "$MODEL_PATH" ]]; then echo "Local model: $MODEL_PATH"; fi
if command -v vmtouch >/dev/null 2>&1; then
  echo "vmtouch: available (run setup_edge_optimizations.sh as root to raise memlock and enable persistent locking)"
else
  echo "vmtouch: not installed (optional; install it for constrained-edge model locking)"
fi
if ((SKIP_HEALTH == 0)); then
  "$LAUNCHER" health --skip-ollama-check
fi
