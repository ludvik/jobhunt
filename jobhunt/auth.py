"""Authentication flow: 1Password auto-login and manual browser fallback.

FR-01: run_auth() resolves credentials via 1Password and logs in automatically.
FR-02: ensure_session() checks for an existing session file before fetching.
FR-20: Falls back to headed manual browser login when op is unavailable.
"""

from __future__ import annotations

import sys

from jobhunt import browser, credentials
from jobhunt.config import SESSION_DIR, SESSION_PATH
from jobhunt.models import Credential
from jobhunt.utils import log_info, log_warn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_session(config: dict) -> None:
    """Ensure a LinkedIn session file exists; trigger auth if missing (FR-02).

    Exits with code 1 if the auth flow fails.
    """
    if SESSION_PATH.exists():
        return

    log_info("No session file found. Running authentication...")
    success = run_auth(config)
    if not success:
        print(
            "Error: authentication failed. Please run 'jobhunt auth' manually.",
            file=sys.stderr,
        )
        sys.exit(1)


def run_auth(config: dict) -> bool:
    """Run the full auth flow.

    1. Attempt to resolve credentials from 1Password (FR-01).
    2. If successful → automated Playwright login.
    3. If unavailable / no match → manual browser login (FR-20).

    Returns True on success, False on failure.
    """
    domain = config["sources"]["linkedin"]["op_domain"]
    preferred_emails = config["credential_preferences"]["preferred_emails"]

    credential = credentials.resolve_credential(domain, preferred_emails)

    if credential is None:
        # resolve_credential already printed the reason; fall back to manual
        return _do_manual_login()

    print("Logging in to LinkedIn automatically...", flush=True)
    return _do_playwright_login(credential)


# ---------------------------------------------------------------------------
# Automated login (FR-01)
# ---------------------------------------------------------------------------


def _do_playwright_login(credential: Credential) -> bool:
    """Use Playwright headless Chromium to fill and submit the LinkedIn login form.

    Returns True if the session is valid after submission, False otherwise.
    """
    context, browser_inst, pw = browser.launch_context(None, headless=True)
    try:
        page = context.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30_000)

        # Fill username and password (NEVER log credential.password)
        page.fill("#username", credential.username)
        page.fill("#password", credential.password)
        page.click('[type="submit"]')

        # Wait for navigation to settle
        try:
            page.wait_for_load_state("domcontentloaded", timeout=20_000)
            page.wait_for_timeout(2_000)
        except Exception:
            pass

        if not browser.is_session_valid(page):
            print(
                "Error: Login failed. Check your LinkedIn credentials.",
                file=sys.stderr,
            )
            return False

        _persist_session(context)
        return True

    finally:
        context.close()
        browser_inst.close()
        pw.stop()


# ---------------------------------------------------------------------------
# Manual login fallback (FR-20)
# ---------------------------------------------------------------------------


def _do_manual_login() -> bool:
    """Open a headed Chromium browser for the user to log in manually.

    Blocks until the user presses Enter in the terminal, then saves the
    session state identically to the automated flow.

    Returns True on success, False if interrupted.
    """
    print(
        "Opening browser — please log in to LinkedIn, then press Enter here when done...",
        flush=True,
    )
    context, browser_inst, pw = browser.launch_context(None, headless=False)
    try:
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        try:
            input()  # Block until user presses Enter
        except (EOFError, KeyboardInterrupt):
            return False

        _persist_session(context)
        return True

    finally:
        context.close()
        browser_inst.close()
        pw.stop()


# ---------------------------------------------------------------------------
# Session persistence helper
# ---------------------------------------------------------------------------


def _persist_session(context) -> None:
    """Save storage state to SESSION_PATH with 0600 permissions (NFR-06)."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    browser.save_storage_state(context, str(SESSION_PATH))
    print(f"✓ Session saved to {SESSION_PATH}")
