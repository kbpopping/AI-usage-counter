"""
Live watch mode for aiusage.

Runs a persistent, auto-refreshing dashboard directly in the terminal.
Stays visible across project switches — just keep the terminal pane open.

Usage:
    aiusage watch                  # default: refresh every 30s
    aiusage watch --interval 10    # refresh every 10s
    aiusage watch --provider claude
    aiusage watch --compact        # minimal one-liner progress bar
"""

from __future__ import annotations

import time
import os
import sys
import signal
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich import box

from .display import console, fmt_tokens, fmt_cost, progress_bar, time_until
from .parser import load_all_records
from .aggregator import aggregate_daily
from .pricing import calc_cost


# ── Token limit constants ──────────────────────────────────────────────────
# These are estimates; Claude Max users have rate limits, not hard token caps.
# We use these for the "remaining %" progress bars.

PROVIDER_DAILY_LIMITS: dict[str, int] = {
    "claude":     1_000_000,   # ~Claude Max 5h window equivalent
    "codex":      500_000,
    "gemini":     1_000_000,
    "openrouter": 300_000,
}

CLAUDE_5H_LIMIT  = 1_000_000
CLAUDE_7D_LIMIT  = 5_000_000


# ── Compact one-liner bar (for status bars in small terminal panes) ─────────

def _compact_bar(provider: str, used: int, remaining_pct: float, model: str) -> Text:
    """Single-line compact progress bar for small terminal areas."""
    width = 24
    remaining_filled = int(width * remaining_pct / 100)
    used_filled = width - remaining_filled

    if remaining_pct >= 40:
        color = "bright_green"
    elif remaining_pct >= 15:
        color = "bright_yellow"
    else:
        color = "bright_red"

    t = Text()
    t.append(f"{provider:<12}", style="bold cyan")
    t.append("█" * remaining_filled, style=color)
    t.append("░" * used_filled, style="dim red")
    t.append(f" {remaining_pct:5.1f}% rem ", style=f"bold {color}")
    t.append(f"({fmt_tokens(used)} used)", style="dim")
    return t


# ── Full dashboard renderable (returns a Rich renderable) ─────────────────

def _build_dashboard(
    provider: str = "all",
    claude_usage=None,
    context=None,
) -> Table:
    """Build the full live dashboard as a Rich renderable."""
    from datetime import date

    records = load_all_records(provider)
    today_str = date.today().isoformat()
    today_records = [r for r in records
                     if r.timestamp.astimezone().strftime("%Y-%m-%d") == today_str]

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ide_label = context.ide if context else "Terminal"
    model_label = context.model_friendly if context else "—"
    active_provider = context.provider if context else provider

    # ── Root layout table ──────────────────────────────────────────────────
    root = Table(box=None, show_header=False, padding=0, expand=True)
    root.add_column("content")

    # ── Header ────────────────────────────────────────────────────────────
    header = Table(box=box.SIMPLE, show_header=False, padding=(0, 2), expand=True)
    header.add_column("L")
    header.add_column("R", justify="right")
    header.add_row(
        Text.assemble(
            ("🤖 aiusage  ", "bold bright_cyan"),
            ("LIVE WATCH  ", "bold white"),
            (f"│  IDE: ", "dim"),
            (ide_label, "cyan"),
            ("  │  Model: ", "dim"),
            (model_label, "yellow"),
        ),
        Text(f"⏱  {now_str}", style="dim"),
    )
    root.add_row(Panel(header, border_style="bright_blue", padding=0))

    # ── Today's usage gauges (per provider) ───────────────────────────────
    gauge_table = Table(box=box.SIMPLE, show_header=True, header_style="bold white",
                        padding=(0, 1), expand=True)
    gauge_table.add_column("Provider",  min_width=12, style="bold")
    gauge_table.add_column("Remaining", min_width=44)
    gauge_table.add_column("Used",      justify="right", min_width=10)
    gauge_table.add_column("Limit",     justify="right", min_width=10, style="dim")
    gauge_table.add_column("Input",     justify="right", style="green")
    gauge_table.add_column("Output",    justify="right", style="blue")
    gauge_table.add_column("Messages",  justify="right", style="dim")

    # Claude live data if available
    if claude_usage and claude_usage.five_hour_pct is not None:
        used_5h = int((claude_usage.five_hour_pct / 100) * CLAUDE_5H_LIMIT)
        rem_5h = 100.0 - claude_usage.five_hour_pct
        bar_5h = _compact_bar("Claude 5h", used_5h, rem_5h, model_label)

        rem_color = "bright_green" if rem_5h >= 40 else ("bright_yellow" if rem_5h >= 15 else "bright_red")
        remaining_bar = progress_bar(100 - claude_usage.five_hour_pct, width=36)

        gauge_table.add_row(
            "[bright_cyan]Claude[/bright_cyan]\n[dim]5h Window[/dim]",
            remaining_bar,
            fmt_tokens(used_5h),
            fmt_tokens(CLAUDE_5H_LIMIT),
            "—", "—",
            f"resets {time_until(claude_usage.five_hour_resets_at)}",
        )
        if claude_usage.seven_day_pct is not None:
            used_7d = int((claude_usage.seven_day_pct / 100) * CLAUDE_7D_LIMIT)
            gauge_table.add_row(
                "[bright_cyan]Claude[/bright_cyan]\n[dim]7d Window[/dim]",
                progress_bar(100 - claude_usage.seven_day_pct, width=36),
                fmt_tokens(used_7d),
                fmt_tokens(CLAUDE_7D_LIMIT),
                "—", "—",
                f"resets {time_until(claude_usage.seven_day_resets_at)}",
            )
    else:
        # Compute from local records
        by_provider: dict = {}
        for rec in today_records:
            if rec.provider not in by_provider:
                by_provider[rec.provider] = {"input": 0, "output": 0, "total": 0, "messages": 0}
            g = by_provider[rec.provider]
            g["input"]    += rec.input_tokens
            g["output"]   += rec.output_tokens
            g["total"]    += rec.total_tokens
            g["messages"] += 1

        if not by_provider:
            gauge_table.add_row(
                "[dim]no data[/dim]", Text("No usage today", style="dim"),
                "0", "—", "0", "0", "0"
            )
        else:
            for prov, g in sorted(by_provider.items()):
                limit = PROVIDER_DAILY_LIMITS.get(prov, 500_000)
                used = g["total"]
                remaining_pct = max(0.0, 100.0 - (used / limit * 100))
                # Note: remaining = 100% - used%
                bar = progress_bar(remaining_pct, width=36)
                from .providers.detector import PROVIDER_COLORS
                color = PROVIDER_COLORS.get(prov, "white")
                gauge_table.add_row(
                    f"[{color}]{prov}[/{color}]",
                    bar,
                    fmt_tokens(used),
                    fmt_tokens(limit),
                    fmt_tokens(g["input"]),
                    fmt_tokens(g["output"]),
                    str(g["messages"]),
                )

    root.add_row(Panel(gauge_table,
                       title="[bold]📊 Token Remaining (Today)[/bold]",
                       border_style="cyan", padding=(0, 1)))

    # ── Hourly activity (last 12 hours as sparkline) ───────────────────────
    from collections import defaultdict
    from datetime import timedelta
    now_utc = datetime.now(timezone.utc)
    hourly: dict[int, int] = defaultdict(int)
    for rec in records:
        h = int((now_utc - rec.timestamp).total_seconds() / 3600)
        if h < 12:
            hourly[h] += rec.total_tokens

    hours_ordered = [hourly.get(h, 0) for h in range(11, -1, -1)]
    max_h = max(hours_ordered) if hours_ordered else 1
    bars = " ▁▂▃▄▅▆▇█"
    spark_chars = []
    for v in hours_ordered:
        level = int((v / max_h) * (len(bars) - 1))
        spark_chars.append(bars[level])

    spark_text = Text()
    spark_text.append("12h ago  ", style="dim")
    spark_text.append("".join(spark_chars), style="bright_cyan")
    spark_text.append("  now", style="dim")
    spark_text.append(f"   peak: {fmt_tokens(max_h)}/hr", style="yellow")

    root.add_row(Panel(spark_text,
                       title="[bold]📈 Hourly Activity (last 12h)[/bold]",
                       border_style="blue", padding=(0, 2)))

    # ── Today's summary totals ─────────────────────────────────────────────
    total_inp = sum(r.input_tokens for r in today_records)
    total_out = sum(r.output_tokens for r in today_records)
    total_tok = sum(r.total_tokens for r in today_records)
    total_cost = sum(calc_cost(r.model, r.input_tokens, r.output_tokens,
                               r.cache_write_tokens, r.cache_read_tokens)
                     for r in today_records)

    summary = Table(box=box.SIMPLE, show_header=False, padding=(0, 3))
    summary.add_column("k", style="dim")
    summary.add_column("v", style="bold")
    summary.add_column("k2", style="dim")
    summary.add_column("v2", style="bold")
    summary.add_row(
        "Total Tokens Today", fmt_tokens(total_tok),
        "Est. Cost Today", fmt_cost(total_cost),
    )
    summary.add_row(
        "Input Tokens", f"[green]{fmt_tokens(total_inp)}[/green]",
        "Output Tokens", f"[blue]{fmt_tokens(total_out)}[/blue]",
    )
    summary.add_row(
        "Messages", str(len(today_records)),
        "Active Provider", f"[bright_cyan]{active_provider}[/bright_cyan]",
    )

    root.add_row(Panel(summary,
                       title="[bold]📋 Today's Summary[/bold]",
                       border_style="green", padding=(0, 1)))

    # ── Footer ────────────────────────────────────────────────────────────
    root.add_row(Text(
        "  Press Ctrl+C to exit  │  Progress bars show remaining capacity (100%=full, 0%=depleted)",
        style="dim", justify="center"
    ))

    return root


def run_watch(
    provider: str = "all",
    interval: int = 30,
    compact: bool = False,
) -> None:
    """
    Main entry point for the live watch mode.
    Renders a refreshing dashboard at `interval` second intervals.
    """
    from .providers.detector import detect_context

    def _handle_exit(sig, frame):
        console.print("\n[dim]Watch stopped.[/dim]")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_exit)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_exit)

    console.print(f"[dim]Starting live watch (refresh every {interval}s). Press Ctrl+C to stop.[/dim]")
    time.sleep(0.5)

    ctx = detect_context()

    with Live(console=console, refresh_per_second=1, screen=False) as live:
        while True:
            # Fetch Claude live data if available
            claude_usage = None
            if provider in ("all", "claude"):
                try:
                    from .providers.claude import fetch_live_usage
                    usage, err = fetch_live_usage()
                    if not err:
                        claude_usage = usage
                except Exception:
                    pass

            # Re-detect context on each refresh (model may change)
            try:
                ctx = detect_context()
            except Exception:
                pass

            if compact:
                # Compact mode: just show one-liner bars
                records = load_all_records(provider)
                from datetime import date
                today_str = date.today().isoformat()
                today_records = [r for r in records
                                 if r.timestamp.astimezone().strftime("%Y-%m-%d") == today_str]
                lines = []
                if claude_usage and claude_usage.five_hour_pct is not None:
                    rem = 100.0 - claude_usage.five_hour_pct
                    used = int((claude_usage.five_hour_pct / 100) * CLAUDE_5H_LIMIT)
                    lines.append(_compact_bar("Claude 5h", used, rem, ctx.model_friendly))
                else:
                    total_today = sum(r.total_tokens for r in today_records)
                    limit = PROVIDER_DAILY_LIMITS.get(ctx.provider, 500_000)
                    rem = max(0.0, 100.0 - total_today / limit * 100)
                    lines.append(_compact_bar(ctx.provider, total_today, rem, ctx.model_friendly))

                table = Table(box=None, show_header=False, padding=0)
                table.add_column("c")
                for line in lines:
                    table.add_row(line)
                live.update(table)
            else:
                dashboard = _build_dashboard(provider, claude_usage, ctx)
                live.update(dashboard)

            time.sleep(interval)
