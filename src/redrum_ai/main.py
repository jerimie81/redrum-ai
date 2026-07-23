import sqlite3
import sys
import os
import json
import logging
import time
import subprocess
import shutil
import resource
import socket
import urllib.parse
from pathlib import Path
from redrum_ai.config import load_config, AppConfig
from redrum_memory.database import (
    check_database,
    save_conversation_turn,
    prune_memories,
    get_relevant_knowledge,
    list_knowledge_entries,
    delete_knowledge_entry,
    export_memory,
    db_session,
    fetch_table_names
)
from redrum_ai.model import check_ollama, send_to_ollama
from redrum_ai.offline import (
    get_offline_project_assessment,
    get_offline_project_review,
    get_offline_question_response,
    get_offline_response,
)
from redrum_ai.prompt import construct_prompt
from redrum_ai.cli import build_parser, read_query_from_args
from redrum_memory.migrations import run_migrations
from redrum_ai.telemetry import build_bug_report, classify_error, collect_metrics, log_event, new_session_id
from redrum_ai.web_access import answer as live_web_answer
__version__ = "0.1.0"

def emit_json(payload) -> None:
    print(json.dumps(payload, indent=2))

def setup_logger(config: AppConfig):
    verbose = config.verbose
    logger = logging.getLogger("redrum_ai")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if not logger.handlers:
        # Create a log file inside the current project workspace directory or fallback to current dir
        import os
        from logging.handlers import RotatingFileHandler
        os.makedirs(config.state_dir, exist_ok=True)
        log_path = os.path.join(config.state_dir, "redrum-ai.log")
        fh = RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=3)
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "session_id": "%(process)d", "message": "%(message)s"}'
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
        # Add stdout stream handler if verbose
        if verbose:
            sh = logging.StreamHandler(sys.stderr)
            sh.setFormatter(logging.Formatter("[LOG] %(levelname)s: %(message)s"))
            logger.addHandler(sh)
    return logger

def summarize_older_conversations(config: AppConfig) -> None:
    from redrum_memory.database import get_unsummarized_conversations, save_conversation_summary
    
    unsummarized = get_unsummarized_conversations(config.db_path, config.project_slug)
    if len(unsummarized) < 4:
        return
        
    lines = []
    for row in unsummarized:
        role = row["role"]
        content = row["content"]
        lines.append(f"{role.capitalize()}: {content}")
    conv_text = "\n".join(lines)
    
    prompt = (
        "You are redrum-ai. Summarize the following dialogue between the User and the Agent "
        "into a single concise paragraph. Focus on key decisions made, code changed, or tasks completed:\n\n"
        f"{conv_text}\n\n"
        "Summary:"
    )
    
    try:
        if config.verbose:
            print("Summarizing older conversations in background...", file=sys.stderr)
        summary = send_to_ollama(config, prompt)
        
        start_id = unsummarized[0]["id"]
        end_id = unsummarized[-1]["id"]
        save_conversation_summary(
            config.db_path,
            summary,
            start_id,
            end_id,
            project_slug=config.project_slug,
            workspace_path=config.workspace_path
        )
        if config.verbose:
            print(f"Saved summary for conversation IDs {start_id} to {end_id}.", file=sys.stderr)
    except Exception as exc:
        if config.verbose:
            print(f"Failed to summarize older conversations: {exc}", file=sys.stderr)

















def main_entry(argv: list[str] | None = None) -> int:
    from redrum_ai.errors import RedrumError
    try:
        return _main_impl(argv)
    except RedrumError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1

def _main_impl(argv: list[str] | None = None) -> int:
    from redrum_ai.commands import handle_capabilities_command, handle_health_command, handle_tool_command, handle_tools_command, handle_memory_command, handle_model_command, handle_task_command, handle_it_partner_command, handle_metrics_command, handle_proactive_command, handle_bug_report_command, handle_bootstrap_command, handle_chat_command

    if argv is None:
        argv = sys.argv[1:]

    # Legacy query subcommand fallback interceptor
    subcommands = {"chat", "capabilities", "health", "tool", "tools", "memory", "model", "task", "metrics", "bug-report", "bootstrap", "query"}
    has_sub = False
    
    for arg in argv:
        if not arg.startswith("-"):
            if arg in subcommands:
                has_sub = True
            break
            
    if not has_sub and len(argv) > 0 and argv[0] not in ["--version", "-h", "--help"]:
        import difflib
        insert_idx = 0
        while insert_idx < len(argv):
            if argv[insert_idx] == "--config" and insert_idx + 1 < len(argv):
                insert_idx += 2
            elif argv[insert_idx] in ["--verbose", "-v"]:
                insert_idx += 1
            else:
                break
                
        if len(argv) > insert_idx:
            possible_command = argv[insert_idx]
            if not possible_command.startswith("-"):
                matches = difflib.get_close_matches(possible_command, subcommands, n=1, cutoff=0.7)
                if matches:
                    print(f"Unknown command '{possible_command}'. Did you mean '{matches[0]}'?\nFalling back to chat query...", file=sys.stderr)
                    
        if len(argv) == 0:
            argv.append("chat")
        else:
            argv.insert(insert_idx, "query")

    parser = build_parser(__version__)
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config_path)
    except Exception as exc:
        from redrum_ai.errors import ConfigurationError
        raise ConfigurationError(f"Configuration error: {exc}")

    config.verbose = args.verbose
    config.output_json = args.output_json
    config.quiet = args.quiet
    config.no_color = args.no_color
    
    # Setup structured logger
    logger = setup_logger(config)
    logger.info(f"Running redrum-ai subcommand: '{args.subcommand}'")
    
    if config.runtime_profile == "constrained-edge":
        edge_warnings = check_edge_environment(config)
        if edge_warnings:
            for w in edge_warnings:
                print(f"[EDGE WARNING] {w}", file=sys.stderr)
        # Edge auto-launch is only relevant to local llama runtimes.  Never
        # replace a user-selected hosted or OpenAI-compatible provider.
        if config.model_provider in {"llama_cpp", "llama_server"}:
            launch_edge_llama_server(config)
            config.model_provider = "llama_server"

    # If capabilities sub-command is given, return early without db checks
    if args.subcommand == "capabilities":
        return handle_capabilities_command(args)

    # Database check and run migrations
    try:
        run_migrations(config.db_path, config.verbose)
    except Exception as exc:
        logger.error(f"Migration error: {exc}")
        log_event(
            config.db_path,
            "error",
            f"Migration error: {exc}",
            severity="error",
            metadata=json.dumps({"classification": classify_error(str(exc))}),
        )
        from redrum_ai.errors import DatabaseError
        raise DatabaseError(f"Migration error: {exc}")

    # Route Subcommands
    if args.subcommand == "health":
        return handle_health_command(config, args)
        
    elif args.subcommand == "tool":
        return handle_tool_command(config, args)

    elif args.subcommand == "tools":
        return handle_tools_command(config, args)
        
    elif args.subcommand == "memory":
        return handle_memory_command(config, args)

    elif args.subcommand == "model":
        return handle_model_command(config, args)

    elif args.subcommand == "it-partner":
        return handle_it_partner_command(config, args)
    elif args.subcommand == "metrics":
        return handle_metrics_command(config, args)

    elif args.subcommand == "task":
        return handle_task_command(config, args)

    elif args.subcommand == "proactive":
        return handle_proactive_command(config, args)

    elif args.subcommand == "metrics":
        return handle_metrics_command(config, args)

    elif args.subcommand == "bug-report":
        return handle_bug_report_command(config)
        
    elif args.subcommand == "bootstrap":
        return handle_bootstrap_command(config)

    elif args.subcommand == "chat":
        return handle_chat_command(config)


    elif args.subcommand == "query":
        # Legacy/Single-turn query execution
        if args.self_check:
            db_health = check_database(config.db_path)
            for msg in db_health.messages:
                print(msg)
            
            ollama_ok = True
            if not args.skip_ollama_check:
                ollama_health = check_ollama(config)
                for msg in ollama_health.messages:
                    print(msg)
                ollama_ok = ollama_health.ok

            return 0 if (db_health.ok and ollama_ok) else 1

        query = read_query_from_args(args)
        if not query:
            parser.print_usage(sys.stderr)
            return 2

        db_health = check_database(config.db_path)
        if not db_health.ok:
            from redrum_ai.errors import DatabaseError
            messages = ", ".join(db_health.messages)
            raise DatabaseError(f"Database error: {messages}")

        if config.allow_web_access:
            try:
                live_answer = live_web_answer(query)
            except Exception as exc:
                print(f"[WEB WARNING] live lookup failed: {exc}", file=sys.stderr)
                live_answer = None
            if live_answer:
                save_conversation_turn(config.db_path, "user", query, project_slug=config.project_slug, workspace_path=config.workspace_path, user_id=config.user_id)
                save_conversation_turn(config.db_path, "agent", live_answer, project_slug=config.project_slug, workspace_path=config.workspace_path, user_id=config.user_id)
                print(live_answer)
                return 0

        offline_assessment = get_offline_project_assessment(query)
        if offline_assessment is not None:
            save_conversation_turn(
                config.db_path,
                "user",
                query,
                project_slug=config.project_slug,
                workspace_path=config.workspace_path,
                user_id=config.user_id,
            )
            save_conversation_turn(
                config.db_path,
                "agent",
                offline_assessment,
                project_slug=config.project_slug,
                workspace_path=config.workspace_path,
                user_id=config.user_id,
            )
            logger.info("Answered path-aware project assessment request without contacting Ollama")
            print(offline_assessment)
            return 0

        offline_review = get_offline_project_review(query, config.workspace_path)
        if offline_review is not None:
            save_conversation_turn(
                config.db_path,
                "user",
                query,
                project_slug=config.project_slug,
                workspace_path=config.workspace_path,
                user_id=config.user_id,
            )
            save_conversation_turn(
                config.db_path,
                "agent",
                offline_review,
                project_slug=config.project_slug,
                workspace_path=config.workspace_path,
                user_id=config.user_id,
            )
            logger.info("Answered project review request via offline fallback without contacting Ollama")
            print(offline_review)
            return 0

        offline_response = get_offline_response(query)
        if offline_response is not None:
            save_conversation_turn(
                config.db_path,
                "user",
                query,
                project_slug=config.project_slug,
                workspace_path=config.workspace_path,
                user_id=config.user_id,
            )
            save_conversation_turn(
                config.db_path,
                "agent",
                offline_response,
                project_slug=config.project_slug,
                workspace_path=config.workspace_path,
                user_id=config.user_id,
            )
            logger.info("Answered via offline fallback without contacting Ollama")
            print(offline_response)
            return 0

        if args.inspect_context:
            prompt = construct_prompt(
                config,
                query,
                mode=args.mode,
                response_format=args.response_format
            )
            print(prompt)
            return 0

        ollama_health = check_ollama(config)
        for message in ollama_health.messages:
            if not message.endswith("ready"):
                print(f"[MODEL WARNING] {message}", file=sys.stderr)
        if not ollama_health.ok:
            offline_answer = get_offline_question_response(query, config)
            if offline_answer:
                save_conversation_turn(
                    config.db_path,
                    "user",
                    query,
                    project_slug=config.project_slug,
                    workspace_path=config.workspace_path,
                    user_id=config.user_id,
                )
                save_conversation_turn(
                    config.db_path,
                    "agent",
                    offline_answer,
                    project_slug=config.project_slug,
                    workspace_path=config.workspace_path,
                    user_id=config.user_id,
                )
                logger.info("Answered question via offline fallback without contacting Ollama")
                print(offline_answer)
                return 0
            from redrum_ai.errors import ModelConnectionError
            messages = ", ".join(ollama_health.messages)
            raise ModelConnectionError(f"Ollama error: {messages}")

        summarize_older_conversations(config)

        if args.mode in ["execution", "planning"]:
            from redrum_ai.runner import run_agent_loop
            try:
                result_report = run_agent_loop(config, query)
                print(result_report)
                return 0
            except Exception as exc:
                logger.error(f"Agent loop error: {exc}")
                log_event(
                    config.db_path,
                    "error",
                    f"Agent loop error: {exc}",
                    severity="error",
                    metadata=json.dumps({"classification": classify_error(str(exc))}),
                )
                from redrum_ai.errors import AgentExecutionError
                raise AgentExecutionError(f"Agent Loop Execution Error: {exc}")

        try:
            start_prompt_time = time.time()
            prompt = construct_prompt(
                config,
                query,
                mode=args.mode,
                response_format=args.response_format
            )
            
            if args.debug or config.verbose:
                print("Generated prompt:\n---", file=sys.stderr)
                print(prompt, file=sys.stderr)
                print("---\n", file=sys.stderr)

            ai_response = send_to_ollama(config, prompt)
            latency = time.time() - start_prompt_time
            logger.info(f"Ollama prompt executed in {latency:.3f}s")
            
            save_conversation_turn(
                config.db_path,
                "user",
                query,
                project_slug=config.project_slug,
                workspace_path=config.workspace_path,
                user_id=config.user_id,
            )
            save_conversation_turn(
                config.db_path,
                "agent",
                ai_response,
                project_slug=config.project_slug,
                workspace_path=config.workspace_path,
                user_id=config.user_id,
            )

            pruned = prune_memories(config.db_path, project_slug=config.project_slug)
            if config.verbose and pruned:
                print(f"Pruned {pruned} old conversation turns from memory.", file=sys.stderr)

        except (RuntimeError, sqlite3.Error) as exc:
            logger.error(f"Execution error: {exc}")
            log_event(
                config.db_path,
                "error",
                f"Execution error: {exc}",
                severity="error",
                metadata=json.dumps({"classification": classify_error(str(exc))}),
            )
            from redrum_ai.errors import RedrumError
            raise RedrumError(f"Execution error: {exc}")

        print(ai_response)
        return 0

    return 1

def check_edge_environment(config: AppConfig) -> list[str]:
    warnings = []
    try:
        zram_active = False
        if os.path.exists("/proc/swaps"):
            with open("/proc/swaps", "r") as f:
                if "zram" in f.read():
                    zram_active = True
        if not zram_active:
            warnings.append("ZRam swap is not active. This may cause OOM errors on constrained edge hardware.")
            
        model_path = resolve_edge_model_path(config)
        if not model_path:
            warnings.append("No GGUF model found for vmtouch; set REDRUM_AI_MODEL_PATH to the model file.")
        elif not ensure_vmtouch_lock(model_path, config):
            try:
                memlock_mb = resource.getrlimit(resource.RLIMIT_MEMLOCK)[0] / (1024 * 1024)
                model_mb = os.path.getsize(model_path) / (1024 * 1024)
                warnings.append(f"vmtouch cannot lock {model_path}: memlock limit is {memlock_mb:.0f} MiB but model is {model_mb:.0f} MiB. Run setup_edge_optimizations.sh as root and start a new login session.")
            except OSError:
                warnings.append(f"vmtouch could not lock model {model_path}. Check the memlock limit and permissions.")
    except Exception as exc:
        warnings.append(f"Failed to check edge environment: {exc}")
    
    return warnings


def resolve_edge_model_path(config: AppConfig) -> str | None:
    """Find the actual GGUF used by the edge profile, not an Ollama blob guess."""
    configured = os.path.expanduser(config.edge_model_path.strip()) if config.edge_model_path else ""
    candidates = [configured]
    if os.path.isabs(config.llama_cpp_filename):
        candidates.append(os.path.expanduser(config.llama_cpp_filename))
    candidates.extend([
        os.path.expanduser("~/.ollama/models/blobs/sha256-gemma-3-4b-it-Q4_0.gguf"),
        os.path.expanduser("~/usb-ai/AI/models/gemma-2-2b-it-Q4_K_M.gguf"),
        os.path.expanduser("~/models/gemma-2-2b-it-Q4_K_M.gguf"),
    ])
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.realpath(candidate)
    return None


def _vmtouch_running_for(model_path: str) -> bool:
    try:
        output = subprocess.check_output(["ps", "-eo", "args="], text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return False
    return "vmtouch" in output and model_path in output


def ensure_vmtouch_lock(model_path: str, config: AppConfig) -> bool:
    """Start one persistent vmtouch lock daemon and verify its target path."""
    if _vmtouch_running_for(model_path):
        return True
    if not shutil.which("vmtouch"):
        return False
    try:
        soft_limit, _ = resource.getrlimit(resource.RLIMIT_MEMLOCK)
        model_size = os.path.getsize(model_path)
        if soft_limit != resource.RLIM_INFINITY and soft_limit < model_size:
            return False
    except (OSError, ValueError):
        return False
    state_dir = Path(config.state_dir or os.path.expanduser("~/.local/state/redrum-ai"))
    state_dir.mkdir(parents=True, exist_ok=True)
    pidfile = state_dir / "vmtouch-model.pid"
    log_path = state_dir / "vmtouch-model.log"
    try:
        with log_path.open("ab") as log:
            subprocess.Popen(
                ["vmtouch", "-dl", "-w", "-P", str(pidfile), model_path],
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        for _ in range(20):
            time.sleep(0.1)
            if _vmtouch_running_for(model_path):
                return True
    except (OSError, ValueError):
        return False
    return False

def launch_edge_llama_server(config: AppConfig):
    # A constrained profile must remain usable on hosts without a local
    # llama-server binary (and in restricted containers where socket creation
    # itself may be denied).  Fall back to the configured provider cleanly.
    server_binary = "/usr/local/lib/ollama/llama-server"
    if not os.path.exists(server_binary):
        if not config.quiet:
            print(f"Warning: {server_binary} not found. Cannot auto-launch edge server.", file=sys.stderr)
        return

    parsed = urllib.parse.urlparse(config.llama_server_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8080

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            try:
                s.connect((host, port))
                return
            except (ConnectionRefusedError, TimeoutError, OSError):
                pass
    except OSError as exc:
        if not config.quiet:
            print(f"Warning: unable to probe llama-server at {host}:{port}: {exc}", file=sys.stderr)
        return
            
    if not config.quiet:
        print("Launching optimized llama-server for constrained-edge profile...", file=sys.stderr)
    
    model_path = resolve_edge_model_path(config)
    if not model_path:
        if not config.quiet:
            print("Warning: no GGUF model found for constrained-edge llama-server.", file=sys.stderr)
        return
        
    cmd = [
        server_binary,
        "--model", model_path,
        "--no-mmap",
        "--threads", "2",
        "--parallel", "1",
        "--cache-type-k", "q8_0",
        "--cram", "256",
        "--ub", "256",
        "--ctx-size", "8192",
        "--port", str(port)
    ]
    
    if not os.path.exists(cmd[0]):
        if not config.quiet:
            print(f"Warning: {cmd[0]} not found. Cannot auto-launch edge server.", file=sys.stderr)
        return
        
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
    except Exception as exc:
        if not config.quiet:
            print(f"Failed to launch llama-server: {exc}", file=sys.stderr)

if __name__ == "__main__":
    sys.exit(main_entry())
