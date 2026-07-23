#!/usr/bin/env python3
"""Regression tests for redrum-ai."""

import os
import sqlite3
import subprocess
import sys
import json
import time
from datetime import datetime
import tempfile

# Add src to python path to import database functions directly
sys.path.insert(0, "/home/redrum/.gemini/redrum-ai/src")
import os
os.environ["PYTHONPATH"] = "/home/redrum/.gemini/redrum-ai/src:" + os.environ.get("PYTHONPATH", "")

TEST_DB_PATH = "/home/redrum/.gemini/redrum-ai/tests/test_memory.db"

import pytest

@pytest.fixture(scope="session", autouse=True)
def test_db_setup():
    setup_test_db()
    yield
    teardown_test_db()


def setup_test_db():
    import gc
    print(f"Setting up test database at {TEST_DB_PATH}...")
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass
        
    conn = sqlite3.connect(TEST_DB_PATH)
    try:
        # Create initial schema (Version 1 only)
        conn.execute("""
        CREATE TABLE conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            role TEXT CHECK(role IN ('user', 'agent', 'system')),
            content TEXT,
            context_summary TEXT
        );
        """)
        conn.execute("""
        CREATE TABLE knowledge_bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            tags TEXT,
            source_uri TEXT
        );
        """)
        conn.execute("""
        CREATE TABLE user_preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE,
            value TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """)
        
        # Seed preferences
        conn.execute(
            "INSERT INTO user_preferences (key, value) VALUES ('preferred_language', 'Python/Rust');"
        )
        conn.execute(
            "INSERT INTO user_preferences (key, value) VALUES ('response_style', 'concise, direct');"
        )
        conn.commit()
    finally:
        conn.close()
        del conn
        gc.collect()

    from redrum_ai.migrations import run_migrations
    run_migrations(TEST_DB_PATH, verbose=False)

def teardown_test_db():
    print(f"Tearing down test database at {TEST_DB_PATH}...")
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

def test_self_check():
    print("Running selfcheck...")
    res = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "--self-check"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_MODEL": "qwen2.5:0.5b",
            "REDRUM_AI_DB_PATH": TEST_DB_PATH,
        }
    )
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)
    assert res.returncode == 0, "Selfcheck failed!"
    print("Selfcheck passed.")

def test_migrations():
    print("Running migration schema checks...")
    conn = sqlite3.connect(TEST_DB_PATH)
    try:
        # Check migrations table version
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        assert row is not None and row[0] == 7, f"Expected migration version 7, got {row[0] if row else 'None'}"
        
        # Check scoping columns in conversations
        columns = [r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        assert "project_slug" in columns
        assert "workspace_path" in columns
        assert "user_id" in columns
        assert "source_uri" in columns
        
        # Check tasks and summaries tables exist
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "tasks" in tables
        assert "conversation_summaries" in tables
        assert "work_events" in tables
        assert "memory_facts" in tables
        assert "memory_reviews" in tables
        assert "memory_sessions" in tables
    finally:
        conn.close()
        del conn
        import gc
        gc.collect()
    print("Migration schema checks passed.")

def test_ping():
    print("Running ping test...")
    res = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "ping"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_MODEL": "qwen2.5:0.5b",
            "REDRUM_AI_DB_PATH": TEST_DB_PATH,
        }
    )
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)
    assert res.returncode == 0, "Ping execution failed!"
    assert len(res.stdout.strip()) > 0, "Response empty!"
    print("Ping test passed.")

def test_preferences_retrieval():
    print("Running user preferences retrieval test...")
    res = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "What is my preferred language?"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_MODEL": "qwen2.5:0.5b",
            "REDRUM_AI_DB_PATH": TEST_DB_PATH,
        }
    )
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)
    assert res.returncode == 0, "Preferences query failed!"
    assert len(res.stdout.strip()) > 0, "Preferences response is empty!"
    
    # Check if turn is saved in DB
    conn = sqlite3.connect(TEST_DB_PATH)
    try:
        rows = conn.execute("SELECT role, content, project_slug, user_id FROM conversations ORDER BY id DESC LIMIT 2").fetchall()
        assert len(rows) == 2, "Conversation turns were not saved to database!"
        # check user role and scoping metadata
        assert rows[1][0] == "user"
        assert rows[1][1] == "What is my preferred language?"
        assert rows[1][2] is not None
        assert rows[1][3] is not None
        # check agent role
        assert rows[0][0] == "agent"
    finally:
        conn.close()
        del conn
        import gc
        gc.collect()
        
    print("Preferences test passed.")

def test_ranked_retrieval():
    print("Running ranked retrieval test...")
    conn = sqlite3.connect(TEST_DB_PATH)
    try:
        # Insert a few documents in knowledge_bases with different ages and scopes
        conn.execute("""
        INSERT OR REPLACE INTO knowledge_bases (name, content, tags, source_uri, timestamp)
        VALUES 
        ('Older Python Doc', 'Python programming is fun.', 'legacy', '/other/path/file.py', '2026-05-19 12:00:00'),
        ('Newer Rust Doc', 'Rust is system programming.', 'modern', '/home/redrum/workspace/file.rs', '2026-06-19 02:00:00'),
        ('Scoped Python Doc', 'Python is powerful.', 'redrum-ai', '/home/redrum/workspace/app.py', '2026-06-19 02:10:00');
        """)
        conn.commit()
    finally:
        conn.close()
        del conn
        import gc
        gc.collect()

    from redrum_ai.database import get_relevant_knowledge
    
    # Retrieve knowledge for "python" with project_slug="redrum-ai" and workspace_path="/home/redrum/workspace"
    results = get_relevant_knowledge(
        TEST_DB_PATH,
        query="python",
        project_slug="redrum-ai",
        workspace_path="/home/redrum/workspace"
    )
    
    # Print results for debug
    for r in results:
        print(f"Name: {r['name']}, Score: {r['score']}")
        
    assert len(results) > 0, "No results returned!"
    # Scoped Python Doc should be ranked FIRST because it matches 'python', has project tags 'redrum-ai' and starts with workspace_path, and is very new!
    assert results[0]['name'] == 'Scoped Python Doc', f"Expected 'Scoped Python Doc' first, got '{results[0]['name']}'"
    print("Ranked retrieval checks passed.")

def test_memory_fact_inference_and_search():
    print("Running memory fact inference test...")
    from redrum_ai.database import upsert_memory_fact, list_memory_facts

    upsert_memory_fact(
        TEST_DB_PATH,
        "preferred_shell",
        "zsh",
        source_type="user",
        project_slug="redrum-ai",
        workspace_path="/home/redrum/workspace",
        user_id="redrum",
        confidence=0.92,
        salience_score=9.0,
    )
    facts = list_memory_facts(
        TEST_DB_PATH,
        project_slug="redrum-ai",
        workspace_path="/home/redrum/workspace",
        user_id="redrum",
    )
    assert any(fact["canonical_key"] == "preferred_shell" and fact["memory_value"] == "zsh" for fact in facts), "Inserted memory fact not found"

    from redrum_ai.database import get_relevant_knowledge
    results = get_relevant_knowledge(
        TEST_DB_PATH,
        query="what shell do I prefer",
        project_slug="redrum-ai",
        workspace_path="/home/redrum/workspace",
    )
    assert any(result["name"] == "preferred_shell" and result["content"] == "zsh" for result in results), "Memory fact not returned by retrieval"
    print("Memory fact inference test passed.")

def test_tool_manifest():
    print("Running tool manifest test...")
    from redrum_ai.tools import registry

    manifest = registry.manifest()
    names = {tool["name"] for tool in manifest["tools"]}
    assert "inspect_file" in names
    assert "patch_file" in names
    assert "execute_argv" in names
    assert "web_fetch" in names
    assert manifest["tool_count"] >= 10
    print("Tool manifest test passed.")

def test_inspect_context():
    print("Running inspect context test...")
    res = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "--inspect-context", "test-query"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_MODEL": "qwen2.5:0.5b",
            "REDRUM_AI_DB_PATH": TEST_DB_PATH,
        }
    )
    print("STDOUT:", res.stdout)
    assert res.returncode == 0, "Inspect context execution failed!"
    assert "Current Request" in res.stdout, "Context missing 'Current Request'!"
    assert "test-query" in res.stdout, "Context missing query!"
    print("Inspect context test passed.")

def test_offline_date_fallback():
    print("Running offline date fallback test...")
    today = datetime.now().astimezone()
    expected = f"Today is {today.strftime('%A, %B')} {today.day}, {today.year}."
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = os.path.join(tmpdir, "memory.db")
        res = subprocess.run(
            [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "what is the date today"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "REDRUM_AI_DB_PATH": temp_db,
            }
        )
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        assert res.returncode == 0, "Offline date fallback failed!"
        assert expected in res.stdout.strip(), f"Expected '{expected}' in output, got: {res.stdout.strip()}"
    print("Offline date fallback test passed.")

def test_offline_project_review_fallback():
    print("Running offline project review fallback test...")
    prompt = "without making any changes review the project in the current directory and make 5 suggestions that would enhance the application"
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = os.path.join(tmpdir, "memory.db")
        res = subprocess.run(
            ["/bin/bash", "/home/redrum/.gemini/redrum-ai/redrum-ai", prompt],
            capture_output=True,
            text=True,
            cwd="/home/redrum/.gemini/redrum-ai",
            env={
                **os.environ,
                "REDRUM_AI_DB_PATH": temp_db,
            }
        )
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        assert res.returncode == 0, "Offline project review fallback failed!"
        assert "Here are 5 suggestions" in res.stdout
        assert res.stdout.count("1.") == 1
        assert res.stdout.count("5.") == 1
    print("Offline project review fallback test passed.")

def test_local_backend_fallback():
    print("Running local backend fallback test...")
    prompt = "avatar fire and ash reviews"
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = os.path.join(tmpdir, "memory.db")
        res = subprocess.run(
            ["/bin/bash", "/home/redrum/.gemini/redrum-ai/redrum-ai", prompt],
            capture_output=True,
            text=True,
            cwd="/home/redrum/.gemini/redrum-ai",
            env={
                **os.environ,
                "REDRUM_AI_DB_PATH": temp_db,
                "OLLAMA_URL": "http://localhost:9999",
            }
        )
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        assert res.returncode == 0, "Local backend fallback failed!"
        output = res.stdout.strip().lower()
        assert output, "Local backend response was empty!"
        assert (
            "local fallback backend" in output
            or "can't fetch live reviews" in output
            or "i can help" in output
        ), f"Unexpected local backend response: {res.stdout.strip()}"
    print("Local backend fallback test passed.")

def test_path_aware_project_assessment():
    print("Running path-aware project assessment test...")
    prompt = "what is your assessment of the project ~/.gemini/git/frp-freedom"
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = os.path.join(tmpdir, "memory.db")
        res = subprocess.run(
            ["/bin/bash", "/home/redrum/.gemini/redrum-ai/redrum-ai", prompt],
            capture_output=True,
            text=True,
            cwd="/home/redrum/.gemini/redrum-ai",
            env={
                **os.environ,
                "REDRUM_AI_DB_PATH": temp_db,
            }
        )
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        assert res.returncode == 0, "Path-aware project assessment failed!"
        output = res.stdout.lower()
        assert "assessment of" in output
        assert "frp-freedom" in output
        assert "strengths" in output
        assert "concerns" in output
    print("Path-aware project assessment test passed.")

def test_git_workflow_helper():
    print("Running git workflow helper test...")
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Redrum"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "redrum@example.com"], cwd=tmpdir, check=True, capture_output=True, text=True)

        sample_file = os.path.join(tmpdir, "sample.txt")
        with open(sample_file, "w") as f:
            f.write("initial content\n")
        subprocess.run(["git", "add", "sample.txt"], cwd=tmpdir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "feat: initial commit"], cwd=tmpdir, check=True, capture_output=True, text=True)

        with open(sample_file, "a") as f:
            f.write("workflow update\n")

        from redrum_ai.tools import invoke_tool

        result = invoke_tool(
            "git_tool",
            {"action": "workflow", "args": ["feature/git-workflow", "chore: workflow update", "."]},
            workspace_path=tmpdir,
            db_path=TEST_DB_PATH,
        )

        assert isinstance(result, dict)
        assert result["exit_code"] == 0
        assert "Git workflow complete" in result["output"]
        assert "Pull Request Draft" in result["output"]
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert branch == "feature/git-workflow"
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=tmpdir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert status == ""
    print("Git workflow helper test passed.")

def test_performance_checks():
    print("Running performance checks...")
    from redrum_ai.config import AppConfig
    from redrum_ai.context import ContextAssembler
    from redrum_ai.database import get_relevant_knowledge
    from redrum_ai.prompt import construct_prompt

    config = AppConfig()
    config.db_path = TEST_DB_PATH
    config.project_slug = "redrum-ai"
    config.workspace_path = "/home/redrum/.gemini/redrum-ai"
    config.agent_config_text = ""

    prompt_start = time.perf_counter()
    for idx in range(120):
        prompt = construct_prompt(config, f"benchmark query {idx}", mode="chat")
        assert prompt
    prompt_elapsed = time.perf_counter() - prompt_start

    with tempfile.TemporaryDirectory() as tmpdir:
        perf_db = os.path.join(tmpdir, "perf.db")
        conn = sqlite3.connect(perf_db)
        try:
            conn.execute(
                """
                CREATE TABLE knowledge_bases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    content TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    tags TEXT,
                    source_uri TEXT
                )
                """
            )
            entries = []
            for idx in range(400):
                entries.append((
                    f"Python Note {idx}",
                    f"Python entry {idx} with project-specific detail and repeated context for retrieval benchmarking.",
                    "redrum-ai,benchmark",
                    f"/home/redrum/.gemini/redrum-ai/file{idx}.py",
                    f"2026-06-{(idx % 20) + 1:02d} 12:00:00",
                ))
            conn.executemany(
                """
                INSERT INTO knowledge_bases (name, content, tags, source_uri, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                entries,
            )
            conn.commit()
        finally:
            conn.close()

        retrieval_start = time.perf_counter()
        for _ in range(80):
            results = get_relevant_knowledge(
                perf_db,
                query="python project benchmark",
                limit=5,
                project_slug="redrum-ai",
                workspace_path="/home/redrum/.gemini/redrum-ai",
            )
            assert results
        retrieval_elapsed = time.perf_counter() - retrieval_start

    print(f"Prompt assembly benchmark: {prompt_elapsed:.4f}s total")
    print(f"Retrieval benchmark: {retrieval_elapsed:.4f}s total")
    assert prompt_elapsed < 1.5, f"Prompt assembly too slow: {prompt_elapsed:.4f}s"
    assert retrieval_elapsed < 2.0, f"Retrieval too slow: {retrieval_elapsed:.4f}s"
    print("Performance checks passed.")

def test_tool_registry():
    print("Running tool registry test...")
    from redrum_ai.tools import registry, invoke_tool
    
    test_file = "/tmp/redrum_ai_test_tool.txt"
    with open(test_file, "w") as f:
        f.write("hello from tool registry test")
        
    try:
        content = invoke_tool(
            "read_file",
            {"path": test_file},
            workspace_path="/tmp",
            db_path=TEST_DB_PATH
        )
        assert content["output"] == "hello from tool registry test", f"Expected content, got: {content}"
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)
            
    print("Tool registry test passed.")

def test_path_validation_rejects_escape(monkeypatch):
    print("Running path validation test...")
    from redrum_ai import tools

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = os.path.join(tmpdir, "workspace")
        sibling = os.path.join(tmpdir, "work")
        os.makedirs(workspace, exist_ok=True)
        os.makedirs(sibling, exist_ok=True)
        allowed_file = os.path.join(workspace, "allowed.txt")
        with open(allowed_file, "w") as handle:
            handle.write("ok")
        outside_file = os.path.join(sibling, "escape.txt")
        with open(outside_file, "w") as handle:
            handle.write("nope")
        link_path = os.path.join(workspace, "escape-link.txt")
        os.symlink(outside_file, link_path)

        monkeypatch.setattr(
            tools,
            "load_permissions_config",
            lambda: {
                "allowed_directories": [],
                "allow_internet_search": False,
                "allow_internet_fetch": False,
                "allowed_domains": [],
                "command_allowlist": list(tools.COMMAND_ALLOWLIST),
                "command_denylist": list(tools.COMMAND_DENYLIST),
            },
        )

        assert tools.validate_path(allowed_file, workspace) == os.path.realpath(allowed_file)
        with pytest.raises(PermissionError):
            tools.validate_path(outside_file, workspace)
        with pytest.raises(PermissionError):
            tools.validate_path(link_path, workspace)
    print("Path validation test passed.")

def test_recent_conversations_scope_filter():
    print("Running conversation scope filter test...")
    from redrum_ai.database import save_conversation_turn, get_recent_conversations
    from redrum_ai.migrations import run_migrations

    with tempfile.TemporaryDirectory() as tmpdir:
        scoped_db = os.path.join(tmpdir, "scoped.db")
        run_migrations(scoped_db, verbose=False)
        save_conversation_turn(
            scoped_db,
            "user",
            "project scoped",
            project_slug="redrum-ai",
            workspace_path="/home/redrum/workspace-a",
            user_id="redrum",
        )
        save_conversation_turn(
            scoped_db,
            "user",
            "other project",
            project_slug="other-project",
            workspace_path="/home/redrum/workspace-b",
            user_id="someone-else",
        )
        rows = get_recent_conversations(
            scoped_db,
            project_slug="redrum-ai",
            workspace_path="/home/redrum/workspace-a",
            user_id="redrum",
            limit=10,
        )
        contents = [row["content"] for row in rows]
        assert "project scoped" in contents
        assert "other project" not in contents
    print("Conversation scope filter test passed.")

def test_conversation_summarization():
    print("Running conversation summarization test...")
    conn = sqlite3.connect(TEST_DB_PATH)
    try:
        # Seed 8 conversations (16 turns) to trigger summarization threshold (> 6 turns)
        for i in range(8):
            conn.execute(
                """
                INSERT INTO conversations (role, content, project_slug)
                VALUES ('user', 'say hello ' || ?, 'redrum-ai')
                """,
                (str(i),)
            )
            conn.execute(
                """
                INSERT INTO conversations (role, content, project_slug)
                VALUES ('agent', 'replied hello ' || ?, 'redrum-ai')
                """,
                (str(i),)
            )
        conn.commit()
    finally:
        conn.close()
        del conn
        import gc
        gc.collect()

    from redrum_ai.database import get_unsummarized_conversations
    unsummarized = get_unsummarized_conversations(TEST_DB_PATH, project_slug="redrum-ai")
    assert len(unsummarized) >= 10, f"Expected at least 10 unsummarized turns, got {len(unsummarized)}"
    
    # Run the summarization flow
    from redrum_ai.main import summarize_older_conversations
    from redrum_ai.config import AppConfig
    
    config = AppConfig()
    config.db_path = TEST_DB_PATH
    config.project_slug = "redrum-ai"
    config.model_name = "qwen2.5:0.5b"
    config.ollama_url = "http://localhost:11434"
    config.verbose = True
    
    summarize_older_conversations(config)
    
    conn = sqlite3.connect(TEST_DB_PATH)
    try:
        summaries = conn.execute("SELECT summary FROM conversation_summaries WHERE project_slug = 'redrum-ai'").fetchall()
        assert len(summaries) > 0, "No summary was created!"
        print("Created summary text:", summaries[0][0])
    finally:
        conn.close()
        del conn
        import gc
        gc.collect()
        
    print("Conversation summarization test passed.")

def test_capabilities_command():
    print("Running capabilities subcommand test...")
    res = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "capabilities", "--host-api-version", "1.0.0"],
        capture_output=True,
        text=True
    )
    print("STDOUT:", res.stdout)
    assert res.returncode == 0, f"Command failed with code {res.returncode}. Stderr: {res.stderr}"
    data = json.loads(res.stdout)
    assert "capabilities" in data
    assert "tools" in data
    assert data["negotiation"]["compatible"] is True
    assert any(item["name"] == "task.intake" for item in data["capabilities"])
    print("Capabilities subcommand test passed.")

def test_health_command():
    print("Running health subcommand test...")
    res = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "health", "--skip-ollama-check"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_DB_PATH": TEST_DB_PATH
        }
    )
    print("STDOUT:", res.stdout)
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["database"]["status"] == "ready"
    assert data["ollama"]["status"] == "skipped"
    print("Health subcommand test passed.")

def test_direct_tool_command():
    print("Running direct tool subcommand test...")
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"content inside temp file")
        temp_path = f.name
        
    try:
        args_payload = json.dumps({"path": temp_path})
        res = subprocess.run(
            [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "tool", "--name", "read_file", "--args", args_payload],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "REDRUM_AI_DB_PATH": TEST_DB_PATH
            }
        )
        print("STDOUT:", res.stdout)
        print("STDERR:", res.stderr)
        assert res.returncode == 0
        data = json.loads(res.stdout)
        assert data["exit_code"] == 0
        assert data["output"] == "content inside temp file"
        
        bad_payload = json.dumps({"bad_param": 123})
        res_bad = subprocess.run(
            [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "tool", "--name", "read_file", "--args", bad_payload],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "REDRUM_AI_DB_PATH": TEST_DB_PATH
            }
        )
        print("STDOUT (bad):", res_bad.stdout)
        assert res_bad.returncode == 1
        data_bad = json.loads(res_bad.stdout)
        assert data_bad["exit_code"] == 1
        assert "Schema Validation Error" in data_bad["output"]
        
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
    print("Direct tool subcommand test passed.")

def test_memory_command():
    print("Running memory subcommand test...")
    res_insert = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "memory", "insert", "--name", "API Key Note", "--content", "secret-content", "--tags", "redrum-ai"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_DB_PATH": TEST_DB_PATH
        }
    )
    print("STDOUT (insert):", res_insert.stdout)
    assert res_insert.returncode == 0
    data_ins = json.loads(res_insert.stdout)
    assert data_ins["status"] == "success"
    
    res_search = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "memory", "search", "Key Note"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_DB_PATH": TEST_DB_PATH
        }
    )
    print("STDOUT (search):", res_search.stdout)
    assert res_search.returncode == 0
    data_search = json.loads(res_search.stdout)
    assert len(data_search) > 0
    assert data_search[0]["name"] == "API Key Note"
    print("Memory subcommand test passed.")

def test_task_and_handoff_commands():
    print("Running task and handoff command tests...")
    res_intake = subprocess.run(
        [
            sys.executable,
            "/home/redrum/.gemini/redrum-ai/ai_partner.py",
            "task",
            "intake",
            "Write deterministic plugin tests",
            "--priority",
            "high",
            "--acceptance-criteria",
            "Regression tests pass",
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_DB_PATH": TEST_DB_PATH
        }
    )
    print("STDOUT (intake):", res_intake.stdout)
    assert res_intake.returncode == 0
    intake_data = json.loads(res_intake.stdout)
    task = intake_data["task"]
    assert task["status"] == "ready"
    assert task["priority"] == "high"
    assert task["acceptance_criteria"] == "Regression tests pass"

    res_update = subprocess.run(
        [
            sys.executable,
            "/home/redrum/.gemini/redrum-ai/ai_partner.py",
            "task",
            "update",
            "--id",
            str(task["id"]),
            "--status",
            "needs_review",
            "--append-notes",
            "Verified through CLI regression path.",
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_DB_PATH": TEST_DB_PATH
        }
    )
    print("STDOUT (update):", res_update.stdout)
    assert res_update.returncode == 0
    update_data = json.loads(res_update.stdout)
    assert update_data["task"]["status"] == "needs_review"
    assert "Verified through CLI" in update_data["task"]["session_notes"]

    res_handoff = subprocess.run(
        [
            sys.executable,
            "/home/redrum/.gemini/redrum-ai/ai_partner.py",
            "task",
            "handoff",
            "--id",
            str(task["id"]),
        ],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_DB_PATH": TEST_DB_PATH
        }
    )
    print("STDOUT (handoff):", res_handoff.stdout)
    assert res_handoff.returncode == 0
    handoff_data = json.loads(res_handoff.stdout)
    assert handoff_data["status"] == "ready_for_handoff"
    assert handoff_data["tasks"][0]["status"] == "needs_review"
    print("Task and handoff command tests passed.")

def test_metrics_and_bug_report_commands():
    print("Running metrics and bug-report command tests...")
    res_metrics = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "metrics"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_DB_PATH": TEST_DB_PATH
        }
    )
    print("STDOUT (metrics):", res_metrics.stdout)
    assert res_metrics.returncode == 0
    metrics = json.loads(res_metrics.stdout)
    assert "tasks" in metrics
    assert "events" in metrics
    assert metrics["events"]["total"] >= 1

    res_bug = subprocess.run(
        [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "bug-report"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "REDRUM_AI_DB_PATH": TEST_DB_PATH
        }
    )
    print("STDOUT (bug-report):", res_bug.stdout)
    assert res_bug.returncode == 0
    bug = json.loads(res_bug.stdout)
    assert bug["redrum_ai_version"]
    assert "recent_events" in bug
    print("Metrics and bug-report command tests passed.")

def test_bootstrap_command():
    print("Running bootstrap subcommand test...")
    bootstrap_db = TEST_DB_PATH + "_bootstrap"
    if os.path.exists(bootstrap_db):
        os.remove(bootstrap_db)
        
    try:
        res = subprocess.run(
            [sys.executable, "/home/redrum/.gemini/redrum-ai/ai_partner.py", "bootstrap"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "REDRUM_AI_DB_PATH": bootstrap_db
            }
        )
        print("STDOUT:", res.stdout)
        assert res.returncode == 0
        assert "Bootstrap completed successfully" in res.stdout
        
        conn = sqlite3.connect(bootstrap_db)
        try:
            val = conn.execute("SELECT value FROM user_preferences WHERE key = 'preferred_language'").fetchone()[0]
            assert val == "Python/Rust"
        finally:
            conn.close()
    finally:
        if os.path.exists(bootstrap_db):
            os.remove(bootstrap_db)
            
    print("Bootstrap subcommand test passed.")
