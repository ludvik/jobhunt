#!/usr/bin/env python3
"""pipeline.py — jobhunt workflow orchestrator.

Usage: uv run python scripts/pipeline.py [--dry-run] [--job-id N] [--limit N] [--timeout M] [--verbose] [--skip-fetch]
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from string import Template

import yaml

from scripts.ats_resolver import classify_ats_from_url, get_ats_hint_for_url

# ── Paths ─────────────────────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).parent.parent.resolve()
DATA_DIR = Path.home() / ".openclaw" / "data" / "jobhunt"
def _daily_log_path() -> Path:
    from datetime import date
    return DATA_DIR / "logs" / f"pipeline-{date.today().isoformat()}.log"


# ── Config ────────────────────────────────────────────────────────────────────
def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(skill_dir: Path = SKILL_DIR, data_dir: Path = DATA_DIR) -> dict:
    """Merge skill-dir defaults with data-dir user overrides (deep merge)."""
    skill_cfg = skill_dir / "config.yaml"
    data_cfg = data_dir / "config.yaml"
    config: dict = {}
    if skill_cfg.exists():
        config = yaml.safe_load(skill_cfg.read_text()) or {}
    if data_cfg.exists():
        override = yaml.safe_load(data_cfg.read_text()) or {}
        config = _deep_merge(config, override)
    return config


# ── Discord notifications ─────────────────────────────────────────────────────
_DEFAULT_DISCORD_CHANNEL = "1476444984055169054"


def notify(message: str, log: logging.Logger, channel_id: str = _DEFAULT_DISCORD_CHANNEL) -> None:
    """Send a progress message to Discord channel."""
    try:
        subprocess.run(
            ["openclaw", "message", "send", "--channel", "discord",
             "--target", channel_id, "--message", message],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:
        log.warning("PIPELINE: Failed to send notification: %s", e)


# ── Logging ───────────────────────────────────────────────────────────────────
def setup_logging(verbose: bool) -> logging.Logger:
    log_file = _daily_log_path()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "[%(asctime)s] [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%SZ"
    logging.Formatter.converter = time.gmtime  # UTC timestamps

    logger = logging.getLogger("pipeline")
    logger.setLevel(level)

    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    logger.addHandler(console_handler)
    return logger


# ── Prompt loading ────────────────────────────────────────────────────────────
def load_prompt(role: str, variables: dict,
                data_dir: Path = DATA_DIR, skill_dir: Path = SKILL_DIR) -> str:
    """Load prompt template — data-dir overrides skill-dir."""
    data_path = data_dir / "agents" / role / "task_prompt.md"
    skill_path = skill_dir / "agents" / role / "task_prompt.md"
    path = data_path if data_path.exists() else skill_path
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found for role '{role}': {path}")
    template_str = path.read_text(encoding="utf-8")
    return Template(template_str).safe_substitute(variables)


def load_agent_config(role: str, global_config: dict,
                      data_dir: Path = DATA_DIR, skill_dir: Path = SKILL_DIR) -> dict:
    """Load per-role config — data-dir overrides skill-dir, merged on top of global pipeline."""
    data_path = data_dir / "agents" / role / "config.yaml"
    skill_path = skill_dir / "agents" / role / "config.yaml"
    path = data_path if data_path.exists() else skill_path
    role_cfg: dict = {}
    if path.exists():
        role_cfg = yaml.safe_load(path.read_text()) or {}
    merged = global_config.get("pipeline", {}).copy()
    merged.update(role_cfg)
    return merged


# ── Agent invocation ──────────────────────────────────────────────────────────
def run_agent(session_id: str, prompt: str, timeout: int, thinking: str,
              dry_run: bool, log: logging.Logger, model: str | None = None,
              agent: str | None = None) -> dict:
    """Invoke openclaw agent, return parsed JSON result."""
    cmd = [
        "openclaw", "agent",
        "--session-id", session_id,
        "--message", prompt,
        "--thinking", thinking,
        "--timeout", str(timeout),
        "--json",
    ]
    if model:
        cmd.extend(["--model", model])
    if agent:
        cmd.extend(["--agent", agent])
    log.info("PIPELINE: Invoking agent session=%s model=%s timeout=%ds", session_id, model or "default", timeout)
    log.debug("PIPELINE: Command: %s", " ".join(cmd))

    if dry_run:
        log.info("PIPELINE: [DRY RUN] Would run: %s", " ".join(cmd))
        return {"dry_run": True}

    # If prompt is very long, write to temp file and instruct agent to read it
    if len(prompt) > 10000:
        import tempfile
        prompt_file = Path(tempfile.mkdtemp()) / f"{session_id}-prompt.md"
        prompt_file.write_text(prompt)
        # Replace the --message with a short instruction to read the file
        cmd = [c for c in cmd]
        for i, c in enumerate(cmd):
            if c == "--message" and i + 1 < len(cmd):
                cmd[i + 1] = f"Read and follow the instructions in {prompt_file} exactly. Do NOT summarize or skip any section."
                break
        log.info("PIPELINE: Prompt too long (%d chars), wrote to %s", len(prompt), prompt_file)

    try:
        # Use Popen to avoid pipe buffer deadlock on large agent output
        import tempfile as _tf
        stdout_file = Path(_tf.mkdtemp()) / f"{session_id}-stdout.json"
        stderr_file = Path(_tf.mkdtemp()) / f"{session_id}-stderr.log"
        with open(stdout_file, "w") as fout, open(stderr_file, "w") as ferr:
            proc = subprocess.Popen(cmd, stdout=fout, stderr=ferr, text=True)
            try:
                proc.wait(timeout=timeout + 30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                log.error("PIPELINE: Agent %s timed out after %ds", session_id, timeout)
                return {"error": "subprocess_timeout"}

        if proc.returncode != 0:
            err_text = stderr_file.read_text()[:500] if stderr_file.exists() else ""
            log.error("PIPELINE: Agent %s exited %d: %s", session_id, proc.returncode, err_text)
            return {"error": err_text, "returncode": proc.returncode}

        stdout_text = stdout_file.read_text().strip() if stdout_file.exists() else ""
        try:
            return json.loads(stdout_text) if stdout_text else {}
        except json.JSONDecodeError as exc:
            log.error("PIPELINE: Agent %s returned invalid JSON: %s", session_id, exc)
            return {"error": "invalid_json"}
    except Exception as exc:
        log.error("PIPELINE: Agent %s unexpected error: %s", session_id, exc)
        return {"error": str(exc)}


# ── DB helpers ────────────────────────────────────────────────────────────────
def get_eligible_jobs(db_path: Path, limit: int) -> list[dict]:
    """Return jobs with status='new', up to limit."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, title, company, job_url AS url, status FROM jobs "
            "WHERE status='new' ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_tailored_jobs(db_path: Path, limit: int, data_dir: Path = DATA_DIR) -> list[dict]:
    """Return jobs with status='tailored' AND resume artifact exists."""
    if limit <= 0:
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, title, company, job_url AS url, status FROM jobs "
            "WHERE status='tailored' ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    jobs = [dict(r) for r in rows]
    return [j for j in jobs if (data_dir / "resumes" / str(j["id"]) / "tailored.md").exists()]


def get_job(db_path: Path, job_id: int) -> dict | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, title, company, job_url AS url, status FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    return dict(row) if row else None


def get_job_status(db_path: Path, job_id: int) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    return row[0] if row else None


# ── Fetch ─────────────────────────────────────────────────────────────────────
def count_new_jobs(db_path: Path) -> int:
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'new'").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def _count_total_jobs(db_path: Path) -> int:
    try:
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0



def classify_new_jobs(db_path: Path, config: dict, log: logging.Logger,
                      channel_id: str = _DEFAULT_DISCORD_CHANNEL) -> None:
    """Filter new jobs using exclude-pattern blacklist, marking irrelevant ones as not_suitable."""
    import re as _re

    classify_cfg = config.get("classify", {})
    if not classify_cfg.get("enabled", True):
        log.info("PIPELINE: Classification disabled — skipping.")
        return

    exclude_patterns = classify_cfg.get("exclude_patterns", [])
    compiled = [_re.compile(p, _re.IGNORECASE) for p in exclude_patterns]
    blocked_platforms = classify_cfg.get("blocked_platforms", [])

    if not db_path.exists():
        log.info("PIPELINE: DB not found — skipping classification.")
        return

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, title, company, job_url FROM jobs WHERE status='new'"
        ).fetchall()

    kept = 0
    skipped = 0
    total = len(rows)

    for row in rows:
        job_id = row["id"]
        title = row["title"] or ""
        company = row["company"] or ""

        matched_pattern = None
        # Check blocked platforms (CAPTCHA, etc.)
        job_url = row["job_url"] or ""
        for bp in blocked_platforms:
            if bp in job_url:
                matched_pattern = f"blocked_platform ({bp})"
                break

        if not matched_pattern:
            for pat in compiled:
                if pat.search(title):
                    matched_pattern = pat.pattern
                    break

        # Check JD for low experience requirement (X+ years where X < 5)
        if not matched_pattern:
            import re as _re2
            jd = ""
            with sqlite3.connect(db_path) as conn2:
                conn2.row_factory = sqlite3.Row
                row2 = conn2.execute("SELECT jd_text FROM jobs WHERE id=?", (job_id,)).fetchone()
                if row2:
                    jd = row2["jd_text"] or ""
            min_years = classify_cfg.get("min_experience_years", 0)
            if min_years and jd:
                # Only check for non-senior titles (senior roles often have low stated minimums)
                senior_keywords = ['senior', 'sr.', 'staff', 'principal', 'lead', 'director',
                                   'vp', 'head', 'chief', 'distinguished', 'founding', 'manager']
                is_senior_title = any(kw in title.lower() for kw in senior_keywords)
                if not is_senior_title:
                    year_matches = _re2.findall(r'(\d+)\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|professional)', jd, _re2.IGNORECASE)
                    if year_matches:
                        max_required = max(int(y) for y in year_matches)
                        if max_required < min_years:
                            matched_pattern = f"experience_too_junior ({max_required}+ years < {min_years})"

        if matched_pattern:
            log.info("PIPELINE: Filtered job %d (%s @ %s) — matched: %s",
                     job_id, title, company, matched_pattern)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE jobs SET status='not_suitable', status_updated_at=datetime('now') WHERE id=?",
                    (job_id,)
                )
            skipped += 1
        else:
            kept += 1

    log.info("PIPELINE: Classification complete — %d kept, %d filtered out of %d new jobs",
             kept, skipped, total)
    if skipped > 0:
        notify(f"Classification: {kept} kept, {skipped} filtered out of {total} new jobs",
               log, channel_id)


def run_fetch(config: dict, dry_run: bool, log: logging.Logger,
              skill_dir: Path = SKILL_DIR, db_path: Path = DATA_DIR / "jobhunt.db",
              channel_id: str = _DEFAULT_DISCORD_CHANNEL) -> None:
    fetch_cfg = config.get("fetch", {})
    limit = fetch_cfg.get("limit", 30)
    lookback = fetch_cfg.get("lookback", 14)
    fetch_urls = fetch_cfg.get("urls", [])

    if not fetch_urls:
        # Fall back to single recommended URL (backward compat)
        fallback_url = config.get("sources", {}).get("linkedin", {}).get(
            "fetch_url", "https://www.linkedin.com/jobs/collections/recommended/"
        )
        fetch_urls = [{"name": "recommended", "url": fallback_url}]

    # Write fetch output to dedicated log file
    fetch_log_path = DATA_DIR / "logs" / "fetch.log"
    fetch_log_path.parent.mkdir(parents=True, exist_ok=True)
    _fh = logging.FileHandler(str(fetch_log_path), mode="a")
    _fh.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ"))
    log.addHandler(_fh)

    log.info("PIPELINE: Running fetch for %d collection(s), --limit %d --lookback %d",
             len(fetch_urls), limit, lookback)
    before = count_new_jobs(db_path)
    log.info("PIPELINE: Before fetch: %d new jobs", before)

    if dry_run:
        for entry in fetch_urls:
            name = entry.get("name", "?") if isinstance(entry, dict) else "?"
            url = entry.get("url", entry) if isinstance(entry, dict) else entry
            log.info("PIPELINE: [DRY RUN] Would fetch collection: %s (%s)", name, url)
        return

    for i, entry in enumerate(fetch_urls, 1):
        name = entry.get("name", "?") if isinstance(entry, dict) else "?"
        url = entry.get("url", entry) if isinstance(entry, dict) else entry
        log.info("PIPELINE: Fetching collection %d/%d: %s", i, len(fetch_urls), name)
        count_before = count_new_jobs(db_path)
        total_before = _count_total_jobs(db_path)
        try:
            result = subprocess.run(
                ["uv", "run", "--directory", str(skill_dir), "python", "scripts/cli.py",
                 "fetch", "--limit", str(limit), "--lookback", str(lookback), "--url", url],
                cwd=skill_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 min max per collection
            )
            if result.returncode != 0:
                log.warning("PIPELINE: Collection '%s' FAILED (exit %d): %s",
                            name, result.returncode, result.stderr[:200])
            else:
                total_after = _count_total_jobs(db_path)
                new_added = total_after - total_before
                duplicated = limit - new_added  # approximate: limit attempted minus new
                log.info("PIPELINE: Collection '%s' done — %d new, %d total",
                         name, new_added, total_after)
        except subprocess.TimeoutExpired:
            log.warning("PIPELINE: Collection '%s' timed out (300s), skipping", name)
        except Exception as exc:
            log.warning("PIPELINE: Collection '%s' failed: %s", name, exc)

    after = count_new_jobs(db_path)
    newly = after - before
    log.info("PIPELINE: After all fetches: %d new jobs (%d newly fetched)", after, newly)
    notify(f"Fetch complete ({len(fetch_urls)} collections). {before} -> {after} new jobs ({newly} newly fetched)",
           log, channel_id)
    log.removeHandler(_fh)
    _fh.close()


# ── Main ──────────────────────────────────────────────────────────────────────
# ── Code-driven tailor (1 LLM call) ──────────────────────────────────────────
def run_tailor_direct(job: dict, config: dict, db_path: Path, log: logging.Logger,
                      skill_dir: Path = SKILL_DIR, data_dir: Path = DATA_DIR) -> bool:
    """Tailor a resume using code-driven LLM call. Returns True on success."""
    jid = job["id"]

    # 1. Read JD from DB
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT jd_text, title, company FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row or not row["jd_text"]:
        log.error("PIPELINE: Job %d: No JD text in DB", jid)
        return False
    jd_text = row["jd_text"]

    # 2. Read prompts
    classify_prompt_path = skill_dir / "references" / "prompts" / "classify.md"
    tailor_prompt_path = skill_dir / "references" / "prompts" / "tailor.md"
    if not classify_prompt_path.exists() or not tailor_prompt_path.exists():
        log.error("PIPELINE: Job %d: Prompt files missing", jid)
        return False
    classify_prompt = classify_prompt_path.read_text()
    tailor_prompt = tailor_prompt_path.read_text()

    # 3. Read all base resumes
    base_resume_dir = data_dir / "profile" / "base-resumes"
    direction_map = {
        "ai": "base-cv-ai-engineer.md",
        "ic": "base-resume-ic.md",
        "mgmt": "base-resume-mgmt.md",
        "venture": "base-resume-venture-builder.md",
    }

    # 4. Single LLM call: classify + tailor combined
    combined_prompt = f"""You have TWO tasks. Complete both in ONE response.

## TASK 1: Classify
{classify_prompt}

## TASK 2: Tailor
{tailor_prompt}

## Input

### Job Description
{jd_text}

### Available Base Resumes
"""
    for direction, filename in direction_map.items():
        resume_path = base_resume_dir / filename
        if resume_path.exists():
            combined_prompt += f"\n#### Direction: {direction}\n{resume_path.read_text()}\n"

    combined_prompt += """
## Output Format
Respond with EXACTLY this format (no other text):

DIRECTION: <ai|ic|mgmt|venture>
---RESUME---
<tailored resume markdown>
"""

    # Call LLM via openclaw agent with no-tool instruction
    log.info("PIPELINE: Job %d: Running code-driven tailor (single LLM call)", jid)
    session_id = f"jobhunt-tailor-{jid}"
    
    result = subprocess.run(
        ["openclaw", "agent",
         "--agent", "jobhunt-apply",
         "--session-id", session_id,
         "--message", f"RESPOND DIRECTLY. Do NOT use any tools. Do NOT read any files. All input is below.\n\n{combined_prompt}",
         "--thinking", "off",
         "--timeout", "120",
         "--json"],
        capture_output=True, text=True, timeout=150
    )

    if result.returncode != 0:
        log.error("PIPELINE: Job %d: Tailor LLM call failed (exit %d)", jid, result.returncode)
        return False

    # Parse output — openclaw agent --json returns {result: {payloads: [{text: "..."}]}}
    try:
        import json as _json
        agent_out = _json.loads(result.stdout)
        res = agent_out.get("result", {})
        if isinstance(res, dict):
            payloads = res.get("payloads", [])
            response_text = payloads[0]["text"] if payloads else ""
        else:
            response_text = str(res)
    except Exception:
        response_text = result.stdout
    response_text = str(response_text)

    # Extract direction and resume
    direction = "ic"  # default
    resume_md = response_text
    
    if "DIRECTION:" in response_text and "---RESUME---" in response_text:
        parts = response_text.split("---RESUME---", 1)
        header = parts[0]
        resume_md = parts[1].strip() if len(parts) > 1 else ""
        for d in ["ai", "ic", "mgmt", "venture"]:
            if f"DIRECTION: {d}" in header.lower() or f"DIRECTION: {d}" in header:
                direction = d
                break
    elif response_text.strip():
        # Fallback: assume entire response is the resume
        resume_md = response_text.strip()

    if not resume_md or len(resume_md) < 100:
        log.error("PIPELINE: Job %d: Tailor output too short (%d chars)", jid, len(resume_md))
        return False

    # 5. Write output files
    resume_dir = data_dir / "resumes" / str(jid)
    resume_dir.mkdir(parents=True, exist_ok=True)
    (resume_dir / "tailored.md").write_text(resume_md)
    
    import json as _json
    meta = {
        "job_id": jid,
        "title": job["title"],
        "company": job["company"],
        "base_direction": direction,
        "base_resume": direction_map.get(direction, "base-resume-ic.md"),
        "tailored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (resume_dir / "meta.json").write_text(_json.dumps(meta, indent=2))

    # 6. Update DB status
    update_result = subprocess.run(
        ["uv", "run", "--directory", str(skill_dir), "python", "scripts/cli.py",
         "status", str(jid), "--set", "tailored", "--note", f"Base: {direction}"],
        capture_output=True, text=True, timeout=30
    )
    if update_result.returncode != 0:
        log.warning("PIPELINE: Job %d: Status update failed, trying direct SQL", jid)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE jobs SET status='tailored', status_updated_at=datetime('now') WHERE id=?",
                (jid,))

    log.info("PIPELINE: Job %d: Tailored (direction=%s, %d chars)", jid, direction, len(resume_md))
    return True


def _force_apply_failed(db_path: Path, job_id: int, note: str, log: logging.Logger) -> None:
    """Write apply_failed to DB if job status is not already terminal.

    Called as a guard when the apply agent exits without writing its own status.
    Only acts when current status is 'tailored' (i.e. still pre-apply).
    """
    current = get_job_status(db_path, job_id)
    if current in ("applied", "blocked", "apply_failed"):
        return  # agent already wrote status — do not overwrite
    log.warning(
        "PIPELINE: _force_apply_failed: job %d status=%s — writing apply_failed (note=%s)",
        job_id, current, note,
    )
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE jobs SET status='apply_failed', status_updated_at=datetime('now') WHERE id=?",
                (job_id,),
            )
    except Exception as exc:
        log.error("PIPELINE: _force_apply_failed: DB write failed for job %d: %s", job_id, exc)


# ── ATS pre-resolution ────────────────────────────────────────────────────────

def _extract_linkedin_external_url(job_url: str, timeout: int = 15) -> str | None:
    """Open a LinkedIn job page and extract the external apply URL via browser evaluate.

    Returns the href of the first non-LinkedIn "Apply" / "company website" link,
    or None if not found or on any error.  Total wall-clock time is bounded by
    *timeout* (seconds, default 15).
    """
    # JS that finds the first non-LinkedIn "apply" anchor on the page
    js_fn = (
        "() => {"
        "  const links = Array.from(document.querySelectorAll('a'));"
        "  for (const a of links) {"
        "    const text = (a.textContent || '').toLowerCase().trim();"
        "    const href = a.href || '';"
        "    if ((text.includes('apply') || text.includes('company website'))"
        "        && href && !href.includes('linkedin.com')) {"
        "      return href;"
        "    }"
        "  }"
        "  return null;"
        "}"
    )
    nav_timeout = max(timeout - 5, 5)
    try:
        nav = subprocess.run(
            ["openclaw", "browser", "--browser-profile", "openclaw", "navigate", job_url],
            capture_output=True, text=True, timeout=nav_timeout,
        )
        if nav.returncode != 0:
            return None
        time.sleep(2)  # brief settle for JS rendering
        eval_result = subprocess.run(
            ["openclaw", "browser", "--browser-profile", "openclaw", "evaluate",
             "--fn", js_fn],
            capture_output=True, text=True, timeout=10,
        )
        if eval_result.returncode != 0:
            return None
        raw = eval_result.stdout.strip()
        if not raw:
            return None
        # Output may be JSON-encoded string or raw URL
        try:
            val = json.loads(raw)
            if isinstance(val, str) and val.startswith("http"):
                return val
        except Exception:
            if raw.startswith("http"):
                return raw
    except Exception:
        pass
    return None


def resolve_apply_url(
    job_url: str,
    job_id: int,
    company: str,
    log: logging.Logger | None = None,
    _linkedin_extractor=None,  # injectable for tests
) -> tuple[str, str]:
    """Compute the best apply URL before handing off to the apply agent.

    Resolution pipeline (total time ≤ 20 s):
      1. LinkedIn URL  → extract external apply link via browser evaluate (≤15 s)
      2. Classify the resolved URL with classify_ats_from_url
         - Known ATS → return as-is (already a form URL)
      3. Non-ATS / company page → check ATS cache by host
         - Cache hit with iframe_src → use iframe_src as final URL
         - Cache hit without iframe_src → keep URL, note platform hint
         - No cache → keep URL, note "company_page_no_cache"

    Args:
        job_url:             Raw job URL from DB (may be LinkedIn or direct ATS).
        job_id:              Job ID for logging.
        company:             Company name for logging.
        log:                 Optional logger.
        _linkedin_extractor: Override for _extract_linkedin_external_url (testing).

    Returns:
        (final_url, resolution_note)
        resolution_note is a semicolon-separated chain of hints, e.g.
        "linkedin_external;ats_direct:greenhouse"
    """
    from urllib.parse import urlparse

    _log = log or logging.getLogger("pipeline")

    if not job_url:
        return "", "no_url"

    resolved_url = job_url
    notes: list[str] = []

    # ── Step 1: LinkedIn external link extraction ─────────────────────────────
    try:
        parsed = urlparse(job_url)
        is_linkedin = "linkedin.com" in parsed.netloc.lower()
    except Exception:
        is_linkedin = False

    extractor = _linkedin_extractor if _linkedin_extractor is not None else _extract_linkedin_external_url

    if is_linkedin:
        try:
            external = extractor(job_url, timeout=15)
            if external:
                _log.info("PIPELINE: Job %d: LinkedIn → external URL: %s", job_id, external)
                resolved_url = external
                notes.append("linkedin_external")
            else:
                _log.info("PIPELINE: Job %d: LinkedIn — no external URL found, using original", job_id)
                notes.append("linkedin_no_external")
        except Exception as exc:
            _log.warning("PIPELINE: Job %d: LinkedIn extraction error: %s", job_id, exc)
            notes.append("linkedin_extract_failed")

    # ── Step 2: ATS classification ────────────────────────────────────────────
    ats_platform = classify_ats_from_url(resolved_url)
    if ats_platform != "generic":
        notes.append(f"ats_direct:{ats_platform}")
        _log.info("PIPELINE: Job %d: Resolved URL classified as %s — using directly",
                  job_id, ats_platform)
        return resolved_url, ";".join(notes)

    # ── Step 3: Cache lookup for iframe hint ──────────────────────────────────
    cache_hint = get_ats_hint_for_url(resolved_url)
    if cache_hint:
        platform = cache_hint.get("platform", "generic")
        iframe_src = cache_hint.get("iframe_src", "")
        if iframe_src and iframe_src.startswith("http"):
            notes.append(f"cache_iframe:{platform}")
            _log.info("PIPELINE: Job %d: Cache hit — iframe src (%s): %s",
                      job_id, platform, iframe_src)
            return iframe_src, ";".join(notes)
        else:
            notes.append(f"cache_hint:{platform}")
            _log.info("PIPELINE: Job %d: Cache hit — platform %s, no iframe src; keeping URL",
                      job_id, platform)
    else:
        notes.append("company_page_no_cache")
        _log.info("PIPELINE: Job %d: Non-ATS company page — no cache entry", job_id)

    return resolved_url, ";".join(notes)


def main() -> None:
    parser = argparse.ArgumentParser(description="jobhunt pipeline orchestrator")
    parser.add_argument("--dry-run", action="store_true",
                        help="Plan only — no agent calls, no DB changes")
    parser.add_argument("--job-id", type=int, help="Process a single job by ID")
    parser.add_argument("--limit", type=int, help="Max jobs to process (overrides config)")
    parser.add_argument("--timeout", type=int, default=50, help="Pipeline timeout in minutes")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip fetch step")
    args = parser.parse_args()

    log = setup_logging(args.verbose)
    log.info("PIPELINE: === Run started ===")
    deadline = time.monotonic() + args.timeout * 60
    log.info("PIPELINE: Timeout set to %d minutes", args.timeout)

    config = load_config(SKILL_DIR, DATA_DIR)
    db_path = DATA_DIR / "jobhunt.db"

    pipeline_cfg = config.get("pipeline", {})
    limit = args.limit if args.limit is not None else pipeline_cfg.get("limit", 10)
    channel_id = pipeline_cfg.get("discord_channel", _DEFAULT_DISCORD_CHANNEL)

    results = {
        "total": 0, "applied": 0, "blocked": 0,
        "apply_failed": 0, "tailor_failed": 0, "skipped": 0,
    }

    # Step 1: Fetch (skip for single-job or --skip-fetch)
    if not args.skip_fetch and not args.job_id:
        run_fetch(config, args.dry_run, log, channel_id=channel_id)

    # Step 1b: Classify new jobs (filter irrelevant ones)
    if not args.job_id:
        classify_new_jobs(db_path, config, log, channel_id=channel_id)

    # Step 2: Determine job queue
    if args.job_id:
        if not db_path.exists():
            log.error("PIPELINE: DB not found at %s", db_path)
            sys.exit(1)
        job = get_job(db_path, args.job_id)
        if not job:
            log.error("PIPELINE: Job %d not found", args.job_id)
            sys.exit(1)
        if job["status"] not in ("new", "tailored"):
            log.info("PIPELINE: Job %d not eligible (status=%s)", args.job_id, job["status"])
            sys.exit(0)
        queue_tailor = [job] if job["status"] == "new" else []
        queue_apply = []
        if job["status"] == "tailored":
            resume_exists = (DATA_DIR / "resumes" / str(job["id"]) / "tailored.md").exists()
            if resume_exists:
                log.info("PIPELINE: Skipping tailor, status=tailored")
                queue_apply = [job]
            else:
                log.warning("PIPELINE: Job %d status=tailored but no resume artifact; re-tailoring", job["id"])
                queue_tailor = [job]
    else:
        if not db_path.exists():
            log.info("PIPELINE: DB not found — no jobs to process.")
            sys.exit(0)
        queue_apply = get_tailored_jobs(db_path, limit)
        remaining = limit - len(queue_apply)
        queue_tailor = get_eligible_jobs(db_path, remaining) if remaining > 0 else []

    # Build unified queue: new jobs first (newest first), then tailored
    unified_queue = queue_tailor + queue_apply
    total = len(unified_queue)
    if total == 0:
        log.info("PIPELINE: No eligible jobs. Exiting.")
        sys.exit(0)

    log.info("PIPELINE: Queue — %d jobs (%d tailored, %d new)",
             total, len(queue_apply), len(queue_tailor))
    notify(f"Pipeline starting — {len(queue_tailor)} to tailor, {len(queue_apply)} to apply", log, channel_id)

    if args.dry_run:
        for j in queue_tailor:
            log.info("PIPELINE: [DRY RUN] Would tailor: Job %d (%s @ %s)",
                     j["id"], j["title"], j["company"])
        for j in queue_apply:
            log.info("PIPELINE: [DRY RUN] Would apply: Job %d (%s @ %s)",
                     j["id"], j["title"], j["company"])
        log.info("PIPELINE: [DRY RUN] Plan complete. No changes made.")
        sys.exit(0)

    # Ensure jobhunt browser profile is running for apply phase
    if queue_apply or queue_tailor:
        try:
            subprocess.run(
                ["openclaw", "browser", "start", "--browser-profile", "jobhunt"],
                capture_output=True, timeout=15,
            )
            log.info("PIPELINE: Jobhunt browser profile started (or already running)")
        except Exception as e:
            log.warning("PIPELINE: Failed to start jobhunt browser: %s", e)

    # Step 3: Unified sequential loop — tailor then apply each job
    tailor_cfg = load_agent_config("tailor", config)
    apply_cfg = load_agent_config("apply", config)

    for i, job in enumerate(unified_queue):
        if time.monotonic() > deadline:
            log.warning("PIPELINE: Timeout reached (%d min). Stopping.", args.timeout)
            notify(f"Pipeline timeout ({args.timeout}min) reached. Stopping.", log, channel_id)
            break
        jid = job["id"]
        results["total"] += 1

        # ── Tailor phase (only for new jobs) ──────────────────────────────
        if job["status"] == "new":
            log.info("PIPELINE: === Tailor job %d (%s @ %s) [%d/%d] ===",
                     jid, job["title"], job["company"], i + 1, total)
            if args.dry_run:
                log.info("PIPELINE: [DRY RUN] Would tailor job %d", jid)
            else:
                success = run_tailor_direct(job, config, db_path, log)
                if not success:
                    log.error("PIPELINE: Job %d: Tailor failed", jid)
                    results["tailor_failed"] += 1
                    continue

            log.info("PIPELINE: Job %d: Tailor complete. Status = tailored", jid)
        else:
            log.info("PIPELINE: === Apply job %d (%s @ %s) [%d/%d] (already tailored) ===",
                     jid, job["title"], job["company"], i + 1, total)

        # ── Apply phase ───────────────────────────────────────────────────
        if time.monotonic() > deadline:
            log.warning("PIPELINE: Timeout reached (%d min). Stopping before apply.", args.timeout)
            notify(f"Pipeline timeout ({args.timeout}min) reached. Stopping.", log, channel_id)
            break

        resume_path = DATA_DIR / "resumes" / str(jid) / "tailored.md"
        pdf_path = DATA_DIR / "resumes" / str(jid) / "resume.pdf"
        final_resume = str(pdf_path) if pdf_path.exists() else str(resume_path)

        # Pre-read files so agent doesn't have to
        structured_yaml = ""
        structured_path = DATA_DIR / "profile" / "structured.yaml"
        if structured_path.exists():
            structured_yaml = structured_path.read_text()

        platform_knowledge = ""
        platform_dir = SKILL_DIR / "references" / "platforms"

        tailored_md = ""
        if resume_path.exists():
            tailored_md = resume_path.read_text()

        # ── ATS pre-resolution ────────────────────────────────────────────────
        original_job_url = job["url"] or ""
        log.info("PIPELINE: Job %d: Resolving apply URL from %s", jid, original_job_url)
        resolved_job_url, resolution_note = resolve_apply_url(
            original_job_url, jid, job["company"] or "", log=log
        )
        log.info("PIPELINE: Job %d: Resolved URL=%s note=%s", jid, resolved_job_url, resolution_note)

        # Match platform knowledge against resolved URL (not original URL)
        detected_platform = classify_ats_from_url(resolved_job_url)
        matched_platform_file = "(none)"
        if platform_dir.exists():
            stopwords = {"jobs", "career", "careers", "apply", "portal", "work"}
            url_lower = (resolved_job_url or "").lower()
            for pf in platform_dir.glob("*.md"):
                if pf.name == "README.md":
                    continue
                stem = pf.stem
                keywords = [kw for kw in stem.replace("-", " ").replace(".", " ").split() if len(kw) > 3 and kw not in stopwords]
                if any(kw in url_lower for kw in keywords):
                    platform_knowledge = pf.read_text()
                    matched_platform_file = pf.name
                    break

        log.info(
            "PIPELINE: Routing info — job_id=%d title=%r company=%r platform=%s platform_file=%s",
            jid,
            job.get("title") or "",
            job.get("company") or "",
            detected_platform,
            matched_platform_file,
        )

        # Build legacy ats_hint_text for backward compat (still injected into prompt)
        ats_hint = get_ats_hint_for_url(resolved_job_url)
        ats_hint_text = ""
        if ats_hint:
            ats_hint_text = (
                f"ATS cache: host has platform={ats_hint['platform']}"
                + (f", iframe_src={ats_hint['iframe_src']}" if ats_hint.get("iframe_src") else "")
                + f" (cached {ats_hint.get('updated_at', 'unknown')})"
            )
            log.info("PIPELINE: Job %d: ATS cache hit — %s", jid, ats_hint_text)

        prompt_vars = {
            "job_id": jid,
            "job_title": job["title"],
            "company": job["company"],
            "job_url": resolved_job_url,          # primary URL for agent navigation
            "original_job_url": original_job_url,
            "resolved_job_url": resolved_job_url,
            "resolution_note": resolution_note,
            "skill_dir": str(SKILL_DIR),
            "data_dir": str(DATA_DIR),
            "resume_path": final_resume,
            "discord_channel": pipeline_cfg.get("discord_channel", _DEFAULT_DISCORD_CHANNEL),
            "structured_yaml_content": structured_yaml,
            "platform_knowledge_content": platform_knowledge,
            "tailored_resume_content": tailored_md,
            "ats_hint": ats_hint_text,
        }
        prompt = load_prompt("apply", prompt_vars)
        timeout = apply_cfg.get("apply_timeout", 600)
        thinking = apply_cfg.get("thinking_level", "low")
        model = apply_cfg.get("model", None)
        session_id = f"jobhunt-apply-{jid}"

        agent_name = apply_cfg.get("agent", "jobhunt-apply")
        agent_result = run_agent(session_id, prompt, timeout, thinking, args.dry_run, log, model=model, agent=agent_name)

        if "error" in agent_result:
            log.error("PIPELINE: Job %d: Apply agent error — %s", jid, agent_result["error"])
            # Force-writeback: agent exited with error and may not have updated status
            _force_apply_failed(db_path, jid, "apply_agent_error", log)
            results["apply_failed"] += 1
            continue

        # Poll DB for final status (max 60s)
        log.info("PIPELINE: Job %d: Polling DB for final status (up to 60s)...", jid)
        final_status: str | None = None
        for _ in range(30):
            time.sleep(2)
            final_status = get_job_status(db_path, jid)
            if final_status in ("applied", "blocked", "apply_failed"):
                log.info("PIPELINE: Job %d: DB status confirmed = %s", jid, final_status)
                break
        else:
            log.warning("PIPELINE: Job %d: DB polling timed out (60s). Status = %s", jid, final_status)

        # Guard: if agent exited without writing a terminal status, force apply_failed
        if final_status not in ("applied", "blocked", "apply_failed"):
            log.warning(
                "PIPELINE: Job %d: Status still '%s' after agent exit — forcing apply_failed",
                jid, final_status,
            )
            _force_apply_failed(db_path, jid, "apply_agent_no_status_update", log)
            final_status = "apply_failed"

        log.info("PIPELINE: Job %d: Final status = %s", jid, final_status)

        # Clean up browser tabs after each job
        try:
            import urllib.request, json as _json
            tabs_raw = urllib.request.urlopen("http://127.0.0.1:18800/json/list", timeout=3).read()
            tabs = _json.loads(tabs_raw)
            closed = 0
            for t in tabs:
                if t.get("type") == "page":
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:18800/json/close/{t['id']}", timeout=2)
                        closed += 1
                    except Exception:
                        pass
            if closed:
                log.info("PIPELINE: Closed %d browser tab(s)", closed)
        except Exception:
            pass  # browser may not be running during tailor-only jobs
        if final_status == "applied":
            notify(f"Applied: Job {jid} ({job['company']} - {job['title']})", log, channel_id)
        elif final_status == "blocked":
            notify(f"Blocked: Job {jid} ({job['company']} - {job['title']})", log, channel_id)
        else:
            notify(f"Failed to apply: Job {jid} ({job['company']} - {job['title']}) status={final_status}", log, channel_id)
        if final_status in results:
            results[final_status] += 1
        else:
            results["apply_failed"] += 1

    # Step 5: Summary
    log.info("PIPELINE: === Run complete ===")
    log.info(
        "PIPELINE: Summary — total=%d applied=%d blocked=%d apply_failed=%d tailor_failed=%d",
        results["total"], results["applied"], results["blocked"],
        results["apply_failed"], results["tailor_failed"],
    )
    notify(
        f"Pipeline complete — applied={results['applied']} blocked={results['blocked']} "
        f"failed={results['apply_failed']} tailor_failed={results['tailor_failed']}",
        log,
        channel_id,
    )

    # Step 6: Post-run analysis — update TODO.md with failure patterns
    try:
        _analyze_run(db_path, results, log)
    except Exception as e:
        log.warning("PIPELINE: Post-run analysis failed: %s", e)

    sys.exit(0)


def _analyze_run(db_path: Path, results: dict, log: logging.Logger) -> None:
    """Analyze this run's failures and append to TODO.md."""
    from datetime import datetime, timezone
    import json as _json

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get this run's failed/blocked jobs
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        failures = conn.execute(
            """SELECT id, title, company, job_url, status
               FROM jobs WHERE status IN ('apply_failed','blocked')
               AND date(status_updated_at) = date('now')"""
        ).fetchall()

    if not failures:
        log.info("PIPELINE: No failures to analyze.")
        return

    # Categorize by URL domain
    from urllib.parse import urlparse
    platform_stats: dict[str, dict] = {}
    for f in failures:
        url = f["job_url"] or ""
        domain = urlparse(url).netloc if url.startswith("http") else "unknown"
        # Simplify domain
        for key in ["greenhouse", "lever", "workday", "icims", "ashby", "amazon.jobs",
                     "walmart", "uber", "ebay", "oracle", "microsoft"]:
            if key in domain or key in url.lower():
                domain = key
                break
        if domain not in platform_stats:
            platform_stats[domain] = {"fail": 0, "block": 0, "jobs": []}
        if f["status"] == "apply_failed":
            platform_stats[domain]["fail"] += 1
        else:
            platform_stats[domain]["block"] += 1
        platform_stats[domain]["jobs"].append(f"{f['id']} ({f['company']})")

    # Append to TODO.md
    todo_path = Path.home() / ".openclaw" / "workspace" / "tool-dev" / "jobhunt" / "TODO.md"
    if todo_path.exists():
        todo = todo_path.read_text()
        # Append run entry to history table
        entry = f"| {today} | {results['applied']} | {results['apply_failed']} | {results['blocked']} | {results['tailor_failed']} | auto |"
        if entry not in todo:
            todo = todo.replace(
                "| 2026-03-03 | 1 | 14 | 6 | 0 | Multi-tab ref issues, prompt bloat |",
                f"| 2026-03-03 | 1 | 14 | 6 | 0 | Multi-tab ref issues, prompt bloat |\n{entry}"
            )
            todo_path.write_text(todo)

    # Log summary
    log.info("PIPELINE: Failure analysis — %d failures across %d platforms:",
             len(failures), len(platform_stats))
    for plat, stats in sorted(platform_stats.items(), key=lambda x: -(x[1]["fail"]+x[1]["block"])):
        log.info("  %s: %d fail, %d block — %s",
                 plat, stats["fail"], stats["block"], ", ".join(stats["jobs"][:3]))


if __name__ == "__main__":
    main()
