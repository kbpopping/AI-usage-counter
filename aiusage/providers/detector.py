"""
IDE & AI Provider Auto-Detector

Scans running processes, environment variables, and config file locations
to determine which IDE the user is in and which AI provider/model is active.

Supported IDEs:
  - Cursor
  - VS Code
  - Claude Code (CLI)
  - Antigravity
  - Trae
  - Windsurf
  - JetBrains (IntelliJ, PyCharm, WebStorm, etc.)
  - Neovim / Vim
  - Zed

Supported Providers:
  - Claude (Anthropic)
  - Codex / OpenAI
  - Gemini (Google)
  - OpenRouter
"""

from __future__ import annotations

import os
import sys
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Known IDE process names ────────────────────────────────────────────────

IDE_PROCESS_MAP: dict[str, str] = {
    # Process name fragment -> Human-readable IDE name
    "cursor":       "Cursor",
    "code":         "VS Code",
    "windsurf":     "Windsurf",
    "trae":         "Trae",
    "antigravity":  "Antigravity",
    "claude":       "Claude Code",
    "idea":         "IntelliJ IDEA",
    "pycharm":      "PyCharm",
    "webstorm":     "WebStorm",
    "goland":       "GoLand",
    "rider":        "Rider",
    "nvim":         "Neovim",
    "vim":          "Vim",
    "zed":          "Zed",
    "helix":        "Helix",
    "emacs":        "Emacs",
}

# ── Known AI provider env vars ─────────────────────────────────────────────

PROVIDER_ENV_SIGNALS: list[tuple[str, str, str]] = [
    # (env_var, provider, model_hint)
    ("ANTHROPIC_API_KEY",           "claude",      ""),
    ("CLAUDE_CODE_OAUTH_TOKEN",     "claude",      ""),
    ("OPENAI_API_KEY",              "codex",       "gpt-4o"),
    ("CODEX_MODEL",                 "codex",       ""),
    ("OPENROUTER_API_KEY",          "openrouter",  ""),
    ("GOOGLE_API_KEY",              "gemini",      "gemini-2.5-pro"),
    ("GEMINI_API_KEY",              "gemini",      "gemini-2.5-pro"),
    ("GOOGLE_GENERATIVE_AI_API_KEY","gemini",      "gemini-2.5-pro"),
]

# ── Model name normalisation ───────────────────────────────────────────────

MODEL_ALIASES: dict[str, str] = {
    "claude-opus-4":         "Claude Opus 4",
    "claude-opus-4-5":       "Claude Opus 4.5",
    "claude-sonnet-4-5":     "Claude Sonnet 4.5",
    "claude-sonnet-4":       "Claude Sonnet 4",
    "claude-haiku-4-5":      "Claude Haiku 4.5",
    "claude-sonnet-3-7":     "Claude Sonnet 3.7",
    "claude-sonnet-3-5":     "Claude Sonnet 3.5",
    "claude-haiku-3-5":      "Claude Haiku 3.5",
    "claude-opus-3":         "Claude Opus 3",
    "gpt-4o":                "GPT-4o",
    "gpt-4o-mini":           "GPT-4o Mini",
    "gpt-4.1":               "GPT-4.1",
    "gpt-4.1-mini":          "GPT-4.1 Mini",
    "gpt-4.1-nano":          "GPT-4.1 Nano",
    "o3":                    "o3",
    "o4-mini":               "o4-mini",
    "gemini-2.5-pro":        "Gemini 2.5 Pro",
    "gemini-2.5-flash":      "Gemini 2.5 Flash",
    "gemini-2.0-flash":      "Gemini 2.0 Flash",
    "gemini-1.5-pro":        "Gemini 1.5 Pro",
}


def friendly_model(model_id: str) -> str:
    """Return a human-friendly model name."""
    model_lower = model_id.lower()
    for key, label in MODEL_ALIASES.items():
        if model_lower.startswith(key):
            return label
    return model_id


# ── Process scanning ───────────────────────────────────────────────────────

def _list_processes() -> list[str]:
    """Return a list of running process names (lowercase)."""
    system = platform.system()
    try:
        if system == "Windows":
            result = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().splitlines()
            procs = []
            for line in lines:
                parts = line.strip('"').split('","')
                if parts:
                    procs.append(parts[0].lower())
            return procs
        else:
            result = subprocess.run(
                ["ps", "-eo", "comm"],
                capture_output=True, text=True, timeout=5
            )
            return [l.strip().lower() for l in result.stdout.splitlines()]
    except Exception:
        return []


def detect_ide() -> str:
    """Return the name of the currently running IDE, or 'Terminal'."""
    # Check TERM_PROGRAM and IDE-specific env vars first (faster than process scan)
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    vscode_pid = os.environ.get("VSCODE_PID") or os.environ.get("VSCODE_IPC_HOOK_CLI")
    cursor_env = os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_SESSION_ID")
    antigravity_env = os.environ.get("ANTIGRAVITY_ENV") or os.environ.get("ANTIGRAVITY_SESSION")
    trae_env = os.environ.get("TRAE_SESSION") or os.environ.get("TRAE_IDE")
    windsurf_env = os.environ.get("WINDSURF_EXTENSION_NAME")

    if cursor_env:
        return "Cursor"
    if antigravity_env:
        return "Antigravity"
    if trae_env:
        return "Trae"
    if windsurf_env:
        return "Windsurf"
    if vscode_pid:
        return "VS Code"
    if "cursor" in term_program:
        return "Cursor"
    if "vscode" in term_program:
        return "VS Code"

    # Check if running inside Claude Code
    if os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("ANTHROPIC_AUTH"):
        return "Claude Code"

    # Fall back to process scan
    procs = _list_processes()
    for proc_fragment, ide_name in IDE_PROCESS_MAP.items():
        if any(proc_fragment in p for p in procs):
            return ide_name

    return "Terminal"


# ── Active model detection ─────────────────────────────────────────────────

def _read_claude_last_model() -> Optional[str]:
    """Try to read the last-used Claude model from local config/logs."""
    # Check ~/.claude/settings.json or last JSONL event
    settings_path = Path.home() / ".claude" / "settings.json"
    if settings_path.exists():
        try:
            import json
            with open(settings_path) as f:
                data = json.load(f)
            model = data.get("model") or data.get("defaultModel") or data.get("last_model")
            if model:
                return model
        except Exception:
            pass

    # Scan last JSONL log
    projects_dir = Path.home() / ".claude" / "projects"
    if projects_dir.exists():
        try:
            import json
            # Find most recently modified JSONL
            jsonl_files = sorted(projects_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            for jsonl in jsonl_files[:3]:
                # Read last few lines
                with open(jsonl, encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                for line in reversed(lines[-50:]):
                    try:
                        obj = json.loads(line.strip())
                        msg = obj.get("message", {})
                        model = msg.get("model") or obj.get("model")
                        if model and "claude" in model.lower():
                            return model
                    except Exception:
                        continue
        except Exception:
            pass
    return None


def _read_codex_last_model() -> Optional[str]:
    """Try to read last Codex model from env or config."""
    model = os.environ.get("CODEX_MODEL") or os.environ.get("OPENAI_MODEL")
    if model:
        return model
    # Check ~/.codex/config.json
    cfg = Path.home() / ".codex" / "config.json"
    if cfg.exists():
        try:
            import json
            with open(cfg) as f:
                data = json.load(f)
            return data.get("model")
        except Exception:
            pass
    return None


def _read_gemini_last_model() -> Optional[str]:
    """Try to read last Gemini model from env or config."""
    return os.environ.get("GEMINI_MODEL") or os.environ.get("GOOGLE_AI_MODEL") or "gemini-2.5-pro"


@dataclass
class DetectedContext:
    ide: str = "Terminal"
    provider: str = "claude"
    model: str = ""
    model_friendly: str = ""
    confidence: str = "low"     # "high" | "medium" | "low"
    signals: list[str] = field(default_factory=list)


def detect_context() -> DetectedContext:
    """
    Detect the current IDE, AI provider, and model.
    Returns a DetectedContext with the best available information.
    """
    ctx = DetectedContext()
    ctx.ide = detect_ide()
    signals = []

    # ── Determine provider & model ─────────────────────────────────────────
    # Priority: explicit env vars > credential files > JSONL logs > defaults

    # 1. Check env vars
    for env_var, provider, model_hint in PROVIDER_ENV_SIGNALS:
        if os.environ.get(env_var):
            ctx.provider = provider
            if model_hint:
                ctx.model = model_hint
            signals.append(f"env:{env_var}")
            ctx.confidence = "medium"
            break

    # 2. Claude: check credentials file
    creds_path = Path.home() / ".claude" / ".credentials.json"
    if creds_path.exists():
        ctx.provider = "claude"
        signals.append("creds:~/.claude/.credentials.json")
        model = _read_claude_last_model()
        if model:
            ctx.model = model
            ctx.confidence = "high"
            signals.append(f"model_from_logs:{model}")

    # 3. Codex: check config
    elif (Path.home() / ".codex").exists():
        ctx.provider = "codex"
        signals.append("dir:~/.codex/")
        model = _read_codex_last_model()
        if model:
            ctx.model = model
            ctx.confidence = "high"

    # 4. Gemini: check env
    elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        ctx.provider = "gemini"
        ctx.model = _read_gemini_last_model() or "gemini-2.5-pro"
        ctx.confidence = "medium"
        signals.append("env:GEMINI_API_KEY")

    # 5. Default fallback
    if not ctx.model:
        defaults = {
            "claude":      "claude-sonnet-4-5",
            "codex":       "gpt-4o",
            "gemini":      "gemini-2.5-pro",
            "openrouter":  "gpt-4o",
        }
        ctx.model = defaults.get(ctx.provider, "claude-sonnet-4-5")
        if ctx.confidence == "low":
            signals.append("fallback:default_model")

    ctx.model_friendly = friendly_model(ctx.model)
    ctx.signals = signals
    return ctx
