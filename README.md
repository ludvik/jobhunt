# jobhunt

CLI tool for automated LinkedIn job discovery and local tracking.

Scrapes LinkedIn's recommended jobs feed, extracts full job descriptions, and stores unique postings in a local SQLite database. Maintains a persistent Playwright browser session; authentication is handled automatically via 1Password CLI with a manual browser fallback.

## Install

```bash
bash install.sh
```

This installs Python dependencies via `uv`, installs Playwright Chromium, creates `~/.openclaw/data/jobhunt/`, and copies `SKILL.md` to `~/.openclaw/skills/jobhunt/`.

## Quick Start

```bash
# Authenticate with LinkedIn (once)
uv run jobhunt auth

# Fetch recommended jobs (default: 30-day lookback, up to 100 jobs)
uv run jobhunt fetch

# List tracked jobs
uv run jobhunt list

# Show full details including job description
uv run jobhunt show 42
```

Add an alias to your shell profile for convenience:
```bash
alias jobhunt="uv run jobhunt"
```

## Commands

| Command | Description |
|---------|-------------|
| `jobhunt auth` | Authenticate with LinkedIn |
| `jobhunt config --show` | View configuration |
| `jobhunt config --set-pref EMAIL` | Set preferred 1Password email |
| `jobhunt fetch [--limit N] [--lookback N] [--dry-run] [--verbose]` | Scrape jobs |
| `jobhunt list [filters] [--json]` | List tracked jobs |
| `jobhunt show <id>` | Show full job details |

See `SKILL.md` for complete documentation.

## Requirements

- macOS arm64 (Apple Silicon)
- Python 3.11+ via `uv`
- 1Password CLI (`op` >= 2.0) — optional; manual login fallback available
- An active LinkedIn account

## Data Locations

| Path | Purpose |
|------|---------|
| `~/.openclaw/data/jobhunt/jobhunt.db` | SQLite database |
| `~/.openclaw/data/jobhunt/config.json` | Configuration |
| `~/.openclaw/data/jobhunt/session/linkedin.json` | Session (0600) |

## Development

```bash
uv sync
uv run playwright install chromium
uv run pytest
uv run jobhunt --help
```
