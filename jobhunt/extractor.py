"""Playwright-based JD extraction and content normalisation.

FR-05/06: extract_jd() scrapes the full job description from a detail page.
FR-07: compute_hash() computes the MD5 jd_hash from normalised text.
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser

from jobhunt.models import ExtractionError
from jobhunt.utils import log_warn

# ---------------------------------------------------------------------------
# Verified selectors (2026-02-25 against live LinkedIn DOM)
# ---------------------------------------------------------------------------

_JD_PRIMARY_SELECTOR = ".description__text"
_JD_FALLBACK_SELECTOR = ".show-more-less-html__markup"
_SHOW_MORE_SELECTOR = "button.show-more-less-html__button--more"

# ---------------------------------------------------------------------------
# HTML stripper
# ---------------------------------------------------------------------------


class _HTMLStripper(HTMLParser):
    """Converts HTML to plain text, inserting newlines at block boundaries."""

    BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def strip_html(html: str) -> str:
    """Strip HTML tags from html, preserving block-level spacing as newlines.

    Uses stdlib html.parser — no third-party dependencies.
    """
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


# ---------------------------------------------------------------------------
# Hash computation (FR-07)
# ---------------------------------------------------------------------------


def compute_hash(jd_text: str) -> str:
    """Return the MD5 hex digest of the normalised jd_text.

    Normalisation steps (in order):
      1. Strip any residual HTML tags.
      2. Collapse all whitespace (spaces, tabs, newlines) to a single space.
      3. Strip leading/trailing whitespace.
      4. Lowercase.
      5. MD5 hex digest of the UTF-8 encoded result.

    Example (TC-07):
      Input:  '  <b>Engineer</b>\\n\\nAt Stripe. '
      Output: MD5('engineer at stripe.')
    """
    # Step 1: guard against any residual HTML
    text = re.sub(r"<[^>]+>", "", jd_text)
    # Step 2: collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Step 3+4: strip and lowercase
    text = text.strip().lower()
    # Step 5: MD5
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# JD extraction from a Playwright page (FR-06)
# ---------------------------------------------------------------------------


def extract_jd(page) -> str:
    """Extract the full plain-text job description from the current detail page.

    Algorithm:
      1. Wait for JD container (primary selector, then fallback).
      2. Click "Show more" button if visible.
      3. Get inner HTML of container.
      4. Strip HTML to plain text.
      5. Return plain text; raise ExtractionError if empty.

    Raises:
        ExtractionError: if the JD container is not found or the result is empty.
    """
    # Step 1: wait for JD container
    container_selector = _JD_PRIMARY_SELECTOR
    try:
        page.wait_for_selector(_JD_PRIMARY_SELECTOR, timeout=10_000)
    except Exception:
        try:
            page.wait_for_selector(_JD_FALLBACK_SELECTOR, timeout=5_000)
            container_selector = _JD_FALLBACK_SELECTOR
        except Exception as exc:
            raise ExtractionError(
                f"JD container not found on {page.url}: {exc}"
            ) from exc

    # Step 2: click "Show more" if present
    try:
        btn = page.locator(_SHOW_MORE_SELECTOR)
        if btn.is_visible(timeout=2_000):
            btn.click()
            page.wait_for_timeout(1_000)
    except Exception:
        pass  # "Show more" is optional; failure is acceptable

    # Step 3: get inner HTML (try primary, then fallback)
    container = page.locator(container_selector)
    if container.count() == 0:
        container = page.locator(_JD_FALLBACK_SELECTOR)
    if container.count() == 0:
        raise ExtractionError(f"JD container missing after wait on {page.url}")

    try:
        html = container.inner_html()
    except Exception as exc:
        raise ExtractionError(f"Failed to get inner HTML on {page.url}: {exc}") from exc

    # Step 4: strip HTML
    text = strip_html(html).strip()

    # Step 5: validate result
    if not text:
        raise ExtractionError(f"Extracted JD is empty on {page.url}")

    return text
