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

_JOB_CARD_SELECTOR = ".job-search-card"
_JOB_ID_PATTERN = re.compile(r"jobPosting:(\d+)")
_JOB_CARD_FALLBACKS = ["li[data-occludable-job-id]", "div.job-card-container"]

_MAX_EMPTY_SCROLLS = 5  # consecutive empty scrolls before assuming end-of-feed

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
    """Scroll the job feed, yielding JobCard objects within the lookback window.

    Stops when:
      (a) All visible cards are older than lookback_days.
      (b) No new cards appear after MAX_EMPTY_SCROLLS consecutive scrolls.
      (c) Total yielded reaches limit.
    """
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    seen_ids: set[str] = set()
    cards_yielded = 0
    no_new_cards_streak = 0

    while cards_yielded < limit:
        # Collect all currently visible job card elements
        card_elements = page.locator(_JOB_CARD_SELECTOR).all()

        # Fallback selectors if primary yields nothing
        if not card_elements:
            for fallback in _JOB_CARD_FALLBACKS:
                card_elements = page.locator(fallback).all()
                if card_elements:
                    break
            if not card_elements:
                log_error(
                    "LinkedIn DOM structure has changed — no job cards found. "
                    "Please open a GitHub issue."
                )
                return

        new_this_scroll = 0
        all_too_old = True

        for el in card_elements:
            # Extract platform_id from data-entity-urn
            entity_urn = el.get_attribute("data-entity-urn") or ""
            m = _JOB_ID_PATTERN.search(entity_urn)
            if not m:
                # Try data-occludable-job-id fallback
                job_id_attr = el.get_attribute("data-occludable-job-id") or ""
                if not job_id_attr:
                    continue
                platform_id = job_id_attr.strip()
            else:
                platform_id = m.group(1)

            if platform_id in seen_ids:
                continue
            seen_ids.add(platform_id)
            new_this_scroll += 1

            # Parse posted_at from card (avoid unnecessary detail page visit)
            time_el = el.locator("time[datetime]").first
            if time_el.count() > 0:
                datetime_attr = time_el.get_attribute("datetime")
                posted_at = parse_iso(datetime_attr)
            else:
                any_time = el.locator("time").first
                label = any_time.inner_text() if any_time.count() > 0 else ""
                posted_at = parse_relative_date(label)

            # Lookback cutoff check
            if posted_at and posted_at < cutoff_date:
                continue  # too old — skip but don't stop yet
            else:
                all_too_old = False

            # Extract card fields (verified selectors §4.2)
            try:
                title = el.locator(".base-search-card__title").inner_text().strip()
                company = el.locator(".base-search-card__subtitle").inner_text().strip()
                location = el.locator(".job-search-card__location").inner_text().strip()
                job_url = el.locator("a.base-card__full-link").get_attribute("href") or ""
            except Exception as exc:
                log_warn(f"Failed to extract card fields for {platform_id}: {exc}")
                continue

            if not job_url:
                continue
            if job_url.startswith("/"):
                job_url = f"https://www.linkedin.com{job_url}"

            if not title or not company:
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

        # End-of-feed detection
        if new_this_scroll == 0:
            no_new_cards_streak += 1
            if no_new_cards_streak >= _MAX_EMPTY_SCROLLS:
                return
        else:
            no_new_cards_streak = 0

        # All visible cards are beyond lookback window → stop
        if all_too_old and new_this_scroll > 0:
            return

        # Scroll down to trigger lazy-load
        page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        page.wait_for_timeout(1_500)


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
    "updated": "  (JD changed)",
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
