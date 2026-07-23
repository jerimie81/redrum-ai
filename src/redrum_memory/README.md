# redrum-memory

Standalone memory and persistence core for redrum-ai.

## Architecture & Responsibilities
- **Relational Storage:** SQLite database schema, transaction context, user preferences, tasks, and anti-pattern memory.
- **Episodic Memory:** Conversation history preservation and tracking.
- **Vector Core:** Integration with LanceDB and embedding utilities.
- **Schema Evolution:** Fully automated, idempotent migrations.

## Installation
```bash
pip install -e src/redrum_memory
```
