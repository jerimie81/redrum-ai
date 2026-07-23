import os
import json
from typing import Dict, Any

def handle_url_summary(url: str, config) -> str:
    from redrum_ai.model import send_to_ollama
    # In a real app we'd fetch the URL here. For now we prompt the model.
    prompt = f"The user pasted this URL: {url}. If you can guess the content from the URL, provide a summary. Otherwise, instruct the user to use a web fetch tool."
    return send_to_ollama(config, prompt)

def generate_mermaid_diagram(codebase_summary: str, config) -> str:
    from redrum_ai.model import send_to_ollama
    prompt = (
        "Generate a Mermaid JS architectural diagram (graph TD) based on this codebase summary:\n"
        f"{codebase_summary}\n"
        "Output ONLY the mermaid code block, nothing else."
    )
    return send_to_ollama(config, prompt)

def translate_code(code: str, target_language: str, config) -> str:
    from redrum_ai.model import send_to_ollama
    prompt = (
        f"Translate the following code to {target_language}. Output ONLY the translated code block.\n\n"
        f"```{code}```\n"
    )
    return send_to_ollama(config, prompt)

def generate_sql_query(nl_query: str, schema_context: str, config) -> str:
    from redrum_ai.model import send_to_ollama
    prompt = (
        "Translate the following natural language query into a SQL query based on the schema.\n"
        f"Schema: {schema_context}\n"
        f"Query: {nl_query}\n"
        "Output ONLY the SQL code."
    )
    return send_to_ollama(config, prompt)
