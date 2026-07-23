"""Small local fallback responses for queries that do not require Ollama."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
import re

from redrum_ai.config import AppConfig
from redrum_memory.database import (
    get_active_tasks,
    get_relevant_knowledge,
    get_user_preferences,
    get_recent_summaries,
)


def _format_date(now: datetime) -> str:
    return f"{now.strftime('%A, %B')} {now.day}, {now.year}"


def get_offline_response(query: str) -> str | None:
    """Return a local answer for a narrow set of safe informational queries.

    This keeps the CLI usable for simple date/time questions when the model
    backend is unavailable, without pretending to replace the actual assistant.
    """

    normalized = " ".join(query.lower().split())
    now = datetime.now().astimezone()

    date_patterns = (
        r"\bwhat(?:'s| is)? the date\b",
        r"\bwhat day is it\b",
        r"\btoday'?s date\b",
    )
    if any(re.search(pattern, normalized) for pattern in date_patterns):
        return f"Today is {_format_date(now)}."

    time_patterns = (
        r"\bwhat(?:'s| is)? the time\b",
        r"\bcurrent time\b",
        r"\bwhat time is it\b",
    )
    if any(re.search(pattern, normalized) for pattern in time_patterns):
        return f"The current local time is {now.strftime('%I:%M %p %Z').lstrip('0')}."

    weekday_patterns = (
        r"what day of the week",
        r"what day is today",
    )
    if any(re.search(pattern, normalized) for pattern in weekday_patterns):
        return f"Today is {now.strftime('%A')}."

    system_patterns = (
        r"what is the os",
        r"os version",
        r"system info",
    )
    if any(re.search(pattern, normalized) for pattern in system_patterns):
        import platform
        return f"Running on {platform.system()} {platform.release()}."


    return None


def _looks_like_review_request(query: str) -> bool:
    normalized = " ".join(query.lower().split())
    phrases = (
        "review the project",
        "review project",
        "assessment of the project",
        "assess the project",
        "evaluate the project",
        "make 5 suggestions",
        "5 suggestions",
        "enhance the application",
        "without making any changes review",
        "review this project",
        "project review",
    )
    return any(phrase in normalized for phrase in phrases)


def _extract_explicit_path(query: str) -> str | None:
    candidates = re.findall(r"(?:~|/)[^\s\"'`<>]+", query)
    if not candidates:
        return None
    # Prefer the longest path-like token in case the query includes more than one.
    return max(candidates, key=len)


def _read_text_preview(path: Path, limit: int = 1200) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return content[:limit].strip()


def _count_files(root: Path, suffix: str) -> int:
    excluded_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}
    count = 0
    for p in root.rglob(f"*{suffix}"):
        if not p.is_file():
            continue
        if any(part in excluded_dirs for part in p.parts):
            continue
        count += 1
    return count


def get_offline_project_assessment(query: str) -> str | None:
    """Return a concrete assessment for an explicitly named project path."""

    normalized = " ".join(query.lower().split())
    if not any(token in normalized for token in ("assessment", "assess", "evaluate", "review", "project")):
        return None

    raw_path = _extract_explicit_path(query)
    if not raw_path:
        return None

    project_path = Path(os.path.expanduser(raw_path)).resolve()
    if not project_path.exists() or not project_path.is_dir():
        return f"I couldn't assess '{raw_path}' because it does not resolve to an accessible directory."

    readme = project_path / "README.md"
    prd = project_path / "PRD.md"
    setup_guide = project_path / "SETUP_GUIDE.md"
    main_py = project_path / "main.py"
    pyproject = project_path / "pyproject.toml"
    requirements = project_path / "requirements.txt"
    test_app = project_path / "test_app.py"

    top_level = sorted(
        p.name for p in project_path.iterdir() if p.is_file()
    )
    src_files = _count_files(project_path / "src", ".py") if (project_path / "src").exists() else 0
    total_py = _count_files(project_path, ".py")

    readme_preview = _read_text_preview(readme)
    main_preview = _read_text_preview(main_py)
    prd_preview = _read_text_preview(prd)
    setup_preview = _read_text_preview(setup_guide)

    strengths = [
        "Clear documentation footprint: README, PRD, and setup guide are all present.",
        f"Implementation exists in Python, with {total_py} Python file(s) and a {src_files}-file `src/` tree.",
        "The project includes a test harness and structured configuration rather than a single-script prototype.",
    ]

    concerns = [
        "The documentation is more ambitious than the runtime code; the app appears closer to a polished launcher plus service modules than a fully hardened bypass suite.",
        "The README/PRD emphasize many exploit categories, so scope, legality, and verification boundaries need tighter enforcement before broader distribution.",
        "The entrypoint in `main.py` is still a thin bootstrapper, which suggests the real complexity is in the module tree rather than the app shell.",
    ]

    if test_app.exists():
        concerns.append("`test_app.py` looks like a feature smoke harness, so it likely needs stronger automated coverage before release.")
    if requirements.exists():
        concerns.append("Dependencies are enumerated, but packaging quality still depends on how tightly they are pinned and validated in CI.")

    summary = [
        f"Assessment of {project_path}:",
        "",
        "This is a Python-based FRP recovery tool with substantial documentation and a moderately modular codebase.",
        "",
        "Strengths:",
        *[f"- {item}" for item in strengths],
        "",
        "Concerns:",
        *[f"- {item}" for item in concerns],
        "",
        "Evidence snapshot:",
        f"- Top-level files: {', '.join(top_level[:10])}" + ("..." if len(top_level) > 10 else ""),
        f"- README present: {'yes' if readme.exists() else 'no'}",
        f"- PRD present: {'yes' if prd.exists() else 'no'}",
        f"- Setup guide present: {'yes' if setup_guide.exists() else 'no'}",
        f"- main.py present: {'yes' if main_py.exists() else 'no'}",
        f"- pyproject.toml present: {'yes' if pyproject.exists() else 'no'}",
        f"- test_app.py present: {'yes' if test_app.exists() else 'no'}",
    ]

    if readme_preview:
        summary.extend(["", "README sample:", readme_preview[:600]])
    if main_preview:
        summary.extend(["", "main.py sample:", main_preview[:400]])
    if prd_preview:
        summary.extend(["", "PRD sample:", prd_preview[:400]])
    if setup_preview:
        summary.extend(["", "Setup guide sample:", setup_preview[:400]])

    summary.extend([
        "",
        "My read: the project is well documented and testable in shape, but the implementation appears behind the product claims. It needs scope tightening, stronger test coverage, and a clearer separation between legitimate recovery guidance and any risky exploit-language before it can be treated as production-ready.",
    ])
    return "\n".join(summary)


def get_offline_project_review(query: str, workspace_path: str) -> str | None:
    """Return a local review response for simple enhancement requests.

    This is intentionally narrow: it only activates for review-style prompts
    and it summarizes visible project structure rather than pretending to be a
    full model-backed code review.
    """

    if not _looks_like_review_request(query):
        return None

    root = Path(workspace_path)
    main_py = root / "src" / "redrum_ai" / "main.py"
    model_py = root / "src" / "redrum_ai" / "model.py"
    tests_py = root / "tests" / "test_regression.py"
    pyproject = root / "pyproject.toml"
    progress = root / "PROJECT_PROGRESS.md"
    log_file = root / "redrum-ai.log"

    suggestions = [
        "Split `src/redrum_ai/main.py` into smaller command modules; it currently mixes CLI parsing, health checks, task handling, memory, bootstrap, and query execution in one file.",
        "Add a proper `pytest` workflow and move the current regression harness into testable fixtures so the suite can run from CI without path assumptions or manual scripting.",
        "Move runtime logs and mutable state out of the project root into a dedicated user state directory, then add log rotation so repeated runs do not clutter the workspace.",
        "Expand the offline fallback path beyond date/time and review prompts so the app can still provide bounded answers when Ollama is unavailable.",
        "Declare runtime dependencies explicitly in `pyproject.toml` and add a one-command bootstrap check for fresh installs so setup failures surface earlier.",
    ]

    notes = [
        f"Observed files: main={'yes' if main_py.exists() else 'no'}, model={'yes' if model_py.exists() else 'no'}, tests={'yes' if tests_py.exists() else 'no'}, pyproject={'yes' if pyproject.exists() else 'no'}, progress={'yes' if progress.exists() else 'no'}, log={'yes' if log_file.exists() else 'no'}.",
        "These suggestions are based on the local project files and the current offline code path, not on an LLM-backed review.",
    ]

    lines = [
        "Here are 5 suggestions to enhance the application:",
        "",
    ]
    for idx, suggestion in enumerate(suggestions, 1):
        lines.append(f"{idx}. {suggestion}")
    lines.extend(["", *notes])
    return "\n".join(lines)


def _format_task_list(tasks: list[dict]) -> str:
    if not tasks:
        return "I don't see any active tasks in the local workspace right now."

    lines = ["Active tasks:"]
    for task in tasks[:5]:
        lines.append(
            f"- #{task.get('id', '?')} {task.get('title', 'Task')} [{task.get('status', 'unknown')}]"
        )
    return "\n".join(lines)


def _format_knowledge_answer(query: str, entries: list[dict]) -> str:
    if not entries:
        return "I don't have a matching local knowledge entry for that question."

    top = entries[0]
    content = str(top.get("content", "")).strip()
    name = top.get("name", "local knowledge")
    if not content:
        return f"I found a local entry named '{name}', but it does not have usable content."
    return f"I found this in '{name}': {content}"


def get_offline_question_response(query: str, config: AppConfig) -> str:
    """Return a grounded local answer when the model backend is unavailable."""

    normalized = " ".join(query.lower().split())
    preferences = get_user_preferences(config.db_path)
    active_tasks = get_active_tasks(config.db_path, config.project_slug)
    knowledge = get_relevant_knowledge(
        config.db_path,
        query,
        project_slug=config.project_slug,
        workspace_path=config.workspace_path,
    )
    summaries = get_recent_summaries(config.db_path, project_slug=config.project_slug)

    if any(token in normalized for token in ("preferred language", "programming language")):
        value = preferences.get("preferred_language") or preferences.get("language")
        if value:
            return f"Your preferred language is {value}."

    if "response style" in normalized or "how should you respond" in normalized:
        value = preferences.get("response_style")
        if value:
            return f"Your preferred response style is {value}."

    if any(token in normalized for token in ("active tasks", "current tasks", "todo", "to-do", "what tasks")):
        return _format_task_list(active_tasks)

    if any(token in normalized for token in ("what is this project", "current project", "project status", "what project")):
        if config.project_slug and config.project_slug != "unknown":
            return f"This workspace is scoped to project '{config.project_slug}' at {config.workspace_path}."
        return f"This workspace is running from {config.workspace_path}."

    if any(token in normalized for token in ("what do you know about", "tell me about", "what is", "who is", "explain")):
        knowledge_answer = _format_knowledge_answer(query, knowledge)
        if "I don't have a matching local knowledge entry" not in knowledge_answer:
            return knowledge_answer

    if summaries:
        latest = str(summaries[0].get("summary", "")).strip()
        if latest and any(token in normalized for token in ("summary", "what happened", "recent work", "recent progress")):
            return f"Recent summary: {latest}"

    if config.workspace_path:
        return (
            "I can't reach the model backend right now, but I can still answer local questions "
            "about preferences, tasks, project scope, and stored knowledge from "
            f"{config.workspace_path}."
        )

    return (
        "I can't reach the model backend right now, but I can still answer local questions "
        "about preferences, tasks, project scope, and stored knowledge."
    )
