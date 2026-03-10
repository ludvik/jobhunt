"""Greenhouse HTTP apply — submit applications without browser automation.

Submits Greenhouse job applications via HTTP POST (multipart/form-data).
Falls back gracefully if CAPTCHA is detected in the response.

Usage:
    from scripts.greenhouse_apply import apply_greenhouse
    status = apply_greenhouse(
        job_id=123, job_url="...", jd_text="...",
        profile={...}, resume_path=Path("resume.pdf"),
        tailored_md_path=Path("tailored.md"),
        company="Acme", db_path=Path("jobs.db"),
    )
    # Returns: "applied" | "blocked" | "apply_failed"
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("jobhunt.greenhouse")

# ---------------------------------------------------------------------------
# URL / token extraction
# ---------------------------------------------------------------------------

_GH_URL_PATTERNS = [
    r"job-boards\.greenhouse\.io/([^/?#]+)/jobs/(\d+)",
    r"boards\.greenhouse\.io/([^/?#]+)/jobs/(\d+)",
    r"/jobs/([^/?#]+)/(\d+)",
]

_GH_JID_PATTERN = r"[?&]gh_jid=(\d+)"


def extract_greenhouse_info(job_url: str, jd_text: str = "") -> dict[str, str] | None:
    """Extract board_token and job_id from a Greenhouse URL or JD text.

    Returns {"board_token": str, "job_id": str} or None if not detected.
    Handles:
    - job-boards.greenhouse.io/{board_token}/jobs/{id}
    - boards.greenhouse.io/{board_token}/jobs/{id}
    - company.com/careers?gh_jid={id}  (board_token searched in JD text)
    """
    log.debug("Extracting Greenhouse info from URL: %s", job_url)

    for pattern in _GH_URL_PATTERNS:
        m = re.search(pattern, job_url)
        if m:
            board_token, job_id = m.group(1), m.group(2)
            log.info("Extracted board_token=%s job_id=%s from URL", board_token, job_id)
            return {"board_token": board_token, "job_id": job_id}

    jid_match = re.search(_GH_JID_PATTERN, job_url)
    if jid_match:
        job_id = jid_match.group(1)
        log.debug("Found gh_jid=%s; searching JD text for board_token", job_id)
        for pattern in _GH_URL_PATTERNS:
            m = re.search(pattern, jd_text)
            if m:
                board_token = m.group(1)
                log.info("Extracted board_token=%s from JD text", board_token)
                return {"board_token": board_token, "job_id": job_id}
        log.warning("Found gh_jid=%s but could not determine board_token", job_id)
        return None

    log.debug("URL does not appear to be a Greenhouse job URL: %s", job_url)
    return None


def is_greenhouse_url(job_url: str, jd_text: str = "") -> bool:
    """Return True if this job appears to be hosted on Greenhouse."""
    if "greenhouse.io" in job_url:
        return True
    if "gh_jid=" in job_url and jd_text and "greenhouse.io" in jd_text:
        return True
    return False


# ---------------------------------------------------------------------------
# API: fetch job questions
# ---------------------------------------------------------------------------


def get_job_questions(board_token: str, job_id: str) -> dict[str, Any]:
    """Fetch job post with questions from the Greenhouse public API.

    GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}?questions=true

    No auth required. Returns full JSON including 'questions' list.
    Each question has: label, required, description, and a nested 'fields' list.
    Each field has: name, type, values (options for selects).
    """
    url = (
        f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
        "?questions=true"
    )
    log.info("Fetching Greenhouse job questions: %s", url)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    log.info(
        "Got job '%s' with %d question(s)",
        data.get("title", "unknown"),
        len(data.get("questions", [])),
    )
    log.debug("Questions payload:\n%s", json.dumps(data.get("questions", []), indent=2))
    return data


# ---------------------------------------------------------------------------
# Form data builder
# ---------------------------------------------------------------------------

_DECLINE_LABELS = {
    "i don't wish to answer",
    "i don't wish to self-identify",
    "decline to self-identify",
    "prefer not to say",
    "prefer not to answer",
    "i prefer not to say",
    "decline",
    "prefer not to disclose",
    "do not wish to answer",
    "i do not wish to self-identify",
    "i do not wish to answer",
    "choose not to disclose",
}

# (label_pattern, static_answer_or___decline__)
_STATIC_ANSWERS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"work.{0,30}authoriz|authoriz.{0,30}work", re.I), "Yes"),
    (re.compile(r"legally.{0,20}work", re.I), "Yes"),
    (re.compile(r"sponsor", re.I), "No"),
    (re.compile(r"require.{0,30}visa", re.I), "No"),
    (re.compile(r"located.{0,60}colorado|european economic|eea|united kingdom.{0,30}switzerland", re.I), "No"),
    (re.compile(r"how did you hear", re.I), "LinkedIn"),
    (re.compile(r"referred by", re.I), "LinkedIn"),
    (re.compile(r"source of (your )?application", re.I), "LinkedIn"),
    (re.compile(r"(i agree|agree to the|data.{0,20}consent|privacy.{0,20}policy)", re.I), "Yes"),
    (re.compile(r"gender", re.I), "__decline__"),
    (re.compile(r"veteran|military", re.I), "__decline__"),
    (re.compile(r"disabilit", re.I), "__decline__"),
    (re.compile(r"ethnic|race|racial", re.I), "__decline__"),
    (re.compile(r"sexual.{0,20}orient", re.I), "__decline__"),
]


def _find_decline_option(options: list[dict]) -> str | None:
    """Find the decline/prefer-not-to-answer option value."""
    for opt in options:
        if opt.get("label", "").strip().lower() in _DECLINE_LABELS:
            return str(opt.get("value", opt.get("label", "")))
    return None


def _find_option_by_label(options: list[dict], target: str) -> str | None:
    """Find option value by exact label match (case-insensitive)."""
    tl = target.lower().strip()
    for opt in options:
        if opt.get("label", "").lower().strip() == tl:
            return str(opt.get("value", opt.get("label", "")))
    return None


def _get_profile_field(profile: dict, *keys: str, default: str = "") -> str:
    """Safely navigate nested profile dict."""
    val: Any = profile
    for key in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(key, {})
    return val if isinstance(val, str) else default


def _handle_field(
    field_name: str,
    q_type: str,
    options: list[dict],
    label: str,
    required: bool,
    profile: dict,
    company: str,
    form: dict[str, Any],
) -> None:
    """Populate form[field_name] based on label heuristics and question type."""

    # LinkedIn
    if re.search(r"linkedin", label, re.I):
        form[field_name] = _get_profile_field(profile, "links", "linkedin")
        log.debug("  -> LinkedIn: %s", form[field_name])
        return

    # Website / portfolio / GitHub
    if re.search(r"website|portfolio|github", label, re.I):
        form[field_name] = (
            _get_profile_field(profile, "links", "website")
            or _get_profile_field(profile, "links", "github")
        )
        log.debug("  -> Website/GitHub: %s", form[field_name])
        return

    # Current / most recent company
    if re.search(r"current.{0,20}company|most recent.{0,20}company|employer", label, re.I):
        form[field_name] = (
            _get_profile_field(profile, "personal", "current_company") or company
        )
        log.debug("  -> Current company: %s", form[field_name])
        return

    # Static answer rules (work auth, sponsorship, EEO, agreement, referral)
    for pattern, answer in _STATIC_ANSWERS:
        if pattern.search(label):
            if answer == "__decline__":
                val = _find_decline_option(options) if options else None
                if val is not None:
                    form[field_name] = val
                    log.debug("  -> EEO decline: %s = %r", field_name, val)
                elif options:
                    form[field_name] = str(options[0].get("value", ""))
                    log.warning(
                        "  -> No decline option for %r; using first option: %r",
                        label, form[field_name],
                    )
                else:
                    log.warning("  -> No options for EEO question %r; leaving blank", label)
            else:
                if options:
                    val = _find_option_by_label(options, answer)
                    if val is not None:
                        form[field_name] = val
                        log.debug("  -> Static (option): %s = %r", field_name, val)
                    else:
                        # Try first option with matching prefix
                        form[field_name] = str(options[0].get("value", answer))
                        log.debug(
                            "  -> Static (first option fallback): %s = %r",
                            field_name, form[field_name],
                        )
                else:
                    form[field_name] = answer
                    log.debug("  -> Static (raw): %s = %r", field_name, answer)
            return

    # Zip code / postal code
    if re.search(r"zip\s*code|postal\s*code", label, re.I):
        form[field_name] = _get_profile_field(profile, "personal", "zip_code") or "98052"
        log.debug("  -> Zip code: %s", form[field_name])
        return

    # Years of experience (yes/no or numeric)
    if re.search(r"years?.{0,30}experience|experience.{0,30}years?", label, re.I):
        if options:
            val = _find_option_by_label(options, "Yes")
            if val is not None:
                form[field_name] = val
                log.debug("  -> Experience (Yes): %s = %r", field_name, val)
                return
        form[field_name] = "15"
        log.debug("  -> Experience (numeric): %s", form[field_name])
        return

    # Location (from profile)
    if re.search(r"\blocation\b|city|state|where.{0,20}based", label, re.I):
        form[field_name] = _get_profile_field(profile, "personal", "location")
        log.debug("  -> Location: %s", form[field_name])
        return

    # Open-ended textarea questions — provide brief relevant answer
    if q_type == "textarea" and required:
        # Generate a concise answer referencing experience
        form[field_name] = (
            "Yes, I have extensive experience in this area. "
            "At Microsoft, I led platform engineering across teams of 200+ engineers, "
            "building and maintaining developer tools, CI/CD pipelines, and local development "
            "environments at scale. I've designed containerized dev environments, streamlined "
            "onboarding workflows, and improved developer productivity metrics across "
            "multiple product lines. Please see my resume for detailed project descriptions."
        )
        log.debug("  -> Open-ended (generic): %s chars", len(form[field_name]))
        return

    # Free-text fallback — leave blank, warn if required
    if required:
        log.warning(
            "  -> Required field with no auto-answer: %r (name=%s type=%s)",
            label, field_name, q_type,
        )
    form.setdefault(field_name, "")
    log.debug("  -> Unhandled (blank): name=%s type=%s label=%r", field_name, q_type, label)


# Skip these standard field names (handled separately via base form fields)
_SKIP_FIELD_NAMES = {"first_name", "last_name", "email", "phone", "resume", "resume_text"}


def build_form_data(
    questions: list[dict],
    profile: dict,
    resume_path: Path,
    tailored_md_path: Path,
    company: str,
) -> dict[str, Any]:
    """Build multipart form data from Greenhouse job questions and user profile.

    The Greenhouse API returns questions with this structure:
        {label, required, description, fields: [{name, type, values: [{label, value}]}]}

    Returns a flat dict of field_name -> value ready for HTTP POST.
    Profile structure (structured.yaml):
        personal: {first_name, last_name, email, phone, location, current_company}
        links: {linkedin, github, website}
    """
    log.info("Building form data for %d question(s)", len(questions))

    # Standard top-level fields always included
    form: dict[str, Any] = {
        "first_name": _get_profile_field(profile, "personal", "first_name"),
        "last_name":  _get_profile_field(profile, "personal", "last_name"),
        "email":      _get_profile_field(profile, "personal", "email"),
        "phone":      _get_profile_field(profile, "personal", "phone"),
        "location":   _get_profile_field(profile, "personal", "location"),
    }
    log.debug("Base fields: %s", form)

    for q in questions:
        label: str     = q.get("label", "")
        required: bool = q.get("required", False)

        # Greenhouse API nests field info in a "fields" list.
        # Each question can have multiple sub-fields (e.g. resume has file + textarea).
        for field_def in q.get("fields", []):
            field_name: str = field_def.get("name", "")
            q_type: str     = field_def.get("type", "")
            # Options for select fields are in "values" list: [{label, value}]
            options: list   = field_def.get("values", [])

            log.debug(
                "  Field: name=%s type=%s required=%s options=%d label=%r",
                field_name, q_type, required, len(options), label,
            )

            if field_name in _SKIP_FIELD_NAMES:
                log.debug("  -> Skipping standard field: %s", field_name)
                continue

            _handle_field(
                field_name=field_name,
                q_type=q_type,
                options=options,
                label=label,
                required=required,
                profile=profile,
                company=company,
                form=form,
            )

    log.info("Form data built: %d field(s)", len(form))
    log.debug("Form data (values): %s", {k: v for k, v in form.items()})
    return form


# ---------------------------------------------------------------------------
# CAPTCHA detection
# ---------------------------------------------------------------------------

_CAPTCHA_SIGNALS = [
    "recaptcha", "hcaptcha", "captcha", "cf-challenge",
    "challenge-platform", "turnstile", "just a moment",
    "checking your browser",
]


def _detect_captcha(resp: requests.Response) -> bool:
    """Return True if the response looks like a CAPTCHA challenge."""
    url_lower = resp.url.lower()
    for sig in _CAPTCHA_SIGNALS:
        if sig in url_lower:
            log.debug("CAPTCHA signal in URL: %s", sig)
            return True
    if "html" in resp.headers.get("Content-Type", ""):
        body = resp.text.lower()
        for sig in _CAPTCHA_SIGNALS:
            if sig in body:
                log.debug("CAPTCHA signal in body: %s", sig)
                return True
    return False


# ---------------------------------------------------------------------------
# Resume resolution
# ---------------------------------------------------------------------------


def _get_resume_bytes(resume_path: Path, tailored_md_path: Path) -> tuple[str, bytes, str]:
    """Return (filename, content_bytes, mime_type). Prefers PDF; falls back to text."""
    candidates = [
        resume_path,
        tailored_md_path.with_suffix(".pdf"),
    ]
    if resume_path.suffix.lower() != ".pdf":
        candidates.append(resume_path.with_suffix(".pdf"))

    for p in candidates:
        if p.exists() and p.suffix.lower() == ".pdf":
            log.info("Using PDF resume: %s", p)
            return p.name, p.read_bytes(), "application/pdf"

    if tailored_md_path.exists():
        log.info("No PDF found; using tailored Markdown as plain text: %s", tailored_md_path)
        text = tailored_md_path.read_text(encoding="utf-8")
        return tailored_md_path.stem + ".txt", text.encode("utf-8"), "text/plain"

    raise FileNotFoundError(
        f"No resume found. Checked: {[str(c) for c in candidates]} and {tailored_md_path}"
    )


# ---------------------------------------------------------------------------
# HTTP submission
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# S3 resume upload helpers
# ---------------------------------------------------------------------------

_GH_PRESIGNED_URL = "https://boards.greenhouse.io/uncacheable_attributes/presigned_fields"


def _upload_resume_to_s3(
    resume_path: Path,
    tailored_md_path: Path | None = None,
) -> tuple[str, str] | None:
    """Upload resume to Greenhouse's S3 bucket via presigned URL.

    Returns (resume_url, resume_filename) on success, or None on failure.
    """
    md_path = tailored_md_path or (resume_path.with_suffix(".md") if resume_path else None)
    try:
        resume_fname, resume_bytes, resume_mime = _get_resume_bytes(
            resume_path, md_path or resume_path
        )
    except FileNotFoundError as exc:
        log.error("Cannot find resume: %s", exc)
        return None

    log.info("Fetching S3 presigned fields from Greenhouse")
    try:
        presign_resp = requests.get(
            _GH_PRESIGNED_URL,
            params={"fields[]": "resume"},
            timeout=15,
        )
        presign_resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("Failed to fetch presigned fields: %s", exc)
        return None

    presign_data = presign_resp.json()
    log.debug("Presigned fields response keys: %s", list(presign_data.keys()))

    # Response: {"url": "https://s3.amazonaws.com/...", "resume": {"fields": {...}, "key": "stash/..."}}
    s3_url: str = presign_data.get("url", "")
    resume_presign = presign_data.get("resume", {})
    fields: dict = resume_presign.get("fields", {})
    key_template: str = resume_presign.get("key", "")

    if not s3_url or not fields or not key_template:
        log.error("Unexpected presigned response structure: %s", presign_data)
        return None

    # Replace key template placeholders
    import time, uuid
    key = key_template.replace("{timestamp}", str(int(time.time() * 1000)))
    key = key.replace("{unique_id}", uuid.uuid4().hex[:8])

    # Build S3 upload form data
    s3_fields = {
        "utf8": "\u2713",
        "authenticity_token": "",
        "key": key,
        "Content-Type": resume_mime,
        **fields,
    }

    # POST multipart to S3 with presigned fields + file
    log.info("Uploading resume to S3: %s (key=%s)", s3_url, key[:60])
    try:
        s3_resp = requests.post(
            s3_url,
            data=s3_fields,
            files={"file": (resume_fname, resume_bytes, resume_mime)},
            timeout=30,
        )
    except requests.RequestException as exc:
        log.error("S3 upload request failed: %s", exc)
        return None

    if s3_resp.status_code not in (200, 201, 204):
        log.error("S3 upload returned HTTP %s: %s", s3_resp.status_code, s3_resp.text[:200])
        return None

    # Extract final URL from S3 XML response or construct it
    loc_match = re.search(r"<Location>([^<]+)</Location>", s3_resp.text)
    if loc_match:
        final_url = loc_match.group(1)
    else:
        final_url = s3_url.rstrip("/") + "/" + key.lstrip("/")

    log.info("Resume uploaded to S3: %s", final_url)
    return final_url, resume_fname


# ---------------------------------------------------------------------------
# Page HTML parsing helpers
# ---------------------------------------------------------------------------


def _extract_fingerprint(html: str) -> str:
    """Extract the fingerprint value from Greenhouse page HTML."""
    m = re.search(r'"fingerprint":"([^"]+)"', html)
    if m:
        return m.group(1)
    log.debug("No fingerprint found in page HTML")
    return ""


def _extract_disable_captcha(html: str) -> bool:
    """Return True if the board has CAPTCHA disabled (disable_captcha: true)."""
    m = re.search(r'"disable_captcha"\s*:\s*(true|false)', html)
    if m:
        return m.group(1) == "true"
    # Default: assume CAPTCHA is enabled (safer assumption)
    return False


def _fetch_page_html(board_token: str, job_id: str) -> str | None:
    """GET the Greenhouse job page HTML. Returns text or None on error."""
    url = f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}"
    log.info("Fetching page HTML: %s", url)
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=15,
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        log.error("Failed to fetch page HTML: %s", exc)
        return None


# ---------------------------------------------------------------------------
# HTTP submission (JSON POST)
# ---------------------------------------------------------------------------

_GH_CAPTCHA_SITE_KEY = "6LfmcbcpAAAAAChNTbhUShzUOAMj_wY9LQIvLFX0"


def submit_application(
    board_token: str,
    job_id: str,
    form_data: dict[str, Any],
    resume_path: Path,
    tailored_md_path: Path | None = None,
    page_html: str | None = None,
    captcha_config: dict | None = None,
) -> dict[str, Any]:
    """Submit the application via JSON POST to Greenhouse.

    Flow:
    1. Upload resume to S3 → get resume_url
    2. Extract fingerprint from page HTML (if provided)
    3. Solve CAPTCHA if enabled and not disabled on the board
    4. JSON POST to boards.greenhouse.io/{board_token}/jobs/{job_id}

    Returns {"success": bool, "message": str, "status_code": int | None}.
    """
    url = f"https://boards.greenhouse.io/{board_token}/jobs/{job_id}"
    log.info("Submitting application to: %s", url)

    md_path = tailored_md_path or resume_path.with_suffix(".md")

    # 1. Upload resume to S3
    s3_result = _upload_resume_to_s3(resume_path, md_path)
    if s3_result is None:
        log.warning("S3 upload failed; falling back to base64 resume embed (not recommended)")
        resume_url = ""
        resume_filename = resume_path.name
    else:
        resume_url, resume_filename = s3_result

    # 2. Extract fingerprint from page HTML
    fingerprint = ""
    disable_captcha = False
    if page_html:
        fingerprint = _extract_fingerprint(page_html)
        disable_captcha = _extract_disable_captcha(page_html)
        log.debug("fingerprint=%r  disable_captcha=%s", fingerprint[:20] if fingerprint else "", disable_captcha)

    # 3. Solve CAPTCHA if needed
    captcha_token: str | None = None
    cfg = captcha_config or {}
    captcha_enabled = cfg.get("enabled", False)

    if captcha_enabled and not disable_captcha:
        log.info("CAPTCHA solving enabled and board requires it — calling CapSolver")
        try:
            from scripts.captcha import solve_recaptcha_enterprise
            captcha_token = solve_recaptcha_enterprise(
                site_key=_GH_CAPTCHA_SITE_KEY,
                page_url=url.replace("boards.greenhouse.io", "job-boards.greenhouse.io"),
            )
            if captcha_token:
                log.info("CAPTCHA solved successfully")
            else:
                log.warning("CAPTCHA solving failed — submission may be blocked (HTTP 428)")
        except Exception as exc:
            log.error("CAPTCHA solver error: %s", exc)
    elif captcha_enabled and disable_captcha:
        log.info("Board has CAPTCHA disabled; skipping CAPTCHA solving")
    else:
        log.info("CAPTCHA solving not enabled in config; skipping")

    # 4. Build JSON body
    job_application: dict[str, Any] = {
        "first_name": form_data.get("first_name", ""),
        "last_name":  form_data.get("last_name", ""),
        "email":      form_data.get("email", ""),
        "phone":      form_data.get("phone", ""),
        "location":   form_data.get("location", ""),
    }

    # Add S3 resume fields
    if resume_url:
        job_application["resume_url"]          = resume_url
        job_application["resume_url_filename"] = resume_filename

    # Add remaining custom fields (skip base fields already included)
    _BASE_FIELDS = {"first_name", "last_name", "email", "phone", "location"}
    for k, v in form_data.items():
        if k not in _BASE_FIELDS and not isinstance(v, tuple):
            job_application[k] = v

    body: dict[str, Any] = {
        "job_application": job_application,
    }
    if fingerprint:
        body["fingerprint"] = fingerprint
    if captcha_token:
        body["g-recaptcha-enterprise-token"] = captcha_token

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/html, */*",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        ),
        "Referer": url,
    }

    log.debug("JSON POST body keys: %s", list(body.keys()))
    log.debug("job_application keys: %s", list(job_application.keys()))

    try:
        resp = requests.post(
            url,
            json=body,
            headers=headers,
            timeout=30,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        log.error("Network error during submission: %s", exc)
        return {"success": False, "message": f"Network error: {exc}", "status_code": None}

    log.info("Response: HTTP %s  final_url=%s", resp.status_code, resp.url)
    log.debug("Response headers: %s", dict(resp.headers))

    # Handle status codes per Greenhouse reverse-engineering
    if resp.status_code == 428:
        log.warning("HTTP 428 — CAPTCHA required or token was rejected")
        return {
            "success": False,
            "message": "CAPTCHA required or token rejected (HTTP 428)",
            "status_code": 428,
            "captcha": True,
        }

    if resp.status_code == 422:
        snippet = resp.text[:500]
        log.error("HTTP 422 Validation error: %s", snippet)
        return {
            "success": False,
            "message": f"Validation error (HTTP 422): {snippet}",
            "status_code": 422,
        }

    if resp.status_code in (200, 201, 302):
        body_lower = resp.text.lower()
        if "thank" in resp.url.lower() or "thank" in body_lower:
            log.info("Application submitted successfully (thank-you page detected)")
            return {"success": True, "message": "Application submitted", "status_code": resp.status_code}
        if "error" in body_lower or "invalid" in body_lower:
            snippet = resp.text[:500]
            log.warning("Error signals in response body: %s", snippet)
            return {
                "success": False,
                "message": f"Submission error detected: {snippet}",
                "status_code": resp.status_code,
            }
        log.info("Application likely submitted (HTTP %s, no errors detected)", resp.status_code)
        return {
            "success": True,
            "message": f"Submitted (HTTP {resp.status_code}, no errors detected in response)",
            "status_code": resp.status_code,
        }

    if _detect_captcha(resp):
        log.warning("CAPTCHA detected in response body — application cannot be auto-submitted")
        return {
            "success": False,
            "message": "CAPTCHA challenge detected; manual submission required",
            "status_code": resp.status_code,
            "captcha": True,
        }

    log.error("Unexpected HTTP %s: %s", resp.status_code, resp.text[:300])
    return {
        "success": False,
        "message": f"HTTP {resp.status_code}: {resp.text[:300]}",
        "status_code": resp.status_code,
    }


# ---------------------------------------------------------------------------
# DB update helper
# ---------------------------------------------------------------------------


def _update_db_status(db_path: Path, job_id: int, status: str, note: str = "") -> None:
    """Update job status in the SQLite jobs table."""
    from scripts.utils import utcnow_iso
    now = utcnow_iso()
    log.debug("DB update: job_id=%d -> %s", job_id, status)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET status=?, updated_at=?, status_updated_at=? WHERE id=?",
            (status, now, now, job_id),
        )
        if note:
            try:
                conn.execute(
                    "INSERT INTO job_notes (job_id, note, created_at) VALUES (?,?,?)",
                    (job_id, note, now),
                )
            except sqlite3.OperationalError:
                log.debug("job_notes table not present; skipping note insert")
        conn.commit()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def apply_greenhouse(
    job_id: int,
    job_url: str,
    jd_text: str,
    profile: dict,
    resume_path: Path,
    tailored_md_path: Path,
    company: str,
    db_path: Path,
    captcha_config: dict | None = None,
) -> str:
    """Apply to a Greenhouse job via HTTP POST (no browser needed).

    Flow:
    1. Extract board_token and job_id from URL
    2. GET page HTML → extract fingerprint, disable_captcha flag
    3. Fetch questions from Greenhouse API
    4. Build form data (profile + question heuristics)
    5. Upload resume to S3
    6. Solve CAPTCHA if enabled (CapSolver)
    7. JSON POST to boards.greenhouse.io
    8. Handle response: 200/302 = success, 428 = captcha failed, 422 = validation error

    Returns one of:
    - "applied"      — submitted successfully
    - "blocked"      — CAPTCHA or other block; needs manual submission
    - "apply_failed" — error during extraction, fetch, or submission

    Updates the jobs table status in db_path.
    """
    # Load captcha config from config.yaml if not provided
    if captcha_config is None:
        try:
            import yaml
            cfg_path = Path(__file__).resolve().parent.parent / "config.yaml"
            if cfg_path.exists():
                with open(cfg_path) as cf:
                    full_cfg = yaml.safe_load(cf) or {}
                captcha_config = full_cfg.get("captcha", {})
                log.debug("Loaded captcha config: %s", captcha_config)
        except Exception as exc:
            log.warning("Could not load config.yaml for captcha settings: %s", exc)
            captcha_config = {}

    log.info("=== Greenhouse apply: job_id=%d  company=%r ===", job_id, company)
    log.info("Job URL: %s", job_url)

    # 1. Extract Greenhouse board_token + gh_job_id from URL
    gh_info = extract_greenhouse_info(job_url, jd_text)
    if not gh_info:
        msg = f"Could not extract Greenhouse identifiers from URL: {job_url}"
        log.error(msg)
        try:
            _update_db_status(db_path, job_id, "apply_failed", note=msg)
        except Exception as exc:
            log.error("DB update failed: %s", exc)
        return "apply_failed"

    board_token = gh_info["board_token"]
    gh_job_id   = gh_info["job_id"]
    log.info("Resolved: board_token=%s  gh_job_id=%s", board_token, gh_job_id)

    # 2. GET page HTML → extract fingerprint and disable_captcha flag
    page_html = _fetch_page_html(board_token, gh_job_id)
    if page_html is None:
        log.warning("Could not fetch page HTML; proceeding without fingerprint/captcha-disable info")
        page_html = ""

    # 3. Fetch job questions from Greenhouse API
    try:
        job_data = get_job_questions(board_token, gh_job_id)
    except requests.HTTPError as exc:
        msg = f"Failed to fetch Greenhouse questions: {exc}"
        log.error(msg)
        try:
            _update_db_status(db_path, job_id, "apply_failed", note=msg)
        except Exception as db_exc:
            log.error("DB update failed: %s", db_exc)
        return "apply_failed"

    questions = job_data.get("questions", [])

    # 4. Build form data from profile + question mapping
    form_data = build_form_data(
        questions=questions,
        profile=profile,
        resume_path=resume_path,
        tailored_md_path=tailored_md_path,
        company=company,
    )

    # 5–7. Upload resume, solve CAPTCHA, JSON POST (handled inside submit_application)
    result = submit_application(
        board_token=board_token,
        job_id=gh_job_id,
        form_data=form_data,
        resume_path=resume_path,
        tailored_md_path=tailored_md_path,
        page_html=page_html,
        captcha_config=captcha_config,
    )

    # 8. Map to final status string
    if result.get("captcha"):
        final_status = "blocked"
        note = f"Greenhouse CAPTCHA block (HTTP {result.get('status_code')}) — manual application required"
    elif result["success"]:
        final_status = "applied"
        note = f"Greenhouse HTTP apply succeeded (HTTP {result.get('status_code')})"
    else:
        final_status = "apply_failed"
        note = f"Greenhouse HTTP apply failed: {result['message']}"

    log.info("Final status: %s — %s", final_status, note)

    # 9. Persist to DB
    try:
        _update_db_status(db_path, job_id, final_status, note=note)
    except Exception as exc:
        log.error("DB update failed (non-fatal): %s", exc)

    return final_status


# ---------------------------------------------------------------------------
# Dry-run / CLI test
# ---------------------------------------------------------------------------


def dry_run(board_token: str = "reddit", job_id: str = "6909091", profile: dict | None = None) -> None:
    """Fetch questions and build form data without submitting.

    Default tests against Reddit job 6909091 (board_token="reddit").
    """
    import pprint
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

    if profile is None:
        profile = {
            "personal": {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "jane@example.com",
                "phone": "+1-555-555-5555",
                "location": "San Francisco, CA",
                "current_company": "Self-employed",
            },
            "links": {
                "linkedin": "https://linkedin.com/in/janedoe",
                "github": "https://github.com/janedoe",
                "website": "",
            },
        }

    sep = "=" * 65
    print(f"\n{sep}")
    print(f"DRY RUN  board_token={board_token!r}  job_id={job_id!r}")
    print(f"{sep}\n")

    # Step 1: Fetch questions
    print("Step 1: Fetching questions from Greenhouse API...")
    job_data = get_job_questions(board_token, job_id)
    questions = job_data.get("questions", [])
    print(f"  Job title : {job_data.get('title')}")
    print(f"  Location  : {job_data.get('location', {}).get('name', '?')}")
    print(f"  Questions : {len(questions)}")

    for q in questions:
        label    = q.get("label", "?")
        required = q.get("required", False)
        for fd in q.get("fields", []):
            opts = fd.get("values", [])
            print(
                f"\n    [{fd.get('type','?'):25s}]  name={fd.get('name','?'):35s}"
                f"  required={str(required):5s}  label={label!r}"
            )
            for opt in opts:
                print(f"         option: {str(opt.get('label')):40s} -> {opt.get('value')!r}")

    # Step 2: Build form data
    print(f"\n{sep}")
    print("Step 2: Building form data (no submission)...")
    dummy_resume = Path("/tmp/dummy_resume.pdf")
    dummy_md     = Path("/tmp/dummy_resume.md")
    form_data = build_form_data(
        questions=questions,
        profile=profile,
        resume_path=dummy_resume,
        tailored_md_path=dummy_md,
        company="Acme Corp",
    )

    print("\n  Form data that WOULD be posted:")
    pprint.pprint(form_data, indent=4)
    print(f"\n{sep}")
    print("DRY RUN COMPLETE — nothing was submitted.")
    print(sep)


if __name__ == "__main__":
    dry_run()
