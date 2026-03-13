"""
JSONL log parser for Claude Code / Codex CLI session files.

Claude Code stores session logs at:
  ~/.claude/projects/<encoded-path>/<session-uuid>.jsonl

Each line is a JSON event. We extract lines of type "assistant" that
contain a "usage" field with token counts.
"""

from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass
class UsageRecord:
    timestamp: datetime
    session_id: str
    project: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    provider: str = "claude"

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def all_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_write_tokens + self.cache_read_tokens


def _claude_projects_dirs() -> list[Path]:
    """Return all directories that might contain Claude Code project JSONL logs."""
    candidates = [
        Path.home() / ".claude" / "projects",
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "claude" / "projects",
    ]
    return [p for p in candidates if p.exists()]


def _codex_projects_dirs() -> list[Path]:
    """Return all directories that might contain Codex JSONL logs."""
    candidates = [
        Path.home() / ".codex" / "sessions",
        Path.home() / ".openai" / "codex" / "sessions",
        Path(os.environ.get("CODEX_HOME", "")) / "sessions" if os.environ.get("CODEX_HOME") else None,
    ]
    return [p for p in candidates if p and p.exists()]


def _parse_jsonl_file(
    path: Path,
    session_id: str,
    project: str,
    provider: str = "claude",
) -> Iterator[UsageRecord]:
    """Yield UsageRecords from a single JSONL file."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Claude Code format
                usage = None
                model = ""
                ts = None

                if provider == "claude":
                    # Claude Code JSONL: {"type": "assistant", "message": {"usage": {...}, "model": "..."}, "timestamp": "..."}
                    msg_type = obj.get("type", "")
                    if msg_type == "assistant":
                        msg = obj.get("message", {})
                        usage = msg.get("usage")
                        model = msg.get("model", "")
                        ts_raw = obj.get("timestamp", "")
                        if ts_raw:
                            try:
                                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                            except ValueError:
                                ts = None
                    # Some versions nest differently
                    elif "usage" in obj and "model" in obj:
                        usage = obj.get("usage")
                        model = obj.get("model", "")
                        ts_raw = obj.get("timestamp", obj.get("created_at", ""))
                        if ts_raw:
                            try:
                                ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                            except (ValueError, TypeError):
                                ts = None

                elif provider == "codex":
                    # Codex format varies; try common fields
                    for usage_key in ("usage", "token_usage"):
                        if usage_key in obj:
                            usage = obj[usage_key]
                            model = obj.get("model", "gpt-4o")
                            ts_raw = obj.get("timestamp", obj.get("created", ""))
                            if ts_raw:
                                try:
                                    if isinstance(ts_raw, (int, float)):
                                        ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
                                    else:
                                        ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                                except (ValueError, TypeError):
                                    ts = None
                            break

                if not usage or not model:
                    continue
                if ts is None:
                    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

                # Override provider if the model indicates a different backend
                actual_provider = provider
                if "gemini" in model.lower():
                    actual_provider = "gemini"

                yield UsageRecord(
                    timestamp=ts,
                    session_id=session_id,
                    project=project,
                    model=model,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cache_write_tokens=usage.get("cache_creation_input_tokens", 0),
                    cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                    provider=actual_provider,
                )
    except (OSError, PermissionError):
        return


def load_all_records(provider: str = "all") -> list[UsageRecord]:
    """Load and return all usage records from local JSONL logs."""
    records: list[UsageRecord] = []

    if provider in ("all", "claude"):
        for base in _claude_projects_dirs():
            for jsonl_path in base.rglob("*.jsonl"):
                # project name = parent dir name, decoded from path encoding
                project_dir = jsonl_path.parent.name
                # Claude encodes the path with hyphens replacing slashes
                project_label = project_dir.replace("-", "/").strip("/")
                # Use last 2 path components as label
                parts = [p for p in project_label.split("/") if p]
                project_label = "/".join(parts[-2:]) if len(parts) >= 2 else (parts[0] if parts else project_dir)
                session_id = jsonl_path.stem
                for rec in _parse_jsonl_file(jsonl_path, session_id, project_label, "claude"):
                    records.append(rec)

    if provider in ("all", "codex"):
        for base in _codex_projects_dirs():
            for jsonl_path in base.rglob("*.jsonl"):
                project_label = jsonl_path.parent.name
                session_id = jsonl_path.stem
                for rec in _parse_jsonl_file(jsonl_path, session_id, project_label, "codex"):
                    records.append(rec)

    return sorted(records, key=lambda r: r.timestamp)
