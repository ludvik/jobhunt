# SKILL.md — jobhunt

## What this tool does

`jobhunt` is a macOS CLI tool that automates LinkedIn job discovery, resume tailoring, and application tracking for a single job seeker. It:

1. Authenticates with LinkedIn via macOS Keychain auto-login (or a headed manual browser fallback).
2. Scrapes LinkedIn's recommended jobs feed using Playwright (headless Chromium).
3. Stores unique job postings in a local SQLite database.
4. Generates JD-tailored resumes via OpenAI, with automatic base direction classification.
5. Tracks jobs through a status pipeline: `new → tailored → blocked/apply_failed/applied`.
6. Provides `list`, `show`, `status`, and `tailor` commands to manage tracked jobs.

All data lives locally at `~/.openclaw/data/jobhunt/`.

---

## Installation

```bash
cd ~/code/openclaw-tools/jobhunt
bash install.sh
```

This installs dependencies, Chromium, default prompt templates, and the `jobhunt` CLI into your shell.

---

## Prerequisites

- Python 3.11+ (managed by `uv`)
- macOS Keychain credentials for LinkedIn and OpenAI (stored via `security` CLI)
- 1Password CLI (`op` >= 2.0) — optional fallback for credential resolution
- An active LinkedIn account
- For PDF generation: `pandoc` and `xelatex` in PATH

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

# 5. Tailor a resume for a job
jobhunt tailor 42

# 6. Update job status
jobhunt status 42 --set applied --note "Applied via LinkedIn Easy Apply"
```

---

## Commands

### `jobhunt auth`

Authenticate with LinkedIn and save the session.

- Resolves credentials from macOS Keychain automatically (primary).
- Falls back to 1Password CLI, then to a headed browser window for manual login.
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
jobhunt list --status blocked,apply_failed # multiple statuses (OR)
jobhunt list --company stripe             # company substring match
jobhunt list --title engineer             # title substring match
jobhunt list --since 2026-02-01           # fetched on or after date
jobhunt list --sort -posted_at --limit 20 # sort by posted date desc
jobhunt list --json                       # JSON output (excludes jd_text)
```

**Columns:** `id | status | title | company | location | posted_at | fetched_at`

**Valid `--status` values:** `new`, `skipped`, `tailored`, `blocked`, `apply_failed`, `applied`

---

### `jobhunt show <id>`

Display all fields for a single job, including the full job description.

```bash
jobhunt show 42
```

Exits with code `1` if the ID does not exist.

---

### `jobhunt tailor <job_id>`

Generate a tailored resume for a tracked job using OpenAI.

```bash
jobhunt tailor 42                          # auto-classify base direction
jobhunt tailor 42 --base mgmt             # force management base resume
jobhunt tailor 42 --dry-run               # print to stdout, no file writes
jobhunt tailor 42 --skip-analyze          # skip match analysis step
jobhunt tailor 42 --tailor-prompt /tmp/t.md  # use custom tailor prompt
```

**What it does:**
1. Validates the job exists and has a non-empty JD.
2. Classifies the JD into a base direction (`ai`, `ic`, `mgmt`, `venture`) unless `--base` is provided.
3. Loads the corresponding base resume from `resume-factory/src/`.
4. Calls OpenAI to rewrite the resume for the specific JD.
5. Writes `tailored.md`, `meta.json`, and optionally `analysis.md` to `~/.openclaw/data/jobhunt/resumes/<job_id>/`.
6. Attempts PDF generation via `resume-factory` (best-effort).
7. Auto-transitions job status from `new` to `tailored`.

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--base` | auto | Force base direction: `ai`, `ic`, `mgmt`, or `venture` |
| `--dry-run` | off | Print markdown to stdout; no files, no status change |
| `--skip-analyze` | off | Skip match analysis (no `analysis.md`) |
| `--tailor-prompt` | — | Override tailor prompt file |
| `--classify-prompt` | — | Override classify prompt file |
| `--analyze-prompt` | — | Override analyze prompt file |

**Exit codes:**
- `0` — success (including tolerated PDF/analysis failures)
- `1` — validation error, missing key, missing prompt, or LLM failure

---

### `jobhunt status <job_id> --set <status>`

Set job status and optionally attach a note.

```bash
jobhunt status 42 --set blocked --note "Waiting for recruiter response"
jobhunt status 42 --set applied
```

**Allowed transitions:**
- `new → skipped`
- `new → tailored`
- `tailored → blocked`
- `tailored → apply_failed`
- `tailored → applied`
- `blocked → tailored`
- `blocked → applied`
- `apply_failed → applied`

Invalid transitions exit with code `1`.

---

## Data Model

All data is stored in `~/.openclaw/data/jobhunt/jobhunt.db` (SQLite).

### `jobs` table

| Field | Description |
|-------|-------------|
| `id` | Local surrogate key |
| `platform_id` | LinkedIn's numeric job ID |
| `title` | Job title |
| `company` | Company name |
| `location` | Location string |
| `posted_at` | ISO-8601 date posted |
| `fetched_at` | ISO-8601 UTC timestamp when first ingested |
| `updated_at` | ISO-8601 UTC timestamp of last JD update |
| `status_updated_at` | ISO-8601 UTC timestamp of last status change |
| `jd_text` | Full plain-text job description |
| `jd_hash` | MD5 of normalised JD (for change detection) |
| `status` | `new` / `skipped` / `tailored` / `blocked` / `apply_failed` / `applied` |

### `job_notes` table

| Field | Description |
|-------|-------------|
| `id` | Auto-increment key |
| `job_id` | FK to `jobs.id` |
| `created_at` | ISO-8601 UTC timestamp |
| `status_after` | Status at time of note |
| `content` | Note text |
| `source` | Origin (`cli` by default) |

---

## Resume Artifacts

Generated per-job in `~/.openclaw/data/jobhunt/resumes/<job_id>/`:

| File | Description |
|------|-------------|
| `tailored.md` | LLM-generated tailored resume (Markdown) |
| `meta.json` | Metadata: base, model, prompt version, timestamps |
| `analysis.md` | Match analysis (score, strengths, gaps, interview tips) |
| `resume.pdf` | PDF output from resume-factory (best-effort) |

---

## Prompt Templates

Editable templates in `~/.openclaw/data/jobhunt/prompts/`:

| File | Purpose |
|------|---------|
| `classify.md` | JD → base direction classification |
| `tailor.md` | Base resume → tailored resume rewrite |
| `analyze.md` | JD + resume → structured match analysis |

Templates use `{{variable}}` placeholders.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `op CLI not found` | Install 1Password CLI or use macOS Keychain |
| `OpenAI API key not found` | Store key: `security add-generic-password -a jobhunt -s openai -w <key>` |
| Session expired mid-fetch | Run `jobhunt auth` again |
| LinkedIn DOM changed | Open a GitHub issue; selectors may need updating |
| PDF generation failed | Install `pandoc` and `xelatex`; `tailored.md` is still retained |

---

## File Locations

| File | Purpose |
|------|---------|
| `~/.openclaw/data/jobhunt/jobhunt.db` | SQLite database |
| `~/.openclaw/data/jobhunt/config.json` | User configuration |
| `~/.openclaw/data/jobhunt/session/linkedin.json` | Playwright session (0600) |
| `~/.openclaw/data/jobhunt/prompts/` | Editable prompt templates |
| `~/.openclaw/data/jobhunt/resumes/<id>/` | Per-job tailored resume artifacts |
