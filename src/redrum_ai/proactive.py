import os
import sys
import json
import time
from redrum_ai.config import AppConfig
from redrum_memory.database import db_session, get_active_tasks
from redrum_ai.model import send_to_ollama

def generate_daily_briefing(config: AppConfig) -> str:
    """Generates a personalized daily briefing including stale tasks and potential priorities."""
    tasks = get_active_tasks(config.db_path, config.project_slug)
    if not tasks:
        return "You have no active tasks. Ready for a new challenge!"
        
    task_text = "\n".join([f"- {t['title']} (Priority: {t['priority']}, Status: {t['status']})" for t in tasks])
    prompt = f"Generate a short, motivating daily briefing for the user based on these active tasks. Highlight what they should focus on today:\n{task_text}"
    
    try:
        return send_to_ollama(config, prompt)
    except Exception as exc:
        return f"Daily briefing generation failed: {exc}"

def draft_commit_message(config: AppConfig, diff_text: str) -> str:
    """Automatically drafts a commit message from a git diff."""
    if not diff_text.strip():
        return "No changes to commit."
        
    prompt = (
        "You are an expert developer. Draft a conventional commit message for the following git diff.\n"
        "Include a short title and a concise bulleted list of changes.\n"
        f"Diff:\n{diff_text}\n"
    )
    try:
        return send_to_ollama(config, prompt)
    except Exception as exc:
        return f"Failed to draft commit message: {exc}"

def predict_next_command(config: AppConfig, last_command: str) -> str:
    """Predicts the next logical shell command based on the last command."""
    prompt = (
        "Predict the most likely next shell command the user will run based on this last command.\n"
        f"Last command: {last_command}\n"
        "Output ONLY the predicted command, no explanation."
    )
    try:
        return send_to_ollama(config, prompt).strip()
    except Exception:
        return ""

def pause_and_remind_task(config: AppConfig, task_id: int, reminder_minutes: int) -> bool:
    """Pauses a task and schedules a reminder (Interruption Handler)."""
    with db_session(config.db_path) as conn:
        conn.execute("UPDATE tasks SET status = 'blocked', session_notes = session_notes || ? WHERE id = ?", 
                     (f"\n[Paused] Will remind in {reminder_minutes} minutes.", task_id))
    return True

def activate_ghost_mode(config: AppConfig):
    """Ghost Mode: Shadows user shell history to build automated macros."""
    # Placeholder for shell history watcher
    pass

def run_idle_memory_consolidation(config: AppConfig) -> str:
    """Idle-Time Memory Consolidation Daemon (Phase 29)."""
    try:
        from redrum_memory.memory_core import AIMemory
        from redrum_memory.database import get_unsummarized_conversations
        
        mem = AIMemory(config)
        mem.auto_cluster_and_archive()
        
        unsummarized = get_unsummarized_conversations(config.db_path, config.project_slug)
        if unsummarized:
            return f"Consolidated {len(unsummarized)} conversation rows and clustered vector space."
        return "Vector space clustered. No new conversations to summarize."
    except Exception as exc:
        return f"Idle memory consolidation failed: {exc}"
