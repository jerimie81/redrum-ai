import json
import logging
import os
import sys
import time
import subprocess
import urllib.parse
import re
import socket
from datetime import datetime

from redrum_ai.config import AppConfig
from redrum_memory.database import (
    check_database,
    save_conversation_turn,
    prune_memories,
    get_relevant_knowledge,
    list_knowledge_entries,
    list_memory_facts,
    delete_knowledge_entry,
    delete_memory_fact,
    export_memory,
    get_memory_stats,
    get_recent_memory_reviews,
    consolidate_memory,
    upsert_memory_fact,
    record_memory_review,
    db_session,
)
from redrum_ai.model import check_ollama, send_to_ollama
from redrum_ai.offline import get_offline_project_assessment, get_offline_project_review, get_offline_question_response, get_offline_response
from redrum_ai.prompt import construct_prompt
from redrum_ai.cli import build_parser, read_query_from_args
from redrum_memory.migrations import run_migrations
from redrum_ai.telemetry import build_bug_report, classify_error, collect_metrics, log_event, new_session_id
from redrum_ai.main import emit_json, __version__, check_edge_environment, launch_edge_llama_server

def handle_capabilities_command(args):
    from redrum_ai.plugin import negotiate_capabilities

    capabilities = negotiate_capabilities(args.host_api_version)
    emit_json(capabilities)
    return 0


def handle_health_command(config: AppConfig, args) -> int:
    from redrum_ai.plugin import build_contract
    from redrum_ai.model import get_model_profiles

    contract = build_contract()
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "database": {
            "path": config.db_path,
            "status": "unknown",
            "errors": []
        },
        "ollama": {
            "url": config.ollama_url,
            "model": config.model_name,
            "provider": config.model_provider,
            "profiles": [profile.__dict__ for profile in get_model_profiles(config)],
            "status": "unknown",
            "errors": []
        },
        "plugin": {
            "api_version": contract["api_version"],
            "capability_count": len(contract["capabilities"]),
            "status": "ready",
            "errors": []
        }
    }
    
    db_health = check_database(config.db_path)
    if db_health.ok:
        report["database"]["status"] = "ready"
    else:
        report["database"]["status"] = "error"
        report["database"]["errors"] = db_health.messages
        
    if not args.skip_ollama_check:
        ollama_health = check_ollama(config)
        if ollama_health.ok:
            report["ollama"]["status"] = "ready"
        else:
            report["ollama"]["status"] = "error"
            report["ollama"]["errors"] = ollama_health.messages
    else:
        report["ollama"]["status"] = "skipped"
        
    if config.runtime_profile == "constrained-edge":
        edge_warnings = check_edge_environment(config)
        report["edge_environment"] = {
            "status": "ready" if not edge_warnings else "warning",
            "warnings": edge_warnings
        }
        
    emit_json(report)
    return 0 if (db_health.ok and (args.skip_ollama_check or ollama_health.ok)) else 1


def handle_tool_command(config: AppConfig, args) -> int:
    from redrum_ai.tools import invoke_tool
    logger = logging.getLogger("redrum_ai")
    session_id = new_session_id()
    
    tool_name = args.name
    try:
        tool_args = json.loads(args.args)
    except Exception as exc:
        err = {"exit_code": 1, "output": f"JSON arguments parsing failed: {exc}"}
        emit_json(err)
        return 1
        
    logger.info(f"Direct tool execution: {tool_name} with args {tool_args}")
    log_event(config.db_path, "tool.invoke", f"Invoking tool {tool_name}", session_id=session_id)
    
    start_time = time.time()
    result = invoke_tool(
        tool_name=tool_name,
        args=tool_args,
        workspace_path=config.workspace_path,
        db_path=config.db_path,
        dry_run=False
    )
    latency = time.time() - start_time
    logger.info(f"Tool {tool_name} finished in {latency:.3f}s")
    
    if not isinstance(result, dict):
        result = {"tool": tool_name, "exit_code": 0 if not str(result).startswith("Schema Validation Error") else 1, "output": str(result), "status": "success"}

    emit_json(result)
    exit_code = result.get("exit_code", 0)
    log_event(
        config.db_path,
        "tool.complete",
        f"Tool {tool_name} finished with exit code {exit_code}",
        session_id=session_id,
        severity="info" if exit_code == 0 else "error",
    )
    return exit_code


def handle_tools_command(config: AppConfig, args) -> int:
    from redrum_ai.tools import registry

    action = getattr(args, "tools_action", "list")
    manifest = registry.manifest()
    if action == "manifest":
        emit_json(manifest)
        return 0
    if action == "list":
        emit_json(
            {
                "api_version": manifest["api_version"],
                "tool_count": manifest["tool_count"],
                "tools": [
                    {
                        "name": tool["name"],
                        "category": tool["category"],
                        "risk": tool["risk"],
                        "permissions": tool["permissions"],
                        "description": tool["description"],
                    }
                    for tool in manifest["tools"]
                ],
            }
        )
        return 0
    return 1


def handle_memory_command(config: AppConfig, args) -> int:
    action = args.memory_action
    if not action:
        print("Error: Subcommand 'memory' requires a sub-action (search, insert).", file=sys.stderr)
        return 2
    if action == "search":
        from redrum_ai.model import get_embedding

        query_emb = get_embedding(config, args.text)
        results = get_relevant_knowledge(
            config.db_path,
            args.text,
            query_embedding=query_emb,
            limit=args.limit,
            project_slug=config.project_slug,
            workspace_path=config.workspace_path,
        )
        emit_json(results)
        return 0

    if action == "insert":
        from redrum_ai.model import get_embedding

        emb = get_embedding(config, args.name + "\n" + args.content)
        emb_str = json.dumps(emb) if emb else None
        with db_session(config.db_path) as conn:
            columns = [r["name"] for r in conn.execute("PRAGMA table_info(knowledge_bases)").fetchall()]
            if "embedding" in columns:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_bases (name, content, tags, source_uri, source_type, confidence, salience_score, review_state, embedding)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (args.name, args.content, args.tags, args.source_uri, "manual", 0.75, 5.0, "unreviewed", emb_str),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_bases (name, content, tags, source_uri, source_type, confidence, salience_score, review_state)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (args.name, args.content, args.tags, args.source_uri, "manual", 0.75, 5.0, "unreviewed"),
                )
        emit_json({"status": "success", "message": f"Inserted knowledge entry: '{args.name}'"})
        return 0

    if action == "review":
        if args.type == "facts":
            emit_json(list_memory_facts(config.db_path, limit=args.limit, project_slug=config.project_slug, workspace_path=config.workspace_path, user_id=config.user_id))
            return 0
        if args.type == "reviews":
            emit_json(get_recent_memory_reviews(config.db_path, limit=args.limit))
            return 0
        if args.type == "sessions":
            with db_session(config.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM memory_sessions
                    WHERE (? = 'unknown' OR project_slug = ?)
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (config.project_slug, config.project_slug, args.limit),
                ).fetchall()
            emit_json([dict(row) for row in rows])
            return 0
        emit_json(list_knowledge_entries(config.db_path, limit=args.limit, project_slug=config.project_slug))
        return 0

    if action == "delete":
        deleted = delete_memory_fact(config.db_path, args.id) if args.type == "fact" else delete_knowledge_entry(config.db_path, args.id)
        emit_json(
            {
                "status": "success" if deleted else "error",
                "deleted": deleted,
                "id": args.id,
                "type": args.type,
                "message": "Memory entry deleted" if deleted else "Memory entry not found",
            }
        )
        return 0 if deleted else 1

    if action == "export":
        emit_json(export_memory(config.db_path, project_slug=config.project_slug))
        return 0

    if action == "stats":
        emit_json(get_memory_stats(config.db_path, project_slug=config.project_slug))
        return 0

    if action == "consolidate":
        emit_json(consolidate_memory(config.db_path, project_slug=config.project_slug, workspace_path=config.workspace_path, user_id=config.user_id))
        return 0

    if action == "reflect":
        from redrum_memory.database import get_recent_conversations
        from redrum_ai.model import send_to_ollama

        conversations = get_recent_conversations(
            config.db_path,
            limit=50,
            project_slug=config.project_slug,
            workspace_path=config.workspace_path,
            user_id=config.user_id,
        )
        if not conversations:
            emit_json({"status": "error", "message": "No recent conversations to reflect on."})
            return 1

        conv_text = "\n".join([f"{row['role'].capitalize()}: {row['content']}" for row in conversations])
        prompt = (
            "Analyze the following recent conversations between the User and the Agent.\n"
            "Extract any new learned user preferences, habits, or implicit feedback (e.g., if the user frequently corrected the agent, format preferences, or tool usage patterns).\n"
            "Format the output strictly as a JSON array of objects, where each object has a 'key' (snake_case) and a 'value' (both strings). "
            "For example: [{\"key\": \"preferred_response_length\", \"value\": \"short\"}, {\"key\": \"correction_habit\", \"value\": \"User frequently corrects syntax errors in bash commands\"}]\n"
            "If no clear preferences or habits are detected, output an empty JSON array [].\n\n"
            f"Conversations:\n{conv_text}\n\n"
            "JSON output:"
        )

        try:
            response = send_to_ollama(config, prompt)
            match = re.search(r"\[.*\]", response, re.DOTALL)
            if match:
                prefs = json.loads(match.group(0))
                inserted = []
                facts_to_store = []
                with db_session(config.db_path) as conn:
                    for p in prefs:
                        k = p.get("key")
                        v = p.get("value")
                        if k and v:
                            key = str(k)
                            value = str(v)
                            conn.execute("INSERT OR REPLACE INTO user_preferences (key, value) VALUES (?, ?)", (key, value))
                            inserted.append({"key": key, "value": value})
                            facts_to_store.append((key, value))
                for key, value in facts_to_store:
                    upsert_memory_fact(
                        config.db_path,
                        key,
                        value,
                        source_type="reflection",
                        project_slug=config.project_slug,
                        workspace_path=config.workspace_path,
                        user_id=config.user_id,
                        confidence=0.8,
                        salience_score=7.0,
                    )
                emit_json({"status": "success", "extracted_preferences": inserted})
                return 0

            emit_json({"status": "error", "message": "Failed to parse JSON array from model output.", "raw_output": response})
            return 1
        except Exception as exc:
            emit_json({"status": "error", "message": f"Reflection failed: {exc}"})
            return 1
    return 1


def handle_model_command(config: AppConfig, args) -> int:
    if args.model_action == "profiles":
        from redrum_ai.model import get_model_profiles, get_available_providers

        emit_json({
            "provider": config.model_provider,
            "model": config.model_name,
            "profiles": [profile.__dict__ for profile in get_model_profiles(config)],
            "available_providers": get_available_providers(),
        })
        return 0

    print("Error: Subcommand 'model' requires an action (profiles).", file=sys.stderr)
    return 2


def _task_row_to_dict(row) -> dict:
    data = dict(row)
    for key in ("description", "acceptance_criteria", "session_notes", "due_date", "workspace_path"):
        if data.get(key) is None:
            data[key] = ""
    return data


def _derive_task_title(request_text: str) -> str:
    compact = " ".join(request_text.split())
    if len(compact) <= 80:
        return compact
    return compact[:77].rstrip() + "..."


def handle_task_command(config: AppConfig, args) -> int:
    from redrum_memory.database import save_task

    action = args.task_action
    if not action:
        print("Error: Subcommand 'task' requires an action (intake, list, update, handoff).", file=sys.stderr)
        return 2

    if action == "intake":
        request_text = " ".join(args.request).strip()
        criteria = args.acceptance_criteria or "Task is complete when the requested outcome is done, verified, and summarized for handoff."
        save_task(
            config.db_path,
            title=_derive_task_title(request_text),
            description=request_text,
            status="ready",
            priority=args.priority,
            due_date=args.due_date,
            project_slug=config.project_slug,
            workspace_path=config.workspace_path,
            acceptance_criteria=criteria,
            session_notes="Created from natural-language intake.",
        )
        with db_session(config.db_path) as conn:
            task = conn.execute(
                "SELECT * FROM tasks WHERE project_slug = ? ORDER BY id DESC LIMIT 1",
                (config.project_slug,),
            ).fetchone()
        log_event(config.db_path, "task.intake", f"Created task {task['id']}: {task['title']}", task_id=task["id"])
        emit_json({"status": "success", "task": _task_row_to_dict(task)})
        return 0

    if action == "list":
        status_filter = "" if args.all else "AND status != 'done'"
        with db_session(config.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM tasks
                WHERE project_slug = ? {status_filter}
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        ELSE 3
                    END,
                    due_date IS NULL,
                    due_date ASC,
                    id ASC
                """,
                (config.project_slug,),
            ).fetchall()
        emit_json([_task_row_to_dict(row) for row in rows])
        return 0

    if action == "update":
        with db_session(config.db_path) as conn:
            existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (args.id,)).fetchone()
            if not existing:
                emit_json({"status": "error", "message": f"Task not found: {args.id}"})
                return 1
            notes = args.notes
            if args.append_notes:
                prior = existing["session_notes"] or ""
                separator = "\n" if prior else ""
                notes = prior + separator + args.append_notes
            if args.status:
                conn.execute("UPDATE tasks SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (args.status, args.id))
            if notes is not None:
                conn.execute("UPDATE tasks SET session_notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (notes, args.id))
            updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (args.id,)).fetchone()
        log_event(config.db_path, "task.update", f"Updated task {args.id}", task_id=args.id)
        emit_json({"status": "success", "task": _task_row_to_dict(updated)})
        return 0

    if action == "handoff":
        with db_session(config.db_path) as conn:
            if args.id:
                rows = conn.execute("SELECT * FROM tasks WHERE id = ?", (args.id,)).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM tasks
                    WHERE project_slug = ? AND status IN ('done', 'needs_review', 'blocked')
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 10
                    """,
                    (config.project_slug,),
                ).fetchall()
        tasks = [_task_row_to_dict(row) for row in rows]
        report = {
            "status": "ready_for_handoff",
            "project_slug": config.project_slug,
            "workspace_path": config.workspace_path,
            "tasks": tasks,
            "completion_criteria": "Review task statuses, acceptance criteria, and session notes before accepting handoff.",
        }
        emit_json(report)
        return 0
    return 1


def handle_it_partner_command(config: AppConfig, args) -> int:
    """Routes the massive Phase 30-49 IT Partner capabilities."""
    import importlib
    domain = args.domain
    task = " ".join(args.task) if args.task else ""
    try:
        module = importlib.import_module(f"redrum_ai.it_partner.{domain}")
        manager_class = getattr(module, f"{domain.capitalize()}Manager")
        manager = manager_class(config)
        print(manager.execute_task(task))
        return 0
    except Exception as exc:
        print(f"IT Partner execution failed: {exc}")
        return 1


def handle_metrics_command(config: AppConfig, args) -> int:
    if getattr(args, "analyze", False):
        from redrum_ai.model import send_to_ollama
        log_path = "redrum-ai.log"
        if os.path.exists(log_path):
            with open(log_path, "r") as f:
                log_data = f.read()[-15000:]
            prompt = "Analyze these recent agent logs for inefficiencies, repeated errors, or slow execution times. Provide a short, actionable self-reflection summary:\n\n" + log_data
            try:
                analysis = send_to_ollama(config, prompt)
                print("--- Self-Reflection Log Analysis ---")
                print(analysis)
                return 0
            except Exception as exc:
                print(f"Analysis failed: {exc}", file=sys.stderr)
                return 1
        else:
            print("No log file found to analyze.", file=sys.stderr)
            return 1
            
    emit_json(collect_metrics(config.db_path))
    return 0


def handle_proactive_command(config: AppConfig, args) -> int:
    from redrum_ai.proactive import generate_daily_briefing, draft_commit_message, predict_next_command
    action = args.proactive_action
    if not action:
        print("Error: Subcommand 'proactive' requires an action.", file=sys.stderr)
        return 2
        
    if action == "briefing":
        print("--- Daily Briefing ---")
        print(generate_daily_briefing(config))
        return 0
    elif action == "draft-commit":
        import subprocess
        try:
            cwd = config.workspace_path or "."
            diff = subprocess.check_output(["git", "diff", "--staged"], text=True, cwd=cwd)
            if not diff.strip():
                diff = subprocess.check_output(["git", "diff"], text=True, cwd=cwd)
            print(draft_commit_message(config, diff))
            return 0
        except Exception as e:
            print(f"Git error: {e}", file=sys.stderr)
            return 1
    elif action == "predict":
        cmd = " ".join(args.last_command)
        print(f"Suggested next command: {predict_next_command(config, cmd)}")
        return 0
    elif action == "daemon":
        from redrum_ai.proactive import run_idle_memory_consolidation
        print(run_idle_memory_consolidation(config))
        return 0
    return 1


def handle_bug_report_command(config: AppConfig) -> int:
    emit_json(build_bug_report(config.db_path, __version__))
    return 0


def handle_bootstrap_command(config: AppConfig) -> int:
    from redrum_memory.database import upsert_memory_fact
    if not config.quiet:
        print("Welcome to redrum-ai bootstrap onboarding!")
        print("Checking dependencies...")
    try:
        import pydantic
        import prompt_toolkit
    except ImportError as e:
        print(f"Missing dependency: {e}. Please run 'pip install -e .' first.", file=sys.stderr)
        return 1

    
    # 1. Run migrations
    try:
        run_migrations(config.db_path, verbose=True)
    except Exception as exc:
        print(f"Migration failed during bootstrap: {exc}", file=sys.stderr)
        return 1
        
    # 2. Seed basic preferences if they don't exist
    seed_facts: list[tuple[str, str]] = []
    with db_session(config.db_path) as conn:
        existing = conn.execute("SELECT COUNT(*) FROM user_preferences").fetchone()[0]
        if existing == 0:
            if not config.quiet:
                print("Seeding initial user preferences...")
            conn.execute("INSERT OR REPLACE INTO user_preferences (key, value) VALUES ('preferred_language', 'Python/Rust');")
            conn.execute("INSERT OR REPLACE INTO user_preferences (key, value) VALUES ('response_style', 'concise, technical');")
            conn.execute("INSERT OR REPLACE INTO user_preferences (key, value) VALUES ('editor_preference', 'VS Code/Terminal');")
            seed_facts = [
                ("preferred_language", "Python/Rust"),
                ("response_style", "concise, technical"),
                ("editor_preference", "VS Code/Terminal"),
            ]
            
        # Add initial conversation turn to welcome user
        existing_turns = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        if existing_turns == 0:
            if not config.quiet:
                print("Seeding welcome conversation...")
            conn.execute(
                """
                INSERT INTO conversations (role, content, project_slug)
                VALUES (?, ?, ?)
                """,
                ("user", "Hello, redrum-ai! Let's start working.", "redrum-ai"),
            )
            conn.execute(
                """
                INSERT INTO conversations (role, content, project_slug)
                VALUES (?, ?, ?)
                """,
                ("agent", "Hello Redrum! I am your persistent local AI partner. Ready to build, modify, and review projects together.", "redrum-ai"),
            )

    for key, value in seed_facts:
        upsert_memory_fact(
            config.db_path,
            key,
            value,
            source_type="bootstrap",
            project_slug=config.project_slug,
            workspace_path=config.workspace_path,
            user_id=config.user_id,
            confidence=0.9,
            salience_score=8.0,
        )
            
    if config.output_json:
        emit_json({
            "status": "success",
            "message": "Bootstrap completed successfully",
            "day_one_workflow": [
                "redrum-ai health --skip-ollama-check",
                "redrum-ai task intake \"Describe the first concrete task\"",
                "redrum-ai --mode planning \"Plan that task\"",
                "redrum-ai task handoff",
            ],
        })
    elif not config.quiet:
        print("\nBootstrap completed successfully! Initial preferences and welcome memory seeded.")
        print("Day one workflow:")
        print("1. redrum-ai health --skip-ollama-check")
        print("2. redrum-ai task intake \"Describe the first concrete task\"")
        print("3. redrum-ai --mode planning \"Plan that task\"")
        print("4. redrum-ai task handoff")
    return 0


def handle_chat_command(config: AppConfig) -> int:
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    except ImportError:
        print("prompt_toolkit is not installed.", file=sys.stderr)
        return 1

    os.makedirs(config.state_dir, exist_ok=True)
    history_file = os.path.join(config.state_dir, "chat_history.txt")
    session = PromptSession(history=FileHistory(history_file))
    print("Welcome to redrum-ai interactive chat! Type 'exit' or 'quit' to leave.")

    while True:
        try:
            query = session.prompt("redrum-ai> ", auto_suggest=AutoSuggestFromHistory()).strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit"):
                break
                
            prompt = construct_prompt(config, query, mode="chat", response_format="concise")
            ai_response = send_to_ollama(config, prompt)
            
            save_conversation_turn(config.db_path, "user", query, config.project_slug, config.workspace_path, config.user_id)
            save_conversation_turn(config.db_path, "agent", ai_response, config.project_slug, config.workspace_path, config.user_id)
            print() # Output already streamed via model.py, just add a newline separator
        except KeyboardInterrupt:
            print("\nAction interrupted.")
            try:
                mistake_feedback = session.prompt("Learn from Mistake: Why did you interrupt? (Press Enter to skip) > ").strip()
                if mistake_feedback:
                    save_conversation_turn(config.db_path, "user", f"I interrupted the previous action because: {mistake_feedback}. Please learn from this.", config.project_slug, config.workspace_path, config.user_id)
                    save_conversation_turn(config.db_path, "agent", "I have noted this feedback and will adjust my future actions accordingly.", config.project_slug, config.workspace_path, config.user_id)
                    print("Feedback saved.")
            except (KeyboardInterrupt, EOFError):
                print()
            continue
        except EOFError:
            break
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)

    return 0
