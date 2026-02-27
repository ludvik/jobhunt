"""Fetch orchestration: scroll loop, retry logic, dedup, summary.

FR-04: scroll_loop() collects job cards with lookback + limit stopping conditions.
FR-11: _fetch_with_retry() retries detail-page extraction up to 3 times.
FR-12: dry_run mode prints JSON instead of writing to DB.
FR-13: print_summary() outputs the final run stats line.
"""

from __future__ import annotations

import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Generator

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from jobhunt import auth, browser, extractor
from jobhunt import db as db_module
from jobhunt.config import DB_PATH, SESSION_PATH
from jobhunt.models import ExtractionError, JobCard, RunStats
from jobhunt.utils import log_error, log_info, log_warn, parse_iso, parse_relative_date

# ---------------------------------------------------------------------------
# LinkedIn selectors (verified 2026-02-25 against live LinkedIn DOM — §4.2)
# ---------------------------------------------------------------------------

_JOB_CARD_SELECTOR = "li[data-occludable-job-id]"
_JOB_ID_PATTERN = re.compile(r"jobPosting:(\d+)")
_JOB_CARD_FALLBACKS = [
    "li[data-occludable-job-id]",
    "div.job-card-container",
    "li.jobs-search-results__list-item",
    "li.scaffold-layout__list-item",
    "li[data-view-name='search-entity-result']",
]

_MAX_EMPTY_SCROLLS = 8  # consecutive empty scrolls before assuming end-of-feed
_POLL_INTERVAL_MS = 500  # ms between card-count polls after scroll
_POLL_TIMEOUT_MS = 4000  # max ms to wait for new cards after scroll

# Card field selector candidates (for logged-in recommended feed compatibility)
_JOB_TITLE_SELECTORS = [
    "a.job-card-list__title--link",
    "a.job-card-container__link",
    ".base-search-card__title",
    "h3",
    "h4",
    "a[data-control-name='job_card_click']",
    "a[href*='/jobs/view/']",
]

_JOB_COMPANY_SELECTORS = [
    ".base-search-card__subtitle",
    "h4.base-search-card__subtitle",
    "a.hidden-nested-link",
    ".job-card-container__company-name",
    ".artdeco-entity-lockup__subtitle",
    "span.job-card-container__primary-description",
    "p[data-test-job-card-container-subtitle]",
]

_JOB_LOCATION_SELECTORS = [
    ".job-search-card__location",
    ".artdeco-entity-lockup__caption",
    ".job-card-container__metadata-item",
    ".job-card-container__metadata-wrapper",
]


# ---------------------------------------------------------------------------
# utility helpers for resilient extraction
# ---------------------------------------------------------------------------

def clean_title(text: str) -> str:
    """Clean a job title by removing verification badge text and deduplication.

    Handles LinkedIn DOM quirk where inner_text() on a container element
    returns the visible title concatenated with aria/span text, e.g.
    'Senior Engineer Senior Engineer' or 'Senior Engineer with verification'.
    """
    # Strip verification badge suffixes (case-insensitive)
    text = re.sub(r"\s+with verification\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+verification badge\s*$", "", text, flags=re.IGNORECASE)

    # Deduplicate: if word list has even length and first half == second half
    words = text.split()
    if len(words) >= 2 and len(words) % 2 == 0:
        mid = len(words) // 2
        if words[:mid] == words[mid:]:
            text = " ".join(words[:mid])

    return text.strip()


def _poll_for_new_cards(page, selector: str, count_before: int) -> bool:
    """Poll for new cards to appear after a scroll, up to _POLL_TIMEOUT_MS.

    Returns True if new cards appeared, False if timeout reached.
    """
    elapsed = 0
    while elapsed < _POLL_TIMEOUT_MS:
        page.wait_for_timeout(_POLL_INTERVAL_MS)
        elapsed += _POLL_INTERVAL_MS
        try:
            count_now = page.locator(selector).count()
            if isinstance(count_now, int) and count_now > count_before:
                return True
        except Exception:
            continue
    return False


def _locator_first(locator):
    """Return `.first` if it exists, else the locator itself."""
    return getattr(locator, "first", locator)


def _first_text(el, selectors: list[str], *, timeout_ms: int = 200) -> str:
    for selector in selectors:
        try:
            locator = _locator_first(el.locator(selector))
            count = locator.count()
            if isinstance(count, int) and count <= 0:
                continue
            return locator.inner_text(timeout=timeout_ms).strip()
        except Exception:
            continue
    return ""


def _first_attr(el, selectors: list[str], attr: str) -> str:
    for selector in selectors:
        try:
            locator = _locator_first(el.locator(selector))
            count = locator.count()
            if isinstance(count, int) and count <= 0:
                continue
            value = locator.get_attribute(attr)
            if value:
                return value.strip()
        except Exception:
            continue
    return ""


def _extract_platform_id(el) -> str:
    """Extract LinkedIn platform_id from a card element."""
    entity_urn = el.get_attribute("data-entity-urn") or ""
    match = _JOB_ID_PATTERN.search(entity_urn)
    if match:
        return match.group(1)
    legacy_id = (el.get_attribute("data-occludable-job-id") or "").strip()
    if legacy_id:
        # some LinkedIn payloads expose the numeric id directly
        if legacy_id.isdigit():
            return legacy_id
    return ""


_JOB_DATE_SELECTORS = [
    "time[datetime]",
    "span.job-search-card__listdate",
    "span.job-search-card__listdate--new",
    "span[class*='listdate']",
    "time",
]


def _extract_posted_at(el) -> datetime | None:
    """Extract posted_at datetime from a job card element.

    Tries multiple selector strategies:
    1. time[datetime] attribute (ISO date)
    2. span.job-search-card__listdate (relative text like '2 days ago')
    3. Any element with class containing 'listdate'
    4. Bare <time> element inner text
    """
    # Strategy 1: time[datetime] attribute
    try:
        time_el = _locator_first(el.locator("time[datetime]"))
        count = time_el.count()
        if (not isinstance(count, int)) or count > 0:
            datetime_attr = time_el.get_attribute("datetime")
            result = parse_iso(datetime_attr)
            if result is not None:
                return result
    except Exception:
        pass

    # Strategy 2–3: text-based date selectors
    for selector in _JOB_DATE_SELECTORS[1:]:
        try:
            loc = _locator_first(el.locator(selector))
            count = loc.count()
            if isinstance(count, int) and count <= 0:
                continue
            label = loc.inner_text(timeout=200).strip()
            if label:
                result = parse_relative_date(label)
                if result is not None:
                    return result
        except Exception:
            continue

    # Strategy 4: bare <time> fallback
    try:
        any_time = _locator_first(el.locator("time"))
        any_count = any_time.count()
        if (not isinstance(any_count, int)) or any_count > 0:
            label = any_time.inner_text(timeout=900).strip()
            return parse_relative_date(label)
    except Exception:
        pass

    return None


def _extract_job_url(el) -> str:
    for selector in [
        "a.base-card__full-link",
        "a[href*='/jobs/view/']",
        "a[data-control-name='job_card_click']",
    ]:
        url = _first_attr(el, [selector], "href")
        if url:
            return f"https://www.linkedin.com{url}" if url.startswith("/") else url
    return ""


def _iter_job_cards(page):
    """Return all job card elements using the preferred selector chain."""
    selectors = [_JOB_CARD_SELECTOR, *_JOB_CARD_FALLBACKS]

    for selector in selectors:
        locator = page.locator(selector)

        # Playwright Locator.count() returns int; in tests it's mocked.
        try:
            count = locator.count()
            if isinstance(count, int) and count > 0:
                return locator.all()
        except Exception:
            pass

        try:
            elements = locator.all()
            if elements:
                return elements
        except Exception:
            continue

    return []


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_fetch(
    config: dict,
    limit: int,
    lookback: int,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Orchestrate the full fetch run.

    FR-03: Detect and recover from expired sessions.
    FR-04: Scroll to collect job cards.
    FR-11: Retry detail-page extraction.
    FR-13: Print summary on completion.
    """
    fetch_url: str = config["sources"]["linkedin"]["fetch_url"]
    print(
        f"Fetching LinkedIn recommended jobs (lookback={lookback}d, limit={limit})...",
        flush=True,
    )

    context, browser_inst, pw = browser.launch_context(str(SESSION_PATH))
    page = context.new_page()

    try:
        page.goto(fetch_url, wait_until="domcontentloaded", timeout=30_000)

        # FR-03: check session validity after navigation
        if not browser.is_session_valid(page):
            log_warn("Session expired. Re-authenticating...")
            context.close()
            browser_inst.close()
            pw.stop()

            success = auth.run_auth(config)
            if not success:
                print(
                    "Error: LinkedIn session expired and re-authentication failed. "
                    "Please run 'jobhunt auth' manually.",
                    file=sys.stderr,
                )
                sys.exit(1)

            context, browser_inst, pw = browser.launch_context(str(SESSION_PATH))
            page = context.new_page()
            page.goto(fetch_url, wait_until="domcontentloaded", timeout=30_000)

            if not browser.is_session_valid(page):
                print(
                    "Error: LinkedIn session expired and re-authentication failed. "
                    "Please run 'jobhunt auth' manually.",
                    file=sys.stderr,
                )
                sys.exit(1)

        # Wait for job cards to render (LinkedIn loads them via JS after DOM ready)
        try:
            for sel in [_JOB_CARD_SELECTOR, *_JOB_CARD_FALLBACKS]:
                try:
                    page.wait_for_selector(sel, timeout=8000)
                    break
                except Exception:
                    continue
        except Exception:
            pass  # scroll_loop will handle empty state

        # Collect all cards first so we know the total for verbose progress
        if verbose:
            log_info("Scrolling feed to collect job cards...")
        cards = list(scroll_loop(page, limit, lookback))
        total = len(cards)

        if verbose:
            log_info(f"Collected {total} job card(s). Processing...")

        stats = RunStats()
        conn = db_module.init_db(DB_PATH)

        try:
            for i, card in enumerate(cards, 1):
                # Skip if already in DB (platform_id dedup — Issue #17)
                if db_module.job_exists(conn, "linkedin", card.platform_id):
                    stats.skipped += 1
                    if verbose:
                        _print_verbose_line(i, total, "skipped", False, card)
                    continue

                result, is_repost = _fetch_with_retry(page, card, conn, dry_run)

                if result == "new":
                    stats.new += 1
                elif result == "updated":
                    stats.updated += 1
                elif result == "skipped":
                    stats.skipped += 1
                elif result == "error":
                    stats.errors += 1

                if verbose:
                    _print_verbose_line(i, total, result, is_repost, card)
        finally:
            conn.close()

    finally:
        context.close()
        browser_inst.close()
        pw.stop()

    if not dry_run:
        print_summary(stats)

    # Exit code 2 if every single job errored (NFR-02)
    if stats.all_failed:
        sys.exit(2)


# ---------------------------------------------------------------------------
# Scroll loop (FR-04, §4.2)
# ---------------------------------------------------------------------------


def scroll_loop(page, limit: int, lookback_days: int) -> Generator[JobCard, None, None]:
    """Page through the job feed, yielding JobCard objects within the lookback window.

    LinkedIn uses button-based pagination (not infinite scroll).
    Stops when:
      (a) All visible cards are older than lookback_days.
      (b) No "Next" button found (last page).
      (c) Total yielded reaches limit.
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    seen_ids: set[str] = set()
    cards_yielded = 0

    while cards_yielded < limit:
        # Wait for cards to render on current page
        try:
            for sel in [_JOB_CARD_SELECTOR, *_JOB_CARD_FALLBACKS]:
                try:
                    page.wait_for_selector(sel, timeout=5000)
                    break
                except Exception:
                    continue
        except Exception:
            pass

        # Collect all job card elements on current page
        card_elements = _iter_job_cards(page)

        if not card_elements:
            log_error(
                "LinkedIn DOM structure has changed — no job cards found. "
                "Please open a GitHub issue."
            )
            return

        new_this_page = 0
        all_too_old = True

        for el in card_elements:
            platform_id = _extract_platform_id(el)
            if not platform_id or platform_id in seen_ids:
                continue
            seen_ids.add(platform_id)
            new_this_page += 1

            # Parse posted_at from card (avoid unnecessary detail page visit)
            posted_at = _extract_posted_at(el)

            # Lookback cutoff check
            if posted_at and posted_at < cutoff_date:
                continue
            else:
                all_too_old = False

            title = clean_title(_first_text(
                el,
                _JOB_TITLE_SELECTORS,
            ))
            company = _first_text(
                el,
                _JOB_COMPANY_SELECTORS,
            )
            location = _first_text(
                el,
                _JOB_LOCATION_SELECTORS,
            )
            job_url = _extract_job_url(el)

            if not job_url:
                continue
            if not title:
                log_warn(f"Failed to extract title for {platform_id}")
                continue

            yield JobCard(
                platform_id=platform_id,
                title=title,
                company=company,
                location=location,
                posted_at=posted_at,
                job_url=job_url,
            )
            cards_yielded += 1
            if cards_yielded >= limit:
                return

        # All visible cards are beyond lookback window → stop
        if all_too_old and new_this_page > 0:
            return

        # No new cards on this page (all seen) — still try next page
        # but if we got zero new IDs, something is wrong
        if new_this_page == 0:
            return

        # Click "Next" button to go to next page
        next_btn = page.locator('button[aria-label="Next"]')
        try:
            if next_btn.count() == 0 or not next_btn.is_enabled():
                return  # Last page
        except Exception:
            return

        try:
            next_btn.click(timeout=3000)
            # Wait for page transition — cards should refresh
            page.wait_for_timeout(2000)
        except Exception:
            return  # Click failed, stop


# ---------------------------------------------------------------------------
# Per-job fetch with retry (FR-11)
# ---------------------------------------------------------------------------


def _fetch_with_retry(
    page,
    card: JobCard,
    conn: sqlite3.Connection,
    dry_run: bool,
) -> tuple[str, bool]:
    """Navigate to the job detail page, extract JD, and upsert.

    Retries up to 3 times (2 s backoff) on PlaywrightTimeoutError or
    ExtractionError. Returns ('error', False) after exhausting retries.

    Also checks session validity mid-fetch (FR-03).
    """
    for attempt in range(3):
        try:
            page.goto(card.job_url, wait_until="domcontentloaded", timeout=15_000)

            # Mid-fetch session check (FR-03)
            if not browser.is_session_valid(page):
                raise ExtractionError(
                    f"Session expired while loading {card.job_url}"
                )

            jd_text = extractor.extract_jd(page)
            jd_hash = extractor.compute_hash(jd_text)

            # Random 1–3 s delay between detail page navigations (§5.1)
            time.sleep(random.uniform(1, 3))

            return db_module.upsert_job(conn, card, jd_text, jd_hash, dry_run)

        except (PlaywrightTimeoutError, ExtractionError) as exc:
            if attempt < 2:
                log_warn(f"Retry {attempt + 1}/3 for {card.platform_id}: {exc}")
                time.sleep(2)
            else:
                log_warn(
                    f"WARN: skipped \"{card.title}\" after 3 retries: {exc}"
                )
                return "error", False

        except Exception as exc:
            log_error(f"Unexpected error for {card.platform_id}: {exc}")
            return "error", False

    return "error", False  # unreachable but makes type checkers happy


# ---------------------------------------------------------------------------
# Verbose output and summary (FR-13)
# ---------------------------------------------------------------------------

_RESULT_LABELS = {
    "new": "saved",
    "updated": "updated",
    "skipped": "skipped",
    "error": "error",
}

_RESULT_ANNOTATIONS = {
    "skipped": "  (duplicate: platform_id)",
}


def _print_verbose_line(
    i: int,
    total: int,
    result: str,
    is_repost: bool,
    card: JobCard,
) -> None:
    """Print a per-job status line to stderr (system-design §7)."""
    label = _RESULT_LABELS.get(result, result)
    annotation = _RESULT_ANNOTATIONS.get(result, "")
    print(
        f'  [{i}/{total}] {label:<7} "{card.title}" @ {card.company}{annotation}',
        file=sys.stderr,
    )
    if is_repost and result == "new":
        print(
            f'  note: possible repost detected "{card.title}" @ {card.company}',
            file=sys.stderr,
        )


def print_summary(stats: RunStats) -> None:
    """Print the one-line run summary to stdout (FR-13)."""
    print(
        f"✓ Run complete: {stats.new} new, {stats.updated} updated, "
        f"{stats.skipped} skipped, {stats.errors} errors"
    )
