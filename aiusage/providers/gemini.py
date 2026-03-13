"""
Gemini provider — usage & quota data via Google AI APIs.

Supports:
  - Google Generative AI API (api.generativeai.googleapis.com)
  - Google AI Studio key (aistudio.google.com)

Auth: GEMINI_API_KEY or GOOGLE_API_KEY environment variable,
      or stored in ~/.config/aiusage/config.json
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class GeminiUsage:
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    # Gemini free tier limits vary by model
    rpm_limit: Optional[int]         # requests per minute
    tpm_limit: Optional[int]         # tokens per minute
    rpd_limit: Optional[int]         # requests per day
    used_rpm: Optional[int]
    used_tpm: Optional[int]
    used_rpd: Optional[int]


# Gemini free-tier token limits (tokens per minute) by model
GEMINI_FREE_TPM: dict[str, int] = {
    "gemini-2.5-pro":   1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    "gemini-1.5-pro":   32_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-1.0-pro":   32_000,
}

GEMINI_FREE_RPM: dict[str, int] = {
    "gemini-2.5-pro":   2,
    "gemini-2.5-flash": 10,
    "gemini-2.0-flash": 15,
    "gemini-1.5-pro":   2,
    "gemini-1.5-flash": 15,
    "gemini-1.0-pro":   60,
}

GEMINI_FREE_RPD: dict[str, int] = {
    "gemini-2.5-pro":   50,
    "gemini-2.5-flash": 500,
    "gemini-2.0-flash": 1_500,
    "gemini-1.5-pro":   50,
    "gemini-1.5-flash": 1_500,
    "gemini-1.0-pro":   1_500,
}


def get_gemini_key(cfg: dict | None = None) -> Optional[str]:
    """Return the Gemini API key from env or config."""
    key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")
    )
    if key:
        return key
    if cfg:
        return cfg.get("providers", {}).get("gemini", {}).get("api_key", "")
    return None


def get_model_limits(model: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Return (tpm_limit, rpm_limit, rpd_limit) for the given model."""
    # Normalize model name
    model_lower = model.lower()
    for key in GEMINI_FREE_TPM:
        if key in model_lower:
            return GEMINI_FREE_TPM[key], GEMINI_FREE_RPM.get(key), GEMINI_FREE_RPD.get(key)
    # Default: gemini-2.5-pro limits
    return 1_000_000, 2, 50


@dataclass
class GeminiCredits:
    """Simplified credits/quota summary for display."""
    model: str
    tpm_limit: int
    rpm_limit: int
    rpd_limit: int
    # We can't query live usage from the free API,
    # so we compute from local JSONL-equivalent data
    tokens_used_today: int = 0
    requests_today: int = 0
    remaining_pct: float = 100.0


def fetch_quota(cfg: dict | None = None, model: str = "gemini-2.5-pro") -> tuple[Optional[GeminiCredits], Optional[str]]:
    """
    Return quota info for Gemini.
    Since Gemini doesn't expose a live usage endpoint publicly,
    we return the known free-tier limits and local usage counts.
    """
    key = get_gemini_key(cfg)
    if not key:
        return None, "No Gemini API key found. Set GEMINI_API_KEY or run `aiusage config --set-gemini-key <key>`."

    tpm, rpm, rpd = get_model_limits(model)

    return GeminiCredits(
        model=model,
        tpm_limit=tpm or 1_000_000,
        rpm_limit=rpm or 10,
        rpd_limit=rpd or 500,
    ), None
