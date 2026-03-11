#!/usr/bin/env python3
"""bu_apply.py — Browser Use apply executor for jobhunt pipeline.

Replaces the openclaw agent for complex ATS platforms (Greenhouse, Workday, Phenom, etc.)
using vision-driven Browser Use agent connected to the existing jobhunt Chrome profile.

Usage (called by pipeline.py):
    uv run python scripts/bu_apply.py \
        --job-id 510 \
        --url https://job-boards.greenhouse.io/embed/... \
        --data-dir ~/.openclaw/data/jobhunt \
        --skill-dir /path/to/jobhunt \
        --timeout 900

Exit codes:
    0 — agent ran (check DB for actual status)
    1 — hard error (config missing, browser unreachable, etc.)
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import sqlite3
import sys
import textwrap
import traceback
from pathlib import Path

import yaml

# ── CDP port for jobhunt browser profile ──────────────────────────────────────
JOBHUNT_CDP_URL = "http://127.0.0.1:18801"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger("bu_apply")


# ── DB helpers ────────────────────────────────────────────────────────────────
def get_db(data_dir: Path) -> Path:
    return data_dir / "jobhunt.db"


def write_job_status(db_path: Path, job_id: int, status: str, note: str = "") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET status=?, status_updated_at=datetime('now'), notes=? WHERE id=?",
            (status, note, job_id),
        )
        conn.commit()


def write_apply_log(data_dir: Path, job_id: int, company: str, title: str,
                    platform: str, job_url: str, steps: list[str],
                    fields: list[str], status: str, duration_s: int, notes: str) -> None:
    log_dir = data_dir / "apply-log"
    log_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Apply Log: {company} — {title}",
        f"Job ID: {job_id}",
        f"Date: {datetime.datetime.utcnow().isoformat(timespec='seconds')}Z",
        f"Platform: {platform}",
        f"Job URL: {job_url}",
        "",
        "## Steps",
    ]
    for i, s in enumerate(steps, 1):
        lines.append(f"{i}. {s}")
    lines += ["", "## Fields Filled"]
    for f in fields:
        lines.append(f"- {f}")
    lines += [
        "",
        "## Result",
        f"Status: {status}",
        f"Duration: {duration_s}s",
        f"Notes: {notes}",
        f"Engine: browser-use",
    ]
    (log_dir / f"{job_id}.md").write_text("\n".join(lines))


# ── Task prompt builder ───────────────────────────────────────────────────────
def build_task(args: argparse.Namespace, structured_yaml: str,
               platform_knowledge: str, tailored_md: str) -> str:
    """Build the task string passed to Browser Use Agent."""
    profile = {
        "name": "Haomin Liu",
        "email": "haomin.liu@gmail.com",
        "phone": "425-380-6253",
        "linkedin": "https://www.linkedin.com/in/haominliu/",
        "address": "3670 172nd Ave NE, Redmond, WA 98052",
        "authorized": "Yes",
        "sponsorship": "No",
        "us_citizen": "No (Authorized to work)",
        "salary": "Prefer not to say",
        "gender": "Decline to self-identify",
        "race": "Decline to self-identify",
        "veteran": "I decline to self-identify",
        "disability": "I don't wish to answer",
    }
    # Override from structured.yaml if available
    if structured_yaml:
        try:
            data = yaml.safe_load(structured_yaml) or {}
            contact = data.get("contact", {})
            if contact.get("name"):
                profile["name"] = contact["name"]
            if contact.get("email"):
                profile["email"] = contact["email"]
            if contact.get("phone"):
                profile["phone"] = contact["phone"]
            if contact.get("linkedin"):
                profile["linkedin"] = contact["linkedin"]
            if contact.get("address"):
                profile["address"] = contact["address"]
        except Exception:
            pass

    platform_section = ""
    if platform_knowledge:
        platform_section = f"""
## Platform-Specific Knowledge
{platform_knowledge[:3000]}
"""

    tailored_section = ""
    if tailored_md:
        tailored_section = f"""
## Tailored Resume Content (for reference when filling experience/skills fields)
{tailored_md[:2000]}
"""

    return textwrap.dedent(f"""
You are a job application agent. Submit a complete job application for the following role.

## Job Details
- Job ID: {args.job_id}
- Company: {args.company}
- Title: {args.title}
- Apply URL: {args.url}
- Resume file path: {args.resume_path}

## Applicant Profile
- Full Name: {profile['name']}
- First Name: Haomin
- Last Name: Liu
- Email: {profile['email']}
- Phone: {profile['phone']}
- Phone country: United States (+1)
- LinkedIn: {profile['linkedin']}
- Address: {profile['address']}
- City: Redmond
- State: Washington (WA)
- Zip: 98052
- Country: United States
- Legally authorized to work in US: Yes
- Requires visa sponsorship: No
- Former employee: No
- How did you hear: LinkedIn / Job Board
- Salary expectation: {profile['salary']}
- Gender: {profile['gender']}
- Race/Ethnicity: {profile['race']}
- Veteran status: {profile['veteran']}
- Disability status: {profile['disability']}
{platform_section}{tailored_section}

## Instructions

### Step 1: Navigate
Go to: {args.url}
Wait for the application form to fully load.

### Step 2: Upload Resume
Upload the resume file at: {args.resume_path}
This is the primary document — always upload it before filling any fields.

### Step 3: Fill All Fields
Fill every visible field using the applicant profile above.
- For dropdowns/selects: click the dropdown, wait for options, click the correct option
- For radio buttons: click the label or the radio itself — try both if one doesn't work
- For phone country selector (intl-tel-input): click the flag/country button, find "United States" in the list and click it
- For React-controlled inputs: after typing, verify the value was accepted; retype if needed
- For checkboxes (consent, privacy, EEO): check them — always agree to privacy/consent, always decline to self-identify for EEO demographics

### Step 4: Answer Application Questions
- Work authorization → Yes
- Sponsorship required → No
- Former employee → No
- Background check consent → Yes / Agree
- Any free-text "why this role" questions → write 2-3 sentences about engineering leadership experience

### Step 5: Submit
Click the final Submit button. Wait for a confirmation message or URL change indicating success.

### Step 6: Write Result to DB
After completion, update the job status in the database:
```bash
sqlite3 {args.data_dir}/jobhunt.db "UPDATE jobs SET status='applied', status_updated_at=datetime('now') WHERE id={args.job_id};"
```

If blocked (CAPTCHA, login wall, form error you cannot resolve):
```bash
sqlite3 {args.data_dir}/jobhunt.db "UPDATE jobs SET status='blocked', status_updated_at=datetime('now') WHERE id={args.job_id};"
```

If failed:
```bash
sqlite3 {args.data_dir}/jobhunt.db "UPDATE jobs SET status='apply_failed', status_updated_at=datetime('now') WHERE id={args.job_id};"
```

### Critical Rules
- ALWAYS update the DB at the end — this is mandatory
- NEVER skip fields marked as required (asterisk or "required" label)
- If a page has multiple steps/tabs, complete ALL of them before considering done
- If you encounter a CAPTCHA that requires human solving, mark as blocked
- Confirmation = page shows "Application submitted", "Thank you", "We received your application", or similar text
""").strip()


# ── Main async runner ─────────────────────────────────────────────────────────
async def run_apply(args: argparse.Namespace) -> int:
    """Run the Browser Use agent. Returns exit code."""
    try:
        from browser_use.agent.service import Agent
        from browser_use.browser.session import BrowserSession
        from browser_use.llm.anthropic.chat import ChatAnthropic
    except ImportError as e:
        log.error("Missing dependency: %s — run `uv add browser-use`", e)
        return 1

    data_dir = Path(args.data_dir)
    skill_dir = Path(args.skill_dir)
    db_path = get_db(data_dir)

    # Load context files
    structured_yaml = ""
    structured_path = data_dir / "profile" / "structured.yaml"
    if structured_path.exists():
        structured_yaml = structured_path.read_text()

    tailored_md = ""
    resume_md = data_dir / "resumes" / str(args.job_id) / "tailored.md"
    if resume_md.exists():
        tailored_md = resume_md.read_text()

    # Load platform knowledge
    platform_knowledge = ""
    platform_dir = skill_dir / "references" / "platforms"
    if platform_dir.exists():
        url_lower = args.url.lower()
        stopwords = {"jobs", "career", "careers", "apply", "portal", "work"}
        for pf in platform_dir.glob("*.md"):
            if pf.name == "README.md":
                continue
            keywords = [kw for kw in pf.stem.replace("-", " ").split()
                        if len(kw) > 3 and kw not in stopwords]
            if any(kw in url_lower for kw in keywords):
                platform_knowledge = pf.read_text()
                log.info("Loaded platform knowledge: %s", pf.name)
                break

    task = build_task(args, structured_yaml, platform_knowledge, tailored_md)
    log.info("Task built (%d chars). Connecting to browser at %s", len(task), JOBHUNT_CDP_URL)

    # Verify CDP endpoint is reachable
    import urllib.request
    try:
        urllib.request.urlopen(f"{JOBHUNT_CDP_URL}/json/version", timeout=5)
    except Exception as e:
        log.error("Cannot reach jobhunt browser at %s: %s", JOBHUNT_CDP_URL, e)
        log.error("Start it with: openclaw browser start --browser-profile jobhunt")
        return 1

    # Close existing tabs before starting
    try:
        tabs_raw = urllib.request.urlopen(f"{JOBHUNT_CDP_URL}/json/list", timeout=3).read()
        tabs = json.loads(tabs_raw)
        for t in tabs:
            if t.get("type") == "page":
                try:
                    urllib.request.urlopen(f"{JOBHUNT_CDP_URL}/json/close/{t['id']}", timeout=2)
                except Exception:
                    pass
        log.info("Closed %d existing tab(s)", len([t for t in tabs if t.get("type") == "page"]))
    except Exception as e:
        log.warning("Could not clean up tabs: %s", e)

    import os
    llm = ChatAnthropic(
        model="claude-sonnet-4-6",
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        timeout=120,
        max_tokens=8192,
    )

    browser_session = BrowserSession(
        cdp_url=JOBHUNT_CDP_URL,
        keep_alive=True,
        highlight_elements=True,
        wait_between_actions=1.5,
        minimum_wait_page_load_time=1.0,
    )

    agent = Agent(
        task=task,
        llm=llm,
        browser_session=browser_session,
        use_vision=True,
        max_failures=5,
        max_actions_per_step=8,
        step_timeout=120,
        enable_planning=True,
    )

    import time
    start = time.time()
    try:
        log.info("Starting Browser Use agent for job %d (%s @ %s)",
                 args.job_id, args.title, args.company)
        history = await agent.run(max_steps=80)
        duration = int(time.time() - start)

        # Check final status in DB (agent should have written it)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE id=?", (args.job_id,)
            ).fetchone()
        final_status = row[0] if row else "unknown"
        log.info("Agent completed. DB status=%s. Duration=%ds", final_status, duration)

        if final_status not in ("applied", "blocked", "apply_failed"):
            log.warning("Agent did not write terminal status — forcing apply_failed")
            write_job_status(db_path, args.job_id, "apply_failed",
                             "bu_apply: agent exited without DB status update")
            final_status = "apply_failed"

        # Write apply log
        success_text = history.final_result() or ""
        write_apply_log(
            data_dir=data_dir,
            job_id=args.job_id,
            company=args.company,
            title=args.title,
            platform="browser-use",
            job_url=args.url,
            steps=[f"Browser Use agent ran {getattr(history, 'number_of_steps', lambda: 0)() if callable(getattr(history, 'number_of_steps', None)) else '?'} steps"],
            fields=["(see agent interaction log)"],
            status=final_status,
            duration_s=duration,
            notes=success_text[:500] if success_text else "No final result text",
        )
        return 0

    except asyncio.TimeoutError:
        log.error("Browser Use agent timed out after %ds", args.timeout)
        write_job_status(db_path, args.job_id, "apply_failed", "bu_apply: asyncio timeout")
        return 1
    except Exception as e:
        log.error("Browser Use agent error: %s\n%s", e, traceback.format_exc())
        write_job_status(db_path, args.job_id, "apply_failed", f"bu_apply: {type(e).__name__}: {e}")
        return 1
    finally:
        try:
            await browser_session.close()
        except Exception:
            pass


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Browser Use apply executor")
    p.add_argument("--job-id", type=int, required=True)
    p.add_argument("--url", required=True, help="Pre-resolved apply URL")
    p.add_argument("--company", default="Unknown")
    p.add_argument("--title", default="Unknown")
    p.add_argument("--resume-path", required=True, help="Path to tailored PDF resume")
    p.add_argument("--data-dir", required=True, help="Path to jobhunt data dir")
    p.add_argument("--skill-dir", required=True, help="Path to jobhunt skill dir")
    p.add_argument("--timeout", type=int, default=900, help="Max run time in seconds")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(
        asyncio.wait_for(run_apply(args), timeout=args.timeout)
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
