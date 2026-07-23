"""
NLP & Human-Computer Interface (Phase 42)
"""
from typing import Dict, Any
from redrum_ai.config import AppConfig
from redrum_ai.model import send_to_ollama

class HciManager:
    def __init__(self, config: AppConfig):
        self.config = config

    def execute_task(self, task_name: str, context: Dict[str, Any] = None) -> str:
        """Dynamically routes execution for NLP & Human-Computer Interface (Phase 42)."""
        ctx = context or {}
        prompt = f"You are an expert in NLP & Human-Computer Interface (Phase 42). Execute the following task:\n{task_name}\nContext: {ctx}"
        return send_to_ollama(self.config, prompt)
