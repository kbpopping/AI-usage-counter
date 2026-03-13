"""
Progressive chart engine for aiusage.

Renders terminal bar charts showing:
  - Usage by provider (stacked)
  - Hourly usage breakdown (sparkline chart)
  - Input vs Output token split
  - Remaining token limit gauge (live progress, counts down from 100% -> 0%)

Uses Rich for all rendering — no external charting dependencies.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.align import Align

from .display import console, fmt_tokens, fmt_cost, progress_bar, time_until
from .parser import UsageRecord
from .pricing import calc_cost


# ── Colour palette ─────────────────────────────────────────────────────────

PROVIDER_COLORS: dict[str, str] = {
    "claude":     "bright_cyan",
    "codex":      "bright_green",
    "openrouter": "bright_magenta",
    "gemini":     "bright_yellow",
}

BAR_CHARS = "▏▎▍▌▋▊▉█"


# ── Horizontal bar chart helper ────────────────────────────────────────────

def _hbar(value: float, max_val: float, width: int = 30, color: str = "cyan") -> Text:
    """Render a single horizontal bar proportional to value/max_val."""
    if max_val <= 0:
        max_val = 1
    frac = min(value / max_val, 1.0)
    filled = int(width * frac)
    remainder = width - filled
    t = Text()
    t.append("█" * filled, style=color)
    t.append("░" * remainder, style="dim")
    return t


def _sparkline(values: list[float], width: int = 40) -> Text:
    """Render a mini sparkline bar chart from a list of values."""
    if not values:
        return Text("(no data)", style="dim")
    max_val = max(values) or 1
    bars = " ▁▂▃▄▅▆▇█"
    t = Text()
    # Downsample or pad to exactly `width` chars
    step = max(1, len(values) / width)
    chars = []
    for i in range(min(width, len(values))):
        idx = int(i * step)
        v = values[min(idx, len(values) - 1)]
        level = int((v / max_val) * (len(bars) - 1))
        chars.append(bars[level])
    t.append("".join(chars), style="bright_cyan")
    return t


# ── Provider chart ─────────────────────────────────────────────────────────

def render_provider_chart(records: list[UsageRecord]) -> None:
    """Render a comparative bar chart of total tokens by provider."""
    if not records:
        console.print("[yellow]No records to chart.[/yellow]")
        return

    # Aggregate by provider
    by_provider: dict[str, dict] = defaultdict(lambda: {
        "input": 0, "output": 0, "total": 0, "cost": 0.0, "messages": 0
    })
    for rec in records:
        g = by_provider[rec.provider]
        g["input"]    += rec.input_tokens
        g["output"]   += rec.output_tokens
        g["total"]    += rec.total_tokens
        g["cost"]     += calc_cost(rec.model, rec.input_tokens, rec.output_tokens,
                                   rec.cache_write_tokens, rec.cache_read_tokens)
        g["messages"] += 1

    max_total = max(g["total"] for g in by_provider.values()) if by_provider else 1

    table = Table(
        title="[bold]Token Usage by Provider[/bold]",
        box=box.ROUNDED, show_header=True, header_style="bold white",
        padding=(0, 1),
    )
    table.add_column("Provider",  style="bold", min_width=12)
    table.add_column("Chart",     min_width=35)
    table.add_column("Tokens",    justify="right", style="bold")
    table.add_column("Input",     justify="right", style="green")
    table.add_column("Output",    justify="right", style="blue")
    table.add_column("Messages",  justify="right", style="dim")
    table.add_column("Est. Cost", justify="right", style="yellow")

    for provider, g in sorted(by_provider.items(), key=lambda x: -x[1]["total"]):
        color = PROVIDER_COLORS.get(provider, "white")
        bar = _hbar(g["total"], max_total, width=32, color=color)
        table.add_row(
            f"[{color}]{provider}[/{color}]",
            bar,
            fmt_tokens(g["total"]),
            fmt_tokens(g["input"]),
            fmt_tokens(g["output"]),
            str(g["messages"]),
            fmt_cost(g["cost"]),
        )

    console.print(table)


# ── Hourly chart ───────────────────────────────────────────────────────────

def render_hourly_chart(records: list[UsageRecord], last_hours: int = 24) -> None:
    """Render a sparkline + bar chart of token usage per hour."""
    if not records:
        console.print("[yellow]No records to chart.[/yellow]")
        return

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=last_hours)
    recent = [r for r in records if r.timestamp >= cutoff]

    if not recent:
        console.print(f"[yellow]No usage in the last {last_hours} hours.[/yellow]")
        return

    # Bucket by hour
    hourly: dict[int, dict] = defaultdict(lambda: {"input": 0, "output": 0, "total": 0, "cost": 0.0})
    for rec in recent:
        hour_offset = int((now - rec.timestamp).total_seconds() / 3600)
        h = min(hour_offset, last_hours - 1)
        g = hourly[h]
        g["input"]  += rec.input_tokens
        g["output"] += rec.output_tokens
        g["total"]  += rec.total_tokens
        g["cost"]   += calc_cost(rec.model, rec.input_tokens, rec.output_tokens,
                                 rec.cache_write_tokens, rec.cache_read_tokens)

    # Build ordered list (oldest -> newest)
    hours_list = list(range(last_hours - 1, -1, -1))
    totals = [hourly.get(h, {}).get("total", 0) for h in hours_list]
    max_total = max(totals) if totals else 1

    # Sparkline header
    spark = _sparkline(totals, width=last_hours)
    console.print(Panel(spark, title=f"[bold cyan]Hourly Token Usage — Last {last_hours}h[/bold cyan]",
                        subtitle="[dim]left=oldest, right=most recent[/dim]",
                        border_style="cyan", padding=(0, 1)))

    # Detailed bar table (show last 12 rows if last_hours > 12)
    display_hours = min(last_hours, 24)
    table = Table(box=box.SIMPLE, show_header=True, header_style="bold white")
    table.add_column("Time (ago)", min_width=14, style="dim")
    table.add_column("Bar", min_width=30)
    table.add_column("Total",  justify="right", style="bold")
    table.add_column("Input",  justify="right", style="green")
    table.add_column("Output", justify="right", style="blue")
    table.add_column("Cost",   justify="right", style="yellow")

    shown = 0
    for h in hours_list:
        g = hourly.get(h, {})
        if g.get("total", 0) == 0 and shown >= 6:
            continue  # Skip empty hours after we've shown some
        bar = _hbar(g.get("total", 0), max_total, width=28, color="bright_cyan")
        label = f"{h}h ago" if h > 0 else "now"
        table.add_row(
            label,
            bar,
            fmt_tokens(g.get("total", 0)),
            fmt_tokens(g.get("input", 0)),
            fmt_tokens(g.get("output", 0)),
            fmt_cost(g.get("cost", 0.0)),
        )
        shown += 1
        if shown >= display_hours:
            break

    console.print(table)


# ── Input vs Output split chart ────────────────────────────────────────────

def render_io_chart(records: list[UsageRecord]) -> None:
    """Render an input vs output token split chart per provider+model."""
    if not records:
        console.print("[yellow]No records to chart.[/yellow]")
        return

    from collections import defaultdict
    groups: dict[tuple, dict] = defaultdict(lambda: {
        "input": 0, "output": 0, "cache_write": 0, "cache_read": 0,
        "total": 0, "messages": 0,
    })
    for rec in records:
        key = (rec.provider, rec.model)
        g = groups[key]
        g["input"]       += rec.input_tokens
        g["output"]      += rec.output_tokens
        g["cache_write"] += rec.cache_write_tokens
        g["cache_read"]  += rec.cache_read_tokens
        g["total"]       += rec.total_tokens
        g["messages"]    += 1

    max_total = max(g["total"] for g in groups.values()) if groups else 1

    table = Table(
        title="[bold]Input vs Output Token Split[/bold]",
        box=box.ROUNDED, show_header=True, header_style="bold white",
    )
    table.add_column("Provider", style="cyan", min_width=10)
    table.add_column("Model",    style="green", min_width=20)
    table.add_column("Input ██", min_width=20)
    table.add_column("Output ██", min_width=20)
    table.add_column("Cache R", justify="right", style="dim")
    table.add_column("Msgs",   justify="right")

    for (provider, model), g in sorted(groups.items(), key=lambda x: -x[1]["total"]):
        total = g["total"] or 1
        inp_frac = g["input"] / total
        out_frac = g["output"] / total
        color = PROVIDER_COLORS.get(provider, "white")
        inp_bar = _hbar(g["input"], max_total, width=18, color="green")
        out_bar = _hbar(g["output"], max_total, width=18, color="blue")
        # Append token count
        inp_text = Text()
        inp_text.append_text(inp_bar)
        inp_text.append(f" {fmt_tokens(g['input'])} ({inp_frac:.0%})", style="dim")
        out_text = Text()
        out_text.append_text(out_bar)
        out_text.append(f" {fmt_tokens(g['output'])} ({out_frac:.0%})", style="dim")
        short_model = model[:28] + "…" if len(model) > 28 else model
        table.add_row(
            f"[{color}]{provider}[/{color}]",
            short_model,
            inp_text,
            out_text,
            fmt_tokens(g["cache_read"]),
            str(g["messages"]),
        )

    console.print(table)


# ── Remaining limit gauge ──────────────────────────────────────────────────

def render_remaining_gauge(
    provider: str,
    model: str,
    used_tokens: int,
    limit_tokens: int,
    window_label: str = "Session",
    resets_at: Optional[datetime] = None,
    extra_info: Optional[dict] = None,
) -> None:
    """
    Render a live remaining-capacity gauge.
    100% = full limit available (not yet used)
    0%   = limit fully depleted
    """
    if limit_tokens <= 0:
        console.print("[yellow]Cannot render gauge: token limit unknown.[/yellow]")
        return

    used_pct = min(100.0, used_tokens / limit_tokens * 100)
    remaining_pct = 100.0 - used_pct
    remaining_tokens = max(0, limit_tokens - used_tokens)

    # Color: green while healthy, yellow as approaching, red when critical
    if remaining_pct >= 40:
        gauge_color = "bright_green"
        gauge_emoji = "🟢"
    elif remaining_pct >= 15:
        gauge_color = "bright_yellow"
        gauge_emoji = "🟡"
    else:
        gauge_color = "bright_red"
        gauge_emoji = "🔴"

    # Build gauge bar (remaining = filled, used = empty)
    bar_width = 40
    remaining_filled = int(bar_width * remaining_pct / 100)
    used_filled = bar_width - remaining_filled

    gauge = Text()
    gauge.append("█" * remaining_filled, style=gauge_color)
    gauge.append("░" * used_filled, style="dim red")
    gauge.append(f"  {remaining_pct:.1f}% remaining", style=f"bold {gauge_color}")

    # Stats table inside the panel
    stats = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    stats.add_column("Label", style="dim", min_width=18)
    stats.add_column("Value", style="bold")

    stats.add_row("Window",           window_label)
    stats.add_row("Model",            model)
    stats.add_row("Limit",            fmt_tokens(limit_tokens))
    stats.add_row("Used",             f"[red]{fmt_tokens(used_tokens)}[/red]")
    stats.add_row("Remaining",        f"[{gauge_color}]{fmt_tokens(remaining_tokens)}[/{gauge_color}]")
    if resets_at:
        stats.add_row("Resets in",    f"[cyan]{time_until(resets_at)}[/cyan]")
    if extra_info:
        for k, v in extra_info.items():
            stats.add_row(k, str(v))

    from rich.console import Group
    content = Group(
        stats,
        Text(""),
        gauge,
    )

    title = f"{gauge_emoji} [bold]{provider.upper()} — Token Budget ({window_label})[/bold]"
    console.print(Panel(content, title=title, border_style=gauge_color, padding=(1, 2)))


# ── Full chart dashboard ───────────────────────────────────────────────────

def render_chart_dashboard(
    records: list[UsageRecord],
    claude_usage=None,
    context=None,
) -> None:
    """
    Render the full progressive chart dashboard:
      1. Provider bar chart
      2. Input/Output split
      3. Hourly sparkline
      4. Remaining limit gauges
    """
    from .display import console

    # Header
    ide_label = context.ide if context else "Terminal"
    model_label = context.model_friendly if context else "Unknown"
    provider_label = context.provider if context else "unknown"

    console.print()
    console.print(Panel(
        f"[bold white]IDE:[/bold white]      [cyan]{ide_label}[/cyan]\n"
        f"[bold white]Provider:[/bold white] [bright_green]{provider_label}[/bright_green]\n"
        f"[bold white]Model:[/bold white]    [yellow]{model_label}[/yellow]",
        title="[bold]🤖 aiusage — Live Chart Dashboard[/bold]",
        border_style="bright_blue",
        padding=(0, 2),
    ))

    # 1. Provider chart
    console.print()
    render_provider_chart(records)

    # 2. I/O split
    console.print()
    render_io_chart(records)

    # 3. Hourly
    console.print()
    render_hourly_chart(records, last_hours=24)

    # 4. Remaining limit gauge (Claude live data if available)
    console.print()
    if claude_usage and claude_usage.five_hour_pct is not None:
        # Claude Max: 5-hour window, estimated ~1M token equivalent
        CLAUDE_5H_LIMIT = 1_000_000
        used = int((claude_usage.five_hour_pct / 100) * CLAUDE_5H_LIMIT)
        render_remaining_gauge(
            provider="Claude",
            model=context.model_friendly if context else "Claude",
            used_tokens=used,
            limit_tokens=CLAUDE_5H_LIMIT,
            window_label="5-Hour Session",
            resets_at=claude_usage.five_hour_resets_at,
        )
        if claude_usage.seven_day_pct is not None:
            CLAUDE_7D_LIMIT = 5_000_000
            used_7d = int((claude_usage.seven_day_pct / 100) * CLAUDE_7D_LIMIT)
            render_remaining_gauge(
                provider="Claude",
                model=context.model_friendly if context else "Claude",
                used_tokens=used_7d,
                limit_tokens=CLAUDE_7D_LIMIT,
                window_label="7-Day Rolling",
                resets_at=claude_usage.seven_day_resets_at,
            )
    else:
        # Compute from local logs — use today's usage
        from datetime import date
        today_str = date.today().isoformat()
        today_records = [r for r in records
                         if r.timestamp.astimezone().strftime("%Y-%m-%d") == today_str]
        if today_records:
            total_today = sum(r.total_tokens for r in today_records)
            # Use model-based context limit estimate
            from .providers.detector import friendly_model
            prov = (context.provider if context else "claude")
            limits = {
                "claude":     500_000,
                "codex":      300_000,
                "gemini":     1_000_000,
                "openrouter": 300_000,
            }
            daily_limit = limits.get(prov, 500_000)
            render_remaining_gauge(
                provider=provider_label,
                model=model_label,
                used_tokens=total_today,
                limit_tokens=daily_limit,
                window_label="Today (est.)",
                extra_info={"Messages": str(len(today_records))},
            )
        else:
            console.print("[dim]No usage today — remaining limit at 100%[/dim]")
