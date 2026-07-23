"""
AI Assistant Memory Core - Multi-tier memory system
Refactored for redrum-memory.
"""
import os
import json
import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import lancedb
    from sentence_transformers import SentenceTransformer
    LANCEDB_AVAILABLE = True
except ImportError:
    LANCEDB_AVAILABLE = False

from redrum_memory.database import db_session

class AIMemory:
    def __init__(self, config: Any, model_name="all-MiniLM-L6-v2"):
        self.config = config
        
        # Determine paths based on AppConfig
        self.sqlite_path = Path(self.config.db_path).expanduser()
        self.base_path = self.sqlite_path.parent
        self.base_path.mkdir(parents=True, exist_ok=True)
        
        self.vector_db_path = self.base_path / "semantic_lancedb"
        
        if LANCEDB_AVAILABLE:
            self.embedding_model = SentenceTransformer(model_name)
            self._init_lancedb()
        
        self._init_sqlite()
        self.short_term = []
        self.max_short_term_tokens = 6000
    
    def _init_lancedb(self):
        """Initialize the LanceDB vector database."""
        self.db = lancedb.connect(str(self.vector_db_path))
        if "interactions" not in self.db.table_names():
            # Create schema with an initial dummy row
            self.table = self.db.create_table(
                "interactions",
                data=[{
                    "id": 1, 
                    "text": "init", 
                    "embedding": self.embedding_model.encode("init").tolist(), 
                    "timestamp": datetime.datetime.now().isoformat(), 
                    "metadata": "{}"
                }]
            )
        else:
            self.table = self.db.open_table("interactions")
    
    def _init_sqlite(self):
        """Ensure core tables exist in the SQLite database."""
        with db_session(str(self.sqlite_path)) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY, 
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
                role TEXT,
                content TEXT,
                project_slug TEXT,
                workspace_path TEXT,
                user_id TEXT,
                source_uri TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS user_preferences (
                key TEXT PRIMARY KEY, 
                value TEXT, 
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            
            # Phase 29: Knowledge Graph (Relational Memory)
            conn.execute("""CREATE TABLE IF NOT EXISTS entities_relations (
                id INTEGER PRIMARY KEY,
                entity_a TEXT,
                relation TEXT,
                entity_b TEXT,
                project_slug TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
            
            # Phase 29: Regret / Anti-Pattern Memory
            conn.execute("""CREATE TABLE IF NOT EXISTS anti_patterns (
                id INTEGER PRIMARY KEY,
                pattern TEXT,
                reason TEXT,
                project_slug TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )""")
    
    def add_interaction(self, user_input: str, ai_response: str, metadata: Optional[Dict] = None):
        """Add a complete user-assistant interaction to memory."""
        ts = datetime.datetime.now().isoformat()
        
        # 1. Update short term memory (context window buffer)
        self.short_term.extend([
            {"role": "user", "content": user_input, "ts": ts},
            {"role": "assistant", "content": ai_response, "ts": ts}
        ])
        
        # Prune short-term memory if it exceeds max tokens
        while len("".join(m["content"] for m in self.short_term)) > self.max_short_term_tokens * 4 and len(self.short_term) > 2:
            self.short_term = self.short_term[2:]
        
        # 2. Update LanceDB vector memory
        if LANCEDB_AVAILABLE:
            emb = self.embedding_model.encode(f"Q: {user_input}\nA: {ai_response}").tolist()
            self.table.add([{
                "text": f"Q: {user_input}\nA: {ai_response}", 
                "embedding": emb, 
                "timestamp": ts, 
                "metadata": json.dumps(metadata or {})
            }])
        
        # 3. Update SQLite episodic memory (using the schema)
        with db_session(str(self.sqlite_path)) as conn:
            conn.execute(
                "INSERT INTO conversations (role, content, project_slug, workspace_path, user_id) VALUES (?, ?, ?, ?, ?)",
                ("user", user_input, self.config.project_slug, self.config.workspace_path, self.config.user_id)
            )
            conn.execute(
                "INSERT INTO conversations (role, content, project_slug, workspace_path, user_id) VALUES (?, ?, ?, ?, ?)",
                ("agent", ai_response, self.config.project_slug, self.config.workspace_path, self.config.user_id)
            )
    
    def retrieve_context(self, query: str, k=5) -> List[str]:
        """Retrieve top k relevant past interactions from LanceDB."""
        if not LANCEDB_AVAILABLE:
            return []
            
        qvec = self.embedding_model.encode(query).tolist()
        results = self.table.search(qvec).limit(k).to_list()
        return [r["text"] for r in results]
    
    def get_recent_context(self) -> List[Dict]:
        """Return the unpruned recent conversation buffer."""
        return self.short_term[-12:]
    
    def save_preference(self, key: str, value: str):
        """Save a user preference to the SQLite database."""
        ts = datetime.datetime.now().isoformat()
        with db_session(str(self.sqlite_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_preferences (key, value, last_updated) VALUES (?, ?, ?)",
                (key, value, ts)
            )

    def auto_cluster_and_archive(self):
        """Phase 29: Vector Auto-Clustering & Archiving."""
        if not LANCEDB_AVAILABLE:
            return
        # Placeholder for K-Means clustering logic
        pass

# Quick local test hook
if __name__ == "__main__":
    class DummyConfig:
        db_path = ":memory:"
        project_slug = "test-project"
        workspace_path = "/tmp"
        user_id = "test-user"
        
    config = DummyConfig()
    mem = AIMemory(config)
    print("✅ redrum-memory refactored and ready!")
