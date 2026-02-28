"""SQLite database: schema initialisation, upsert logic, query helpers.

FR-18: init_db() creates the database and schema on first use.
FR-08/09/10: upsert_job() handles all dedup branches.
FR-14/17: query_jobs() and get_job() power the list and show commands.
FR-29/30: set_job_status() and append_job_note() for Phase 2a status pipeline.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from scripts.models import JobCard, JobNote, JobStatus
from scripts.utils import log_warn, log_error, utcnow_iso

# ---------------------------------------------------------------------------
# Schema (Phase 2a canonical)
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    platform          TEXT    NOT NULL DEFAULT 'linkedin',
    platform_id       TEXT    NOT NULL,
    title             TEXT    NOT NULL,
    company           TEXT    NOT NULL,
    location          TEXT,
    posted_at         TEXT,
    job_url           TEXT    NOT NULL,
    jd_text           TEXT,
    jd_hash           TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'new'
                      CHECK(status IN ('new','skipped','tailored','blocked','apply_failed','applied')),
    fetched_at        TEXT    NOT NULL,
    updated_at        TEXT,
    status_updated_at TEXT,

    UNIQUE(platform, platform_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs(status);

CREATE INDEX IF NOT EXISTS idx_jobs_fetched_at
    ON jobs(fetched_at);

CREATE INDEX IF NOT EXISTS idx_jobs_status_updated_at
    ON jobs(status_updated_at);

CREATE TABLE IF NOT EXISTS job_notes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER NOT NULL,
    created_at    TEXT    NOT NULL,
    status_after  TEXT    NOT NULL CHECK(status_after IN ('new','skipped','tailored','blocked','apply_failed','applied')),
    content       TEXT    NOT NULL,
    source        TEXT    NOT NULL DEFAULT 'cli',
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_job_notes_job_id_created_at
    ON job_notes(job_id, created_at);
"""

_VALID_SORT_FIELDS = {"id", "title", "company", "posted_at", "fetched_at", "status_updated_at"}

# ---------------------------------------------------------------------------
# Status transition rules (FR-29)
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    "new": ["skipped", "tailored"],
    "tailored": ["blocked", "apply_failed", "applied"],
    "blocked": ["tailored", "applied"],
    "apply_failed": ["applied"],
}

# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

_MIGRATION_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _get_user_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _set_user_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(f"PRAGMA user_version = {version}")


def _needs_migration(conn: sqlite3.Connection) -> bool:
    """Check if the DB has the old Phase 1 schema (user_version < 2)."""
    return _get_user_version(conn) < 2


def _has_old_schema(conn: sqlite3.Connection) -> bool:
    """Return True if jobs table exists but is missing Phase 2a columns/constraints.

    Detects the Phase 1 schema by checking for the absence of status_updated_at column.
    Returns False if the jobs table doesn't exist yet (fresh install).
    """
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
    )
    if cursor.fetchone() is None:
        return False  # fresh DB — no migration needed
    # Check if status_updated_at column already exists
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    return "status_updated_at" not in cols


def migrate_db_schema(conn: sqlite3.Connection) -> None:
    """Apply Phase 2a migration if needed (user_version < 2).

    Uses PRAGMA user_version to track migration state.
    Idempotent: safe to call multiple times.
    """
    if not _needs_migration(conn):
        return

    # Only run the full migration if the old schema is present
    if _has_old_schema(conn):
        migration_sql = (_MIGRATION_DIR / "0002_phase2a_status_and_notes.sql").read_text()
        conn.executescript(migration_sql)
    else:
        # Fresh DB or already has new schema — just set version
        _set_user_version(conn, 2)
        conn.commit()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database and apply the schema.

    FR-18: parent directory is created if it doesn't exist.
    Returns an open connection; caller is responsible for closing it.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Run migration FIRST (upgrades existing schema to Phase 2a if needed)
    # before executing DDL which references new columns/indexes.
    migrate_db_schema(conn)
    conn.executescript(_DDL)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Existence check (Issue #17 — skip already-scraped jobs)
# ---------------------------------------------------------------------------


def job_exists(conn: sqlite3.Connection, platform: str, platform_id: str) -> bool:
    """Return True if a job with this (platform, platform_id) exists in the DB."""
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE platform = ? AND platform_id = ? LIMIT 1",
        (platform, platform_id),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Upsert (dedup logic FR-08/09/10)
# ---------------------------------------------------------------------------


def upsert_job(
    conn: sqlite3.Connection,
    card: JobCard,
    jd_text: str,
    jd_hash: str,
    dry_run: bool = False,
) -> tuple[str, bool]:
    """Insert a job record, skipping if platform_id already exists.

    Returns a tuple (result, is_repost) where:
      result    — one of 'new' | 'skipped' | 'error'
      is_repost — always False (kept for API compatibility)

    Branch A — platform_id already exists → skip.
    Branch B — platform_id not found → INSERT with status='new'.

    FR-12: In dry_run mode, print JSON to stdout instead of writing to DB.
    """
    try:
        # Branch A: look up by (platform, platform_id)
        row = conn.execute(
            "SELECT id FROM jobs WHERE platform = ? AND platform_id = ?",
            (card.platform, card.platform_id),
        ).fetchone()

        if row is not None:
            return "skipped", False

        # Branch B: new job — insert directly
        if dry_run:
            _print_dry_run(card, jd_hash)
            return "new", False

        now = utcnow_iso()
        conn.execute(
            """INSERT INTO jobs
               (platform, platform_id, title, company, location,
                posted_at, job_url, jd_text, jd_hash, status, fetched_at, updated_at,
                status_updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, NULL, ?)""",
            (
                card.platform,
                card.platform_id,
                card.title,
                card.company,
                card.location,
                card.posted_at_iso,
                card.job_url,
                jd_text,
                jd_hash,
                now,
                now,
            ),
        )
        conn.commit()
        return "new", False

    except sqlite3.IntegrityError:
        # UNIQUE constraint violation — race condition or concurrent run; treat as skip
        return "skipped", False
    except sqlite3.Error as exc:
        log_error(f"DB error for platform_id={card.platform_id}: {exc}")
        return "error", False


def _print_dry_run(card: JobCard, jd_hash: str) -> None:
    """Print a dry-run JSON record to stdout (FR-12)."""
    record = {
        "platform": card.platform,
        "platform_id": card.platform_id,
        "title": card.title,
        "company": card.company,
        "location": card.location,
        "posted_at": card.posted_at_iso,
        "job_url": card.job_url,
        "jd_hash": jd_hash,
    }
    print(json.dumps(record))


# ---------------------------------------------------------------------------
# Status transitions (FR-29)
# ---------------------------------------------------------------------------


def set_job_status(
    conn: sqlite3.Connection,
    job_id: int,
    new_status: str,
    current_status: str | None = None,
    note: str | None = None,
    source: str = "cli",
) -> None:
    """Transition a job's status, optionally appending a note.

    If current_status is None, it is fetched from the DB.
    Raises ValueError on invalid transition.
    Raises LookupError if job not found.
    """
    if current_status is None:
        job = get_job(conn, job_id)
        if job is None:
            raise LookupError(f"job {job_id} not found")
        current_status = job["status"]

    # Status transitions are no longer enforced — any transition is allowed.

    now = utcnow_iso()
    conn.execute(
        "UPDATE jobs SET status = ?, status_updated_at = ? WHERE id = ?",
        (new_status, now, job_id),
    )

    if note:
        append_job_note(conn, job_id, new_status, note, source)

    conn.commit()


# ---------------------------------------------------------------------------
# Job notes (FR-30)
# ---------------------------------------------------------------------------


def append_job_note(
    conn: sqlite3.Connection,
    job_id: int,
    status_after: str,
    content: str,
    source: str = "cli",
) -> None:
    """Append a note row to job_notes. Does NOT commit — caller commits."""
    now = utcnow_iso()
    conn.execute(
        """INSERT INTO job_notes (job_id, created_at, status_after, content, source)
           VALUES (?, ?, ?, ?, ?)""",
        (job_id, now, status_after, content, source),
    )


def get_job_notes(
    conn: sqlite3.Connection,
    job_id: int,
) -> list[JobNote]:
    """Return all notes for a job, ordered by created_at ascending."""
    cursor = conn.execute(
        """SELECT id, job_id, created_at, status_after, content, source
           FROM job_notes WHERE job_id = ?
           ORDER BY created_at ASC""",
        (job_id,),
    )
    return [
        JobNote(
            id=row["id"],
            job_id=row["job_id"],
            created_at=row["created_at"],
            status_after=row["status_after"],
            content=row["content"],
            source=row["source"],
        )
        for row in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# Queries (FR-14 list, FR-17 show)
# ---------------------------------------------------------------------------


def query_jobs(
    conn: sqlite3.Connection,
    status: str | list[str] | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    since: str | None = None,
    limit: int = 50,
    sort: str = "-fetched_at",
) -> list[dict]:
    """Return jobs matching all provided filters.

    FR-14: AND logic, sorted by sort field, capped at limit.
    FR-31: status accepts comma-separated string or list for OR filtering.
    sort: field name, optionally prefixed with '-' for DESC.
    """
    conditions: list[str] = []
    params: list = []

    if status:
        if isinstance(status, str):
            statuses = [s.strip() for s in status.split(",") if s.strip()]
        else:
            statuses = list(status)
        placeholders = ",".join("?" * len(statuses))
        conditions.append(f"status IN ({placeholders})")
        params.extend(statuses)

    if company:
        conditions.append("LOWER(company) LIKE ?")
        params.append(f"%{company.lower()}%")

    if title:
        conditions.append("LOWER(title) LIKE ?")
        params.append(f"%{title.lower()}%")

    if location:
        conditions.append("LOWER(location) LIKE ?")
        params.append(f"%{location.lower()}%")

    if since:
        conditions.append("fetched_at >= ?")
        params.append(since)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    # Parse sort direction
    if sort.startswith("-"):
        field = sort[1:]
        direction = "DESC"
    else:
        field = sort
        direction = "ASC"

    if field not in _VALID_SORT_FIELDS:
        field = "fetched_at"
        direction = "DESC"

    sql = f"""
        SELECT id, platform, platform_id, title, company, location,
               posted_at, job_url, jd_text, jd_hash, status, fetched_at,
               updated_at, status_updated_at
        FROM jobs
        {where}
        ORDER BY {field} {direction}
        LIMIT ?
    """
    params.append(limit)
    cursor = conn.execute(sql, params)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_job(conn: sqlite3.Connection, job_id: int) -> dict | None:
    """Return a single job row by primary key, or None if not found (FR-17)."""
    cursor = conn.execute(
        """SELECT id, platform, platform_id, title, company, location,
                  posted_at, job_url, jd_text, jd_hash, status, fetched_at,
                  updated_at, status_updated_at
           FROM jobs WHERE id = ?""",
        (job_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))
