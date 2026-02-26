# CLAUDE.md — jobhunt

This file is read automatically by Claude Code at session start. Follow these rules strictly.

## Project

- **Tool:** `jobhunt`
- **Purpose:** CLI tool for automated LinkedIn job discovery and local tracking
- **Language:** Python 3.11+, uv for dependency management
- **Platform:** macOS arm64 (Apple Silicon)

## Directory Structure

```
~/code/openclaw-tools/jobhunt/
├── pyproject.toml
├── README.md
├── .python-version          # "3.11"
├── .gitignore
├── CLAUDE.md
├── jobhunt/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py               # click group, all subcommands
│   ├── auth.py              # 1Password + Playwright login flow
│   ├── browser.py           # browser lifecycle, session persistence
│   ├── config.py            # config.json read/write, path constants
│   ├── credentials.py       # op CLI calls, item ranking
│   ├── db.py                # SQLite init, queries, upsert logic
│   ├── extractor.py         # Playwright scraping, HTML strip, jd_hash
│   ├── fetcher.py           # scroll loop, retry, dedup orchestration
│   ├── models.py            # dataclasses: JobCard, JobRecord, Credential, RunStats
│   └── utils.py             # helpers: truncate_str, parse_relative_date, log_*
└── tests/
    ├── conftest.py
    ├── test_credentials.py
    ├── test_db.py
    ├── test_extractor.py
    ├── test_fetcher.py
    └── test_cli.py
```

## Dev Environment

```bash
# Install dependencies
uv sync
uv run playwright install chromium

# Run tests
uv run pytest

# Run CLI locally
uv run jobhunt --help
```

## Design Documents

Full specs in:
- `~/.openclaw/workspace/tool-dev/jobhunt/requirement-spec.md`
- `~/.openclaw/workspace/tool-dev/jobhunt/system-design.md`

**Read both before writing any code.** The system-design.md has exact pseudocode/algorithms for all key modules.

## ⚠️ CREDENTIAL RESOLUTION CHANGE (supersedes system-design.md §4.1 and §6)

The credential resolution strategy has changed. **Do NOT use 1Password as primary**. Use local secrets files instead:

### New credential resolution order for ALL sources:

1. **Local secrets file (primary)** — `~/.openclaw/secrets/<source>.json`
   - Format: `{"username": "...", "password": "..."}`
   - File must exist with chmod 600
   - For LinkedIn: `~/.openclaw/secrets/linkedin.json` ← already created
   
2. **1Password CLI (fallback)** — only if local file not found AND `op` is available without interactive prompt
   - Same domain-based lookup as before
   - If `op` requires interactive auth → skip, go to fallback

3. **Manual browser login (last resort)** — headed Playwright window

### Anthropic API key (for dev tooling, not jobhunt runtime):
- Stored at `~/.openclaw/secrets/anthropic.key` ← already created
- NOT used by jobhunt at runtime; this is for Claude Code itself

### credentials.py changes:
- `resolve_credential(domain)` → first try `~/.openclaw/secrets/{domain_slug}.json`
  - domain_slug: `linkedin.com` → `linkedin`
- Only fall back to `op item list` if local file not found
- `config.json` no longer needs `op_domain` to be meaningful for credential lookup (keep it for fetch_url)

### secrets directory:
- Path: `~/.openclaw/secrets/` (already exists, chmod 700)
- `linkedin.json` — already populated
- Never commit this directory to git (add to .gitignore)

## Coding Standards

- Follow module structure exactly as specified in system-design.md §2 and §9
- Functions: small, single-responsibility
- Error handling: explicit — log to stderr, use meaningful exit codes (0/1/2)
- No hardcoded paths — use constants from `config.py` (DATA_DIR, SESSION_DIR, etc.)
- Credentials (username/password from 1Password): **never written to disk, never logged**
- Session file must be created with permissions `0600`

## Key Technical Decisions (do not change without PM approval)

- CLI framework: `click` (not argparse, not typer)
- Browser automation: `playwright` Python bindings, Chromium only
- Database: `sqlite3` stdlib — no ORM, no SQLAlchemy
- Table output: `rich` library
- HTML stripping: `html.parser` from stdlib — no BeautifulSoup
- jd_hash: MD5 via `hashlib` — not a DB unique constraint, business-logic only
- Dedup primary key: `UNIQUE(platform, platform_id)` DB constraint
- Package manager: `uv`

## Git Rules

- Branch from `main`: `feature/phase1-fetch-track`
- Commit message format: `type: description`
  types: `feat` / `fix` / `test` / `docs` / `chore`
- Commit in logical units — not one giant commit
- Final commit before PR: `chore: ready for integration test`

## Exit Codes

- 0 = success
- 1 = user/config error (bad args, missing session, job not found)
- 2 = all jobs failed during fetch

## Blockers

Stop and notify PM (Kibi) if you hit any of these:
- LinkedIn DOM selectors don't match what's in system-design.md
- A dependency is missing or broken
- A test cannot be written without changing the design
- Design needs to change for any reason

When completely finished, run:
openclaw system event --text "jobhunt phase1 dev complete: all modules implemented, tests written, SKILL.md done, PR opened" --mode now
