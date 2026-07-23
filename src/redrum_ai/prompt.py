from typing import Iterable, Any
from redrum_ai.config import AppConfig
from redrum_memory.database import (
    get_user_preferences,
    get_relevant_knowledge,
    get_recent_conversations,
    get_active_tasks,
    get_recent_summaries,
    get_anti_patterns,
)
from redrum_ai.context import ContextAssembler

def construct_prompt(
    config: AppConfig,
    user_query: str,
    mode: str = "chat",
    response_format: str = "concise",
    tool_results: list[dict] | None = None
) -> str:
    preferences = get_user_preferences(config.db_path)
    knowledge = get_relevant_knowledge(
        config.db_path,
        user_query,
        project_slug=config.project_slug,
        workspace_path=config.workspace_path,
    )
    recent_conversations = get_recent_conversations(
        config.db_path,
        project_slug=config.project_slug,
        workspace_path=config.workspace_path,
        user_id=config.user_id,
    )
    active_tasks = get_active_tasks(config.db_path, config.project_slug)
    recent_summaries = get_recent_summaries(config.db_path, project_slug=config.project_slug)
    anti_patterns = get_anti_patterns(config.db_path, project_slug=config.project_slug)

    assembler = ContextAssembler(config)
    return assembler.assemble(
        query=user_query,
        preferences=preferences,
        knowledge=knowledge,
        recent_conversations=recent_conversations,
        active_tasks=active_tasks,
        mode=mode,
        tool_results=tool_results,
        response_format=response_format,
        recent_summaries=recent_summaries,
        anti_patterns=anti_patterns
    )

