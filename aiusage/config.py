"""Configuration management for aiusage."""

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    "providers": {
        "claude":      {"enabled": True},
        "codex":       {"enabled": True},
        "openrouter":  {"enabled": False, "api_key": ""},
        "gemini":      {"enabled": False, "api_key": ""},
    },
    "cache_ttl_seconds": 60,
    "timezone": "local",
}


def config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "aiusage" / "config.json"
    return Path.home() / ".config" / "aiusage" / "config.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return DEFAULT_CONFIG.copy()
    try:
        with open(path) as f:
            data = json.load(f)
        # Merge with defaults so new keys always exist
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        return merged
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"Config saved to {path}")
