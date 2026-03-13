"""
Claude provider.

Live rate-limit data:  GET https://api.anthropic.com/api/oauth/usage
Auth:  Bearer <access_token> from ~/.claude/.credentials.json
       (or macOS Keychain on Mac)
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# ── credential loading ─────────────────────────────────────────────────────

def _creds_file_path() -> Optional[Path]:
    """Return path to ~/.claude/.credentials.json if it exists."""
    path = Path.home() / ".claude" / ".credentials.json"
    return path if path.exists() else None


def _load_creds_file() -> Optional[dict]:
    path = _creds_file_path()
    if not path:
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _load_creds_keychain() -> Optional[dict]:
    """Try to read credentials from macOS Keychain (service: Claude Code-credentials)."""
    if platform.system() != "Darwin":
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
    except Exception:
        pass
    return None


def get_access_token() -> Optional[str]:
    """Return a valid OAuth access token for the Claude API."""
    # 1. Environment variable (highest priority)
    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
    if env_token:
        return env_token

    # 2. ~/.claude/.credentials.json
    creds = _load_creds_file()
    if creds:
        oauth = creds.get("claudeAiOauth") or creds
        token = oauth.get("accessToken")
        if token:
            # Check expiry
            expires_at = oauth.get("expiresAt", 0)
            if expires_at:
                import time
                # expiresAt is in milliseconds
                if expires_at / 1000 > time.time() + 30:
                    return token
            else:
                return token

    # 3. macOS Keychain
    creds = _load_creds_keychain()
    if creds:
        oauth = creds.get("claudeAiOauth") or creds
        token = oauth.get("accessToken")
        if token:
            return token

    return None


# ── live usage API ─────────────────────────────────────────────────────────

@dataclass
class ClaudeUsage:
    five_hour_pct: Optional[float]
    five_hour_resets_at: Optional[datetime]
    seven_day_pct: Optional[float]
    seven_day_resets_at: Optional[datetime]
    seven_day_sonnet_pct: Optional[float]
    extra_usage_enabled: bool
    monthly_limit: Optional[float]
    raw: dict


def fetch_live_usage() -> tuple[Optional[ClaudeUsage], Optional[str]]:
    """
    Call the Anthropic OAuth usage API.
    Returns (ClaudeUsage, None) on success, or (None, error_message) on failure.
    """
    token = get_access_token()
    if not token:
        return None, "No Claude credentials found. Run `claude` and log in first."

    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(
            "https://api.anthropic.com/api/oauth/usage",
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 429:
            return None, f"Rate limited by usage API (HTTP 429). Try again in a minute.\n{body}"
        if e.code == 401:
            return None, "Unauthorized (HTTP 401). Your access token may have expired. Re-run `claude` to refresh."
        return None, f"HTTP {e.code}: {body}"
    except Exception as ex:
        return None, f"Network error: {ex}"

    def parse_dt(s: Optional[str]) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    fh = data.get("five_hour") or {}
    sd = data.get("seven_day") or {}
    sd_s = data.get("seven_day_sonnet") or {}
    ex = data.get("extra_usage") or {}

    return ClaudeUsage(
        five_hour_pct=fh.get("utilization"),
        five_hour_resets_at=parse_dt(fh.get("resets_at")),
        seven_day_pct=sd.get("utilization"),
        seven_day_resets_at=parse_dt(sd.get("resets_at")),
        seven_day_sonnet_pct=sd_s.get("utilization"),
        extra_usage_enabled=ex.get("is_enabled", False),
        monthly_limit=ex.get("monthly_limit"),
        raw=data,
    ), None
