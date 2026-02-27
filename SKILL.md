# SKILL.md — jobhunt

## What this tool does

`jobhunt` is a macOS CLI tool that automates LinkedIn job discovery and application tracking for a single job seeker. It:

1. Authenticates with LinkedIn via macOS Keychain auto-login (or a headed manual browser fallback).
2. Scrapes LinkedIn's recommended jobs feed using Playwright (headless Chromium).
3. Stores unique job postings in a local SQLite database.
4. Tracks jobs through a status pipeline: `new → skipped/tailored → blocked/apply_failed/applied`.
5. Provides `list`, `show`, `status` commands to manage tracked jobs.

**Resume tailoring is NOT built into the CLI.** It's handled by the agent layer (see Tailor Workflow below).

All data lives locally at `~/.openclaw/data/jobhunt/`.

---

## Installation

```bash
cd ~/code/openclaw-tools/jobhunt
bash install.sh
```

---

## Prerequisites

- Python 3.11+ (managed by `uv`)
- macOS Keychain credentials for LinkedIn (stored via `security` CLI)
- 1Password CLI (`op` >= 2.0) — optional fallback for credential resolution
- An active LinkedIn account
- For PDF generation: `pandoc` and `xelatex` in PATH (optional)

---

## Quick Start

```bash
# 1. Authenticate (first-time setup)
jobhunt auth

# 2. Fetch recommended jobs
jobhunt fetch --limit 30 --lookback 14

# 3. List tracked jobs
jobhunt list

# 4. Show job detail + JD
jobhunt show <job_id>

# 5. Set status
jobhunt status <job_id> --set tailored --note "Tailored for AI focus"
```

---

## CLI Reference

### `jobhunt auth`
Opens a headed browser for manual LinkedIn login. Saves session to `~/.openclaw/data/jobhunt/session/linkedin.json`.

### `jobhunt fetch [OPTIONS]`
Scrape LinkedIn recommended jobs feed.

| Option | Default | Description |
|--------|---------|-------------|
| `--limit N` | 25 | Max jobs to collect |
| `--lookback N` | 14 | Days to look back |
| `--dry-run` | off | Print without writing to DB |
| `--verbose` | off | Show per-job progress |

### `jobhunt list [OPTIONS]`
List tracked jobs.

| Option | Default | Description |
|--------|---------|-------------|
| `--status S` | all | Filter by status (comma-separated) |
| `--limit N` | 50 | Max rows |
| `--sort-by` | fetched_at | Sort column |

### `jobhunt show <job_id>`
Show full details + JD text for a specific job.

### `jobhunt status <job_id> --set <status> [--note TEXT]`
Update job status. Valid statuses: `new`, `skipped`, `tailored`, `blocked`, `apply_failed`, `applied`.

Status transitions are enforced:
- `new` → `skipped`, `tailored`
- `tailored` → `blocked`, `apply_failed`, `applied`
- `blocked` → `tailored`, `applied`
- `apply_failed` → `applied`

Notes are append-only (never overwritten).

---

## Data Paths

| Path | Purpose |
|------|---------|
| `~/.openclaw/data/jobhunt/jobhunt.db` | SQLite database |
| `~/.openclaw/data/jobhunt/session/linkedin.json` | LinkedIn session (perm 0600) |
| `~/.openclaw/data/jobhunt/config.json` | Config file |
| `~/.openclaw/data/jobhunt/resumes/<job_id>/` | Per-job resume artifacts |

---

## Tailor Workflow (Agent-Driven)

Resume tailoring is done by the agent, NOT the CLI. The CLI provides data; the agent provides intelligence.

### Step-by-step

1. **Read the JD**: `jobhunt show <job_id>` — get JD text from the `--- JD ---` section
2. **Read the classify prompt**: `~/.openclaw/workspace/tool-dev/jobhunt/prompts/classify.md`
3. **Classify**: Send JD + classify prompt → get base direction (`ai`/`ic`/`mgmt`/`venture`)
4. **Read base resume**: `~/code/openclaw-tools/resume-factory/src/base-resume-<direction>.md`
   - `ai` → `base-cv-ai-engineer.md`
   - `ic` → `base-resume-ic.md`
   - `mgmt` → `base-resume-mgmt.md`
   - `venture` → `base-resume-venture-builder.md`
5. **Read the tailor prompt**: `~/.openclaw/workspace/tool-dev/jobhunt/prompts/tailor.md`
6. **Tailor**: Send JD + base resume + tailor prompt → get tailored resume markdown
7. **Write output**: Save to `~/.openclaw/data/jobhunt/resumes/<job_id>/tailored.md`
8. **Optional — Analyze**: Read `prompts/analyze.md`, send JD + tailored resume → save to `resumes/<job_id>/analysis.md`
9. **Optional — PDF**: Run `python ~/code/openclaw-tools/resume-factory/generate_pdf.py --src tailored.md --out resume.pdf`
10. **Update status**: `jobhunt status <job_id> --set tailored --note "Base: <direction>"`
11. **Write meta**: Save `resumes/<job_id>/meta.json` with prompt hash, base direction, timestamp

### Prompt Templates

All prompts live in the workspace (version-controlled):
- `~/.openclaw/workspace/tool-dev/jobhunt/prompts/classify.md`
- `~/.openclaw/workspace/tool-dev/jobhunt/prompts/tailor.md`
- `~/.openclaw/workspace/tool-dev/jobhunt/prompts/analyze.md`

### meta.json Format

```json
{
  "job_id": 42,
  "base_direction": "ic",
  "tailor_prompt_sha256": "abc123...",
  "tailored_at": "2026-02-27T03:00:00Z"
}
```

---

## Architecture Notes

- **LinkedIn feed**: Recommended feed has ~24 cards total (not paginated). Viewport set to 4000px to render all at once.
- **Dedup**: By `(platform, platform_id)`. If a job exists in DB, fetch skips it entirely (no detail page visit).
- **Credentials**: macOS Keychain → 1Password → manual browser login (fallback chain).
- **DB**: SQLite stdlib, `user_version` pragma for schema migration tracking.
