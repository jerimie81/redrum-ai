"""Portable hardware discovery and local-model recommendations."""
from __future__ import annotations

import json, os, platform, shutil
from pathlib import Path
from typing import Any

def _read(path: str) -> str:
    try: return Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    except OSError: return ""

def scan_hardware() -> dict[str, Any]:
    mem_kb = 0
    for line in _read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            try: mem_kb = int(line.split()[1])
            except (ValueError, IndexError): pass
    gpu = _read("/sys/class/drm/card0/device/vendor")
    return {
        "platform": platform.platform(), "system": platform.system(),
        "machine": platform.machine(), "processor": platform.processor(),
        "cpu_count": os.cpu_count() or 1, "memory_gb": round(mem_kb / 1024 / 1024, 2) if mem_kb else None,
        "gpu_vendor": gpu or None, "executables": {x: shutil.which(x) is not None for x in ("ollama", "llama-server", "docker", "podman")},
    }

def recommend_profile(info: dict[str, Any] | None = None) -> dict[str, Any]:
    info = info or scan_hardware()
    ram = info.get("memory_gb") or 8
    threads = max(1, min(int(info.get("cpu_count") or 2), 4))
    if ram <= 4: model, profile = "qwen2.5:1.5b", "constrained-edge"
    elif ram <= 8: model, profile = "gemma3:4b", "constrained-edge"
    elif ram <= 16: model, profile = "qwen2.5:7b", "standard"
    else: model, profile = "qwen2.5:14b", "quality"
    provider = "ollama" if info.get("executables", {}).get("ollama") else "llama_server"
    return {"provider": provider, "model": model, "runtime_profile": profile, "threads": threads, "reason": f"selected for approximately {ram:g} GB RAM"}

if __name__ == "__main__":
    print(json.dumps({"hardware": scan_hardware(), "recommendation": recommend_profile()}, indent=2))
