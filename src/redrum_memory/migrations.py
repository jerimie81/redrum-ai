import sqlite3

MIGRATIONS = [
    # Version 1: Initial schema setup (if not exists)
    [
        """
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            role TEXT CHECK(role IN ('user', 'agent', 'system')),
            content TEXT,
            context_summary TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            path TEXT UNIQUE,
            language TEXT CHECK(language IN ('python', 'java', 'kotlin', 'rust', 'shell', 'other')),
            build_system TEXT,
            last_modified DATETIME
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS code_library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            language TEXT,
            tags TEXT,
            description TEXT,
            snippet_content TEXT,
            usage_count INTEGER DEFAULT 0
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS code_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            file_path TEXT,
            original_snippet TEXT,
            revised_snippet TEXT,
            user_feedback TEXT,
            agent_notes TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS command_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            command_str TEXT NOT NULL,
            working_directory TEXT,
            exit_code INTEGER,
            output_summary TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS file_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            file_name TEXT,
            file_type TEXT,
            last_indexed DATETIME,
            project_id INTEGER,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS knowledge_bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            tags TEXT,
            source_uri TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    ],
    # Version 2: Add scoping and provenance columns to conversations and knowledge_bases
    [
        "ALTER TABLE conversations ADD COLUMN project_slug TEXT;",
        "ALTER TABLE conversations ADD COLUMN workspace_path TEXT;",
        "ALTER TABLE conversations ADD COLUMN user_id TEXT;",
        "ALTER TABLE conversations ADD COLUMN source_uri TEXT;"
    ],
    # Version 3: Add tasks table
    [
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT CHECK(status IN ('backlog', 'ready', 'in_progress', 'blocked', 'needs_review', 'done')) DEFAULT 'backlog',
            priority TEXT CHECK(priority IN ('low', 'medium', 'high', 'critical')) DEFAULT 'medium',
            due_date DATETIME,
            project_slug TEXT,
            workspace_path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """
    ],
    # Version 4: Add conversation_summaries table
    [
        """
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            summary TEXT NOT NULL,
            start_conversation_id INTEGER,
            end_conversation_id INTEGER,
            project_slug TEXT,
            workspace_path TEXT
        );
        """
    ],
    # Version 5: Add acceptance_criteria and session_notes to tasks
    [
        "ALTER TABLE tasks ADD COLUMN acceptance_criteria TEXT;",
        "ALTER TABLE tasks ADD COLUMN session_notes TEXT;"
    ],
    # Version 6: Add structured local observability events and optional embedding support
    [
        """
        CREATE TABLE IF NOT EXISTS work_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT,
            task_id INTEGER,
            event_type TEXT NOT NULL,
            severity TEXT CHECK(severity IN ('debug', 'info', 'warning', 'error')) DEFAULT 'info',
            message TEXT NOT NULL,
            metadata TEXT
        );
        """,
        "ALTER TABLE knowledge_bases ADD COLUMN embedding TEXT;"
    ],
    # Version 7: Expand durable memory and tool provenance
    [
        """
        CREATE TABLE IF NOT EXISTS memory_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_key TEXT NOT NULL,
            memory_value TEXT NOT NULL,
            canonical_key TEXT,
            source_type TEXT DEFAULT 'user',
            source_uri TEXT,
            project_slug TEXT,
            workspace_path TEXT,
            user_id TEXT,
            confidence REAL DEFAULT 0.75,
            salience_score REAL DEFAULT 5.0,
            status TEXT DEFAULT 'active',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at DATETIME
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            memory_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            reviewer TEXT,
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE NOT NULL,
            project_slug TEXT,
            workspace_path TEXT,
            user_id TEXT,
            started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            ended_at DATETIME,
            summary TEXT,
            state_json TEXT
        );
        """,
        "ALTER TABLE knowledge_bases ADD COLUMN source_type TEXT DEFAULT 'manual';",
        "ALTER TABLE knowledge_bases ADD COLUMN confidence REAL DEFAULT 0.75;",
        "ALTER TABLE knowledge_bases ADD COLUMN salience_score REAL DEFAULT 5.0;",
        "ALTER TABLE knowledge_bases ADD COLUMN review_state TEXT DEFAULT 'unreviewed';",
        "ALTER TABLE knowledge_bases ADD COLUMN last_accessed_at DATETIME;",
        "CREATE INDEX IF NOT EXISTS idx_memory_facts_scope ON memory_facts(project_slug, workspace_path, user_id);",
        "CREATE INDEX IF NOT EXISTS idx_memory_facts_status ON memory_facts(status, salience_score);",
        "CREATE INDEX IF NOT EXISTS idx_memory_reviews_lookup ON memory_reviews(memory_type, memory_id, created_at);",
        "CREATE INDEX IF NOT EXISTS idx_memory_sessions_scope ON memory_sessions(project_slug, workspace_path, user_id);"
        ,
        # Chapter 3/4 durable platform tables.  They intentionally live in the
        # existing idempotent migration so databases created by older releases
        # can be upgraded without changing the public migration number.
        """
        CREATE TABLE IF NOT EXISTS memory_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_uri TEXT,
            content_hash TEXT,
            captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            project_slug TEXT,
            workspace_path TEXT,
            metadata TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT NOT NULL,
            entity_type TEXT DEFAULT 'concept',
            aliases TEXT DEFAULT '[]',
            project_slug TEXT,
            workspace_path TEXT,
            confidence REAL DEFAULT 0.75,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(canonical_name, project_slug, workspace_path)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_relations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            predicate TEXT NOT NULL,
            object_id INTEGER NOT NULL,
            source_uri TEXT,
            confidence REAL DEFAULT 0.75,
            project_slug TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(subject_id, predicate, object_id, project_slug)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_type TEXT NOT NULL,
            memory_id INTEGER NOT NULL,
            before_value TEXT,
            after_value TEXT,
            reason TEXT,
            reviewer TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_consolidation_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            cursor TEXT,
            stats_json TEXT,
            error TEXT,
            started_at DATETIME,
            finished_at DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS tool_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            tool_name TEXT NOT NULL,
            request_json TEXT NOT NULL,
            result_json TEXT,
            project_slug TEXT,
            workspace_path TEXT,
            approved INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            previous_digest TEXT,
            digest TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS connector_consents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connector TEXT NOT NULL,
            scopes TEXT NOT NULL,
            granted INTEGER NOT NULL DEFAULT 0,
            project_slug TEXT,
            user_id TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(connector, project_slug, user_id)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS session_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            project_slug TEXT,
            workspace_path TEXT,
            state_json TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            project_slug TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_memory_entities_scope ON memory_entities(project_slug, workspace_path);",
        "CREATE INDEX IF NOT EXISTS idx_memory_relations_subject ON memory_relations(subject_id);",
        "CREATE INDEX IF NOT EXISTS idx_tool_audit_session ON tool_audit(session_id, created_at);",
        "CREATE INDEX IF NOT EXISTS idx_session_checkpoints_session ON session_checkpoints(session_id, created_at);"
    ],
    # Version 8: federated control-plane, policy-bound knowledge, and audit sync.
    [
        """
        CREATE TABLE IF NOT EXISTS federated_nodes (
            node_id TEXT PRIMARY KEY, certificate_fingerprint TEXT NOT NULL,
            public_key TEXT NOT NULL, capabilities TEXT NOT NULL DEFAULT '[]',
            enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP, revoked_at DATETIME
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS capability_leases (
            lease_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, capability TEXT NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}', issued_at DATETIME NOT NULL,
            expires_at DATETIME NOT NULL, revoked_at DATETIME, issuer TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS federated_jobs (
            job_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, payload_json TEXT NOT NULL,
            payload_digest TEXT NOT NULL, signature TEXT NOT NULL, status TEXT NOT NULL,
            vector_clock_json TEXT NOT NULL DEFAULT '{}', created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME, error TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS replay_nonces (
            nonce TEXT PRIMARY KEY, node_id TEXT NOT NULL, seen_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS sync_operations (
            operation_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, entity_key TEXT NOT NULL,
            operation_json TEXT NOT NULL, vector_clock_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued', created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            applied_at DATETIME, conflict_json TEXT
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_access_policies (
            policy_id TEXT PRIMARY KEY, principal TEXT NOT NULL, scope TEXT NOT NULL,
            project_slug TEXT, workspace_path TEXT, max_sensitivity INTEGER NOT NULL DEFAULT 1,
            effect TEXT NOT NULL DEFAULT 'allow', created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memory_provenance (
            provenance_id TEXT PRIMARY KEY, memory_type TEXT NOT NULL, memory_id INTEGER NOT NULL,
            scope TEXT NOT NULL, sensitivity INTEGER NOT NULL DEFAULT 1, source_uri TEXT,
            content_hash TEXT NOT NULL, immutable_record TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS remote_audit_outbox (
            audit_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, sequence_no INTEGER NOT NULL,
            event_json TEXT NOT NULL, previous_digest TEXT, digest TEXT NOT NULL,
            signature TEXT NOT NULL, sent_at DATETIME, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(node_id, sequence_no)
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_federated_jobs_node_status ON federated_jobs(node_id, status);",
        "CREATE INDEX IF NOT EXISTS idx_memory_policy_lookup ON memory_access_policies(principal, scope, project_slug);",
        "CREATE INDEX IF NOT EXISTS idx_memory_provenance_lookup ON memory_provenance(memory_type, memory_id, scope);",
        "CREATE INDEX IF NOT EXISTS idx_audit_outbox_pending ON remote_audit_outbox(node_id, sent_at, sequence_no);"
        ,
        "ALTER TABLE knowledge_bases ADD COLUMN sensitivity INTEGER NOT NULL DEFAULT 1;",
        "ALTER TABLE knowledge_bases ADD COLUMN kb_scope TEXT NOT NULL DEFAULT 'project';",
        "ALTER TABLE knowledge_bases ADD COLUMN project_slug TEXT;",
        "ALTER TABLE knowledge_bases ADD COLUMN workspace_path TEXT;",
        "ALTER TABLE knowledge_bases ADD COLUMN user_id TEXT;",
        "ALTER TABLE memory_facts ADD COLUMN sensitivity INTEGER NOT NULL DEFAULT 1;",
        "ALTER TABLE memory_facts ADD COLUMN kb_scope TEXT NOT NULL DEFAULT 'project';"
    ]
]

def run_migrations(db_path: str, verbose: bool = False):
    conn = sqlite3.connect(db_path)
    try:
        # 1. Create schema_migrations if not exists
        conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()

        # 2. Read already-recorded versions, but do not trust them as the only source of truth.
        recorded_versions = {
            row[0]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            if row and row[0] is not None
        }

        # 3. Apply all migrations idempotently so partially-migrated databases can self-heal.
        for idx, statements in enumerate(MIGRATIONS):
            version = idx + 1
            if verbose:
                print(f"Ensuring migration version {version}...", flush=True)
            for statement in statements:
                try:
                    conn.execute(statement)
                except sqlite3.OperationalError as exc:
                    # Ignore "duplicate column name" or "table already exists" if database was modified manually
                    exc_msg = str(exc).lower()
                    if "duplicate column" in exc_msg or "already exists" in exc_msg:
                        continue
                    raise
            if version not in recorded_versions:
                conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
                recorded_versions.add(version)
            conn.commit()
    finally:
        conn.close()
