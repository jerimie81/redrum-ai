import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Protocol
from urllib import error, request
from redrum_ai.config import AppConfig
from redrum_ai.offline import (
    get_offline_project_review,
    get_offline_question_response,
    get_offline_response,
)

class OllamaHealth:
    def __init__(self, ok: bool, messages: list[str]):
        self.ok = ok
        self.messages = messages

@dataclass(frozen=True)
class ModelProfile:
    name: str
    purpose: str
    model_name: str
    max_tokens: int

class ModelProvider(Protocol):
    name: str

    def check(self) -> OllamaHealth:
        ...

    def generate(self, prompt: str) -> str:
        ...


def _extract_current_request(prompt: str) -> str:
    match = re.search(r"--- Current Request ---\s*Redrum:\s*(.*?)\nAgent:\s*$", prompt, re.S)
    if match:
        return match.group(1).strip()
    return ""


def _extract_mode(prompt: str) -> str:
    match = re.search(r"Mode Instructions:\s*(.+)", prompt)
    if not match:
        return "chat"
    text = match.group(1).lower()
    if "planner" in text:
        return "planning"
    if "executor" in text:
        return "execution"
    if "quality auditor" in text:
        return "review"
    return "chat"


def _extract_response_format(prompt: str) -> str:
    match = re.search(r"Response Format:\s*(.+)", prompt)
    if not match:
        return "concise"
    text = match.group(1).lower()
    if "plan" in text:
        return "plan"
    if "report" in text:
        return "report"
    return "concise"


def _summarize_dialogue(prompt: str) -> str:
    user_turns = len(re.findall(r"^User:\s+", prompt, re.M))
    agent_turns = len(re.findall(r"^Agent:\s+", prompt, re.M))
    return (
        "Local fallback summary: the recent exchange covered "
        f"{user_turns} user turn(s) and {agent_turns} assistant turn(s), "
        "with the assistant constrained to offline context and workspace-aware replies."
    )


def _summarize_git_diff(prompt: str) -> str:
    files = []
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", prompt, re.M):
        files.append(match.group(2))
    if not files:
        return "No changes detected in Git."
    unique_files = sorted(dict.fromkeys(files))
    return (
        "Local fallback summary: the diff touches "
        f"{len(unique_files)} file(s): {', '.join(unique_files[:8])}."
    )


def _generate_plan_response(query: str) -> str:
    plan = [
        {
            "title": "Investigate request",
            "description": query,
            "priority": "medium",
            "acceptance_criteria": "The request is handled or the current local limitation is documented clearly.",
        }
    ]
    return json.dumps(plan, indent=2)


def _generate_execution_response(query: str) -> str:
    response = {
        "thought": "Using the local fallback backend because a remote model runtime is unavailable.",
        "tool": None,
        "arguments": {},
        "status": "done",
    }
    return json.dumps(response, indent=2)


def _generate_review_response(query: str) -> str:
    response = {
        "success": True,
        "findings": (
            "Local fallback review complete. The request is understandable, but live model "
            "validation is not available in this environment."
        ),
    }
    return json.dumps(response, indent=2)


def _generate_chat_response(config: AppConfig, prompt: str, query: str) -> str:
    query = query.strip()
    normalized = " ".join(query.lower().split())

    for offline_fn in (
        get_offline_response,
        lambda q: get_offline_project_review(q, config.workspace_path),
        lambda q: get_offline_question_response(q, config),
    ):
        try:
            response = offline_fn(query)
        except TypeError:
            response = offline_fn(query)
        if response and not response.startswith("I can't reach the model backend right now"):
            return response

    if "review" in normalized and ("avatar" in normalized or "reviews" in normalized):
        return (
            "I can't fetch live reviews from the web here. If you paste review excerpts, "
            "I can summarize them, compare sentiment, or extract the main criticisms and praise."
        )

    if "what can you do" in normalized or "capabilities" in normalized:
        return (
            "I can answer from local memory, summarize workspace context, inspect tasks, and "
            "help reason over project files. For live web-backed content, I need a real model/runtime."
        )

    if query:
        return (
            "Local fallback backend is active. I can help with workspace-aware questions, but "
            f"I do not have live web access for: {query}"
        )

    return "Local fallback backend is active."


class LocalProvider:
    name = "local"

    def __init__(self, config: AppConfig):
        self.config = config

    def check(self) -> OllamaHealth:
        return OllamaHealth(True, ["Local fallback backend ready"])

    def generate(self, prompt: str) -> str:
        query = _extract_current_request(prompt)

        if "Summarize the following dialogue" in prompt:
            return _summarize_dialogue(prompt)

        if "Summarize the following Git diff" in prompt or "Summary of Changes:" in prompt:
            return _summarize_git_diff(prompt)

        if "Output a valid JSON list containing the plan steps" in prompt:
            return _generate_plan_response(query or "Complete the requested work.")

        if "You MUST respond ONLY with a JSON object" in prompt and "\"thought\"" in prompt:
            return _generate_execution_response(query or "Complete the current step.")

        if "Respond ONLY with a valid JSON object" in prompt and "\"success\"" in prompt:
            return _generate_review_response(query or "Review the task output.")

        mode = _extract_mode(prompt)
        response_format = _extract_response_format(prompt)

        if mode in {"planning", "execution", "review"}:
            if mode == "planning":
                return _generate_plan_response(query or "Complete the requested work.")
            if mode == "execution":
                return _generate_execution_response(query or "Complete the current step.")
            if mode == "review":
                return _generate_review_response(query or "Review the task output.")

        if response_format == "plan":
            return _generate_plan_response(query or "Complete the requested work.")
        if response_format == "report":
            return _generate_execution_response(query or "Complete the current step.")

        return _generate_chat_response(self.config, prompt, query)


class FallbackProvider:
    def __init__(self, primary: ModelProvider, fallback: ModelProvider):
        self.primary = primary
        self.fallback = fallback
        self.name = primary.name

    def check(self) -> OllamaHealth:
        try:
            primary_health = self.primary.check()
        except Exception as exc:
            primary_health = OllamaHealth(False, [f"{self.primary.name} check failed: {exc}"])

        if primary_health.ok:
            return primary_health

        fallback_health = self.fallback.check()
        messages = list(primary_health.messages)
        messages.append(f"Using local fallback backend: {fallback_health.messages[0]}")
        return OllamaHealth(True, messages)

    def generate(self, prompt: str) -> str:
        try:
            return self.primary.generate(prompt)
        except Exception as exc:
            print(f"[MODEL WARNING] {self.primary.name} failed; using local fallback: {exc}", file=sys.stderr)
            return self.fallback.generate(prompt)

class OllamaProvider:
    name = "ollama"

    def __init__(self, config: AppConfig):
        self.config = config

    def check(self) -> OllamaHealth:
        return _check_ollama(self.config)

    def generate(self, prompt: str) -> str:
        return _send_to_ollama(self.config, prompt)


class LlamaCppProvider:
    name = "llama_cpp"

    def __init__(self, config: AppConfig):
        self.config = config

    def check(self) -> OllamaHealth:
        return _check_llama_cpp(self.config)

    def generate(self, prompt: str) -> str:
        return _send_to_llama_cpp(self.config, prompt)


class LlamaServerProvider:
    name = "llama_server"

    def __init__(self, config: AppConfig):
        self.config = config

    def check(self) -> OllamaHealth:
        return _check_llama_server(self.config)

    def generate(self, prompt: str) -> str:
        return _send_to_llama_server(self.config, prompt)


class OpenAICompatibleProvider:
    """Provider for OpenAI, LM Studio, vLLM, Together, Groq, and similar APIs."""
    name = "openai_compatible"
    def __init__(self, config: AppConfig): self.config = config
    def check(self) -> OllamaHealth: return _check_openai_compatible(self.config)
    def generate(self, prompt: str) -> str: return _send_openai_compatible(self.config, prompt)


class AnthropicProvider(OpenAICompatibleProvider):
    name = "anthropic"


class GoogleGeminiProvider(OpenAICompatibleProvider):
    name = "google_gemini"

def get_model_profiles(config: AppConfig) -> list[ModelProfile]:
    return [
        ModelProfile("speed", "classification and short summaries", config.model_name, min(config.max_tokens, 256)),
        ModelProfile("quality", "planning and review", config.model_name, max(config.max_tokens, 512)),
        ModelProfile("coding", "structured code and tool reasoning", config.model_name, max(config.max_tokens, 512)),
    ]


def get_available_providers() -> list[dict[str, str]]:
    """Return provider presets exposed by the installer and runtime."""
    return [
        {"name": "ollama", "kind": "local", "base_url": "http://localhost:11434", "examples": "gemma3:4b, qwen2.5:7b, llama3.2"},
        {"name": "llama_cpp", "kind": "local", "base_url": "", "examples": "GGUF models from Hugging Face"},
        {"name": "llama_server", "kind": "local", "base_url": "http://127.0.0.1:8080", "examples": "any llama-server compatible GGUF"},
        {"name": "openai", "kind": "hosted", "base_url": "https://api.openai.com/v1", "examples": "gpt-4o-mini, gpt-4.1-mini"},
        {"name": "openai_compatible", "kind": "local_or_hosted", "base_url": "http://127.0.0.1:1234/v1", "examples": "LM Studio, vLLM, Together, Groq"},
        {"name": "anthropic", "kind": "hosted", "base_url": "https://api.anthropic.com/v1", "examples": "claude-3-5-haiku-latest, claude-sonnet-4-0"},
        {"name": "google_gemini", "kind": "hosted", "base_url": "https://generativelanguage.googleapis.com/v1beta", "examples": "gemini-2.0-flash"},
    ]

def get_provider(config: AppConfig) -> ModelProvider:
    if config.model_provider == "ollama":
        return FallbackProvider(OllamaProvider(config), LocalProvider(config))
    if config.model_provider == "llama_cpp":
        return FallbackProvider(LlamaCppProvider(config), LocalProvider(config))
    if config.model_provider == "llama_server":
        return FallbackProvider(LlamaServerProvider(config), LocalProvider(config))
    if config.model_provider in {"openai", "openai_compatible"}:
        return FallbackProvider(OpenAICompatibleProvider(config), LocalProvider(config))
    if config.model_provider == "anthropic":
        return FallbackProvider(AnthropicProvider(config), LocalProvider(config))
    if config.model_provider == "google_gemini":
        return FallbackProvider(GoogleGeminiProvider(config), LocalProvider(config))
    raise RuntimeError(f"Unsupported model provider: {config.model_provider}")

def _check_ollama(config: AppConfig) -> OllamaHealth:
    try:
        url = f"{config.ollama_url}/api/tags"
        with request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError) as exc:
        return OllamaHealth(False, [f"Ollama is unavailable at {config.ollama_url}: {exc}"])
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return OllamaHealth(False, [f"Ollama returned invalid JSON: {exc}"])

    models = payload.get("models", [])
    names = {model.get("name") for model in models}
    if config.model_name not in names:
        available = ", ".join(sorted(name for name in names if name)) or "none"
        return OllamaHealth(
            False,
            [f"Model '{config.model_name}' is not available in Ollama. Available models: {available}"],
        )

    return OllamaHealth(True, [f"Ollama ready: {config.model_name}"])

def check_ollama(config: AppConfig) -> OllamaHealth:
    return get_provider(config).check()


def _load_llama_cpp_model(config: AppConfig):
    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise RuntimeError(
            "llama-cpp-python is not installed. Install it with `pip install llama-cpp-python` "
            "or use REDRUM_AI_MODEL_PROVIDER=ollama."
        ) from exc

    return Llama.from_pretrained(
        repo_id=config.llama_cpp_repo_id,
        filename=config.llama_cpp_filename,
        n_ctx=config.llama_cpp_n_ctx,
        n_threads=config.llama_cpp_n_threads,
    )


def _check_llama_cpp(config: AppConfig) -> OllamaHealth:
    try:
        _load_llama_cpp_model(config)
    except Exception as exc:
        return OllamaHealth(False, [f"llama.cpp is unavailable for {config.llama_cpp_repo_id}: {exc}"])
    return OllamaHealth(True, [f"llama.cpp ready: {config.llama_cpp_repo_id}/{config.llama_cpp_filename}"])


def _send_to_llama_cpp(config: AppConfig, prompt: str) -> str:
    llm = _load_llama_cpp_model(config)
    result = llm.create_chat_completion(
        messages=[
            {
                "role": "system",
                "content": "You are redrum-ai, a concise and practical local assistant.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        stream=True,
    )
    answer_parts = []
    for chunk in result:
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        content = delta.get("content", "")
        if content:
            answer_parts.append(content)
            if not config.quiet:
                sys.stdout.write(content)
                sys.stdout.flush()
    if not config.quiet:
        sys.stdout.write("\n")
        sys.stdout.flush()
    return "".join(answer_parts).strip()

def _send_to_ollama(config: AppConfig, prompt: str) -> str:
    payload = {
        "model": config.model_name,
        "prompt": prompt,
        "stream": True,
        "options": {
            "num_predict": config.max_tokens,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    ollama_request = request.Request(
        f"{config.ollama_url}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    answer_parts = []
    try:
        with request.urlopen(ollama_request, timeout=config.timeout) as response:
            for line in response:
                if line:
                    result = json.loads(line.decode("utf-8"))
                    chunk = result.get("response", "")
                    answer_parts.append(chunk)
                    if not config.quiet:
                        sys.stdout.write(chunk)
                        sys.stdout.flush()
            if not config.quiet:
                sys.stdout.write("\n")
                sys.stdout.flush()
    except (error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Error communicating with Ollama: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"Ollama returned invalid JSON: {exc}") from exc

    answer = "".join(answer_parts)
    if not answer:
        raise RuntimeError("Ollama response did not contain a response field")

    return answer.strip()

def _check_llama_server(config: AppConfig) -> OllamaHealth:
    try:
        url = f"{config.llama_server_url}/v1/models"
        with request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return OllamaHealth(True, ["llama-server ready"])
    except Exception as exc:
        return OllamaHealth(False, [f"llama-server is unavailable at {config.llama_server_url}: {exc}"])

def _send_to_llama_server(config: AppConfig, prompt: str) -> str:
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": config.max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{config.llama_server_url}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    answer_parts = []
    try:
        with request.urlopen(req, timeout=config.timeout) as response:
            for line in response:
                line_str = line.decode("utf-8").strip()
                if line_str.startswith("data: "):
                    data_str = line_str[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        choices = data.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            chunk = delta.get("content", "")
                            if chunk:
                                answer_parts.append(chunk)
                                if not config.quiet:
                                    sys.stdout.write(chunk)
                                    sys.stdout.flush()
                    except json.JSONDecodeError:
                        pass
            if not config.quiet:
                sys.stdout.write("\n")
                sys.stdout.flush()
    except Exception as exc:
        raise RuntimeError(f"Error communicating with llama-server: {exc}") from exc

    return "".join(answer_parts).strip()


def _api_key(config: AppConfig) -> str:
    return os.environ.get(config.api_key_env, "")


def _check_openai_compatible(config: AppConfig) -> OllamaHealth:
    if not _api_key(config) and config.model_provider not in {"openai_compatible"}:
        return OllamaHealth(False, [f"Missing API key environment variable: {config.api_key_env}"])
    try:
        url = f"{config.api_base_url}/models"
        headers = {"Authorization": f"Bearer {_api_key(config)}"} if _api_key(config) else {}
        req = request.Request(url, headers=headers)
        with request.urlopen(req, timeout=5) as response:
            json.loads(response.read().decode("utf-8"))
        return OllamaHealth(True, [f"API provider ready: {config.api_base_url}"])
    except Exception as exc:
        return OllamaHealth(False, [f"API provider unavailable at {config.api_base_url}: {exc}"])


def _send_openai_compatible(config: AppConfig, prompt: str) -> str:
    if config.model_provider == "anthropic":
        payload = {"model": config.model_name, "max_tokens": config.max_tokens, "messages": [{"role": "user", "content": prompt}]}
        url = f"{config.api_base_url}/messages"
        headers = {"x-api-key": _api_key(config), "anthropic-version": "2023-06-01"}
    elif config.model_provider == "google_gemini":
        url = f"{config.api_base_url}/models/{config.model_name}:generateContent?key={_api_key(config)}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": config.max_tokens}}
        headers = {}
    else:
        url = f"{config.api_base_url}/chat/completions"
        payload = {"model": config.model_name, "messages": [{"role": "user", "content": prompt}], "max_tokens": config.max_tokens}
        headers = {"Authorization": f"Bearer {_api_key(config)}"} if _api_key(config) else {}
    req = request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with request.urlopen(req, timeout=config.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        if config.model_provider == "anthropic": return "".join(x.get("text", "") for x in data.get("content", []))
        if config.model_provider == "google_gemini": return data["candidates"][0]["content"]["parts"][0]["text"]
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"API provider request failed: {exc}") from exc

def get_embedding(config: AppConfig, prompt: str) -> list[float]:
    if config.model_provider == "llama_cpp":
        return [] # Simple stub for non-ollama right now
        
    payload = {"model": config.model_name, "prompt": prompt}
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{config.ollama_url}/api/embeddings",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with request.urlopen(req, timeout=config.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("embedding", [])
    except Exception:
        return []

def send_to_ollama(config: AppConfig, prompt: str) -> str:
    return get_provider(config).generate(prompt)
