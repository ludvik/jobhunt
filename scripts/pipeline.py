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
            "WHERE status='new' ORDER BY fetched_at DESC LIMIT ?",
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
            "WHERE status='tailored' ORDER BY fetched_at DESC LIMIT ?",
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
def run_fetch(config: dict, dry_run: bool, log: logging.Logger,
              skill_dir: Path = SKILL_DIR) -> None:
    fetch_cfg = config.get("fetch", {})
    limit = fetch_cfg.get("limit", 30)
    lookback = fetch_cfg.get("lookback", 14)
    log.info("PIPELINE: Running fetch --limit %d --lookback %d", limit, lookback)
    if dry_run:
        log.info("PIPELINE: [DRY RUN] Skipping fetch")
        return
    result = subprocess.run(
        ["uv", "run", "--directory", str(skill_dir), "python", "scripts/cli.py",
         "fetch", "--limit", str(limit), "--lookback", str(lookback)],
        cwd=skill_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.warning("PIPELINE: Fetch exited %d: %s", result.returncode, result.stderr[:300])
    else:
        log.info("PIPELINE: Fetch complete")


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

    results = {
        "total": 0, "applied": 0, "blocked": 0,
        "apply_failed": 0, "tailor_failed": 0, "skipped": 0,
    }

    # Step 1: Fetch (skip for single-job or --skip-fetch)
    if not args.skip_fetch and not args.job_id:
        run_fetch(config, args.dry_run, log)

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
        queue_tailor = get_eligible_jobs(db_path, limit)
        remaining = limit - len(queue_tailor)
        queue_apply = get_tailored_jobs(db_path, remaining)

    total = len(queue_tailor) + len(queue_apply)
    if total == 0:
        log.info("PIPELINE: No eligible jobs. Exiting.")
        sys.exit(0)

    log.info("PIPELINE: Queue — tailor: %d, apply: %d", len(queue_tailor), len(queue_apply))

    if args.dry_run:
        for j in queue_tailor:
            log.info("PIPELINE: [DRY RUN] Would tailor: Job %d (%s @ %s)",
                     j["id"], j["title"], j["company"])
        for j in queue_apply:
            log.info("PIPELINE: [DRY RUN] Would apply: Job %d (%s @ %s)",
                     j["id"], j["title"], j["company"])
        log.info("PIPELINE: [DRY RUN] Plan complete. No changes made.")
        sys.exit(0)

    # Step 3: Tailor loop
    tailor_cfg = load_agent_config("tailor", config)
    tailor_success: list[dict] = []

    for i, job in enumerate(queue_tailor):
        if time.monotonic() > deadline:
            log.warning("PIPELINE: Timeout reached (%d min). Stopping tailor loop.", args.timeout)
            break
        jid = job["id"]
        log.info("PIPELINE: === Tailor job %d (%s @ %s) [%d/%d] ===",
                 jid, job["title"], job["company"], i + 1, len(queue_tailor))
        results["total"] += 1

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
        tailor_success.append(job)

    # Step 4: Apply loop
    apply_queue = queue_apply + tailor_success
    apply_cfg = load_agent_config("apply", config)

    for i, job in enumerate(apply_queue):
        if time.monotonic() > deadline:
            log.warning("PIPELINE: Timeout reached (%d min). Stopping apply loop.", args.timeout)
            break
        jid = job["id"]
        log.info("PIPELINE: === Apply job %d (%s @ %s) [%d/%d] ===",
                 jid, job["title"], job["company"], i + 1, len(apply_queue))
        if job not in tailor_success:
            results["total"] += 1

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
    sys.exit(0)


if __name__ == "__main__":
    main()
