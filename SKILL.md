# SKILL.md — jobhunt

## What this tool does

`jobhunt` is a macOS CLI tool that automates LinkedIn job discovery and local tracking for a single job seeker. It:

1. Authenticates with LinkedIn via 1Password CLI auto-login (or a headed manual browser fallback).
2. Scrapes LinkedIn's recommended jobs feed using Playwright (headless Chromium).
3. Stores unique job postings in a local SQLite database.
4. Provides `list` and `show` commands to review tracked jobs.

All data lives locally at `~/.openclaw/data/jobhunt/`.

---

## Installation

```bash
cd ~/code/openclaw-tools/jobhunt
bash install.sh
```

This installs dependencies, Chromium, and the `jobhunt` CLI into your shell.

---

## Prerequisites

- Python 3.11+ (managed by `uv`)
- 1Password CLI (`op` ≥ 2.0) — optional; required for automatic login
  - Install: https://developer.1password.com/docs/cli/get-started/
  - Must be signed in: `op signin`
- An active LinkedIn account

---

## Quick Start

```bash
# 1. Authenticate (first-time setup)
jobhunt auth

# 2. Fetch recommended jobs
jobhunt fetch

# 3. List tracked jobs
jobhunt list

# 4. Show full details for a specific job
jobhunt show 42
```

---

## Commands

### `jobhunt auth`

Authenticate with LinkedIn and save the session.

- Resolves credentials from 1Password automatically (domain-based lookup).
- Falls back to a headed browser window for manual login if `op` is unavailable.
- Session saved to `~/.openclaw/data/jobhunt/session/linkedin.json` at mode `0600`.

```bash
jobhunt auth
```

---

### `jobhunt config`

View or update configuration settings.

```bash
# Show current config
jobhunt config --show

# Add an email as the highest-priority LinkedIn credential
jobhunt config --set-pref work@example.com
```

Config file: `~/.openclaw/data/jobhunt/config.json`

---

### `jobhunt fetch`

Scrape LinkedIn recommended jobs and store new postings.

```bash
jobhunt fetch                          # default: lookback=30d, limit=100
jobhunt fetch --limit 20              # cap at 20 jobs
jobhunt fetch --lookback 7            # only jobs posted in the last 7 days
jobhunt fetch --dry-run --limit 5     # preview without writing to DB
jobhunt fetch --verbose               # show per-job status lines
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--limit` | 100 | Maximum jobs to process |
| `--lookback` | 30 | Only ingest jobs posted within N days |
| `--dry-run` | off | Scrape and print JSON without writing to DB |
| `--verbose` | off | Print per-job status lines to stderr |

**Exit codes:**
- `0` — success (or dry-run)
- `1` — auth failure
- `2` — every single job failed during fetch

---

### `jobhunt list`

Query and display tracked jobs.

```bash
jobhunt list                              # all jobs, default sort
jobhunt list --status new                 # filter by status
jobhunt list --status new,tailoring       # multiple statuses
jobhunt list --company stripe             # company substring match
jobhunt list --title engineer             # title substring match
jobhunt list --since 2026-02-01           # fetched on or after date
jobhunt list --sort -posted_at --limit 20 # sort by posted date desc
jobhunt list --json                       # JSON output (excludes jd_text)
jobhunt list --json | jq '.[].title'      # pipe to jq
```

**Columns:** `id | status | title | company | location | posted_at | fetched_at`

**Valid `--status` values:** `new`, `skip`, `tailoring`, `applied`, `rejected`

---

### `jobhunt show <id>`

Display all fields for a single job, including the full job description.

```bash
jobhunt show 42
```

Exits with code `1` if the ID does not exist.

---

## Data Model

All data is stored in `~/.openclaw/data/jobhunt/jobhunt.db` (SQLite).

Key fields:

| Field | Description |
|-------|-------------|
| `id` | Local surrogate key |
| `platform_id` | LinkedIn's numeric job ID |
| `title` | Job title |
| `company` | Company name |
| `location` | Location string |
| `posted_at` | ISO-8601 date posted |
| `fetched_at` | ISO-8601 UTC timestamp when first ingested |
| `updated_at` | ISO-8601 UTC timestamp of last JD update (NULL if never updated) |
| `jd_text` | Full plain-text job description |
| `jd_hash` | MD5 of normalised JD (for change detection) |
| `status` | Workflow status: `new` / `skip` / `tailoring` / `applied` / `rejected` |

To manually update a job's status, edit the SQLite database directly:
```bash
sqlite3 ~/.openclaw/data/jobhunt/jobhunt.db \
  "UPDATE jobs SET status='tailoring' WHERE id=42;"
```

---

## Deduplication

Two-layer dedup strategy:

1. **Platform ID (DB-level):** `UNIQUE(platform, platform_id)` constraint prevents duplicate listings.
2. **JD hash (application-level):** If the same `platform_id` is scraped again with a different `jd_hash`, the JD is updated in-place (the company edited the description).

Possible reposts (same JD on a different listing ID) are logged as warnings but inserted normally so you see them.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `op CLI not found` | Install 1Password CLI or use manual login |
| Session expired mid-fetch | Run `jobhunt auth` again |
| LinkedIn DOM changed | Open a GitHub issue; selectors may need updating |
| CAPTCHA / security checkpoint | Run `jobhunt auth` in a headed browser (automatic fallback) |
| All jobs erroring | Check network, re-run `jobhunt auth` |

---

## File Locations

| File | Purpose |
|------|---------|
| `~/.openclaw/data/jobhunt/jobhunt.db` | SQLite database |
| `~/.openclaw/data/jobhunt/config.json` | User configuration |
| `~/.openclaw/data/jobhunt/session/linkedin.json` | Playwright session (0600) |
