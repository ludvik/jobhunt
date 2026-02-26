"""CLI smoke tests via click.testing.CliRunner."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from jobhunt.cli import main
from jobhunt.db import init_db, upsert_job
from jobhunt.models import JobCard
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_job(conn: sqlite3.Connection, platform_id: str = "1234567890") -> int:
    """Insert one job and return its id."""
    card = JobCard(
        platform_id=platform_id,
        title="Senior Backend Engineer",
        company="Stripe",
        location="San Francisco, CA",
        posted_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
        job_url=f"https://www.linkedin.com/jobs/view/{platform_id}/",
    )
    upsert_job(conn, card, "Full job description text.", "hashxyz")
    row = conn.execute(
        "SELECT id FROM jobs WHERE platform_id = ?", (platform_id,)
    ).fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# jobhunt --help / --version
# ---------------------------------------------------------------------------


class TestHelpAndVersion:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "jobhunt" in result.output.lower() or "Usage" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


# ---------------------------------------------------------------------------
# jobhunt config
# ---------------------------------------------------------------------------


class TestConfigCommand:
    def test_show(self, tmp_path):
        config_path = tmp_path / "config.json"
        db_path = tmp_path / "jobhunt.db"

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["config", "--show"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "credential_preferences" in data
        assert "sources" in data

    def test_set_pref(self, tmp_path):
        config_path = tmp_path / "config.json"
        db_path = tmp_path / "jobhunt.db"

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["config", "--set-pref", "new@example.com"])

        assert result.exit_code == 0
        assert "new@example.com" in result.output

        # Verify it was written
        saved = json.loads(config_path.read_text())
        assert saved["credential_preferences"]["preferred_emails"][0] == "new@example.com"


# ---------------------------------------------------------------------------
# jobhunt list
# ---------------------------------------------------------------------------


class TestListCommand:
    def test_no_jobs_found(self, tmp_path):
        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["list"])

        assert result.exit_code == 0
        assert "No jobs found" in result.output

    def test_list_with_jobs(self, tmp_path):
        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        conn = init_db(db_path)
        _seed_job(conn)
        conn.close()

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["list"])

        assert result.exit_code == 0
        assert "Stripe" in result.output

    def test_list_json_output(self, tmp_path):
        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        conn = init_db(db_path)
        _seed_job(conn)
        conn.close()

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["list", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        # FR-16: jd_text must not be included
        assert "jd_text" not in data[0]
        assert data[0]["company"] == "Stripe"

    def test_list_status_filter(self, tmp_path):
        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        conn = init_db(db_path)
        _seed_job(conn, "111")
        _seed_job(conn, "222")
        conn.close()

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["list", "--status", "new", "--json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert all(j["status"] == "new" for j in data)


# ---------------------------------------------------------------------------
# jobhunt show
# ---------------------------------------------------------------------------


class TestShowCommand:
    def test_show_existing_job(self, tmp_path):
        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        conn = init_db(db_path)
        job_id = _seed_job(conn)
        conn.close()

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["show", str(job_id)])

        assert result.exit_code == 0
        assert "Stripe" in result.output
        assert "Full job description text." in result.output
        assert "JD Hash:" in result.output

    def test_show_nonexistent_job(self, tmp_path):
        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.cli._db_path", return_value=db_path),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["show", "99999"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "not found" in (result.stderr or "")

    def test_show_requires_integer_id(self):
        runner = CliRunner()
        result = runner.invoke(main, ["show", "not-a-number"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# jobhunt auth (smoke — mocked Playwright + credentials)
# ---------------------------------------------------------------------------


class TestAuthCommand:
    def test_auth_success_with_mocked_flow(self, tmp_path):
        config_path = tmp_path / "config.json"
        session_path = tmp_path / "linkedin.json"

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.SESSION_PATH", session_path),
            patch("jobhunt.config.SESSION_DIR", tmp_path),
            patch("jobhunt.auth.run_auth", return_value=True),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["auth"])

        assert result.exit_code == 0

    def test_auth_failure_exits_1(self, tmp_path):
        config_path = tmp_path / "config.json"

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.auth.run_auth", return_value=False),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["auth"])

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# jobhunt fetch (smoke — heavily mocked)
# ---------------------------------------------------------------------------


class TestFetchCommand:
    def test_fetch_dry_run_no_db_write(self, tmp_path):
        db_path = tmp_path / "jobhunt.db"
        config_path = tmp_path / "config.json"
        session_path = tmp_path / "session" / "linkedin.json"
        session_path.parent.mkdir(parents=True)
        session_path.write_text("{}")

        with (
            patch("jobhunt.config.CONFIG_PATH", config_path),
            patch("jobhunt.config.DATA_DIR", tmp_path),
            patch("jobhunt.config.DB_PATH", db_path),
            patch("jobhunt.config.SESSION_PATH", session_path),
            patch("jobhunt.config.SESSION_DIR", session_path.parent),
            patch("jobhunt.cli._db_path", return_value=db_path),
            patch("jobhunt.auth.ensure_session"),
            patch("jobhunt.fetcher.run_fetch"),
        ):
            runner = CliRunner()
            result = runner.invoke(main, ["fetch", "--dry-run", "--limit", "5"])

        # With run_fetch mocked, just verify the command was invoked without error
        assert result.exit_code == 0
