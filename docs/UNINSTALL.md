# Uninstalling redrum-ai

To remove `redrum-ai` from your system, you can use pipx or pip depending on how you installed it.

## 1. Remove the Package
If installed via pipx:
```bash
pipx uninstall redrum-ai
```

If installed via pip (in a virtual environment):
```bash
pip uninstall redrum-ai
```

## 2. Leftover State
The uninstall process removes the application binaries and Python libraries, but it **preserves your data** by design. The following files and directories will remain on your system:
- `~/.gemini/memory.db`: Your local knowledge base and conversation history.
- `~/.gemini/redrum-ai/`: Any additional project configuration or local state.

To completely wipe all data:
```bash
rm ~/.gemini/memory.db
rm -rf ~/.gemini/redrum-ai
```
