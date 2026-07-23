"""
Infrastructure as Code & Cloud Architecture (Phase 30)
"""
from typing import Dict, Any
from redrum_ai.config import AppConfig
from redrum_ai.model import send_to_ollama

class IacManager:
    def __init__(self, config: AppConfig):
        self.config = config

    def execute_task(self, task_name: str, context: Dict[str, Any] = None) -> str:
        """Dynamically routes execution for Infrastructure as Code & Cloud Architecture (Phase 30)."""
        ctx = context or {}
        prompt = f"You are an expert in Infrastructure as Code & Cloud Architecture (Phase 30). Execute the following task:\n{task_name}\nContext: {ctx}"
        return send_to_ollama(self.config, prompt)
