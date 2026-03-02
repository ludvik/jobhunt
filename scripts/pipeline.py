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

# ── Paths ─────────────────────────────────────────────────────────────────────
SKILL_DIR = Path(__file__).parent.parent.resolve()
DATA_DIR = Path.home() / ".openclaw" / "data" / "jobhunt"
LOG_FILE = DATA_DIR / "logs" / "pipeline.log"


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
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "[%(asctime)s] [%(levelname)s] %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%SZ"
    logging.Formatter.converter = time.gmtime  # UTC timestamps

    logger = logging.getLogger("pipeline")
    logger.setLevel(level)

    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
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
              dry_run: bool, log: logging.Logger) -> dict:
    """Invoke openclaw agent, return parsed JSON result."""
    cmd = [
        "openclaw", "agent",
        "--session-id", session_id,
        "--message", prompt,
        "--thinking", thinking,
        "--timeout", str(timeout),
        "--json",
    ]
    log.info("PIPELINE: Invoking agent session=%s timeout=%ds", session_id, timeout)
    log.debug("PIPELINE: Command: %s", " ".join(cmd))

    if dry_run:
        log.info("PIPELINE: [DRY RUN] Would run: %s", " ".join(cmd))
        return {"dry_run": True}

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 30,
        )
        if result.returncode != 0:
            log.error("PIPELINE: Agent %s exited %d: %s",
                      session_id, result.returncode, result.stderr[:500])
            return {"error": result.stderr, "returncode": result.returncode}
        return json.loads(result.stdout) if result.stdout.strip() else {}
    except subprocess.TimeoutExpired:
        log.error("PIPELINE: Agent %s timed out after %ds", session_id, timeout)
        return {"error": "subprocess_timeout"}
    except json.JSONDecodeError as exc:
        log.error("PIPELINE: Agent %s returned invalid JSON: %s", session_id, exc)
        return {"error": "invalid_json"}


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
    """Filter new jobs by title/level/salary rules, marking irrelevant ones as 'skipped'."""
    import re as _re

    classify_cfg = config.get("classify", {})
    if not classify_cfg.get("enabled", True):
        log.info("PIPELINE: Classification disabled — skipping.")
        return

    title_patterns = [_re.compile(p, _re.IGNORECASE) for p in classify_cfg.get("title_patterns", [])]
    min_level = [kw.lower() for kw in classify_cfg.get("min_level", [])]
    min_salary = classify_cfg.get("min_salary", 0)

    # Salary extraction: matches $180,000 / $180K / 180,000/year / $180000
    _salary_re = _re.compile(
        r"\$?([0-9]{2,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+)[kK]?(?:\s*/\s*(?:year|yr|annual))?",
        _re.IGNORECASE,
    )
    _dollar_re = _re.compile(r"\$[0-9]")

    def _parse_salaries(text: str) -> list[float]:
        """Return list of salary figures found in text (in dollars)."""
        if not text:
            return []
        results = []
        for m in _salary_re.finditer(text):
            raw = m.group(0)
            # Only consider values that look like salary amounts (preceded by $ or followed by K)
            num_str = m.group(1).replace(",", "")
            try:
                val = float(num_str)
            except ValueError:
                continue
            if raw.startswith("$") or raw.lower().endswith("k"):
                if raw.lower().endswith("k") and not raw.startswith("$"):
                    # bare number with K suffix — check surroundings
                    pass
                if raw.lower().endswith("k"):
                    val *= 1000
                # Plausible salary range: $30k–$2M
                if 30_000 <= val <= 2_000_000:
                    results.append(val)
        return results

    if not db_path.exists():
        log.info("PIPELINE: DB not found — skipping classification.")
        return

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, title, company, jd_text FROM jobs WHERE status='new'"
        ).fetchall()

    kept = 0
    skipped = 0
    total = len(rows)

    for row in rows:
        job_id = row["id"]
        title = row["title"] or ""
        company = row["company"] or ""
        description = row["jd_text"] or ""

        reason = None

        # 1. Title pattern match (REQUIRED)
        if title_patterns and not any(p.search(title) for p in title_patterns):
            reason = "title_mismatch"

        # 2. Level keyword match (REQUIRED)
        if reason is None and min_level:
            title_lower = title.lower()
            if not any(kw in title_lower for kw in min_level):
                reason = "level_mismatch"

        # 3. Salary check (OPTIONAL — only skip if salary mentioned and ALL below min)
        if reason is None and min_salary:
            salaries = _parse_salaries(description)
            if salaries and all(s < min_salary for s in salaries):
                reason = "salary_below_min"

        if reason:
            log.info("PIPELINE: Filtered job %d (%s @ %s) — reason: %s",
                     job_id, title, company, reason)
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    "UPDATE jobs SET status='not_suitable', status_updated_at=datetime('now') WHERE id=?",
                    (job_id,)
                )
            skipped += 1
        else:
            kept += 1

    log.info("PIPELINE: Classification complete — %d kept, %d skipped out of %d new jobs",
             kept, skipped, total)
    notify(f"Classification complete — {kept} kept, {skipped} skipped out of {total} new jobs",
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
            prompt_vars = {
                "job_id": jid,
                "job_title": job["title"],
                "company": job["company"],
                "job_url": job["url"],
                "skill_dir": str(SKILL_DIR),
                "data_dir": str(DATA_DIR),
            }
            prompt = load_prompt("tailor", prompt_vars)
            timeout = tailor_cfg.get("tailor_timeout", 600)
            thinking = tailor_cfg.get("thinking_level", "low")
            session_id = f"jobhunt-tailor-{jid}"

            agent_result = run_agent(session_id, prompt, timeout, thinking, args.dry_run, log)

            if "error" in agent_result:
                log.error("PIPELINE: Job %d: Tailor failed — %s", jid, agent_result["error"])
                results["tailor_failed"] += 1
                continue

            # Poll DB for status change (max 60s)
            log.info("PIPELINE: Job %d: Polling DB for status=tailored (up to 60s)...", jid)
            new_status: str | None = None
            for _ in range(30):
                time.sleep(2)
                new_status = get_job_status(db_path, jid)
                if new_status == "tailored":
                    log.info("PIPELINE: Job %d: DB status confirmed = tailored", jid)
                    break
            else:
                log.warning("PIPELINE: Job %d: DB polling timed out (60s). Status = %s", jid, new_status)

            if new_status != "tailored":
                log.error("PIPELINE: Job %d: Status still '%s' after tailor agent. Skipping apply.",
                          jid, new_status)
                results["tailor_failed"] += 1
                continue

            log.info("PIPELINE: Job %d: Tailor complete. Status = tailored", jid)
            notify(f"Tailored: Job {jid} ({job['company']} - {job['title']})", log, channel_id)
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

        prompt_vars = {
            "job_id": jid,
            "job_title": job["title"],
            "company": job["company"],
            "job_url": job["url"],
            "skill_dir": str(SKILL_DIR),
            "data_dir": str(DATA_DIR),
            "resume_path": final_resume,
            "discord_channel": pipeline_cfg.get("discord_channel", _DEFAULT_DISCORD_CHANNEL),
        }
        prompt = load_prompt("apply", prompt_vars)
        timeout = apply_cfg.get("apply_timeout", 1200)
        thinking = apply_cfg.get("thinking_level", "low")
        session_id = f"jobhunt-apply-{jid}"

        agent_result = run_agent(session_id, prompt, timeout, thinking, args.dry_run, log)

        if "error" in agent_result:
            log.error("PIPELINE: Job %d: Apply agent error — %s", jid, agent_result["error"])
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

        log.info("PIPELINE: Job %d: Final status = %s", jid, final_status)
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
    sys.exit(0)


if __name__ == "__main__":
    main()
