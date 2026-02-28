"""Tests for db.py: schema init, upsert branches, query filters."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.db import get_job, init_db, job_exists, query_jobs, upsert_job
from scripts.models import JobCard
from scripts.utils import utcnow_iso


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------


class TestInitDb:
    def test_creates_file(self, tmp_path: Path):
        db_path = tmp_path / "jobs.db"
        conn = init_db(db_path)
        conn.close()
        assert db_path.exists()

    def test_creates_jobs_table(self, tmp_db: sqlite3.Connection):
        cursor = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        )
        assert cursor.fetchone() is not None

    def test_creates_job_notes_table(self, tmp_db: sqlite3.Connection):
        cursor = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='job_notes'"
        )
        assert cursor.fetchone() is not None

    def test_creates_status_index(self, tmp_db: sqlite3.Connection):
        cursor = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_jobs_status'"
        )
        assert cursor.fetchone() is not None

    def test_creates_fetched_at_index(self, tmp_db: sqlite3.Connection):
        cursor = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_jobs_fetched_at'"
        )
        assert cursor.fetchone() is not None

    def test_creates_status_updated_at_index(self, tmp_db: sqlite3.Connection):
        cursor = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_jobs_status_updated_at'"
        )
        assert cursor.fetchone() is not None

    def test_creates_job_notes_index(self, tmp_db: sqlite3.Connection):
        cursor = tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_job_notes_job_id_created_at'"
        )
        assert cursor.fetchone() is not None

    def test_idempotent(self, tmp_path: Path):
        db_path = tmp_path / "jobs.db"
        conn1 = init_db(db_path)
        conn1.close()
        conn2 = init_db(db_path)
        conn2.close()  # should not raise

    def test_creates_parent_dirs(self, tmp_path: Path):
        db_path = tmp_path / "nested" / "dir" / "jobs.db"
        conn = init_db(db_path)
        conn.close()
        assert db_path.exists()


# ---------------------------------------------------------------------------
# upsert_job — branch A: existing platform_id → always skip (#17)
# ---------------------------------------------------------------------------


class TestUpsertJobBranchA:
    """Existing platform_id → always skipped, regardless of jd_hash."""

    def test_returns_skipped_same_hash(self, tmp_db, sample_card):
        upsert_job(tmp_db, sample_card, "Some job description", "aaa")

        result, is_repost = upsert_job(tmp_db, sample_card, "Some job description", "aaa")
        assert result == "skipped"
        assert is_repost is False

    def test_returns_skipped_different_hash(self, tmp_db, sample_card):
        """Issue #17: even if jd_hash differs, existing platform_id → skipped."""
        upsert_job(tmp_db, sample_card, "original jd", "aaa")
        result, is_repost = upsert_job(tmp_db, sample_card, "new jd content", "bbb")
        assert result == "skipped"
        assert is_repost is False

    def test_no_db_write(self, tmp_db, sample_card):
        upsert_job(tmp_db, sample_card, "Some job description", "aaa")

        count_before = tmp_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        upsert_job(tmp_db, sample_card, "Some job description", "aaa")
        count_after = tmp_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

        assert count_before == count_after == 1

    def test_jd_not_updated_on_duplicate(self, tmp_db, sample_card):
        """Issue #17: original jd_text preserved when platform_id exists."""
        upsert_job(tmp_db, sample_card, "original jd", "aaa")
        upsert_job(tmp_db, sample_card, "new jd content", "bbb")

        row = tmp_db.execute(
            "SELECT jd_text, jd_hash FROM jobs WHERE platform_id = ?",
            (sample_card.platform_id,),
        ).fetchone()
        assert row["jd_text"] == "original jd"
        assert row["jd_hash"] == "aaa"


# ---------------------------------------------------------------------------
# upsert_job — branch B: new platform_id → insert
# ---------------------------------------------------------------------------


class TestUpsertJobBranchB:
    """TC-10: fresh DB → new row inserted with status='new'."""

    def test_returns_new(self, tmp_db, sample_card):
        result, is_repost = upsert_job(tmp_db, sample_card, "jd text", "aaa")
        assert result == "new"
        assert is_repost is False

    def test_row_inserted(self, tmp_db, sample_card):
        upsert_job(tmp_db, sample_card, "jd text", "aaa")
        row = tmp_db.execute(
            "SELECT * FROM jobs WHERE platform_id = ?",
            (sample_card.platform_id,),
        ).fetchone()
        assert row is not None
        assert row["status"] == "new"
        assert row["updated_at"] is None
        assert row["fetched_at"] is not None
        assert row["status_updated_at"] is not None

    def test_posted_at_stored(self, tmp_db, sample_card):
        upsert_job(tmp_db, sample_card, "jd text", "aaa")
        row = tmp_db.execute(
            "SELECT posted_at FROM jobs WHERE platform_id = ?",
            (sample_card.platform_id,),
        ).fetchone()
        assert row["posted_at"] == "2026-02-20"

    def test_dry_run_does_not_insert(self, tmp_db, sample_card, capsys):
        result, _ = upsert_job(tmp_db, sample_card, "jd text", "aaa", dry_run=True)
        assert result == "new"
        count = tmp_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 0
        captured = capsys.readouterr()
        # Should have printed JSON to stdout
        import json
        data = json.loads(captured.out.strip())
        assert data["platform_id"] == sample_card.platform_id


# ---------------------------------------------------------------------------
# upsert_job — branch B: same jd_hash, different platform_id (#17)
# ---------------------------------------------------------------------------


class TestUpsertJobSameHashDifferentId:
    """Issue #17: no repost detection — just insert both."""

    def test_returns_new_no_repost_flag(self, tmp_db, sample_card, sample_card_2):
        upsert_job(tmp_db, sample_card, "jd text", "ccc")
        result, is_repost = upsert_job(tmp_db, sample_card_2, "jd text", "ccc")
        assert result == "new"
        assert is_repost is False

    def test_both_rows_exist(self, tmp_db, sample_card, sample_card_2):
        upsert_job(tmp_db, sample_card, "jd text", "ccc")
        upsert_job(tmp_db, sample_card_2, "jd text", "ccc")
        count = tmp_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        assert count == 2


# ---------------------------------------------------------------------------
# job_exists (#17)
# ---------------------------------------------------------------------------


class TestJobExists:
    def test_returns_false_when_empty(self, tmp_db):
        assert job_exists(tmp_db, "linkedin", "9999999999") is False

    def test_returns_true_after_insert(self, tmp_db, sample_card):
        upsert_job(tmp_db, sample_card, "jd text", "hash1")
        assert job_exists(tmp_db, "linkedin", sample_card.platform_id) is True

    def test_returns_false_for_different_id(self, tmp_db, sample_card):
        upsert_job(tmp_db, sample_card, "jd text", "hash1")
        assert job_exists(tmp_db, "linkedin", "0000000000") is False


# ---------------------------------------------------------------------------
# query_jobs
# ---------------------------------------------------------------------------


def _seed_jobs(conn: sqlite3.Connection) -> None:
    """Insert a variety of jobs for filter/sort tests.

    Uses Phase 2a canonical status values.
    """
    jobs = [
        ("1111111111", "Backend Engineer", "Stripe", "SF, CA", "2026-02-20", "new"),
        ("2222222222", "Frontend Engineer", "Google", "NY, NY", "2026-02-15", "tailored"),
        ("3333333333", "Staff Engineer", "Stripe", "Remote", "2026-02-10", "applied"),
        ("4444444444", "DevOps Engineer", "Meta", "Seattle, WA", "2026-02-05", "new"),
        ("5555555555", "Data Scientist", "OpenAI", "SF, CA", "2026-01-30", "skipped"),
    ]
    for pid, title, company, location, posted, status in jobs:
        conn.execute(
            """INSERT INTO jobs
               (platform, platform_id, title, company, location, posted_at,
                job_url, jd_text, jd_hash, status, fetched_at, updated_at, status_updated_at)
               VALUES ('linkedin', ?, ?, ?, ?, ?,
                       'https://example.com', 'desc', 'hash', ?, '2026-02-25T10:00:00Z', NULL, '2026-02-25T10:00:00Z')""",
            (pid, title, company, location, posted, status),
        )
    conn.commit()


class TestQueryJobs:
    def test_returns_all_when_no_filters(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db)
        assert len(rows) == 5

    def test_filter_by_status_single(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, status="new")
        assert all(r["status"] == "new" for r in rows)
        assert len(rows) == 2

    def test_filter_by_status_multiple(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, status="new,tailored")
        statuses = {r["status"] for r in rows}
        assert statuses == {"new", "tailored"}
        assert len(rows) == 3

    def test_filter_by_company_case_insensitive(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, company="stripe")
        assert len(rows) == 2
        assert all("Stripe" in r["company"] for r in rows)

    def test_filter_by_title_substring(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, title="engineer")
        assert len(rows) == 4

    def test_filter_by_location(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, location="SF")
        assert len(rows) == 2

    def test_limit(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, limit=2)
        assert len(rows) == 2

    def test_sort_ascending(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, sort="posted_at")
        dates = [r["posted_at"] for r in rows]
        assert dates == sorted(dates)

    def test_sort_descending(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, sort="-posted_at")
        dates = [r["posted_at"] for r in rows]
        assert dates == sorted(dates, reverse=True)

    def test_empty_result(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, company="nonexistent_company_xyz")
        assert rows == []

    def test_combined_filters(self, tmp_db):
        _seed_jobs(tmp_db)
        rows = query_jobs(tmp_db, status="new", company="stripe")
        assert len(rows) == 1
        assert rows[0]["company"] == "Stripe"


# ---------------------------------------------------------------------------
# get_job
# ---------------------------------------------------------------------------


class TestGetJob:
    def test_returns_job_when_found(self, tmp_db, sample_card):
        upsert_job(tmp_db, sample_card, "jd text", "hash1")
        row = tmp_db.execute("SELECT id FROM jobs").fetchone()
        job_id = row[0]

        job = get_job(tmp_db, job_id)
        assert job is not None
        assert job["platform_id"] == sample_card.platform_id
        assert job["title"] == sample_card.title

    def test_returns_none_when_not_found(self, tmp_db):
        job = get_job(tmp_db, 99999)
        assert job is None

    def test_includes_all_fields(self, tmp_db, sample_card):
        upsert_job(tmp_db, sample_card, "full jd text here", "hash1")
        row = tmp_db.execute("SELECT id FROM jobs").fetchone()
        job = get_job(tmp_db, row[0])

        expected_keys = {
            "id", "platform", "platform_id", "title", "company", "location",
            "posted_at", "job_url", "jd_text", "jd_hash", "status",
            "fetched_at", "updated_at", "status_updated_at",
        }
        assert set(job.keys()) == expected_keys
        assert job["jd_text"] == "full jd text here"
