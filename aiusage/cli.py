"""
aiusage — AI token & cost tracker CLI

Commands:
  status   Live rate-limit status from provider APIs
  daily    Daily token usage from local JSONL logs
  monthly  Monthly token usage from local JSONL logs
  session  Per-session breakdown
  blocks   5-hour billing windows
  cost     Estimated API cost summary
  config   Show / edit config file path
  chart    Progressive bar charts by provider/hourly/input-output/remaining
  watch    Live auto-refreshing dashboard (persistent — survives project switches)
  detect   Auto-detect current IDE and active AI provider/model

Options (most commands):
  --provider / -p  claude|codex|openrouter|gemini|all  (default: all)
  --since          YYYYMMDD — filter start date
  --until          YYYYMMDD — filter end date
  --project        filter by project name fragment
  --json           output raw JSON
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from . import __version__
from .aggregator import aggregate_blocks, aggregate_daily, aggregate_monthly, aggregate_sessions
from .config import config_path, load_config, save_config
from .display import (
    console,
    render_blocks_table,
    render_claude_status,
    render_daily_table,
    render_monthly_table,
    render_openrouter_status,
    render_session_table,
)
from .parser import load_all_records, UsageRecord
from .pricing import calc_cost


# ── helpers ───────────────────────────────────────────────────────────────

def _parse_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        raise click.BadParameter(f"Invalid date: {s!r}. Use YYYYMMDD or YYYY-MM-DD.")


def _filter_records(
    records: list[UsageRecord],
    provider: str,
    since: Optional[str],
    until: Optional[str],
    project: Optional[str],
) -> list[UsageRecord]:
    if provider and provider != "all":
        records = [r for r in records if r.provider == provider]
    if since:
        since_dt = _parse_date(since)
        records = [r for r in records if r.timestamp >= since_dt]
    if until:
        until_dt = _parse_date(until)
        records = [r for r in records if r.timestamp <= until_dt]
    if project:
        records = [r for r in records if project.lower() in r.project.lower()]
    return records


# ── CLI ───────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name="aiusage")
def cli():
    """aiusage — track AI token usage from Claude Code, Codex, and more."""
    pass


# ── status ────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--provider", "-p", default="all", show_default=True,
              type=click.Choice(["all", "claude", "openrouter"], case_sensitive=False))
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def status(provider, as_json):
    """Live rate-limit status from provider APIs."""
    cfg = load_config()
    output = {}

    if provider in ("all", "claude") and cfg["providers"].get("claude", {}).get("enabled", True):
        from .providers.claude import fetch_live_usage
        usage, err = fetch_live_usage()
        if err:
            console.print(f"[red]Claude:[/red] {err}")
        else:
            if as_json:
                output["claude"] = usage.raw
            else:
                render_claude_status(usage)

    if provider in ("all", "openrouter") and cfg["providers"].get("openrouter", {}).get("enabled", False):
        from .providers.openrouter import fetch_credits
        usage, err = fetch_credits(cfg)
        if err:
            console.print(f"[red]OpenRouter:[/red] {err}")
        else:
            if as_json:
                from dataclasses import asdict
                output["openrouter"] = asdict(usage)
            else:
                render_openrouter_status(usage)

    if as_json:
        click.echo(json.dumps(output, indent=2, default=str))


# ── daily ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--provider", "-p", default="all", show_default=True)
@click.option("--since", default="", help="Start date YYYYMMDD")
@click.option("--until", default="", help="End date YYYYMMDD")
@click.option("--project", default="", help="Filter by project name fragment")
@click.option("--breakdown", is_flag=True, help="Show per-model breakdown")
@click.option("--json", "as_json", is_flag=True)
def daily(provider, since, until, project, breakdown, as_json):
    """Daily token usage and estimated costs from local logs."""
    records = _filter_records(load_all_records(provider), provider, since, until, project)
    if not records:
        console.print("[yellow]No records found. Is Claude Code / Codex installed and have you used it?[/yellow]")
        console.print(f"  Expected logs at [cyan]~/.claude/projects/[/cyan]")
        return

    if breakdown:
        # group by (date, provider, model)
        from collections import defaultdict
        groups: dict = defaultdict(lambda: {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0,
                                             "total_tokens": 0, "cost": 0.0, "messages": 0})
        for rec in records:
            key = (rec.timestamp.astimezone().strftime("%Y-%m-%d"), rec.provider, rec.model)
            g = groups[key]
            g["input"]        += rec.input_tokens
            g["output"]       += rec.output_tokens
            g["cache_write"]  += rec.cache_write_tokens
            g["cache_read"]   += rec.cache_read_tokens
            g["total_tokens"] += rec.total_tokens
            g["cost"]         += calc_cost(rec.model, rec.input_tokens, rec.output_tokens,
                                           rec.cache_write_tokens, rec.cache_read_tokens)
            g["messages"]     += 1
        rows = [{"date": f"{d} [{m}]", "provider": p, **v} for (d, p, m), v in sorted(groups.items())]
    else:
        rows = aggregate_daily(records)

    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
    else:
        render_daily_table(rows, title=f"Daily Usage — {len(records):,} messages")


# ── monthly ───────────────────────────────────────────────────────────────

@cli.command()
@click.option("--provider", "-p", default="all")
@click.option("--since", default="")
@click.option("--until", default="")
@click.option("--project", default="")
@click.option("--json", "as_json", is_flag=True)
def monthly(provider, since, until, project, as_json):
    """Monthly token usage and estimated costs."""
    records = _filter_records(load_all_records(provider), provider, since, until, project)
    rows = aggregate_monthly(records)
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
    else:
        render_monthly_table(rows)


# ── session ───────────────────────────────────────────────────────────────

@cli.command()
@click.option("--provider", "-p", default="all")
@click.option("--since", default="")
@click.option("--until", default="")
@click.option("--project", default="")
@click.option("--limit", "-n", default=30, show_default=True, help="Max sessions to show")
@click.option("--json", "as_json", is_flag=True)
def session(provider, since, until, project, limit, as_json):
    """Per-session token usage breakdown."""
    records = _filter_records(load_all_records(provider), provider, since, until, project)
    rows = aggregate_sessions(records)[:limit]
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
    else:
        render_session_table(rows, title=f"Sessions (most recent {limit})")


# ── blocks ────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--provider", "-p", default="claude")
@click.option("--since", default="", help="Start date YYYYMMDD")
@click.option("--hours", default=5, show_default=True, help="Block size in hours")
@click.option("--json", "as_json", is_flag=True)
def blocks(provider, since, hours, as_json):
    """Show usage grouped into N-hour billing windows."""
    records = _filter_records(load_all_records(provider), provider, since, "", "")
    rows = aggregate_blocks(records, block_hours=hours)
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
    else:
        render_blocks_table(rows)


# ── cost ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--provider", "-p", default="all")
@click.option("--since", default="")
@click.option("--until", default="")
@click.option("--json", "as_json", is_flag=True)
def cost(provider, since, until, as_json):
    """Estimated API cost summary (if you were paying per-token)."""
    from collections import defaultdict
    from .display import fmt_cost, fmt_tokens

    records = _filter_records(load_all_records(provider), provider, since, until, "")
    if not records:
        console.print("[yellow]No records found.[/yellow]")
        return

    # Group by (provider, model)
    groups: dict = defaultdict(lambda: {
        "input": 0, "output": 0, "cache_write": 0, "cache_read": 0,
        "total_tokens": 0, "cost": 0.0, "messages": 0,
    })
    for rec in records:
        key = (rec.provider, rec.model)
        g = groups[key]
        g["input"]        += rec.input_tokens
        g["output"]       += rec.output_tokens
        g["cache_write"]  += rec.cache_write_tokens
        g["cache_read"]   += rec.cache_read_tokens
        g["total_tokens"] += rec.total_tokens
        g["cost"]         += calc_cost(rec.model, rec.input_tokens, rec.output_tokens,
                                       rec.cache_write_tokens, rec.cache_read_tokens)
        g["messages"]     += 1

    total_cost = sum(g["cost"] for g in groups.values())
    total_tokens = sum(g["total_tokens"] for g in groups.values())

    if as_json:
        rows = [{"provider": p, "model": m, **v} for (p, m), v in sorted(groups.items())]
        click.echo(json.dumps({"total_cost_usd": total_cost, "total_tokens": total_tokens, "breakdown": rows},
                              indent=2, default=str))
        return

    from rich.table import Table
    from rich import box as rbox

    table = Table(title="Estimated Cost at API Rates", box=rbox.ROUNDED)
    table.add_column("Provider",      style="cyan")
    table.add_column("Model",         style="green",   min_width=30)
    table.add_column("Messages",      justify="right")
    table.add_column("Total Tokens",  justify="right", style="bold")
    table.add_column("Input",         justify="right")
    table.add_column("Output",        justify="right")
    table.add_column("Est. Cost",     justify="right", style="yellow bold")

    for (prov, model), g in sorted(groups.items(), key=lambda x: -x[1]["cost"]):
        table.add_row(
            prov, model,
            f"{g['messages']:,}",
            fmt_tokens(g["total_tokens"]),
            fmt_tokens(g["input"]),
            fmt_tokens(g["output"]),
            fmt_cost(g["cost"]),
        )

    table.add_section()
    table.add_row(
        "[bold]TOTAL[/bold]", "",
        "", fmt_tokens(total_tokens), "", "",
        f"[bold yellow]{fmt_cost(total_cost)}[/bold yellow]",
    )

    console.print(table)
    console.print(
        f"\n[dim]Note: This is an estimate at API pay-as-you-go rates.\n"
        f"Claude Max subscribers have unlimited usage for a flat monthly fee.[/dim]"
    )


# ── config ────────────────────────────────────────────────────────────────

@cli.command("config")
@click.option("--show",              is_flag=True, help="Show current config as JSON")
@click.option("--init",              is_flag=True, help="Create default config file")
@click.option("--set-openrouter-key", default="", metavar="KEY", help="Set OpenRouter API key")
@click.option("--set-gemini-key",     default="", metavar="KEY", help="Set Google Gemini API key")
def config_cmd(show, init, set_openrouter_key, set_gemini_key):
    """Manage aiusage configuration."""
    cfg = load_config()

    if set_openrouter_key:
        cfg["providers"]["openrouter"]["api_key"] = set_openrouter_key
        cfg["providers"]["openrouter"]["enabled"] = True
        save_config(cfg)
        console.print("[green]OpenRouter API key saved.[/green]")
        return

    if set_gemini_key:
        cfg["providers"]["gemini"]["api_key"] = set_gemini_key
        cfg["providers"]["gemini"]["enabled"] = True
        save_config(cfg)
        console.print("[green]Gemini API key saved.[/green]")
        return

    if init:
        save_config(cfg)
        return

    if show:
        # Redact secrets before printing
        import copy
        safe = copy.deepcopy(cfg)
        for prov in ("openrouter", "gemini"):
            key = safe.get("providers", {}).get(prov, {}).get("api_key", "")
            if key:
                safe["providers"][prov]["api_key"] = key[:8] + "..." if len(key) > 8 else "***"
        console.print_json(json.dumps(safe, indent=2))
        return

    # Default: show info
    console.print(Panel(
        f"[bold]Config file:[/bold] [cyan]{config_path()}[/cyan]\n\n"
        f"Run [bold]aiusage config --show[/bold] to see current settings.\n"
        f"Run [bold]aiusage config --init[/bold] to create the config file.\n"
        f"Run [bold]aiusage config --set-openrouter-key sk-or-...[/bold] to add your OpenRouter key.\n"
        f"Run [bold]aiusage config --set-gemini-key AIza...[/bold] to add your Gemini API key.",
        title="aiusage Config",
        border_style="blue",
    ))


# ── chart ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--provider", "-p", default="all", show_default=True,
              help="Filter by provider (claude/codex/gemini/openrouter/all)")
@click.option("--since", default="", help="Start date YYYYMMDD")
@click.option("--until", default="", help="End date YYYYMMDD")
@click.option("--project", default="", help="Filter by project name")
@click.option("--type", "chart_type",
              type=click.Choice(["all", "provider", "hourly", "io", "remaining"], case_sensitive=False),
              default="all", show_default=True,
              help="Which chart(s) to render")
@click.option("--hours", default=24, show_default=True, help="Hours of history for hourly chart")
def chart(provider, since, until, project, chart_type, hours):
    """Progressive bar charts: usage by provider, hourly, input/output split, remaining limit."""
    from .chart import (
        render_provider_chart, render_hourly_chart,
        render_io_chart, render_chart_dashboard,
    )
    from .providers.detector import detect_context

    records = _filter_records(load_all_records(provider), provider, since, until, project)
    ctx = detect_context()

    # Fetch Claude live data if available
    claude_usage = None
    cfg = load_config()
    if provider in ("all", "claude") and cfg["providers"].get("claude", {}).get("enabled", True):
        try:
            from .providers.claude import fetch_live_usage
            usage, err = fetch_live_usage()
            if not err:
                claude_usage = usage
        except Exception:
            pass

    if chart_type == "all":
        render_chart_dashboard(records, claude_usage=claude_usage, context=ctx)
    elif chart_type == "provider":
        render_provider_chart(records)
    elif chart_type == "hourly":
        render_hourly_chart(records, last_hours=hours)
    elif chart_type == "io":
        render_io_chart(records)
    elif chart_type == "remaining":
        from .chart import render_remaining_gauge
        from datetime import date
        today_str = date.today().isoformat()
        today_records = [r for r in records
                         if r.timestamp.astimezone().strftime("%Y-%m-%d") == today_str]
        if claude_usage and claude_usage.five_hour_pct is not None:
            from .watch import CLAUDE_5H_LIMIT
            used = int((claude_usage.five_hour_pct / 100) * CLAUDE_5H_LIMIT)
            render_remaining_gauge(
                provider="Claude",
                model=ctx.model_friendly,
                used_tokens=used,
                limit_tokens=CLAUDE_5H_LIMIT,
                window_label="5-Hour Session",
                resets_at=claude_usage.five_hour_resets_at,
            )
        else:
            from .watch import PROVIDER_DAILY_LIMITS
            prov = ctx.provider
            used = sum(r.total_tokens for r in today_records)
            limit = PROVIDER_DAILY_LIMITS.get(prov, 500_000)
            render_remaining_gauge(
                provider=prov,
                model=ctx.model_friendly,
                used_tokens=used,
                limit_tokens=limit,
                window_label="Today (est.)",
            )


# ── watch ──────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--provider", "-p", default="all", show_default=True)
@click.option("--interval", "-i", default=30, show_default=True,
              help="Refresh interval in seconds")
@click.option("--compact", is_flag=True,
              help="Minimal one-liner progress bar (great for small terminal panes)")
def watch(provider, interval, compact):
    """Live auto-refreshing dashboard. Stays active across project switches.

    Tip: Pin this in a dedicated terminal pane in your IDE.
    It auto-detects your provider and model and refreshes every N seconds.
    """
    from .watch import run_watch
    run_watch(provider=provider, interval=interval, compact=compact)


# ── detect ─────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON")
def detect(as_json):
    """Auto-detect current IDE and active AI provider/model."""
    import json as _json
    from .providers.detector import detect_context

    ctx = detect_context()

    if as_json:
        click.echo(_json.dumps({
            "ide":            ctx.ide,
            "provider":       ctx.provider,
            "model":          ctx.model,
            "model_friendly": ctx.model_friendly,
            "confidence":     ctx.confidence,
            "signals":        ctx.signals,
        }, indent=2))
        return

    from rich.table import Table
    from rich import box as rbox

    conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(ctx.confidence, "white")

    table = Table(box=rbox.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("Key", style="dim", min_width=18)
    table.add_column("Value", style="bold")

    table.add_row("IDE",             f"[cyan]{ctx.ide}[/cyan]")
    table.add_row("Provider",        f"[bright_green]{ctx.provider}[/bright_green]")
    table.add_row("Model",           f"[yellow]{ctx.model_friendly}[/yellow]")
    table.add_row("Model ID",        f"[dim]{ctx.model}[/dim]")
    table.add_row("Confidence",      f"[{conf_color}]{ctx.confidence}[/{conf_color}]")
    table.add_row("Detection Signals", ", ".join(ctx.signals) or "(none)")

    console.print(Panel(
        table,
        title="[bold]🔍 Detected Environment[/bold]",
        border_style="bright_blue",
        padding=(0, 1),
    ))

    if ctx.confidence == "low":
        console.print(
            "[dim]Tip: Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY "
            "to improve detection confidence.[/dim]"
        )


def main():
    cli()


if __name__ == "__main__":
    main()
