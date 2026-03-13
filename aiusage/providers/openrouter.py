"""
OpenRouter provider.
Fetches credit balance from https://openrouter.ai/api/v1/credits
using an API key stored in config or OPENROUTER_API_KEY env var.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional


@dataclass
class OpenRouterUsage:
    total_credits: float
    usage: float
    remaining: float


def get_api_key(config: dict) -> Optional[str]:
    return (
        os.environ.get("OPENROUTER_API_KEY")
        or config.get("providers", {}).get("openrouter", {}).get("api_key", "")
        or None
    )


def fetch_credits(config: dict) -> tuple[Optional[OpenRouterUsage], Optional[str]]:
    key = get_api_key(config)
    if not key:
        return None, "No OpenRouter API key. Set OPENROUTER_API_KEY or add it to ~/.config/aiusage/config.json"

    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return None, f"OpenRouter HTTP {e.code}: {e.read().decode(errors='replace')}"
    except Exception as ex:
        return None, f"OpenRouter error: {ex}"

    d = data.get("data", data)
    total = d.get("total_credits", d.get("total", 0))
    usage = d.get("usage", 0)
    return OpenRouterUsage(
        total_credits=total,
        usage=usage,
        remaining=total - usage,
    ), None
