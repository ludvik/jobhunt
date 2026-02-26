"""SQLite database: schema initialisation, upsert logic, query helpers.

FR-18: init_db() creates the database and schema on first use.
FR-08/09/10: upsert_job() handles all dedup branches.
FR-14/17: query_jobs() and get_job() power the list and show commands.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from jobhunt.models import JobCard
from jobhunt.utils import log_warn, utcnow_iso

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform    TEXT    NOT NULL DEFAULT 'linkedin',
    platform_id TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    company     TEXT    NOT NULL,
    location    TEXT,
    posted_at   TEXT,
    job_url     TEXT    NOT NULL,
    jd_text     TEXT,
    jd_hash     TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'new'
                CHECK(status IN ('new','skip','tailoring','applied','rejected')),
    fetched_at  TEXT    NOT NULL,
    updated_at  TEXT,

    UNIQUE(platform, platform_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status
    ON jobs(status);

CREATE INDEX IF NOT EXISTS idx_jobs_fetched_at
    ON jobs(fetched_at);
"""

_VALID_SORT_FIELDS = {"id", "title", "company", "posted_at", "fetched_at"}

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
    conn.executescript(_DDL)
    conn.commit()
    return conn


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
    """Upsert a job record using the two-layer dedup strategy.

    Returns a tuple (result, is_repost) where:
      result    — one of 'new' | 'updated' | 'skipped' | 'error'
      is_repost — True if a jd_hash collision was detected on the insert path

    FR-08: Branch A — platform_id already exists.
      A1: jd_hash unchanged  → skip silently.
      A2: jd_hash changed    → update jd_text, jd_hash, updated_at in place.

    FR-09: Branch B — platform_id not found; check jd_hash collision.
      Collision detected → log warn, proceed with INSERT anyway.
      No collision       → insert normally.

    FR-10: INSERT new records with status='new'.
    FR-12: In dry_run mode, print JSON to stdout instead of writing to DB.
    """
    try:
        # Branch A: look up by (platform, platform_id)
        row = conn.execute(
            "SELECT id, jd_hash FROM jobs WHERE platform = ? AND platform_id = ?",
            (card.platform, card.platform_id),
        ).fetchone()

        if row is not None:
            existing_id, existing_hash = row["id"], row["jd_hash"]

            if existing_hash == jd_hash:
                # A1: unchanged — skip
                return "skipped", False
            else:
                # A2: JD changed — update in place
                if not dry_run:
                    conn.execute(
                        """UPDATE jobs
                           SET jd_text = ?, jd_hash = ?, updated_at = ?
                           WHERE id = ?""",
                        (jd_text, jd_hash, utcnow_iso(), existing_id),
                    )
                    conn.commit()
                return "updated", False

        # Branch B: not found — check for jd_hash collision (FR-09)
        collision = conn.execute(
            "SELECT platform_id FROM jobs WHERE jd_hash = ? LIMIT 1",
            (jd_hash,),
        ).fetchone()

        is_repost = collision is not None
        if is_repost:
            log_warn(
                f"[repost?] platform_id={card.platform_id} has same jd_hash "
                f"as existing platform_id={collision['platform_id']}; inserting anyway."
            )

        if dry_run:
            _print_dry_run(card, jd_hash)
            return "new", is_repost

        # INSERT new record (FR-10)
        conn.execute(
            """INSERT INTO jobs
               (platform, platform_id, title, company, location,
                posted_at, job_url, jd_text, jd_hash, status, fetched_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, NULL)""",
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
                utcnow_iso(),
            ),
        )
        conn.commit()
        return "new", is_repost

    except sqlite3.IntegrityError:
        # UNIQUE constraint violation — race condition or concurrent run; treat as skip
        return "skipped", False
    except sqlite3.Error as exc:
        from jobhunt.utils import log_error
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
# Queries (FR-14 list, FR-17 show)
# ---------------------------------------------------------------------------


def query_jobs(
    conn: sqlite3.Connection,
    status: str | None = None,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    since: str | None = None,
    limit: int = 50,
    sort: str = "-fetched_at",
) -> list[dict]:
    """Return jobs matching all provided filters.

    FR-14: AND logic, sorted by sort field, capped at limit.
    sort: field name, optionally prefixed with '-' for DESC.
    """
    conditions: list[str] = []
    params: list = []

    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
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
               posted_at, job_url, jd_text, jd_hash, status, fetched_at, updated_at
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
                  posted_at, job_url, jd_text, jd_hash, status, fetched_at, updated_at
           FROM jobs WHERE id = ?""",
        (job_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))
