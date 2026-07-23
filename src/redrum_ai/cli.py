import argparse
import sys

def read_query_from_args(args: argparse.Namespace) -> str:
    if hasattr(args, "query") and args.query:
        return " ".join(args.query).strip()

    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    return ""

def build_parser(version: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redrum-ai",
        description="Run the redrum-ai local assistant and plugin interface.",
        epilog=(
            "Examples:\n"
            "  redrum-ai health --skip-ollama-check\n"
            "  redrum-ai task intake \"Audit the backup script\" --priority high\n"
            "  redrum-ai capabilities --host-api-version 1.0.0\n"
            "  redrum-ai tool --name read_file --args '{\"path\":\"README.md\"}'\n"
            "  redrum-ai bug-report"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        help="Path to JSON configuration file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Prefer machine-readable JSON output where supported",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress nonessential human-readable status output",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output for terminals and logs",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version}",
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # chat subparser
    chat_parser = subparsers.add_parser("chat", help="Start an interactive REPL session")


    # query subparser (legacy chat fallback)
    query_parser = subparsers.add_parser("query", help="Legacy chat/query interface")
    query_parser.add_argument("query", nargs="*", help="Prompt to send to the assistant")
    query_parser.add_argument("--debug", action="store_true", help="Print the assembled prompt")
    query_parser.add_argument("--self-check", action="store_true", help="Check database and Ollama readiness")
    query_parser.add_argument(
        "--skip-ollama-check",
        action="store_true",
        help="Only check local database readiness when using --self-check",
    )
    query_parser.add_argument(
        "--mode",
        choices=["chat", "planning", "execution", "review"],
        default="chat",
        help="Interaction mode for the assistant",
    )
    query_parser.add_argument(
        "--response-format",
        choices=["concise", "plan", "report"],
        default="concise",
        help="Format structure for the response",
    )
    query_parser.add_argument(
        "--inspect-context",
        action="store_true",
        help="Print the assembled context and prompt without calling Ollama",
    )

    # capabilities subparser
    cap_p = subparsers.add_parser("capabilities", help="Display metadata of plugin capabilities and tool schemas")
    cap_p.add_argument("--host-api-version", default=None, help="Host plugin API version to negotiate against")

    # health subparser
    health_p = subparsers.add_parser("health", help="Execute startup diagnostics and health checks")
    health_p.add_argument(
        "--skip-ollama-check",
        action="store_true",
        help="Only verify database tables, skip Ollama model checks",
    )

    # tool subparser
    tool_p = subparsers.add_parser("tool", help="Directly invoke registered tool by name with arguments")
    tool_p.add_argument("--name", required=True, help="Registered tool name")
    tool_p.add_argument("--args", required=True, help="JSON arguments for the tool")

    tools_p = subparsers.add_parser("tools", help="Inspect the registered tool manifest")
    tools_sub = tools_p.add_subparsers(dest="tools_action", help="Tool manifest actions")
    tools_sub.add_parser("list", help="List registered tools")
    tools_sub.add_parser("manifest", help="Print the full tool manifest")

    # memory subparser
    memory_p = subparsers.add_parser("memory", help="Manage companion memory store")
    memory_sub = memory_p.add_subparsers(dest="memory_action", help="Memory actions")
    
    m_search = memory_sub.add_parser("search", help="Query knowledge bases")
    m_search.add_argument("text", help="Text search query")
    m_search.add_argument("--limit", type=int, default=5, help="Maximum result count")
    
    m_insert = memory_sub.add_parser("insert", help="Insert a knowledge base entry")
    m_insert.add_argument("--name", required=True, help="Knowledge base title")
    m_insert.add_argument("--content", required=True, help="Text contents")
    m_insert.add_argument("--tags", default="", help="Comma separated tags")
    m_insert.add_argument("--source-uri", default="", help="Source URI identifier")

    m_review = memory_sub.add_parser("review", help="List memory records for inspection")
    m_review.add_argument("--limit", type=int, default=50, help="Maximum records to show")
    m_review.add_argument("--type", choices=["knowledge", "facts", "reviews", "sessions"], default="knowledge")

    m_delete = memory_sub.add_parser("delete", help="Delete a knowledge base entry by ID")
    m_delete.add_argument("--id", type=int, required=True, help="Knowledge entry ID")
    m_delete.add_argument("--type", choices=["knowledge", "fact"], default="knowledge")

    memory_sub.add_parser("export", help="Export scoped memory and tasks as JSON")

    memory_sub.add_parser("reflect", help="Analyze recent conversations to extract learned user preferences and habits")
    memory_sub.add_parser("stats", help="Print memory statistics for the current scope")
    memory_sub.add_parser("consolidate", help="Run memory consolidation and deduplication")

    # model subparser
    model_p = subparsers.add_parser("model", help="Inspect model provider configuration")
    model_sub = model_p.add_subparsers(dest="model_action", help="Model actions")
    model_sub.add_parser("profiles", help="List configured model profiles")

    # task subparser
    task_p = subparsers.add_parser("task", help="Manage structured tasks and handoff reports")
    task_sub = task_p.add_subparsers(dest="task_action", help="Task actions")

    t_intake = task_sub.add_parser("intake", help="Create a structured task from a natural-language request")
    t_intake.add_argument("request", nargs="+", help="Natural-language task request")
    t_intake.add_argument("--priority", choices=["low", "medium", "high", "critical"], default="medium")
    t_intake.add_argument("--due-date", default=None, help="Optional due date or timestamp")
    t_intake.add_argument("--acceptance-criteria", default="", help="Explicit completion criteria")

    t_list = task_sub.add_parser("list", help="List tasks")
    t_list.add_argument("--all", action="store_true", help="Include completed tasks")

    t_update = task_sub.add_parser("update", help="Update task status or session notes")
    t_update.add_argument("--id", type=int, required=True, help="Task ID")
    t_update.add_argument("--status", choices=["backlog", "ready", "in_progress", "blocked", "needs_review", "done"])
    t_update.add_argument("--notes", default=None, help="Replace session notes")
    t_update.add_argument("--append-notes", default=None, help="Append to session notes")

    # IT Partner Subparser (Phases 30-49)
    it_partner_sub = subparsers.add_parser("it-partner", help="Access advanced IT Operations and SRE tools")
    it_partner_sub.add_argument("domain", choices=[
        "iac", "k8s", "sre", "cicd", "finops", "security", "data_eng", 
        "network", "mlops", "chaos", "os_kernel", "swarm", "hci", 
        "web3", "hardware", "enterprise", "reverse_eng", "rpa", 
        "quantum", "evolution"
    ], help="The IT domain to target")
    it_partner_sub.add_argument("task", nargs="+", help="Natural language description of the task")

    t_handoff = task_sub.add_parser("handoff", help="Create a ready-for-handoff report")
    t_handoff.add_argument("--id", type=int, help="Optional single task ID")

    # proactive subparsers
    proactive_p = subparsers.add_parser("proactive", help="Proactive assistance and autonomy features")
    proactive_sub = proactive_p.add_subparsers(dest="proactive_action", help="Proactive actions")
    
    proactive_sub.add_parser("briefing", help="Generate a daily personalized briefing")
    
    p_draft = proactive_sub.add_parser("draft-commit", help="Draft a commit message from git diff")
    
    p_predict = proactive_sub.add_parser("predict", help="Predict the next logical command")
    p_predict.add_argument("last_command", nargs="+", help="The last executed command")
    
    proactive_sub.add_parser("daemon", help="Run the idle memory consolidation daemon")

    # observability subparsers
    metrics_p = subparsers.add_parser("metrics", help="Display local usage and failure metrics")
    metrics_p.add_argument("--analyze", action="store_true", help="Use AI to analyze logs and find inefficiencies")
    subparsers.add_parser("bug-report", help="Capture reproducible diagnostic details")

    # bootstrap subparser
    subparsers.add_parser("bootstrap", help="Run interactive onboarding checklist to seed preferences")

    return parser
