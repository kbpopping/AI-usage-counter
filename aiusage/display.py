"""Rich-based terminal display helpers."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()


# ── progress bar ──────────────────────────────────────────────────────────

def progress_bar(pct: float, width: int = 20) -> Text:
    """Return a colored progress bar Text object."""
    pct = max(0.0, min(100.0, pct))
    filled = int(width * pct / 100)
    bar = "█" * filled + "░" * (width - filled)
    if pct >= 90:
        color = "red"
    elif pct >= 70:
        color = "yellow"
    else:
        color = "green"
    t = Text()
    t.append(bar, style=color)
    t.append(f" {pct:.1f}%", style="bold")
    return t


def time_until(dt: Optional[datetime]) -> str:
    if not dt:
        return "unknown"
    now = datetime.now(timezone.utc)
    delta = dt - now
    if delta.total_seconds() < 0:
        return "expired"
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m = rem // 60
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_cost(usd: float) -> str:
    if usd >= 1:
        return f"${usd:.2f}"
    return f"${usd:.4f}"


# ── status panel ──────────────────────────────────────────────────────────

def render_claude_status(usage, provider_label: str = "Claude") -> None:
    """Render the live Claude usage panel."""
    from rich.columns import Columns

    rows = []

    if usage.five_hour_pct is not None:
        rows.append((
            "5-Hour Session",
            progress_bar(usage.five_hour_pct),
            f"resets in [cyan]{time_until(usage.five_hour_resets_at)}[/cyan]",
        ))

    if usage.seven_day_pct is not None:
        rows.append((
            "7-Day Rolling",
            progress_bar(usage.seven_day_pct),
            f"resets in [cyan]{time_until(usage.seven_day_resets_at)}[/cyan]",
        ))

    if usage.seven_day_sonnet_pct is not None:
        rows.append((
            "7-Day (Sonnet)",
            progress_bar(usage.seven_day_sonnet_pct),
            "",
        ))

    if not rows:
        console.print(Panel("[yellow]No usage data returned from API.[/yellow]", title=provider_label))
        return

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("Window", style="bold white", min_width=18)
    table.add_column("Usage")
    table.add_column("Reset")

    for label, bar, reset_str in rows:
        table.add_row(label, bar, reset_str)

    if usage.extra_usage_enabled:
        extra = Text("⚡ Extra usage enabled", style="yellow")
        if usage.monthly_limit:
            extra.append(f"  (limit: ${usage.monthly_limit:.0f}/mo)")
        table.add_row("Overage", extra, "")

    console.print(Panel(table, title=f"[bold cyan]{provider_label} — Live Rate Limits[/bold cyan]", border_style="cyan"))


def render_openrouter_status(usage) -> None:
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("", style="bold white", min_width=18)
    table.add_column("")
    table.add_row("Total Credits",  f"[green]${usage.total_credits:.4f}[/green]")
    table.add_row("Used",           f"[yellow]${usage.usage:.4f}[/yellow]")
    table.add_row("Remaining",      f"[cyan]${usage.remaining:.4f}[/cyan]")
    console.print(Panel(table, title="[bold magenta]OpenRouter — Credits[/bold magenta]", border_style="magenta"))


# ── daily / monthly tables ────────────────────────────────────────────────

def render_daily_table(rows: list[dict], title: str = "Daily Usage") -> None:
    """
    rows: list of dicts with keys: date, provider, input, output, cache_write, cache_read, cost, total_tokens
    """
    table = Table(title=title, box=box.ROUNDED, show_lines=False)
    table.add_column("Date",         style="bold white", min_width=12)
    table.add_column("Provider",     style="cyan",       min_width=8)
    table.add_column("Input",        justify="right",    style="green")
    table.add_column("Output",       justify="right",    style="blue")
    table.add_column("Cache W",      justify="right",    style="dim")
    table.add_column("Cache R",      justify="right",    style="dim")
    table.add_column("Total",        justify="right",    style="bold")
    table.add_column("Est. Cost",    justify="right",    style="yellow")

    for row in rows:
        table.add_row(
            str(row["date"]),
            row.get("provider", ""),
            fmt_tokens(row.get("input", 0)),
            fmt_tokens(row.get("output", 0)),
            fmt_tokens(row.get("cache_write", 0)),
            fmt_tokens(row.get("cache_read", 0)),
            fmt_tokens(row.get("total_tokens", 0)),
            fmt_cost(row.get("cost", 0.0)),
        )
    console.print(table)


def render_session_table(rows: list[dict], title: str = "Sessions") -> None:
    table = Table(title=title, box=box.ROUNDED)
    table.add_column("Session",      style="dim",        max_width=12)
    table.add_column("Project",      style="cyan",       max_width=30)
    table.add_column("Provider",     style="magenta",    min_width=8)
    table.add_column("Model",        style="green",      min_width=15)
    table.add_column("Messages",     justify="right")
    table.add_column("Total Tokens", justify="right",    style="bold")
    table.add_column("Est. Cost",    justify="right",    style="yellow")
    table.add_column("Last Active",  style="dim")

    for row in rows:
        ts = row.get("last_active")
        ts_str = ts.strftime("%Y-%m-%d %H:%M") if isinstance(ts, datetime) else str(ts or "")
        table.add_row(
            str(row.get("session_id", ""))[:10] + "…",
            row.get("project", ""),
            row.get("provider", ""),
            row.get("model", ""),
            str(row.get("messages", 0)),
            fmt_tokens(row.get("total_tokens", 0)),
            fmt_cost(row.get("cost", 0.0)),
            ts_str,
        )
    console.print(table)


def render_blocks_table(rows: list[dict]) -> None:
    """Render 5-hour billing blocks."""
    table = Table(title="5-Hour Billing Blocks", box=box.ROUNDED)
    table.add_column("Block Start",   style="bold white", min_width=18)
    table.add_column("Block End",     style="dim",        min_width=18)
    table.add_column("Total Tokens",  justify="right",    style="bold")
    table.add_column("Est. Cost",     justify="right",    style="yellow")
    table.add_column("Messages",      justify="right")

    for row in rows:
        start = row.get("start")
        end = row.get("end")
        start_str = start.strftime("%Y-%m-%d %H:%M") if isinstance(start, datetime) else str(start)
        end_str   = end.strftime("%Y-%m-%d %H:%M")   if isinstance(end, datetime)   else str(end)
        table.add_row(
            start_str,
            end_str,
            fmt_tokens(row.get("total_tokens", 0)),
            fmt_cost(row.get("cost", 0.0)),
            str(row.get("messages", 0)),
        )
    console.print(table)


def render_monthly_table(rows: list[dict]) -> None:
    table = Table(title="Monthly Usage", box=box.ROUNDED)
    table.add_column("Month",         style="bold white", min_width=10)
    table.add_column("Provider",      style="cyan",       min_width=8)
    table.add_column("Total Tokens",  justify="right",    style="bold")
    table.add_column("Input",         justify="right",    style="green")
    table.add_column("Output",        justify="right",    style="blue")
    table.add_column("Cache Saved",   justify="right",    style="dim")
    table.add_column("Est. Cost",     justify="right",    style="yellow")
    table.add_column("Sessions",      justify="right")

    for row in rows:
        table.add_row(
            str(row.get("month", "")),
            row.get("provider", ""),
            fmt_tokens(row.get("total_tokens", 0)),
            fmt_tokens(row.get("input", 0)),
            fmt_tokens(row.get("output", 0)),
            fmt_tokens(row.get("cache_read", 0)),
            fmt_cost(row.get("cost", 0.0)),
            str(row.get("sessions", 0)),
        )
    console.print(table)
