---
name: jobhunt
description: >
  Automated job-hunt pipeline for macOS. Fetches LinkedIn job postings, tailors resumes
  using AI, and submits applications via browser automation. Runs on a cron schedule.
  Commands: pipeline, fetch, list, show, status, auth. Use when asked to run the job
  pipeline, check job status, tailor a resume for a job, or apply to jobs automatically.
---

# SKILL.md — jobhunt

## What this tool does

`jobhunt` is a macOS CLI tool that automates LinkedIn job discovery and application tracking. It:

1. Authenticates with LinkedIn via macOS Keychain (or manual browser fallback).
2. Scrapes LinkedIn's recommended jobs feed using Playwright (headless Chromium).
3. Stores job postings in a local SQLite database.
4. Tracks jobs through: `new → skipped/tailored → blocked/apply_failed/applied`.

**Resume tailoring and application submission are agent-driven** — the CLI provides data; agents provide intelligence.

All data lives at `~/.openclaw/data/jobhunt/`.

---

## Installation

```bash
cd {baseDir}
bash install.sh
```

---

## Prerequisites

- Python 3.11+ (managed by `uv`)
- macOS Keychain credentials for LinkedIn
- An active LinkedIn account
- For PDF generation: `pandoc` and `xelatex` in PATH (optional)

---

## Quick Start

```bash
jobhunt auth                                              # First-time LinkedIn login
jobhunt fetch --limit 30 --lookback 14                   # Scrape recommended jobs
jobhunt list                                              # List tracked jobs
jobhunt show <job_id>                                     # Show job detail + JD
jobhunt status <job_id> --set tailored --note "done"     # Update status
```

---

## CLI Reference

### `jobhunt auth`
Opens a headed browser for manual LinkedIn login. Saves session to `~/.openclaw/data/jobhunt/session/linkedin.json`.

### `jobhunt fetch [OPTIONS]`
| Option | Default | Description |
|--------|---------|-------------|
| `--limit N` | 25 | Max jobs to collect |
| `--lookback N` | 14 | Days to look back |
| `--dry-run` | off | Print without writing to DB |
| `--verbose` | off | Show per-job progress |

### `jobhunt list [OPTIONS]`
| Option | Default | Description |
|--------|---------|-------------|
| `--status S` | all | Filter by status (comma-separated) |
| `--limit N` | 50 | Max rows |
| `--sort-by` | fetched_at | Sort column |

### `jobhunt show <job_id>`
Show full details + JD text for a specific job.

### `jobhunt status <job_id> --set <status> [--note TEXT]`
Update job status. Valid statuses: `new`, `skipped`, `tailored`, `blocked`, `apply_failed`, `applied`.

Status transitions enforced:
- `new` → `skipped`, `tailored`
- `tailored` → `blocked`, `apply_failed`, `applied`
- `blocked` → `tailored`, `applied`
- `apply_failed` → `applied`

---

## Data Paths

| Path | Purpose |
|------|---------|
| `~/.openclaw/data/jobhunt/jobhunt.db` | SQLite database |
| `~/.openclaw/data/jobhunt/session/linkedin.json` | LinkedIn session (perm 0600) |
| `~/.openclaw/data/jobhunt/resumes/<job_id>/` | Per-job resume artifacts |
| `~/.openclaw/data/jobhunt/profile/` | Applicant ground truth (structured.yaml + narrative md files) |
| `~/.openclaw/data/jobhunt/apply-log/<job_id>.md` | Per-job apply log |
| `~/.openclaw/data/jobhunt/apply-knowledge/platforms/` | Platform experience knowledge base |

---

## Tailor Workflow (Agent-Driven)

Resume tailoring is done by the agent. Steps:

1. **Read the JD**: `jobhunt show <job_id>` — get JD text from the `--- JD ---` section
2. **Read the classify prompt**: `{baseDir}/references/prompts/classify.md`
3. **Classify**: Send JD + classify prompt → get base direction (`ai`/`ic`/`mgmt`/`venture`)
4. **Read base resume**: `$data_dir/profile/base-resumes/base-resume-<direction>.md`
   - `ai` → `base-cv-ai-engineer.md` | `ic` → `base-resume-ic.md`
   - `mgmt` → `base-resume-mgmt.md` | `venture` → `base-resume-venture-builder.md`
5. **Read the tailor prompt**: `{baseDir}/references/prompts/tailor.md`
6. **Tailor**: Send JD + base resume + tailor prompt → get tailored resume markdown
7. **Write output**: Save to `~/.openclaw/data/jobhunt/resumes/<job_id>/tailored.md`
8. **Optional — Analyze**: Read `prompts/analyze.md`, send JD + tailored resume → save to `resumes/<job_id>/analysis.md`
9. **Optional — PDF**: Run `python $data_dir/profile/base-resumes/generate_pdf.py --src tailored.md --out resume.pdf`
10. **Update status**: `jobhunt status <job_id> --set tailored --note "Base: <direction>"`
11. **Write meta**: Save `resumes/<job_id>/meta.json` with prompt hash, base direction, timestamp

---

## Pipeline Overview

The full pipeline (fetch → tailor → apply) is orchestrated by `scripts/pipeline.py`. Agents are spawned per-job. See that script for orchestration logic and batch job handling.

---

## Architecture Notes

- **LinkedIn feed**: Recommended feed has ~24 cards total. Viewport set to 4000px to render all at once.
- **Dedup**: By `(platform, platform_id)`. Existing jobs are skipped entirely.
- **Credentials**: macOS Keychain only. Email: `haomin.liu@gmail.com`.
- **DB**: SQLite stdlib, `user_version` pragma for schema migration tracking.
- **Platform knowledge**: `references/platforms/` — updated by apply agents after each session.
