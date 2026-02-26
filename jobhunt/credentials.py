"""1Password CLI integration: domain-based credential resolution.

FR-01: resolve_credential() queries op, filters by domain, ranks by
preferred_emails, and returns a Credential dataclass.
FR-20: returns None (with explanatory stderr message) if op is unavailable
or no matching item is found — auth.py then falls back to manual login.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from jobhunt.models import Credential
from jobhunt.utils import log_warn, log_error


# ---------------------------------------------------------------------------
# op availability check
# ---------------------------------------------------------------------------

def op_available() -> bool:
    """Return True if the 1Password CLI (op) is found in PATH."""
    return shutil.which("op") is not None


# ---------------------------------------------------------------------------
# op CLI wrappers
# ---------------------------------------------------------------------------

def op_list_items() -> list[dict] | None:
    """Run `op item list --format json` and return parsed JSON.

    Returns None if the command fails or output is not valid JSON.
    """
    result = subprocess.run(
        ["op", "item", "list", "--format", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log_warn(f"op item list failed (exit {result.returncode}): {result.stderr.strip()}")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        log_error(f"op item list returned malformed JSON: {exc}")
        return None


def op_get_item(item_id: str, fields: str = "username") -> list[dict] | None:
    """Run `op item get <item_id> --fields <fields> --format json` and return fields.

    Returns None if the command fails or output is not valid JSON.
    IMPORTANT: Never log the returned field values — they may contain passwords.
    """
    result = subprocess.run(
        ["op", "item", "get", item_id, "--fields", fields, "--reveal", "--format", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log_warn(f"op item get failed for {item_id} (exit {result.returncode})")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        log_error(f"op item get returned malformed JSON for {item_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Domain filtering and email ranking
# ---------------------------------------------------------------------------

def _item_matches_domain(item: dict, domain: str) -> bool:
    """Return True if any URL in the 1Password item contains domain."""
    urls = item.get("urls") or []
    return any(domain in (u.get("href") or "") for u in urls)


def _get_field_value(fields: list[dict], field_id: str) -> str | None:
    """Extract a field value by its id or label from an op field list."""
    for f in fields:
        if f.get("id") == field_id or f.get("label", "").lower() == field_id:
            return f.get("value")
    return None


def rank_by_preferred_emails(
    items: list[dict],
    preferred_emails: list[str],
) -> list[dict]:
    """Sort items so the one matching the highest-priority email comes first.

    For each item, fetches its username via `op item get`. Items whose username
    appears in preferred_emails are ranked by index (lower = higher priority).
    Items not in preferred_emails receive a score of len(preferred_emails).
    """
    scored: list[tuple[int, dict]] = []

    for item in items:
        username = _resolve_username(item["id"])
        if username and username in preferred_emails:
            score = preferred_emails.index(username)
        else:
            score = len(preferred_emails)
        scored.append((score, item))

    scored.sort(key=lambda t: t[0])
    return [item for _, item in scored]


def _resolve_username(item_id: str) -> str | None:
    """Fetch just the username field for an item (used during ranking)."""
    fields = op_get_item(item_id, fields="username")
    if not fields:
        return None
    return _get_field_value(fields, "username")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_credential(domain: str, preferred_emails: list[str]) -> Credential | None:
    """Resolve the best-matching 1Password credential for domain.

    Steps (FR-01):
      1. Check op is available.
      2. List all items; filter by domain URL match.
      3. Rank by preferred_emails.
      4. Retrieve username + password for winner.
      5. Return Credential (never write password to disk or log).

    Returns None (with a stderr explanation) on any failure; auth.py will
    then fall back to manual browser login (FR-20).
    """
    # Step 1 — check op is in PATH
    if not op_available():
        print("op CLI not found — falling back to manual login.", file=sys.stderr, flush=True)
        return None

    print("Resolving LinkedIn credentials from 1Password...", flush=True)

    # Step 2 — list + filter
    all_items = op_list_items()
    if all_items is None:
        print("op returned an error — falling back to manual login.", file=sys.stderr, flush=True)
        return None

    filtered = [item for item in all_items if _item_matches_domain(item, domain)]
    if not filtered:
        print(
            f"No matching 1Password item found for {domain} — falling back to manual login.",
            file=sys.stderr,
            flush=True,
        )
        return None

    # Step 3 — rank by preferred_emails
    ranked = rank_by_preferred_emails(filtered, preferred_emails)
    winner = ranked[0]
    winner_id = winner["id"]

    # Step 4 — retrieve username + password (NEVER log these)
    fields = op_get_item(winner_id, fields="username,password")
    if not fields:
        print("Failed to retrieve credentials from 1Password — falling back to manual login.", file=sys.stderr, flush=True)
        return None

    username = _get_field_value(fields, "username")
    password = _get_field_value(fields, "password")

    if not username or not password:
        log_warn(f"Missing username or password in 1Password item {winner_id}")
        print("Incomplete credentials — falling back to manual login.", file=sys.stderr, flush=True)
        return None

    # Step 5 — return in-memory credential (never serialised to disk)
    return Credential(username=username, password=password, item_id=winner_id)
