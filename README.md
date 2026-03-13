# aiusage 🤖

> Track AI token usage from Claude Code, Codex, OpenRouter, Gemini, and more — from your terminal.

Built from the ground up as a **secure, privacy-first** alternative to GUI tools like CodexBar. No browser cookie extraction. No system tray. No precompiled binaries to trust. Just a clean Python CLI that reads **your own local files**.

---

## Features

| Command             | What it shows |
|---------------------|---------------|
| `aiusage status`    | **Live** rate-limit gauges from the Claude OAuth API (5h session %, 7-day %) |
| `aiusage daily`     | Daily token breakdown from local JSONL logs |
| `aiusage monthly`   | Monthly aggregated usage + estimated costs |
| `aiusage session`   | Per-session breakdown with project, model, cost |
| `aiusage blocks`    | 5-hour billing windows (matches Claude's rate-limit windows) |
| `aiusage cost`      | Estimated API cost per model at pay-as-you-go rates |
| `aiusage chart`     | **NEW** Progressive bar charts: by provider, hourly, input/output, remaining limit |
| `aiusage watch`     | **NEW** Live auto-refreshing dashboard — stays active across project switches |
| `aiusage detect`    | **NEW** Auto-detect your current IDE + active AI provider/model |
| `aiusage config`    | Manage settings |

---

## Install

### Option A — Install from source (recommended)

```bash
git clone https://github.com/kbpopping/AI-usage-counter.git
cd AI-usage-counter
pip install -e .
```

### Option B — Install directly

```bash
pip install .
```

### Option C — No install, just run

```bash
python -m aiusage.cli --help
```

### Prerequisites

- Python 3.10+
- `click` and `rich` (installed automatically)
- At least one of: **Claude Code**, **Codex CLI**, **Gemini API** installed and used

> **Windows users:** If `python` isn't found, use `py` instead (e.g. `py -m pip install -e .`)

---

## Quick Start

```bash
# Detect your IDE and active AI provider automatically
aiusage detect

# Full progressive chart dashboard
aiusage chart

# Chart just by provider
aiusage chart --type provider

# Chart input vs output token split
aiusage chart --type io

# Remaining token gauge (counts DOWN from 100% → 0%)
aiusage chart --type remaining

# Hourly usage sparkline (last 48h)
aiusage chart --type hourly --hours 48

# Live auto-refreshing dashboard (pin in a terminal pane!)
aiusage watch

# Refresh every 10 seconds
aiusage watch --interval 10

# Compact single-line progress bar for small panes
aiusage watch --compact

# See live rate limits (requires Claude Code OAuth login)
aiusage status

# Daily token usage from your logs
aiusage daily

# Monthly breakdown
aiusage monthly

# Top sessions by token usage
aiusage session

# 5-hour billing blocks
aiusage blocks

# Cost estimate if you were paying API rates
aiusage cost

# Filter by provider and date
aiusage daily --provider claude --since 20260101
aiusage cost --provider claude --since 20260301

# JSON output (pipe-friendly)
aiusage daily --json | jq '.[] | select(.cost > 0.5)'
```

---

## 🔴 Live Watch Mode (Persistent Dashboard)

The `aiusage watch` command is designed to be **pinned as a dedicated terminal pane** in your IDE. It will:

- ✅ **Auto-detect** which IDE you're in (Cursor, VS Code, Claude Code, Trae, Windsurf, etc.)
- ✅ **Auto-detect** your active AI provider and model (Claude Sonnet, GPT-4o, Gemini Pro, etc.)
- ✅ Show a **live remaining token gauge** (100% = full limit, 0% = depleted)
- ✅ Update automatically on a configurable interval
- ✅ Stay alive **across project switches** — just keep the terminal pane open
- ✅ Show **hourly sparkline activity** and **today's token summary**

```bash
# Pin this in your IDE's integrated terminal:
aiusage watch --interval 30

# For a minimal status bar in a narrow pane:
aiusage watch --compact --interval 15
```

### IDE Setup (one-time)

| IDE | How to pin |
|-----|-----------|
| **VS Code / Cursor** | Open terminal → split pane → run `aiusage watch` in the second pane |
| **Claude Code** | Run `aiusage watch` in a background terminal tab |
| **Trae / Windsurf** | Open an integrated terminal → run `aiusage watch` |
| **Any IDE** | `aiusage watch` survives project switches — just don't close the pane |

---

## 📊 Chart Command

```bash
# Full chart dashboard (all charts at once)
aiusage chart

# Individual charts
aiusage chart --type provider    # Stacked bar chart by provider
aiusage chart --type hourly      # Hourly sparkline + bar chart
aiusage chart --type io          # Input vs Output token split
aiusage chart --type remaining   # Remaining limit gauge

# Filter options
aiusage chart --provider claude --since 20260301
aiusage chart --type hourly --hours 72
```

---

## 🔍 Auto-Detection

`aiusage detect` scans your environment to identify:
- **IDE**: Cursor, VS Code, Claude Code, Trae, Windsurf, Antigravity, JetBrains, Neovim, Zed, etc.
- **Provider**: Claude, Codex/OpenAI, Gemini, OpenRouter
- **Model**: e.g. Claude Sonnet 4.5, GPT-4o, Gemini 2.5 Pro

Detection uses (in priority order):
1. IDE-specific environment variables (`CURSOR_SESSION_ID`, `VSCODE_PID`, etc.)
2. AI provider credential files (`~/.claude/.credentials.json`, etc.)
3. Most recent JSONL log entries (model name)
4. Running process scan (fallback)

---

## How It Works

### Local JSONL Log Parsing (offline, always works)

Claude Code and Codex write detailed usage logs to disk after every API call:

```
~/.claude/projects/<encoded-path>/<session-uuid>.jsonl
```

Each line is a JSON event. `aiusage` scans these files, extracts `usage` fields, and aggregates them. This works **100% offline** — no API calls needed.

### Live Claude Rate Limits (`status` / `watch` commands)

When you have Claude Code installed and logged in, `aiusage` calls:

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <your OAuth token from ~/.claude/.credentials.json>
anthropic-beta: oauth-2025-04-20
```

This returns your current 5-hour and 7-day rate limit utilization.

---

## Security Design

- **No browser cookie extraction** — unlike CodexBar/Win-CodexBar, we never touch your browser's cookie stores
- **Read-only** — only reads files Claude/Codex already created; never writes or modifies them
- **No telemetry** — no data leaves your machine except the single Anthropic API call for `status`/`watch`
- **Source-readable** — all code is plain Python; audit it in minutes
- **Secrets never logged** — tokens are read in memory and never written to disk or stdout

---

## Supported Providers

| Provider    | Auth method                                      | Data source                            |
|-------------|--------------------------------------------------|----------------------------------------|
| Claude      | OAuth token from `~/.claude/.credentials.json`   | JSONL logs + live API                  |
| Codex       | Local JSONL logs                                  | `~/.codex/sessions/`                   |
| OpenRouter  | API key (env or config)                          | `/api/v1/credits` endpoint             |
| Gemini      | API key (env `GEMINI_API_KEY` or config)         | Free-tier quota limits (model-based)   |

---

## Configuration

Config lives at `~/.config/aiusage/config.json`:

```json
{
  "providers": {
    "claude":      { "enabled": true },
    "codex":       { "enabled": true },
    "openrouter":  { "enabled": false, "api_key": "sk-or-v1-..." },
    "gemini":      { "enabled": false, "api_key": "AIza..." }
  },
  "cache_ttl_seconds": 60,
  "timezone": "local"
}
```

Set your API keys:

```bash
aiusage config --set-openrouter-key sk-or-v1-your-key-here
aiusage config --set-gemini-key AIza-your-gemini-key
aiusage config --show
```

---

## Model Pricing

`aiusage` ships with a built-in pricing table for all major Claude, OpenAI/Codex, and Gemini models. Cost estimates appear in `daily`, `monthly`, `session`, `cost`, and `chart` commands.

> **Note:** These are estimated API pay-as-you-go rates. Claude Max subscribers pay a flat monthly fee, so these numbers show what you'd have paid on the API — useful for understanding your usage value.

---

## Architecture

```
aiusage/
├── cli.py             # Click commands: status, daily, monthly, session, blocks, cost,
│                      #                 config, chart, watch, detect
├── chart.py           # Progressive bar charts & remaining-limit gauges  ← NEW
├── watch.py           # Live auto-refreshing terminal dashboard           ← NEW
├── parser.py          # JSONL log scanner & UsageRecord dataclass
├── aggregator.py      # Group records into daily/monthly/session/block summaries
├── pricing.py         # Model pricing table + cost calculator
├── display.py         # Rich terminal tables, progress bars, panels
├── config.py          # Config load/save
└── providers/
    ├── claude.py      # OAuth credential loader + live usage API
    ├── openrouter.py  # OpenRouter credits API
    ├── gemini.py      # Gemini quota limits                               ← NEW
    └── detector.py    # IDE + AI provider auto-detection                  ← NEW
```

---

## License

MIT
