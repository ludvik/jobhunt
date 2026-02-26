"""Configuration management: path constants, config.json read/write.

FR-18: Auto-create data directory on first use.
FR-19: config.json managed via jobhunt config subcommand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants — the single source of truth for all runtime data locations
# ---------------------------------------------------------------------------

DATA_DIR: Path = Path.home() / ".openclaw" / "data" / "jobhunt"
SESSION_DIR: Path = DATA_DIR / "session"
DB_PATH: Path = DATA_DIR / "jobhunt.db"
SESSION_PATH: Path = SESSION_DIR / "linkedin.json"
CONFIG_PATH: Path = DATA_DIR / "config.json"

# ---------------------------------------------------------------------------
# Default config structure (auto-created on first run)
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict = {
    "credential_preferences": {
        "preferred_emails": [
            "haomin_liu@hotmail.com",
            "haomin.liu@gmail.com",
        ]
    },
    "sources": {
        "linkedin": {
            "op_domain": "linkedin.com",
            "fetch_url": "https://www.linkedin.com/jobs/collections/recommended/",
        }
    },
}

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def load_config() -> dict:
    """Load config.json, creating it with defaults if it doesn't exist.

    Exits with code 1 if the file exists but is malformed JSON.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(_deep_copy(DEFAULT_CONFIG))
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"[ERROR] Config file is malformed JSON: {exc}\n"
            f"        Delete {CONFIG_PATH} to re-initialise.",
            file=sys.stderr,
        )
        sys.exit(1)


def save_config(config: dict) -> None:
    """Write config dict to CONFIG_PATH as pretty-printed JSON."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def prepend_preferred_email(config: dict, email: str) -> dict:
    """Prepend email to preferred_emails list (highest priority).

    If the email is already in the list it is moved to the front.
    Modifies config in place and returns it.
    """
    prefs = config.setdefault("credential_preferences", {})
    emails: list[str] = prefs.setdefault("preferred_emails", [])
    if email in emails:
        emails.remove(email)
    emails.insert(0, email)
    return config


def print_config(config: dict) -> None:
    """Print config dict as pretty-printed JSON to stdout."""
    print(json.dumps(config, indent=2))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deep_copy(obj):
    """Minimal deep-copy for dicts/lists of scalars (no third-party deps)."""
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(v) for v in obj]
    return obj
