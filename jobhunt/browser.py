"""Playwright browser lifecycle: context creation, session persistence, expiry detection.

§4.7: _ensure_chromium() auto-installs Chromium if not present.
§4.6: is_session_valid() detects expired LinkedIn sessions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright, BrowserContext, Browser, Playwright

from jobhunt.utils import log_warn

# ---------------------------------------------------------------------------
# LinkedIn session-expiry URL patterns (FR-03)
# ---------------------------------------------------------------------------

_EXPIRED_URL_PATTERNS = [
    "/login",
    "/authwall",
    "/checkpoint/",
    "/uas/login",
]

# ---------------------------------------------------------------------------
# Chromium auto-install (§4.7)
# ---------------------------------------------------------------------------


def _ensure_chromium() -> None:
    """Check that the Playwright Chromium executable exists; install if not.

    This is a one-time operation; subsequent calls are a no-op.
    Safe to call multiple times.
    """
    try:
        pw = sync_playwright().start()
        chromium_path = pw.chromium.executable_path
        pw.stop()
    except Exception:
        # If we can't determine the path, proceed and let launch() surface errors
        return

    if not os.path.exists(chromium_path):
        print("Chromium not found. Installing (~120 MB)...", file=sys.stderr, flush=True)
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )


# ---------------------------------------------------------------------------
# Context lifecycle
# ---------------------------------------------------------------------------


def launch_context(
    session_path: str | None,
    headless: bool = True,
) -> tuple[BrowserContext, Browser, Playwright]:
    """Launch a Playwright Chromium browser context.

    If session_path points to an existing file, it is loaded as storage state
    (cookies + localStorage) to restore the LinkedIn session.

    Returns (context, browser, playwright) — caller must close all three:
        context.close(); browser.close(); pw.stop()
    """
    _ensure_chromium()

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=headless)

        # Large viewport so LinkedIn renders all job cards on the page
        # (LinkedIn uses "occludable" lazy rendering based on viewport)
        viewport = {"width": 1920, "height": 8000}

        if session_path and os.path.exists(session_path):
            context = browser.new_context(
                storage_state=session_path, viewport=viewport
            )
        else:
            context = browser.new_context(viewport=viewport)

        context.set_default_timeout(8_000)
        context.set_default_navigation_timeout(15_000)
        return context, browser, pw
    except Exception:
        pw.stop()
        raise


# ---------------------------------------------------------------------------
# Session persistence (NFR-06)
# ---------------------------------------------------------------------------


def save_storage_state(context: BrowserContext, path: str) -> None:
    """Save Playwright storage state (cookies + localStorage) to path.

    The file is written with permissions 0600 (owner read/write only) to
    protect authentication cookies (NFR-06).
    """
    state = context.storage_state()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Write with strict permissions: open with O_CREAT | O_TRUNC at mode 0600
    fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f)
    except Exception:
        # fd was consumed by fdopen; nothing more to close
        raise


# ---------------------------------------------------------------------------
# Session expiry detection (FR-03, §4.6)
# ---------------------------------------------------------------------------


def is_session_valid(page) -> bool:
    """Return False if the page indicates an expired/invalid LinkedIn session.

    Checks:
      1. Final URL contains any of the known auth-redirect path segments.
      2. Presence of the login form element.
    """
    current_url = page.url

    for pattern in _EXPIRED_URL_PATTERNS:
        if pattern in current_url:
            return False

    # Secondary check: login form presence
    try:
        if page.locator("form#login-form").count() > 0:
            return False
    except Exception:
        pass

    return True
