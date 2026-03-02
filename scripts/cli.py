"""Click CLI: entry point and all subcommand definitions.

Subcommands: auth | config | fetch | list | show | tailor | status
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from scripts import __version__
from scripts.models import JobStatus
from scripts.utils import truncate_str

# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=__version__, prog_name="jobhunt")
def main() -> None:
    """CLI tool for automated LinkedIn job discovery and local tracking."""


# ---------------------------------------------------------------------------
# jobhunt auth (FR-01, FR-20)
# ---------------------------------------------------------------------------


@main.command("auth")
def cmd_auth() -> None:
    """Authenticate with LinkedIn (auto-login via 1Password or manual fallback)."""
    from scripts import auth
    from scripts.config import load_config

    config = load_config()
    success = auth.run_auth(config)
    if not success:
        print("Error: authentication failed.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# jobhunt config (FR-19)
# ---------------------------------------------------------------------------


@main.command("config")
@click.option("--show", "action", flag_value="show", help="Print current config.json to stdout.")
@click.option(
    "--set-pref",
    "email",
    default=None,
    metavar="EMAIL",
    help="Prepend EMAIL to preferred_emails list (highest priority).",
)
def cmd_config(action: str | None, email: str | None) -> None:
    """View or update jobhunt configuration settings."""
    from scripts.config import (
        load_config,
        prepend_preferred_email,
        print_config,
        save_config,
    )

    config = load_config()

    if action == "show":
        print_config(config)
        return

    if email:
        prepend_preferred_email(config, email)
        save_config(config)
        print(f"✓ {email} added as highest-priority preferred email.")
        return

    # No flag provided — show usage hint
    click.echo(ctx_cmd_config.get_help(click.Context(cmd_config)))


# Fix: capture ctx for help display
ctx_cmd_config = cmd_config  # noqa: F841 (used above)


# ---------------------------------------------------------------------------
# jobhunt fetch (FR-02, FR-03, FR-04 … FR-13)
# ---------------------------------------------------------------------------


@main.command("fetch")
@click.option("--limit", default=100, show_default=True, help="Maximum jobs to process.")
@click.option("--lookback", default=30, show_default=True, help="Only ingest jobs posted within N days.")
@click.option("--dry-run", is_flag=True, help="Scrape without writing to the database.")
@click.option("--verbose", is_flag=True, help="Print per-job status lines.")
@click.option("--url", default=None, help="Fetch a single URL instead of all configured URLs.")
def cmd_fetch(limit: int, lookback: int, dry_run: bool, verbose: bool, url: str | None) -> None:
    """Scrape LinkedIn job collections and store new postings."""
    from scripts import auth, fetcher
    from scripts.config import load_config
    from scripts import db as db_module

    config = load_config()

    # FR-18: ensure DB exists
    db_module.init_db(str(_db_path()))

    # FR-02: ensure session exists (auto-auth if missing)
    auth.ensure_session(config)

    if url:
        # Fetch a single specific URL
        fetcher.run_fetch(
            config=config,
            limit=limit,
            lookback=lookback,
            dry_run=dry_run,
            verbose=verbose,
            fetch_url=url,
        )
    else:
        # Fetch all configured URLs
        fetch_urls = config.get("fetch", {}).get("urls", [])
        if not fetch_urls:
            # Fall back to single recommended URL (backward compat)
            fallback_url = (
                config.get("sources", {}).get("linkedin", {}).get(
                    "fetch_url", "https://www.linkedin.com/jobs/collections/recommended/"
                )
            )
            fetcher.run_fetch(
                config=config,
                limit=limit,
                lookback=lookback,
                dry_run=dry_run,
                verbose=verbose,
                fetch_url=fallback_url,
            )
        else:
            for entry in fetch_urls:
                fetch_url = entry["url"] if isinstance(entry, dict) else entry
                fetcher.run_fetch(
                    config=config,
                    limit=limit,
                    lookback=lookback,
                    dry_run=dry_run,
                    verbose=verbose,
                    fetch_url=fetch_url,
                )


# ---------------------------------------------------------------------------
# jobhunt list (FR-14, FR-15, FR-16, FR-31)
# ---------------------------------------------------------------------------

_VALID_STATUSES = {s.value for s in JobStatus}


@main.command("list")
@click.option("--status", default=None, help="Filter by status (comma-separated). Values: new,skipped,tailored,blocked,apply_failed,applied.")
@click.option("--company", default=None, help="Case-insensitive company substring.")
@click.option("--title", default=None, help="Case-insensitive title substring.")
@click.option("--location", default=None, help="Case-insensitive location substring.")
@click.option("--since", default=None, metavar="DATE", help="Only jobs fetched on or after YYYY-MM-DD.")
@click.option("--limit", default=50, show_default=True, help="Maximum rows to return.")
@click.option(
    "--sort",
    default="-fetched_at",
    show_default=True,
    help="Sort field; prefix with '-' for descending. E.g. -posted_at",
)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON array.")
def cmd_list(
    status: str | None,
    company: str | None,
    title: str | None,
    location: str | None,
    since: str | None,
    limit: int,
    sort: str,
    as_json: bool,
) -> None:
    """List tracked jobs with optional filters."""
    from scripts import db as db_module
    from scripts.config import load_config

    # Validate status tokens (FR-31)
    if status:
        tokens = [s.strip() for s in status.split(",") if s.strip()]
        invalid = [t for t in tokens if t not in _VALID_STATUSES]
        if invalid:
            print(
                f"Error: invalid status value(s): {', '.join(invalid)}. "
                f"Valid: {', '.join(sorted(_VALID_STATUSES))}",
                file=sys.stderr,
            )
            sys.exit(1)

    load_config()  # ensure data dir exists
    conn = db_module.init_db(str(_db_path()))

    try:
        rows = db_module.query_jobs(
            conn,
            status=status,
            company=company,
            title=title,
            location=location,
            since=since,
            limit=limit,
            sort=sort,
        )
    finally:
        conn.close()

    if as_json:
        _render_json(rows)
    else:
        _render_table(rows)


# ---------------------------------------------------------------------------
# jobhunt show <id> (FR-17)
# ---------------------------------------------------------------------------


@main.command("show")
@click.argument("job_id", type=int)
def cmd_show(job_id: int) -> None:
    """Display full details for a single job by its database ID."""
    from scripts import db as db_module
    from scripts.config import load_config

    load_config()  # ensure data dir exists
    conn = db_module.init_db(str(_db_path()))

    try:
        job = db_module.get_job(conn, job_id)
    finally:
        conn.close()

    if job is None:
        print(f"Error: job {job_id} not found.", file=sys.stderr)
        sys.exit(1)

    _render_detail(job)


# ---------------------------------------------------------------------------
# jobhunt tailor — removed (LLM calls handled by agent layer, not CLI)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# jobhunt status <job_id> --set <status> (FR-29, FR-30)
# ---------------------------------------------------------------------------


@main.command("status")
@click.argument("job_id", type=int)
@click.option(
    "--set", "new_status", required=True,
    type=click.Choice(["new", "skipped", "tailored", "blocked", "apply_failed", "applied"]),
    help="New status to set.",
)
@click.option("--note", default=None, help="Optional note to attach to this status change.")
def cmd_status(job_id: int, new_status: str, note: str | None) -> None:
    """Set job status and optionally attach a note."""
    from scripts import db as db_module
    from scripts.config import load_config

    load_config()
    conn = db_module.init_db(str(_db_path()))

    try:
        db_module.set_job_status(conn, job_id, new_status, note=note)
        print(f"Job {job_id} status set to '{new_status}'.")
    except LookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------


def _render_table(rows: list[dict]) -> None:
    """Print a rich table with standard columns (FR-15)."""
    if not rows:
        print("No jobs found.")
        return

    console = Console()
    table = Table(show_header=True, header_style="bold")

    for col in ("id", "status", "title", "company", "location", "posted_at", "fetched_at"):
        table.add_column(col, overflow="fold")

    for row in rows:
        table.add_row(
            str(row["id"]),
            row["status"] or "",
            truncate_str(row["title"], 40),
            truncate_str(row["company"], 40),
            truncate_str(row["location"] or "", 40),
            row["posted_at"] or "",
            (row["fetched_at"] or "")[:16],
        )

    console.print(table)


def _render_json(rows: list[dict]) -> None:
    """Print jobs as a JSON array, excluding jd_text (FR-16)."""
    filtered = [{k: v for k, v in row.items() if k != "jd_text"} for row in rows]
    print(json.dumps(filtered, indent=2, default=str))


def _render_detail(job: dict) -> None:
    """Print all fields for a single job, including full jd_text (FR-17)."""
    print(f"ID:             {job['id']}")
    print(f"Status:         {job['status']}")
    print(f"Title:          {job['title']}")
    print(f"Company:        {job['company']}")
    print(f"Location:       {job['location'] or '—'}")
    print(f"Posted:         {job['posted_at'] or '—'}")
    print(f"Fetched:        {job['fetched_at'] or '—'}")
    print(f"Updated:        {job['updated_at'] or '—'}")
    print(f"Status Updated: {job.get('status_updated_at') or '—'}")
    print(f"Platform:       {job['platform']}")
    print(f"Job URL:        {job['job_url']}")
    print(f"JD Hash:        {job['jd_hash']}")
    print()
    print("--- JD ---")
    print(job["jd_text"] or "(no description)")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _db_path():
    """Return the DB_PATH constant (deferred import avoids circular issues)."""
    from scripts.config import DB_PATH
    return DB_PATH
