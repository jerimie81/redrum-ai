"""Small standalone memory-ai CLI (``python -m redrum_memory``)."""
import argparse, json
from .engine import MemoryEngine

def main() -> int:
    parser = argparse.ArgumentParser(prog="memory-ai")
    parser.add_argument("db")
    parser.add_argument("action", choices=["search", "export", "purge"])
    parser.add_argument("value", nargs="?")
    parser.add_argument("--project", default="unknown")
    parser.add_argument("--workspace", default="")
    args = parser.parse_args()
    engine = MemoryEngine(args.db, project_slug=args.project, workspace_path=args.workspace)
    value = engine.search(args.value or "") if args.action == "search" else engine.export() if args.action == "export" else {"deleted": engine.purge(before=args.value)}
    print(json.dumps(value, indent=2, default=str))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
