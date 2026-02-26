"""Data models: dataclasses used throughout jobhunt."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    NEW = "new"
    SKIPPED = "skipped"
    TAILORED = "tailored"
    BLOCKED = "blocked"
    APPLY_FAILED = "apply_failed"
    APPLIED = "applied"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class JobCard:
    """In-memory representation of a scraped job card (before DB write)."""
    platform_id: str
    title: str
    company: str
    location: str
    posted_at: datetime | None
    job_url: str
    platform: str = "linkedin"

    @property
    def posted_at_iso(self) -> str | None:
        """ISO-8601 date string for DB storage, or None."""
        if self.posted_at is None:
            return None
        return self.posted_at.date().isoformat()


@dataclass
class JobRecord:
    """Full DB row for a job posting."""
    id: int
    platform: str
    platform_id: str
    title: str
    company: str
    location: str | None
    posted_at: str | None
    job_url: str
    jd_text: str | None
    jd_hash: str
    status: str
    fetched_at: str
    updated_at: str | None


@dataclass
class JobNote:
    """A note attached to a job status transition."""
    job_id: int
    created_at: str
    status_after: str
    content: str
    source: str = "cli"
    id: int | None = None


@dataclass
class TailorMeta:
    """Metadata recorded alongside a tailored resume artifact."""
    job_id: int
    base: str
    model: str
    created_at_utc: str
    tailor_prompt_version: str
    resume_factory_cmd: str


@dataclass
class TailorResult:
    """Return value from run_tailor workflow."""
    success: bool
    tailored_md: str = ""
    base: str = ""
    pdf_ok: bool = False
    analysis_ok: bool = False
    dry_run: bool = False
    error: str = ""


@dataclass
class Credential:
    """1Password credential — never written to disk or logged."""
    username: str
    password: str
    item_id: str


@dataclass
class RunStats:
    """Counters collected during a fetch run."""
    new: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0

    @property
    def total_processed(self) -> int:
        return self.new + self.updated + self.skipped + self.errors

    @property
    def all_failed(self) -> bool:
        """True if every attempted job resulted in an error."""
        return self.total_processed > 0 and self.errors == self.total_processed


class FatalError(Exception):
    """Raised for unrecoverable errors; carries an exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class ExtractionError(Exception):
    """Raised when JD extraction fails (bad selectors, empty content, etc.)."""
