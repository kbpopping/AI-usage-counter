"""Aggregate UsageRecords into daily/monthly/session/block summaries."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from .parser import UsageRecord
from .pricing import calc_cost


def _local_date(ts: datetime) -> str:
    """Convert a UTC datetime to local date string YYYY-MM-DD."""
    try:
        local_ts = ts.astimezone()
    except Exception:
        local_ts = ts
    return local_ts.strftime("%Y-%m-%d")


def _local_month(ts: datetime) -> str:
    try:
        local_ts = ts.astimezone()
    except Exception:
        local_ts = ts
    return local_ts.strftime("%Y-%m")


def aggregate_daily(records: list[UsageRecord]) -> list[dict]:
    """Group records by (date, provider) and sum tokens + cost."""
    groups: dict[tuple, dict] = defaultdict(lambda: {
        "input": 0, "output": 0, "cache_write": 0, "cache_read": 0,
        "total_tokens": 0, "cost": 0.0, "messages": 0,
    })

    for rec in records:
        key = (_local_date(rec.timestamp), rec.provider)
        g = groups[key]
        g["input"]       += rec.input_tokens
        g["output"]      += rec.output_tokens
        g["cache_write"] += rec.cache_write_tokens
        g["cache_read"]  += rec.cache_read_tokens
        g["total_tokens"]+= rec.total_tokens
        g["cost"]        += calc_cost(rec.model, rec.input_tokens, rec.output_tokens,
                                      rec.cache_write_tokens, rec.cache_read_tokens)
        g["messages"]    += 1

    rows = []
    for (date, provider), g in sorted(groups.items()):
        rows.append({"date": date, "provider": provider, **g})
    return rows


def aggregate_monthly(records: list[UsageRecord]) -> list[dict]:
    groups: dict[tuple, dict] = defaultdict(lambda: {
        "input": 0, "output": 0, "cache_write": 0, "cache_read": 0,
        "total_tokens": 0, "cost": 0.0, "sessions": set(), "messages": 0,
    })

    for rec in records:
        key = (_local_month(rec.timestamp), rec.provider)
        g = groups[key]
        g["input"]       += rec.input_tokens
        g["output"]      += rec.output_tokens
        g["cache_write"] += rec.cache_write_tokens
        g["cache_read"]  += rec.cache_read_tokens
        g["total_tokens"]+= rec.total_tokens
        g["cost"]        += calc_cost(rec.model, rec.input_tokens, rec.output_tokens,
                                      rec.cache_write_tokens, rec.cache_read_tokens)
        g["sessions"].add(rec.session_id)
        g["messages"]    += 1

    rows = []
    for (month, provider), g in sorted(groups.items()):
        rows.append({
            "month": month, "provider": provider,
            **{k: v for k, v in g.items() if k != "sessions"},
            "sessions": len(g["sessions"]),
        })
    return rows


def aggregate_sessions(records: list[UsageRecord]) -> list[dict]:
    groups: dict[str, dict] = defaultdict(lambda: {
        "project": "", "provider": "", "model": "",
        "input": 0, "output": 0, "cache_write": 0, "cache_read": 0,
        "total_tokens": 0, "cost": 0.0, "messages": 0,
        "last_active": None, "models": set(),
    })

    for rec in records:
        g = groups[rec.session_id]
        g["project"]     = rec.project
        g["provider"]    = rec.provider
        g["models"].add(rec.model)
        g["input"]       += rec.input_tokens
        g["output"]      += rec.output_tokens
        g["cache_write"] += rec.cache_write_tokens
        g["cache_read"]  += rec.cache_read_tokens
        g["total_tokens"]+= rec.total_tokens
        g["cost"]        += calc_cost(rec.model, rec.input_tokens, rec.output_tokens,
                                      rec.cache_write_tokens, rec.cache_read_tokens)
        g["messages"]    += 1
        if g["last_active"] is None or rec.timestamp > g["last_active"]:
            g["last_active"] = rec.timestamp

    rows = []
    for session_id, g in groups.items():
        # Pick the most common model
        models = g.pop("models")
        g["model"] = max(models, key=lambda m: m) if models else ""
        rows.append({"session_id": session_id, **g})

    return sorted(rows, key=lambda r: r.get("last_active") or datetime.min.replace(tzinfo=None), reverse=True)


def aggregate_blocks(records: list[UsageRecord], block_hours: int = 5) -> list[dict]:
    """
    Group records into N-hour windows aligned to block_hours boundaries.
    Blocks start at midnight UTC, offset by multiples of block_hours.
    """
    if not records:
        return []

    block_delta = timedelta(hours=block_hours)

    def block_start(ts: datetime) -> datetime:
        utc = ts.astimezone(timezone.utc).replace(tzinfo=timezone.utc)
        midnight = utc.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = (utc - midnight).total_seconds()
        block_n = int(elapsed / block_delta.total_seconds())
        return midnight + block_delta * block_n

    groups: dict[datetime, dict] = defaultdict(lambda: {
        "total_tokens": 0, "cost": 0.0, "messages": 0,
        "input": 0, "output": 0,
    })

    for rec in records:
        bs = block_start(rec.timestamp)
        g = groups[bs]
        g["total_tokens"] += rec.total_tokens
        g["input"]        += rec.input_tokens
        g["output"]       += rec.output_tokens
        g["cost"]         += calc_cost(rec.model, rec.input_tokens, rec.output_tokens,
                                       rec.cache_write_tokens, rec.cache_read_tokens)
        g["messages"]     += 1

    rows = []
    for start, g in sorted(groups.items()):
        rows.append({"start": start, "end": start + block_delta, **g})
    return rows
