import getpass
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_DB_PATH = os.path.expanduser("~/.gemini/memory.db")
DEFAULT_OLLAMA_API_URL = "http://localhost:11434"
DEFAULT_MODEL_NAME = "gemma-3-4b-it-Q4_0"
DEFAULT_MODEL_PROVIDER = "ollama"
DEFAULT_LLAMA_CPP_REPO_ID = "ggml-org/gemma-3-4b-it-GGUF"
DEFAULT_LLAMA_CPP_FILENAME = "gemma-3-4b-it-Q4_0.gguf"
DEFAULT_LLAMA_CPP_N_CTX = 4096
DEFAULT_LLAMA_CPP_N_THREADS = max(1, (os.cpu_count() or 4) - 1)
DEFAULT_LLAMA_SERVER_URL = "http://127.0.0.1:8080"
DEFAULT_API_BASE_URL = "https://api.openai.com/v1"

class ConfigError(RuntimeError):
    pass

@dataclass
class AppConfig:
    db_path: str = DEFAULT_DB_PATH
    ollama_url: str = DEFAULT_OLLAMA_API_URL
    model_name: str = DEFAULT_MODEL_NAME
    model_provider: str = DEFAULT_MODEL_PROVIDER
    llama_cpp_repo_id: str = DEFAULT_LLAMA_CPP_REPO_ID
    llama_cpp_filename: str = DEFAULT_LLAMA_CPP_FILENAME
    llama_cpp_n_ctx: int = DEFAULT_LLAMA_CPP_N_CTX
    llama_cpp_n_threads: int = DEFAULT_LLAMA_CPP_N_THREADS
    llama_server_url: str = DEFAULT_LLAMA_SERVER_URL
    api_base_url: str = DEFAULT_API_BASE_URL
    api_key_env: str = "OPENAI_API_KEY"
    timeout: int = 180
    max_tokens: int = 256
    verbose: bool = False
    output_json: bool = False
    quiet: bool = False
    no_color: bool = False
    runtime_profile: str = "standard"
    project_slug: str = "unknown"
    workspace_path: str = ""
    project_root: str = ""
    gemini_root: str = os.path.expanduser("~/.gemini")
    agent_config_path: str = ""
    agent_config_text: str = ""
    user_id: str = ""
    config_dir: str = ""
    state_dir: str = ""
    cache_dir: str = ""
    edge_model_path: str = ""
    allow_web_access: bool = True

def _default_dir(env_name: str, fallback: str) -> str:
    return os.environ.get(env_name, os.path.expanduser(fallback))


def _find_agent_config(start_dir: Path, stop_dir: Path | None = None) -> Path | None:
    current = start_dir.resolve()
    stop = stop_dir.resolve() if stop_dir else None

    while True:
        candidate = current / "AGENT.md"
        if candidate.exists():
            return candidate

        if stop is not None and current == stop:
            break

        if current.parent == current:
            break

        current = current.parent

    return None

def validate_config(config: AppConfig) -> None:
    supported = {"ollama", "llama_cpp", "llama_server", "openai", "openai_compatible", "anthropic", "google_gemini"}
    if config.model_provider not in supported:
        raise ConfigError(
            f"Unsupported model_provider '{config.model_provider}'. Supported providers: {', '.join(sorted(supported))}"
        )

    if config.model_provider == "ollama":
        parsed = urlparse(config.ollama_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(f"Invalid ollama_url '{config.ollama_url}'. Expected http(s) URL.")

    if config.model_provider == "llama_cpp":
        if not config.llama_cpp_repo_id:
            raise ConfigError("llama_cpp_repo_id must not be empty")
        if not config.llama_cpp_filename:
            raise ConfigError("llama_cpp_filename must not be empty")
        if config.llama_cpp_n_ctx <= 0:
            raise ConfigError("llama_cpp_n_ctx must be greater than zero")
        if config.llama_cpp_n_threads <= 0:
            raise ConfigError("llama_cpp_n_threads must be greater than zero")

    if config.model_provider in {"openai", "openai_compatible", "anthropic", "google_gemini"}:
        parsed = urlparse(config.api_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError(f"Invalid api_base_url '{config.api_base_url}'. Expected http(s) URL.")
        if not config.api_key_env:
            raise ConfigError("api_key_env must not be empty")

    if config.timeout <= 0:
        raise ConfigError("timeout must be greater than zero")
    if config.max_tokens <= 0:
        raise ConfigError("max_tokens must be greater than zero")

    db_parent = Path(config.db_path).expanduser().parent
    if not db_parent.exists():
        raise ConfigError(f"Database directory does not exist: {db_parent}")

def load_config(config_file: str | None = None) -> AppConfig:
    config = AppConfig()

    # 1. Load from config file if provided
    if config_file and os.path.exists(config_file):
        try:
            with open(config_file, "r") as f:
                data = json.load(f)
                if "db_path" in data:
                    config.db_path = str(data["db_path"])
                if "ollama_url" in data:
                    config.ollama_url = str(data["ollama_url"])
                if "model_name" in data:
                    config.model_name = str(data["model_name"])
                if "model_provider" in data:
                    config.model_provider = str(data["model_provider"])
                if "llama_cpp_repo_id" in data:
                    config.llama_cpp_repo_id = str(data["llama_cpp_repo_id"])
                if "llama_cpp_filename" in data:
                    config.llama_cpp_filename = str(data["llama_cpp_filename"])
                if "llama_cpp_n_ctx" in data:
                    config.llama_cpp_n_ctx = int(data["llama_cpp_n_ctx"])
                if "llama_cpp_n_threads" in data:
                    config.llama_cpp_n_threads = int(data["llama_cpp_n_threads"])
                if "llama_server_url" in data:
                    config.llama_server_url = str(data["llama_server_url"])
                if "api_base_url" in data:
                    config.api_base_url = str(data["api_base_url"])
                if "api_key_env" in data:
                    config.api_key_env = str(data["api_key_env"])
                if "timeout" in data:
                    config.timeout = int(data["timeout"])
                if "max_tokens" in data:
                    config.max_tokens = int(data["max_tokens"])
                if "project_slug" in data:
                    config.project_slug = str(data["project_slug"])
                if "runtime_profile" in data:
                    config.runtime_profile = str(data["runtime_profile"])
                if "edge_model_path" in data:
                    config.edge_model_path = str(data["edge_model_path"])
                if "allow_web_access" in data:
                    config.allow_web_access = bool(data["allow_web_access"])
        except Exception as exc:
            raise RuntimeError(f"Failed to parse config file: {exc}") from exc

    # 2. Override with env vars
    config.db_path = os.environ.get("REDRUM_AI_DB_PATH", config.db_path)
    config.ollama_url = os.environ.get("REDRUM_AI_OLLAMA_URL", config.ollama_url).rstrip("/")
    config.model_name = os.environ.get("REDRUM_AI_MODEL", config.model_name)
    config.model_provider = os.environ.get("REDRUM_AI_MODEL_PROVIDER", config.model_provider)
    config.llama_cpp_repo_id = os.environ.get("REDRUM_AI_LLAMA_CPP_REPO_ID", config.llama_cpp_repo_id)
    config.llama_cpp_filename = os.environ.get("REDRUM_AI_LLAMA_CPP_FILENAME", config.llama_cpp_filename)
    config.llama_server_url = os.environ.get("REDRUM_AI_LLAMA_SERVER_URL", config.llama_server_url).rstrip("/")
    config.runtime_profile = os.environ.get("REDRUM_AI_RUNTIME_PROFILE", config.runtime_profile)
    config.edge_model_path = os.environ.get("REDRUM_AI_MODEL_PATH", config.edge_model_path)
    web_env = os.environ.get("REDRUM_AI_ALLOW_WEB_ACCESS")
    if web_env is not None:
        config.allow_web_access = web_env.strip().lower() not in {"0", "false", "no", "off"}
    config.api_base_url = os.environ.get("REDRUM_AI_API_BASE_URL", config.api_base_url).rstrip("/")
    config.api_key_env = os.environ.get("REDRUM_AI_API_KEY_ENV", config.api_key_env)
    
    timeout_env = os.environ.get("REDRUM_AI_TIMEOUT")
    if timeout_env:
        config.timeout = int(timeout_env)

    max_tokens_env = os.environ.get("REDRUM_AI_MAX_TOKENS")
    if max_tokens_env:
        config.max_tokens = int(max_tokens_env)

    llama_cpp_n_ctx_env = os.environ.get("REDRUM_AI_LLAMA_CPP_N_CTX")
    if llama_cpp_n_ctx_env:
        config.llama_cpp_n_ctx = int(llama_cpp_n_ctx_env)

    llama_cpp_n_threads_env = os.environ.get("REDRUM_AI_LLAMA_CPP_N_THREADS")
    if llama_cpp_n_threads_env:
        config.llama_cpp_n_threads = int(llama_cpp_n_threads_env)

    # 3. Detect scoping details
    config.user_id = getpass.getuser()
    config.project_root = os.getcwd()
    config.workspace_path = config.project_root
    config.gemini_root = _default_dir("REDRUM_AI_GEMINI_ROOT", "~/.gemini")
    config.config_dir = _default_dir("REDRUM_AI_CONFIG_DIR", "~/.config/redrum-ai")
    config.state_dir = _default_dir("REDRUM_AI_STATE_DIR", "~/.local/state/redrum-ai")
    config.cache_dir = _default_dir("REDRUM_AI_CACHE_DIR", "~/.cache/redrum-ai")

    agent_path = _find_agent_config(Path(config.project_root), Path(config.gemini_root))
    if agent_path:
        config.agent_config_path = str(agent_path)
        try:
            config.agent_config_text = agent_path.read_text(encoding="utf-8", errors="ignore").strip()
        except OSError:
            config.agent_config_text = ""

    # Look for manifest.json in current directory or parent directory to find project_slug
    manifest_path = os.path.join(config.project_root, "manifest.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r") as f:
                manifest_data = json.load(f)
                config.project_slug = manifest_data.get("project_slug", "unknown")
        except Exception:
            pass

    if config_file is None:
        configured_file = os.environ.get("REDRUM_AI_CONFIG_FILE")
        if configured_file:
            return load_config(configured_file)
    validate_config(config)
    return config
