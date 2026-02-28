"""Credential resolution: macOS Keychain first, 1Password fallback.

Priority order (FR-01 updated):
  1. macOS Keychain  — `security find-generic-password -a jobhunt -s <service>`
  2. 1Password CLI   — domain-based lookup via `op` (fallback, requires no interactive auth)
  3. None            — auth.py falls back to manual browser login (FR-20)
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

from scripts.models import Credential
from scripts.utils import log_warn, log_error


# ---------------------------------------------------------------------------
# Service name mapping  (domain → macOS Keychain service key)
# ---------------------------------------------------------------------------

_DOMAIN_TO_SERVICE: dict[str, str] = {
    "linkedin.com": "linkedin",
}


def _domain_to_service(domain: str) -> str | None:
    """Map a source domain to the Keychain service name used by jobhunt."""
    for key, service in _DOMAIN_TO_SERVICE.items():
        if key in domain:
            return service
    return None


# ---------------------------------------------------------------------------
# macOS Keychain (primary)
# ---------------------------------------------------------------------------

def read_keychain(service: str) -> dict | str | None:
    """Read a secret stored under account='jobhunt', service=<service>.

    Returns:
      - dict   if the stored value is valid JSON  (e.g. linkedin credentials)
      - str    if the stored value is a plain string (e.g. an API key)
      - None   if the entry does not exist or the command fails
    Never raises; logs warnings on unexpected errors.
    """
    result = subprocess.run(
        ["security", "find-generic-password", "-a", "jobhunt", "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _resolve_from_keychain(domain: str) -> Credential | None:
    """Try to resolve a Credential from macOS Keychain for the given domain."""
    service = _domain_to_service(domain)
    if not service:
        return None

    data = read_keychain(service)
    if not isinstance(data, dict):
        return None

    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        log_warn(f"Keychain entry for '{service}' missing username or password fields.")
        return None

    return Credential(username=username, password=password, item_id=f"keychain:{service}")


# ---------------------------------------------------------------------------
# 1Password CLI (fallback)
# ---------------------------------------------------------------------------

def op_available() -> bool:
    """Return True if the 1Password CLI (op) is found in PATH."""
    return shutil.which("op") is not None


def op_list_items() -> list[dict] | None:
    """Run `op item list --format json`; returns None on any failure."""
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
    """Run `op item get <item_id> --fields <fields> --format json`.

    Returns None on any failure. NEVER log the returned field values.
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


def _item_matches_domain(item: dict, domain: str) -> bool:
    urls = item.get("urls") or []
    return any(domain in (u.get("href") or "") for u in urls)


def _get_field_value(fields: list[dict], field_id: str) -> str | None:
    for f in fields:
        if f.get("id") == field_id or f.get("label", "").lower() == field_id:
            return f.get("value")
    return None


def _resolve_username(item_id: str) -> str | None:
    fields = op_get_item(item_id, fields="username")
    if not fields:
        return None
    return _get_field_value(fields, "username")


def rank_by_preferred_emails(
    items: list[dict],
    preferred_emails: list[str],
) -> list[dict]:
    scored: list[tuple[int, dict]] = []
    for item in items:
        username = _resolve_username(item["id"])
        score = (
            preferred_emails.index(username)
            if username and username in preferred_emails
            else len(preferred_emails)
        )
        scored.append((score, item))
    scored.sort(key=lambda t: t[0])
    return [item for _, item in scored]


def _resolve_from_op(domain: str, preferred_emails: list[str]) -> Credential | None:
    """Fallback: try 1Password CLI. Returns None on any failure."""
    if not op_available():
        return None

    all_items = op_list_items()
    if all_items is None:
        return None

    filtered = [item for item in all_items if _item_matches_domain(item, domain)]
    if not filtered:
        return None

    ranked = rank_by_preferred_emails(filtered, preferred_emails)
    winner_id = ranked[0]["id"]

    fields = op_get_item(winner_id, fields="username,password")
    if not fields:
        return None

    username = _get_field_value(fields, "username")
    password = _get_field_value(fields, "password")
    if not username or not password:
        return None

    return Credential(username=username, password=password, item_id=winner_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_credential(domain: str, preferred_emails: list[str]) -> Credential | None:
    """Resolve credentials for domain using priority order:
      1. macOS Keychain (silent, headless)
      2. 1Password CLI  (fallback, requires op without interactive auth)
      3. None           → auth.py falls back to manual browser login

    Never logs or writes credential values to disk.
    """
    # 1. Keychain (primary — no prompts, works headlessly)
    cred = _resolve_from_keychain(domain)
    if cred:
        print("Resolving LinkedIn credentials from Keychain...", flush=True)
        return cred

    # 2. 1Password fallback
    print("Keychain lookup failed — trying 1Password...", file=sys.stderr, flush=True)
    cred = _resolve_from_op(domain, preferred_emails)
    if cred:
        return cred

    # 3. Give up — auth.py opens manual browser login
    print(
        f"No credentials found for {domain} — falling back to manual login.",
        file=sys.stderr,
        flush=True,
    )
    return None
