-- Migration 0002: Phase 2a — extend job statuses, add status_updated_at, create job_notes table.
-- Sets PRAGMA user_version = 2 on completion.
-- Idempotent: safe to run multiple times (guarded by user_version check in Python).

PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;

ALTER TABLE jobs RENAME TO jobs_old;

CREATE TABLE jobs (
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

INSERT INTO jobs (
    id, platform, platform_id, title, company, location, posted_at,
    job_url, jd_text, jd_hash, status, fetched_at, updated_at, status_updated_at
)
SELECT
    id,
    platform,
    platform_id,
    title,
    company,
    location,
    posted_at,
    job_url,
    jd_text,
    jd_hash,
    CASE
      WHEN status = 'new' THEN 'new'
      WHEN status IN ('skip','tailoring','rejected') THEN 'new'
      WHEN status IN ('skipped','applied') THEN status
      ELSE 'new'
    END,
    fetched_at,
    updated_at,
    CASE
      WHEN status = 'new' OR status IN ('skip','tailoring','rejected') THEN fetched_at
      ELSE COALESCE(updated_at, fetched_at)
    END
FROM jobs_old;

DROP TABLE jobs_old;

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_fetched_at ON jobs(fetched_at);
CREATE INDEX IF NOT EXISTS idx_jobs_status_updated_at ON jobs(status_updated_at);

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

PRAGMA user_version = 2;

COMMIT;
PRAGMA foreign_keys = ON;
