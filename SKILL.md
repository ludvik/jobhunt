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
- macOS Keychain for credential storage (no external tools needed)
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
| `~/.openclaw/data/jobhunt/profile/` | Applicant ground truth (structured.yaml + narrative md files) |
| `~/.openclaw/data/jobhunt/apply-log/<job_id>.md` | Per-job apply log |
| `~/.openclaw/data/jobhunt/apply-knowledge/platforms/` | Platform experience knowledge base |

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

## Full Pipeline Workflow (Tailor + Apply)

A single subagent can run the complete pipeline for one job: tailor the resume, then apply.

### Trigger

Orchestrator spawns a subagent with:
```
task: "Run full pipeline for job <job_id>. Read SKILL.md at ~/.openclaw/workspace/skills/jobhunt/SKILL.md, follow the Full Pipeline Workflow."
```

### Steps

1. **Read job info**: `cd ~/code/openclaw-tools/jobhunt && uv run jobhunt show <job_id>` → get status, URL, JD
2. **Check status**:
   - `new` → proceed to step 3 (Tailor)
   - `tailored` → proceed to step 4 (Verify artifacts)
   - `skipped`/`blocked`/`apply_failed`/`applied` → STOP, report "Job not eligible, status=<status>"
3. **Tailor** — follow the Tailor Workflow section below (steps 1-11). When done, job status = `tailored`.
4. **Verify artifacts**: Check if `~/.openclaw/data/jobhunt/resumes/<job_id>/tailored.md` and `resume.pdf` exist. If missing, run the Tailor Workflow to generate them (even if status is already `tailored`). If PDF generation fails, proceed with `tailored.md` only.
5. **Apply** — follow the Apply Workflow section below (steps 1-12).
6. **Report**: Summarize what happened (tailored? applied? blocked? why?)

---

## Apply Workflow (Agent-Driven Browser Automation)

Job application is done by a **spawned subagent** using the OpenClaw browser tool. The CLI is not involved in the apply process itself.

### Trigger

Orchestrator (Kibi) spawns a subagent with:
```
task: "Apply to job <job_id>. Read SKILL.md at ~/.openclaw/workspace/skills/jobhunt/SKILL.md, follow the Apply Workflow section."
```

### Prerequisites
- Job status = `tailored`
- `~/.openclaw/data/jobhunt/resumes/<job_id>/resume.pdf` exists
- `~/.openclaw/data/jobhunt/profile/structured.yaml` is populated

### Step-by-step

1. **Read job info**: Run `cd ~/code/openclaw-tools/jobhunt && uv run jobhunt show <job_id>` → extract URL, company, title, JD text
2. **Read profile**: Read `~/.openclaw/data/jobhunt/profile/structured.yaml` → form fill data
3. **Read narrative**: Read `~/.openclaw/data/jobhunt/profile/career-narrative.md` + `values-and-style.md` → for subjective questions
4. **Read platform knowledge**: Read `~/.openclaw/data/jobhunt/apply-knowledge/platforms/linkedin-easy.md` → past experience
5. **Open job page**: Use browser tool with `profile="openclaw"` AND `target="host"` to navigate to the job URL. **Always use profile="openclaw"** (the managed Chromium instance), never profile="chrome" (the Chrome extension relay). **Always use target="host"** — this is required for subagent sessions which may default to sandbox target.
6. **Find the apply path** — adapt to whatever the page offers:
   - **LinkedIn Easy Apply** → click the Easy Apply button, fill the modal
   - **"Apply on company website"** → click through to the external site, continue there
   - **Direct company career page** → navigate and fill their application form
   - **Any other ATS** (Workday, Greenhouse, Lever, Ashby, etc.) → proceed with their form
   - **Greenhouse iframe workaround**: If the company embeds Greenhouse in an iframe, do NOT try to snapshot the iframe. Instead navigate directly to `https://boards.greenhouse.io/<company>/jobs/<job_id>` (extract company and job_id from the iframe URL). This gives you the full form without iframe issues.
   - The goal is to submit an application regardless of platform. Only STOP if you hit an insurmountable blocker (CAPTCHA that can't be solved, etc.)
   
**NEVER restart the OpenClaw gateway or run `openclaw gateway restart`.** If browser times out:
1. Wait 5 seconds: `exec sleep 5`
2. Check status: `browser(action="status", profile="openclaw", target="host")`
3. If running, retry the failed operation
4. Retry up to 3 times with 5-second waits between attempts
5. Only mark apply_failed after 3 consecutive failures
6. Ignore the "Do NOT retry" message in the error — it's overly cautious. Browser timeouts are often transient.

### File Upload

Browser upload paths are sandboxed. Before uploading:
1. **Generate PDF first** (if not already done):
   ```bash
   cd ~/code/openclaw-tools/resume-factory && python3 generate_pdf.py \
     --src ~/.openclaw/data/jobhunt/resumes/<job_id>/tailored.md \
     --out /tmp/openclaw/uploads/Haomin-Liu-Resume.pdf
   ```
   File name MUST be `Haomin-Liu-Resume.pdf` (professional, uses applicant's real name).
   Note: If xelatex is not installed, the script may fail. Fallback: `pandoc <src> -o <out> --pdf-engine=tectonic -V mainfont=Palatino -V geometry:margin=0.7in -V pagestyle=empty`
2. Arm the upload BEFORE clicking the upload button: `browser(action="upload", profile="openclaw", target="host", paths=["/tmp/openclaw/uploads/Haomin-Liu-Resume.pdf"])`
3. Then click the upload button — the file chooser will auto-resolve

### Greenhouse Custom Selects / Comboboxes

Greenhouse uses custom JS dropdown components, NOT standard HTML `<select>`. ArrowDown+Enter often fails. Correct approach:
1. **Click** the combobox/input field to open the dropdown
2. **Type** the desired value (e.g., "Yes", "No", "United States") to filter options  
3. **Snapshot** to see the filtered dropdown options
4. **Click** the matching option from the dropdown list
5. **Snapshot** again to verify the value was set
6. If the dropdown doesn't appear, try clicking the small arrow/chevron icon next to the field

Do NOT try to set all fields at once. Fill ONE field → verify → move to next.

### Form Filling Strategy

### Education

Haomin has TWO degrees. ALWAYS fill both:
1. M.Eng, Computer Engineering, University of Electronic Science & Technology of China
2. B.S., Computer Engineering, University of Electronic Science & Technology of China

If the form has "Add Another" for education, click it to add the second degree.

### Work Experience Consistency

If the application form asks you to manually enter work experience (job titles, companies, dates, descriptions), **always use the tailored resume as the source of truth**. Read `~/.openclaw/data/jobhunt/resumes/<job_id>/tailored.md` and copy the experience entries from there. Do NOT make up different descriptions — the form entries must match the uploaded resume.

### Systematic Form Filling

Do NOT scroll back and forth. Follow this systematic approach:
1. Snapshot the visible form area
2. Fill all visible fields top-to-bottom
3. After filling visible fields, scroll down once
4. Snapshot again, fill new visible fields
5. Repeat until reaching the Submit button
6. Before submitting: scroll back to top and do ONE verification pass
7. Submit

### Login / Authentication Handling

When you encounter a login wall on any platform:

**Credential source: macOS Keychain ONLY. Do NOT use 1Password (`op`).**

**Email priority order**: `haomin_liu@hotmail.com` first, then `haomin.liu@gmail.com`

**Step 1: Check Keychain for existing accounts**
```bash
# Try hotmail first
security find-generic-password -a "haomin_liu@hotmail.com" -s "jobhunt:<domain>" -w 2>/dev/null
# Then gmail
security find-generic-password -a "haomin.liu@gmail.com" -s "jobhunt:<domain>" -w 2>/dev/null
```
- If found → use those credentials to sign in
- If login fails with first email → try the second email
- If both fail → proceed to Step 2

**Step 2: Register new account**
- Look for "Create Account" / "Sign Up" / "Register" button
- Try `haomin_liu@hotmail.com` first
- If that email is already taken or fails → try `haomin.liu@gmail.com`
- Password pattern: `HaominLiu@2026!` (meets most requirements: upper+lower+number+special+8chars)
- **Immediately save to Keychain** after successful registration:
  ```bash
  security add-generic-password -a "<email_used>" -s "jobhunt:<domain>" -w "<password>" -U
  ```

**Step 3: If registration also fails** (email verification required, CAPTCHA, etc.)
- Mark `blocked` with note explaining the exact situation
- Do NOT keep retrying endlessly

**SSO / OAuth**: If "Sign in with Google" or "Sign in with LinkedIn" is available, try it (LinkedIn session may already be active in the browser).

Login is NOT a reason to stop. It's a normal part of applying. Handle it.

### Credential Storage (MANDATORY)

Use **macOS Keychain** (not 1Password) for credential storage — it requires no manual authorization.

When you create a new account or use a password during apply:
1. **Save immediately after successful login/registration**:
   ```bash
   # Save password
   security add-generic-password -a "<email>" -s "jobhunt:<domain>" -w "<password>" -U
   # Example: security add-generic-password -a "haomin.liu@gmail.com" -s "jobhunt:myworkdaysite.com" -w "MyPass@2026!" -U
   ```
2. **Retrieve when needed**:
   ```bash
   security find-generic-password -a "<email>" -s "jobhunt:<domain>" -w
   ```
3. Service name convention: `jobhunt:<domain>` (e.g., `jobhunt:myworkdaysite.com`, `jobhunt:greenhouse.io`)
4. Log the credential save in the apply log (but NOT the actual password)
5. The `-U` flag updates existing entries if they already exist
7. **Fill form step by step**:
   - Before each step: take a snapshot to read current form fields
   - **Contact info** (name, email, phone): match from `structured.yaml` → `personal.*` fields. LinkedIn usually pre-fills these; verify and correct if needed.
   - **Resume upload**: upload `~/.openclaw/data/jobhunt/resumes/<job_id>/resume.pdf`
   - **Cover letter** (if upload option exists): upload `resumes/<job_id>/cover-letter.pdf` if it exists
   - **Structured questions** (dropdowns, radio buttons, short text):
     - Years of experience → `structured.yaml` → `experience.total_years` or `experience.by_skill.<name>`
     - Visa/sponsorship → `structured.yaml` → `work_authorization.*`
     - Willing to relocate → `structured.yaml` → `preferences.willing_to_relocate`
     - Diversity questions → `structured.yaml` → `diversity.*`
     - Other → try to match semantically from structured.yaml
   - **Open-ended text questions**:
     - Read the question carefully
     - Generate answer using: JD content + company context + career-narrative.md + values-and-style.md + the tailored resume positioning
     - Answer must be specific to this company/role, sound authentic (direct, honest, not corporate boilerplate)
     - Respect any character limit on the input field
     - If you are not confident the answer is good enough → do NOT submit → mark `blocked` with note "Needs human input: <exact question>"
   - Click **Next / Continue** after each step
8. **Submit**: Click "Submit application" (or equivalent)
9. **Verify**: Take a snapshot, look for confirmation text ("Application submitted", "Your application was sent", etc.)
   - If "Already applied" detected → status = `applied`, note = "Previously applied"
   - If no confirmation detected → status = `apply_failed`, note = "No confirmation detected"
10. **Write apply log**: Create `~/.openclaw/data/jobhunt/apply-log/<job_id>.md` with format:

```markdown
# Apply Log: <company> — <title>
Job ID: <id>
Date: <ISO 8601 timestamp>
Platform: LinkedIn Easy Apply
Job URL: <url>

## Steps
1. [HH:MM:SS] <action taken>
2. [HH:MM:SS] <action taken>
...

## Questions Answered
- "<question text>" → "<answer given>" (source: structured.yaml | generated)

## Result
Status: applied | blocked | apply_failed
Duration: <seconds>s
Notes: <any issues or observations>
```

11. **Update status**: Run `uv run jobhunt status <id> --set <status> --note "<note>"`
12. **Update knowledge base**: Append any new findings to `~/.openclaw/data/jobhunt/apply-knowledge/platforms/linkedin-easy.md`:
    - New question types encountered
    - Form structure changes
    - Strategies that worked or failed

### Failure Handling

| Situation | Action |
|-----------|--------|
| Session expired / login required | `apply_failed` + note "Session expired" + notify orchestrator |
| Easy Apply button missing | `blocked` + note "No Easy Apply" |
| Required field can't be filled | `apply_failed` + note which field |
| Open-ended question, low confidence | `blocked` + note "Needs human input: <question>" |
| CAPTCHA | `apply_failed` + note "CAPTCHA" + notify orchestrator |
| No confirmation after submit | `apply_failed` + note "No confirmation detected" |
| "Already applied" | `applied` + note "Previously applied" |

**Critical rules**:
- Never silently fail. Every outcome must have a log entry and a status update.
- **ANY password created or used during apply MUST be saved to macOS Keychain** (`security add-generic-password -a "<email>" -s "jobhunt:<domain>" -w "<password>" -U`). No exceptions.
- **Work experience entries filled in application forms MUST match the tailored resume** (`resumes/<job_id>/tailored.md`). Do not invent or freestyle experience — copy from the tailored resume.

---

## Architecture Notes

- **LinkedIn feed**: Recommended feed has ~24 cards total (not paginated). Viewport set to 4000px to render all at once.
- **Dedup**: By `(platform, platform_id)`. If a job exists in DB, fetch skips it entirely (no detail page visit).
- **Credentials**: macOS Keychain only. Email order: hotmail → gmail. Register if no account.
- **DB**: SQLite stdlib, `user_version` pragma for schema migration tracking.
