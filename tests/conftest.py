"""Shared pytest fixtures."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.db import init_db
from scripts.models import JobCard


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    """Return an open in-memory-backed (temp file) DB with the correct schema."""
    db_file = tmp_path / "test.db"
    conn = init_db(db_file)
    yield conn
    conn.close()


@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> Path:
    """Return the path to a fresh temporary DB file (not yet connected)."""
    return tmp_path / "test.db"


# ---------------------------------------------------------------------------
# Job card fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_card() -> JobCard:
    """A minimal valid JobCard fixture."""
    return JobCard(
        platform_id="1234567890",
        title="Senior Backend Engineer",
        company="Stripe",
        location="San Francisco, CA",
        posted_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
        job_url="https://www.linkedin.com/jobs/view/1234567890/",
    )


@pytest.fixture()
def sample_card_2() -> JobCard:
    """A second distinct JobCard fixture."""
    return JobCard(
        platform_id="9876543210",
        title="Staff Software Engineer",
        company="Google",
        location="New York, NY",
        posted_at=datetime(2026, 2, 18, tzinfo=timezone.utc),
        job_url="https://www.linkedin.com/jobs/view/9876543210/",
    )


# ---------------------------------------------------------------------------
# HTML / JD fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_jd_html() -> str:
    """Sample LinkedIn-style JD HTML for extraction tests."""
    return (
        "<div class='description__text'>"
        "<h2>About the role</h2>"
        "<p>We are looking for a <strong>Senior Backend Engineer</strong> to join Stripe.</p>"
        "<ul><li>5+ years experience</li><li>Python or Go</li></ul>"
        "</div>"
    )


@pytest.fixture()
def sample_jd_text() -> str:
    """Expected plain-text after stripping sample_jd_html."""
    return "\nAbout the role\n\nWe are looking for a Senior Backend Engineer to join Stripe.\n5+ years experience\nPython or Go\n"


# ---------------------------------------------------------------------------
# 1Password mock output
# ---------------------------------------------------------------------------


@pytest.fixture()
def op_item_list_output() -> str:
    """Mock JSON from `op item list --format json` with two LinkedIn items."""
    items = [
        {
            "id": "uuid-hotmail",
            "title": "LinkedIn (hotmail)",
            "urls": [{"href": "https://www.linkedin.com/"}],
        },
        {
            "id": "uuid-gmail",
            "title": "LinkedIn (gmail)",
            "urls": [{"href": "https://linkedin.com/"}],
        },
        {
            "id": "uuid-github",
            "title": "GitHub",
            "urls": [{"href": "https://github.com/"}],
        },
    ]
    return json.dumps(items)


@pytest.fixture()
def preferred_emails() -> list[str]:
    return ["haomin_liu@hotmail.com", "haomin.liu@gmail.com"]
