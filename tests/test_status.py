"""Tests for Phase 2a status transitions, job notes, and list --status filter."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from jobhunt.db import (
    ALLOWED_TRANSITIONS,
    append_job_note,
    get_job,
    get_job_notes,
    init_db,
    query_jobs,
    set_job_status,
    upsert_job,
)
from jobhunt.models import JobCard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_card(platform_id: str = "1234567890") -> JobCard:
    return JobCard(
        platform_id=platform_id,
        title="Senior Backend Engineer",
        company="Stripe",
        location="San Francisco, CA",
        posted_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
        job_url=f"https://www.linkedin.com/jobs/view/{platform_id}/",
    )


def _seed_job(conn: sqlite3.Connection, platform_id: str = "1234567890", status: str = "new") -> int:
    """Insert one job and return its id."""
    card = _make_card(platform_id)
    upsert_job(conn, card, "Full job description text.", "hashxyz")
    row = conn.execute(
        "SELECT id FROM jobs WHERE platform_id = ?", (platform_id,)
    ).fetchone()
    job_id = row[0]
    if status != "new":
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        conn.commit()
    return job_id


# ---------------------------------------------------------------------------
# set_job_status — valid transitions
# ---------------------------------------------------------------------------


class TestSetJobStatusValid:
    """FR-29: Test all allowed transitions."""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            ("new", "skipped"),
            ("new", "tailored"),
            ("tailored", "blocked"),
            ("tailored", "apply_failed"),
            ("tailored", "applied"),
            ("blocked", "tailored"),
            ("blocked", "applied"),
            ("apply_failed", "applied"),
        ],
    )
    def test_valid_transition(self, tmp_db, from_status, to_status):
        job_id = _seed_job(tmp_db, status=from_status)
        set_job_status(tmp_db, job_id, to_status)
        job = get_job(tmp_db, job_id)
        assert job["status"] == to_status
        assert job["status_updated_at"] is not None

    def test_status_updated_at_changes(self, tmp_db):
        job_id = _seed_job(tmp_db, status="new")
        job_before = get_job(tmp_db, job_id)
        # Mock utcnow_iso to return a distinct timestamp
        with patch("jobhunt.db.utcnow_iso", return_value="2099-01-01T00:00:00Z"):
            set_job_status(tmp_db, job_id, "tailored")
        job_after = get_job(tmp_db, job_id)
        assert job_after["status_updated_at"] == "2099-01-01T00:00:00Z"
        assert job_after["status_updated_at"] != job_before.get("status_updated_at")


# ---------------------------------------------------------------------------
# set_job_status — invalid transitions
# ---------------------------------------------------------------------------


class TestSetJobStatusInvalid:
    """FR-29: Test that invalid transitions are rejected."""

    @pytest.mark.parametrize(
        "from_status,to_status",
        [
            ("new", "blocked"),
            ("new", "applied"),
            ("new", "apply_failed"),
            ("skipped", "new"),
            ("skipped", "tailored"),
            ("tailored", "new"),
            ("tailored", "skipped"),
            ("blocked", "skipped"),
            ("applied", "new"),
            ("applied", "tailored"),
            ("apply_failed", "new"),
            ("apply_failed", "tailored"),
        ],
    )
    def test_invalid_transition_raises(self, tmp_db, from_status, to_status):
        job_id = _seed_job(tmp_db, status=from_status)
        with pytest.raises(ValueError, match="Invalid transition"):
            set_job_status(tmp_db, job_id, to_status)
        # Status should be unchanged
        job = get_job(tmp_db, job_id)
        assert job["status"] == from_status

    def test_nonexistent_job_raises(self, tmp_db):
        with pytest.raises(LookupError, match="not found"):
            set_job_status(tmp_db, 99999, "tailored")


# ---------------------------------------------------------------------------
# set_job_status with notes (FR-30)
# ---------------------------------------------------------------------------


class TestSetJobStatusWithNote:
    def test_transition_with_note(self, tmp_db):
        job_id = _seed_job(tmp_db, status="tailored")
        set_job_status(tmp_db, job_id, "blocked", note="Waiting for recruiter")
        job = get_job(tmp_db, job_id)
        assert job["status"] == "blocked"

        notes = get_job_notes(tmp_db, job_id)
        assert len(notes) == 1
        assert notes[0].status_after == "blocked"
        assert notes[0].content == "Waiting for recruiter"
        assert notes[0].source == "cli"

    def test_transition_without_note_writes_no_note(self, tmp_db):
        job_id = _seed_job(tmp_db, status="new")
        set_job_status(tmp_db, job_id, "tailored")
        notes = get_job_notes(tmp_db, job_id)
        assert len(notes) == 0

    def test_multiple_notes_appended(self, tmp_db):
        job_id = _seed_job(tmp_db, status="new")
        set_job_status(tmp_db, job_id, "tailored", note="First tailor")
        set_job_status(tmp_db, job_id, "blocked", note="Blocked by requirement")
        set_job_status(tmp_db, job_id, "tailored", note="Re-tailored")

        notes = get_job_notes(tmp_db, job_id)
        assert len(notes) == 3
        assert notes[0].status_after == "tailored"
        assert notes[1].status_after == "blocked"
        assert notes[2].status_after == "tailored"


# ---------------------------------------------------------------------------
# append_job_note directly
# ---------------------------------------------------------------------------


class TestAppendJobNote:
    def test_append_note(self, tmp_db):
        job_id = _seed_job(tmp_db)
        append_job_note(tmp_db, job_id, "new", "Test note", "cli")
        tmp_db.commit()

        notes = get_job_notes(tmp_db, job_id)
        assert len(notes) == 1
        assert notes[0].content == "Test note"
        assert notes[0].source == "cli"

    def test_custom_source(self, tmp_db):
        job_id = _seed_job(tmp_db)
        append_job_note(tmp_db, job_id, "new", "Auto note", "tailor")
        tmp_db.commit()

        notes = get_job_notes(tmp_db, job_id)
        assert notes[0].source == "tailor"


# ---------------------------------------------------------------------------
# query_jobs with status filter (FR-31)
# ---------------------------------------------------------------------------


def _seed_mixed_status_jobs(conn: sqlite3.Connection) -> None:
    """Insert jobs with various statuses for filter tests."""
    jobs = [
        ("1111", "new"),
        ("2222", "new"),
        ("3333", "tailored"),
        ("4444", "blocked"),
        ("5555", "applied"),
        ("6666", "apply_failed"),
    ]
    for pid, status in jobs:
        card = _make_card(pid)
        upsert_job(conn, card, f"JD for {pid}", f"hash_{pid}")
        if status != "new":
            conn.execute(
                "UPDATE jobs SET status = ? WHERE platform_id = ?",
                (status, pid),
            )
    conn.commit()


class TestQueryJobsStatusFilter:
    def test_single_status(self, tmp_db):
        _seed_mixed_status_jobs(tmp_db)
        rows = query_jobs(tmp_db, status="new")
        assert all(r["status"] == "new" for r in rows)
        assert len(rows) == 2

    def test_multiple_statuses_comma_separated(self, tmp_db):
        _seed_mixed_status_jobs(tmp_db)
        rows = query_jobs(tmp_db, status="blocked,apply_failed")
        statuses = {r["status"] for r in rows}
        assert statuses == {"blocked", "apply_failed"}
        assert len(rows) == 2

    def test_multiple_statuses_as_list(self, tmp_db):
        _seed_mixed_status_jobs(tmp_db)
        rows = query_jobs(tmp_db, status=["blocked", "apply_failed"])
        statuses = {r["status"] for r in rows}
        assert statuses == {"blocked", "apply_failed"}

    def test_no_filter_returns_all(self, tmp_db):
        _seed_mixed_status_jobs(tmp_db)
        rows = query_jobs(tmp_db)
        assert len(rows) == 6

    def test_nonexistent_status_returns_empty(self, tmp_db):
        _seed_mixed_status_jobs(tmp_db)
        rows = query_jobs(tmp_db, status="skipped")
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# CLI integration: jobhunt status
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_valid_transition_via_cli(self, tmp_path):
        from click.testing import CliRunner
        from jobhunt.cli import main

        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        conn = init_db(db_path)
        job_id = _seed_job(conn, status="new")
        conn.close()

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["status", str(job_id), "--set", "tailored"])

        assert result.exit_code == 0
        assert "tailored" in result.output

    def test_invalid_transition_via_cli(self, tmp_path):
        from click.testing import CliRunner
        from jobhunt.cli import main

        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        conn = init_db(db_path)
        job_id = _seed_job(conn, status="new")
        conn.close()

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["status", str(job_id), "--set", "applied"])

        assert result.exit_code == 1

    def test_status_with_note_via_cli(self, tmp_path):
        from click.testing import CliRunner
        from jobhunt.cli import main

        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        conn = init_db(db_path)
        job_id = _seed_job(conn, status="tailored")
        conn.close()

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(
                main, ["status", str(job_id), "--set", "blocked", "--note", "Waiting"]
            )

        assert result.exit_code == 0

        conn = init_db(db_path)
        notes = get_job_notes(conn, job_id)
        conn.close()
        assert len(notes) == 1
        assert notes[0].content == "Waiting"

    def test_nonexistent_job_via_cli(self, tmp_path):
        from click.testing import CliRunner
        from jobhunt.cli import main

        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["status", "99999", "--set", "tailored"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "not found" in (result.stderr or "")


# ---------------------------------------------------------------------------
# CLI integration: jobhunt list --status
# ---------------------------------------------------------------------------


class TestListStatusFilter:
    def test_list_single_status(self, tmp_path):
        from click.testing import CliRunner
        from jobhunt.cli import main

        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        conn = init_db(db_path)
        _seed_mixed_status_jobs(conn)
        conn.close()

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["list", "--status", "tailored", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(j["status"] == "tailored" for j in data)

    def test_list_multiple_statuses(self, tmp_path):
        from click.testing import CliRunner
        from jobhunt.cli import main

        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        conn = init_db(db_path)
        _seed_mixed_status_jobs(conn)
        conn.close()

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["list", "--status", "blocked,apply_failed", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        statuses = {j["status"] for j in data}
        assert statuses == {"blocked", "apply_failed"}

    def test_list_invalid_status_rejected(self, tmp_path):
        from click.testing import CliRunner
        from jobhunt.cli import main

        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["list", "--status", "invalid_status"])

        assert result.exit_code == 1
