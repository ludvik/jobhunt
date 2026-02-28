"""Shared utility functions: logging, date parsing, string helpers."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Logging helpers (all go to stderr)
# ---------------------------------------------------------------------------

def log_info(msg: str) -> None:
    print(f"[INFO]  {msg}", file=sys.stderr, flush=True)


def log_warn(msg: str) -> None:
    print(f"[WARN]  {msg}", file=sys.stderr, flush=True)


def log_error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string (seconds precision)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> datetime | None:
    """Parse an ISO-8601 date string (e.g. '2026-02-25') into a UTC datetime.

    Returns None if the input is absent or unparseable.
    """
    if not s:
        return None
    try:
        # Accept date-only (YYYY-MM-DD) or full datetime
        from datetime import date
        d = date.fromisoformat(s[:10])
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return None


# Relative-date patterns ordered from most- to least-specific
_RELATIVE_PATTERNS: list[tuple[str, int]] = [
    (r"just\s+now", 0),
    (r"(\d+)\s+minute", 0),   # handled specially
    (r"(\d+)\s+hour", 0),
    (r"(\d+)\s+day", 0),
    (r"(\d+)\s+week", 0),
    (r"(\d+)\s+month", 0),
]


def parse_relative_date(label: str) -> datetime | None:
    """Convert a relative-date string like '2 days ago' to a UTC datetime.

    Supported patterns:
        'just now', 'X minutes ago', 'X hours ago', 'X days ago',
        'X weeks ago', 'X months ago'

    Returns None if the string is absent or unrecognised.
    """
    if not label:
        return None

    now = datetime.now(timezone.utc)
    text = label.lower().strip()

    if re.search(r"just\s+now", text):
        return now

    m = re.search(r"(\d+)\s+minute", text)
    if m:
        return now - timedelta(minutes=int(m.group(1)))

    m = re.search(r"(\d+)\s+hour", text)
    if m:
        return now - timedelta(hours=int(m.group(1)))

    m = re.search(r"(\d+)\s+day", text)
    if m:
        return now - timedelta(days=int(m.group(1)))

    m = re.search(r"(\d+)\s+week", text)
    if m:
        return now - timedelta(weeks=int(m.group(1)))

    m = re.search(r"(\d+)\s+month", text)
    if m:
        return now - timedelta(days=int(m.group(1)) * 30)

    return None


# ---------------------------------------------------------------------------
# String helpers
# ---------------------------------------------------------------------------

def truncate_str(s: str | None, max_len: int = 40) -> str:
    """Truncate a string to max_len characters, appending '…' if cut.

    FR-15: Long strings are truncated at 40 characters with a trailing '…'.
    """
    if not s:
        return ""
    s = str(s)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…"
