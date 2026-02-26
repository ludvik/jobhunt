"""Tests for fetcher.py: dedup integration, retry logic, dry-run, summary."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, call, patch

import pytest

from jobhunt.db import init_db, upsert_job
from jobhunt.fetcher import _fetch_with_retry, print_summary, scroll_loop
from jobhunt.models import ExtractionError, JobCard, RunStats


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    def test_format(self, capsys):
        stats = RunStats(new=10, updated=2, skipped=3, errors=0)
        print_summary(stats)
        captured = capsys.readouterr()
        assert "10 new" in captured.out
        assert "2 updated" in captured.out
        assert "3 skipped" in captured.out
        assert "0 errors" in captured.out

    def test_zero_stats(self, capsys):
        print_summary(RunStats())
        captured = capsys.readouterr()
        assert "0 new" in captured.out


# ---------------------------------------------------------------------------
# RunStats helpers
# ---------------------------------------------------------------------------


class TestRunStats:
    def test_total_processed(self):
        s = RunStats(new=5, updated=1, skipped=3, errors=2)
        assert s.total_processed == 11

    def test_all_failed_true(self):
        s = RunStats(new=0, updated=0, skipped=0, errors=3)
        assert s.all_failed is True

    def test_all_failed_false_with_successes(self):
        s = RunStats(new=1, updated=0, skipped=0, errors=2)
        assert s.all_failed is False

    def test_all_failed_false_when_empty(self):
        s = RunStats()
        assert s.all_failed is False


# ---------------------------------------------------------------------------
# _fetch_with_retry
# ---------------------------------------------------------------------------


class TestFetchWithRetry:
    def _make_card(self, platform_id="1111111111"):
        return JobCard(
            platform_id=platform_id,
            title="Test Job",
            company="Test Co",
            location="Remote",
            posted_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
            job_url=f"https://www.linkedin.com/jobs/view/{platform_id}/",
        )

    def test_success_returns_new(self, tmp_db):
        card = self._make_card()
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/1111111111/"

        with (
            patch("jobhunt.fetcher.browser.is_session_valid", return_value=True),
            patch("jobhunt.fetcher.extractor.extract_jd", return_value="jd text"),
            patch("jobhunt.fetcher.extractor.compute_hash", return_value="hash1"),
            patch("time.sleep"),
        ):
            result, is_repost = _fetch_with_retry(page, card, tmp_db, dry_run=False)

        assert result == "new"
        assert is_repost is False

    def test_success_skipped_on_duplicate(self, tmp_db, sample_card):
        """Existing platform_id with same hash → skipped."""
        upsert_job(tmp_db, sample_card, "jd text", "hash1")

        page = MagicMock()
        page.url = sample_card.job_url

        with (
            patch("jobhunt.fetcher.browser.is_session_valid", return_value=True),
            patch("jobhunt.fetcher.extractor.extract_jd", return_value="jd text"),
            patch("jobhunt.fetcher.extractor.compute_hash", return_value="hash1"),
            patch("time.sleep"),
        ):
            result, _ = _fetch_with_retry(page, sample_card, tmp_db, dry_run=False)

        assert result == "skipped"

    def test_retries_on_timeout(self, tmp_db):
        """FR-11: retries up to 3 times on PlaywrightTimeoutError."""
        card = self._make_card()
        page = MagicMock()

        from playwright.sync_api import TimeoutError as PwTimeout

        call_count = {"n": 0}

        def flaky_goto(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise PwTimeout("timeout")

        page.goto.side_effect = flaky_goto
        page.url = "https://www.linkedin.com/jobs/view/1111111111/"

        with (
            patch("jobhunt.fetcher.browser.is_session_valid", return_value=True),
            patch("jobhunt.fetcher.extractor.extract_jd", return_value="jd text"),
            patch("jobhunt.fetcher.extractor.compute_hash", return_value="hash1"),
            patch("time.sleep"),
        ):
            result, _ = _fetch_with_retry(page, card, tmp_db, dry_run=False)

        assert result == "new"
        assert call_count["n"] == 3

    def test_returns_error_after_3_failures(self, tmp_db):
        """FR-11: all 3 retries exhausted → error."""
        card = self._make_card()
        page = MagicMock()

        from playwright.sync_api import TimeoutError as PwTimeout
        page.goto.side_effect = PwTimeout("persistent timeout")

        with patch("time.sleep"):
            result, is_repost = _fetch_with_retry(page, card, tmp_db, dry_run=False)

        assert result == "error"
        assert is_repost is False

    def test_retries_on_extraction_error(self, tmp_db):
        """ExtractionError also triggers retry."""
        card = self._make_card()
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/1111111111/"

        call_count = {"n": 0}

        def flaky_extract(p):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ExtractionError("bad selector")
            return "recovered jd text"

        with (
            patch("jobhunt.fetcher.browser.is_session_valid", return_value=True),
            patch("jobhunt.fetcher.extractor.extract_jd", side_effect=flaky_extract),
            patch("jobhunt.fetcher.extractor.compute_hash", return_value="hash1"),
            patch("time.sleep"),
        ):
            result, _ = _fetch_with_retry(page, card, tmp_db, dry_run=False)

        assert result == "new"

    def test_dry_run_does_not_write_db(self, tmp_db):
        card = self._make_card()
        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/1111111111/"

        with (
            patch("jobhunt.fetcher.browser.is_session_valid", return_value=True),
            patch("jobhunt.fetcher.extractor.extract_jd", return_value="jd text"),
            patch("jobhunt.fetcher.extractor.compute_hash", return_value="hash1"),
            patch("time.sleep"),
        ):
            result, _ = _fetch_with_retry(page, card, tmp_db, dry_run=True)

        assert result == "new"
        count = tmp_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 0


# ---------------------------------------------------------------------------
# scroll_loop — stop conditions
# ---------------------------------------------------------------------------


def _make_element(platform_id: str, posted_at: str, title: str = "Test Job", company: str = "TestCo"):
    """Build a mock element that looks like a LinkedIn job card."""
    el = MagicMock()

    # data-entity-urn
    el.get_attribute.return_value = f"urn:li:jobPosting:{platform_id}"

    # time[datetime]
    # .first is a Playwright Locator property — make it return itself so
    # el.locator("time[datetime]").first.count() correctly returns 1.
    time_el = MagicMock()
    time_el.count.return_value = 1
    time_el.get_attribute.return_value = posted_at
    time_el.first = time_el  # .first returns the same mock

    # other fields
    title_el = MagicMock()
    title_el.inner_text.return_value = title
    company_el = MagicMock()
    company_el.inner_text.return_value = company
    location_el = MagicMock()
    location_el.inner_text.return_value = "Remote"
    link_el = MagicMock()
    link_el.get_attribute.return_value = f"https://www.linkedin.com/jobs/view/{platform_id}/"

    def mock_locator(selector):
        if "time[datetime]" in selector:
            return time_el
        if "base-search-card__title" in selector:
            return title_el
        if "base-search-card__subtitle" in selector:
            return company_el
        if "job-search-card__location" in selector:
            return location_el
        if "base-card__full-link" in selector:
            return link_el
        m = MagicMock()
        m.count.return_value = 0
        return m

    el.locator.side_effect = mock_locator
    return el


class TestScrollLoop:
    def _make_page(self, elements_per_scroll: list[list]):
        """Return a page mock that serves different element lists per scroll call."""
        page = MagicMock()
        scroll_calls = {"n": 0}

        def mock_all():
            idx = min(scroll_calls["n"], len(elements_per_scroll) - 1)
            scroll_calls["n"] += 1
            return elements_per_scroll[idx]

        cards_locator = MagicMock()
        cards_locator.all.side_effect = mock_all
        page.locator.return_value = cards_locator
        page.evaluate = MagicMock()
        page.wait_for_timeout = MagicMock()
        return page

    def test_respects_limit(self):
        today = datetime.now(timezone.utc).date().isoformat()
        elements = [_make_element(str(i), today) for i in range(10)]
        page = self._make_page([elements] * 3)

        cards = list(scroll_loop(page, limit=3, lookback_days=30))
        assert len(cards) == 3

    def test_stops_at_end_of_feed(self):
        today = datetime.now(timezone.utc).date().isoformat()
        elements = [_make_element("111", today)]
        # After initial batch, no new cards appear (empty scrolls)
        page = self._make_page([elements] + [[]] * 10)

        cards = list(scroll_loop(page, limit=100, lookback_days=30))
        assert len(cards) == 1

    def test_skips_old_cards(self):
        today = datetime.now(timezone.utc).date().isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=60)).date().isoformat()

        elements = [
            _make_element("111", today),
            _make_element("222", old),
        ]
        page = self._make_page([elements] + [[]] * 10)

        cards = list(scroll_loop(page, limit=100, lookback_days=30))
        assert len(cards) == 1
        assert cards[0].platform_id == "111"

    def test_deduplicates_seen_ids(self):
        today = datetime.now(timezone.utc).date().isoformat()
        elements = [_make_element("111", today)]
        # Same elements appear twice (as if scroll didn't load new ones)
        page = self._make_page([elements, elements] + [[]] * 10)

        cards = list(scroll_loop(page, limit=100, lookback_days=30))
        assert len(cards) == 1

    def test_logs_error_when_no_selectors_match(self, capsys):
        page = MagicMock()
        page.evaluate = MagicMock()
        page.wait_for_timeout = MagicMock()

        empty_loc = MagicMock()
        empty_loc.all.return_value = []
        page.locator.return_value = empty_loc

        cards = list(scroll_loop(page, limit=10, lookback_days=30))
        assert cards == []
        captured = capsys.readouterr()
        assert "DOM structure has changed" in captured.err
