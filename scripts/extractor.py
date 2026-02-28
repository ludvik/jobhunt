"""Playwright-based JD extraction and content normalisation.

FR-05/06: extract_jd() scrapes the full job description from a detail page.
FR-07: compute_hash() computes the MD5 jd_hash from normalised text.
"""

from __future__ import annotations

import hashlib
import json
import re
from html.parser import HTMLParser

from scripts.models import ExtractionError
from scripts.utils import log_warn

# ---------------------------------------------------------------------------
# Verified selectors (updated for LinkedIn DOM drift)
# ---------------------------------------------------------------------------

# Primary/fallback containers we observed across LinkedIn job detail pages.
_JD_CONTAINER_SELECTORS = [
    ".description__text",
    ".show-more-less-html__markup",
    ".jobs-description-content__text",
    ".jobs-box__html-content",
    ".jobs-box__content",
    "section.jobs-description-content",
    ".jobs-description-content",
]

# Fallback selectors with explicit role/region hints.
_JD_DESC_FALLBACKS = [
    "div[data-test='job-description']",
    "section.jobs-description__content",
    "[data-test='jobs-description-content']",
    "article.jobs-description",
]

# Broad fallback selectors when LinkedIn rewrites markup significantly.
_JD_BROAD_SELECTORS = [
    "main",
    "article",
    "section",
    "div[role='main']",
    "div.jobs-details",
]

# Show-more controls (some pages may use one of these).
_SHOW_MORE_SELECTORS = [
    "button.show-more-less-html__button--more",
    "button.show-more-less-html__button",
    "button:has-text('Show more')",
    "button.show-more",
]

# Keep previous symbolic names for compatibility.
_JD_PRIMARY_SELECTOR = _JD_CONTAINER_SELECTORS[0]
_JD_FALLBACK_SELECTOR = _JD_CONTAINER_SELECTORS[1]
_SHOW_MORE_SELECTOR = _SHOW_MORE_SELECTORS[0]


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
# JD extraction helpers
# ---------------------------------------------------------------------------


def _locator_visible(locator) -> bool:
    """Best-effort check for locator visibility without hard failures."""
    try:
        return locator.is_visible(timeout=1_000)
    except Exception:
        return False


def _try_click_show_more(page) -> bool:
    """Try all known "Show more" selectors once and report if any was clicked."""
    for selector in _SHOW_MORE_SELECTORS:
        try:
            btn = page.locator(selector)
            if not hasattr(btn, "count"):
                continue
            count = btn.count()
            if isinstance(count, int) and count <= 0:
                continue
            if _locator_visible(btn):
                btn.click()
                try:
                    page.wait_for_timeout(200)
                except Exception:
                    pass
                return True
        except Exception:
            # Intentionally ignore; show-more is optional.
            continue
    return False


def _extract_from_jsonld(page) -> str:
    """Fallback: extract description from JSON-LD job posting payload."""
    try:
        scripts = page.query_selector_all("script[type='application/ld+json']")
    except Exception:
        return ""

    for script in scripts:
        try:
            payload = script.inner_text()
        except Exception:
            try:
                payload = script.inner_html()
            except Exception:
                continue

        try:
            data = json.loads(payload)
        except Exception:
            continue

        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("@type") not in {"JobPosting", "Job", "EmploymentPosition"}:
                continue
            description = item.get("description") or ""
            if isinstance(description, str) and description.strip():
                return strip_html(description).strip()

    return ""


def _find_jd_container(page):
    """Find a likely JD container locator with best-effort DOM drift handling."""
    selectors = [
        *_JD_CONTAINER_SELECTORS,
        *_JD_DESC_FALLBACKS,
    ]
    last_error: Exception | None = None

    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=1_500)
            container = page.locator(selector)
            try:
                if container.count() > 0:
                    return container
            except Exception:
                # some mocks/tests may return a non-int count type; treat as found after wait.
                if container is not None:
                    return container
        except Exception as exc:
            last_error = exc
            continue

    return None


def _extract_jd_text_from_locator(page, locator, selectors: list[str]) -> str:
    """Extract text from a single resolved locator candidate."""
    candidate_selectors = ["", *(selectors if selectors else [])]
    for selector in candidate_selectors:
        try:
            candidate = locator if selector == "" else page.locator(selector)
            count = candidate.count()
            if isinstance(count, int) and count <= 0:
                continue

            try:
                page.wait_for_timeout(200)
            except Exception:
                pass

            html = candidate.inner_html()
            text = strip_html(html).strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def _extract_from_broad_sections(page) -> str:
    """Last-resort extraction from broad page sections."""
    text_candidates: list[str] = []

    for selector in _JD_BROAD_SELECTORS:
        try:
            loc = page.locator(selector)
            count = loc.count()
            if not isinstance(count, int):
                count = 1

            if count <= 0:
                continue

            for idx in range(min(count, 5)):
                node = loc.nth(idx) if hasattr(loc, "nth") and count > 1 else loc
                try:
                    text = node.inner_text(timeout=300).strip()
                except Exception:
                    continue
                if text and len(text) > 300:
                    text_candidates.append(text)
        except Exception:
            continue

    # prefer strings that contain common JD headings/keywords
    keyword_hits: list[tuple[int, str]] = []
    for text in text_candidates:
        low = text.lower()
        hits = 0
        if "responsib" in low:
            hits += 2
        if "qualif" in low:
            hits += 2
        if "about" in low:
            hits += 1
        if "we are" in low:
            hits += 1
        keyword_hits.append((hits, text))

    if not keyword_hits:
        return ""

    keyword_hits.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
    return keyword_hits[0][1].strip()


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
      5. If DOM extraction fails, fallback to JSON-LD payload.
      6. If still empty, perform broad section fallback.
      7. Return plain text; raise ExtractionError if empty.

    Raises:
        ExtractionError: if the JD container is not found or result is empty.
    """
    selectors = [*_JD_CONTAINER_SELECTORS, *_JD_DESC_FALLBACKS]

    # Step 1: resolve container (best effort).
    container = _find_jd_container(page)

    # Step 2: click "Show more" if visible (best effort).
    _try_click_show_more(page)

    # Step 3: DOM extraction.
    if container is not None:
        text = _extract_jd_text_from_locator(page, container, selectors)
        if text:
            return text

    # Step 5: fallback JSON-LD extraction.
    text = _extract_from_jsonld(page)
    if text:
        return text

    # Step 6: broad structural fallback.
    text = _extract_from_broad_sections(page)
    if text:
        return text

    # Step 7: explicit failure.
    raise ExtractionError(f"JD container not found on {page.url}: no matching description container")


# Keep previous behaviour-compatible wrappers for any external imports/tests.
__all__ = [
    "compute_hash",
    "strip_html",
    "extract_jd",
    "ExtractionError",
]
