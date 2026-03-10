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
RESUMES_DIR: Path = DATA_DIR / "resumes"
PROMPTS_DIR: Path = DATA_DIR / "prompts"

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
            # Kept for backward compatibility; prefer fetch.urls in config.yaml
            "fetch_url": "https://www.linkedin.com/jobs/collections/recommended/",
        }
    },
    "fetch": {
        "limit": 10,
        "lookback": 7,
        "urls": [
            {"name": "recommended", "url": "https://www.linkedin.com/jobs/collections/recommended/"},
            {"name": "unicorn-companies", "url": "https://www.linkedin.com/jobs/collections/unicorn-companies/"},
            {"name": "top-startups", "url": "https://www.linkedin.com/jobs/collections/top-startups/"},
            {"name": "gen-ai", "url": "https://www.linkedin.com/jobs/collections/gen-ai/"},
            {"name": "ai-and-ml", "url": "https://www.linkedin.com/jobs/collections/ai-and-ml/"},
            {"name": "sustainability", "url": "https://www.linkedin.com/jobs/collections/sustainability/"},
            {"name": "remote-jobs", "url": "https://www.linkedin.com/jobs/collections/remote-jobs/"},
            {"name": "manufacturing", "url": "https://www.linkedin.com/jobs/collections/manufacturing/"},
            {"name": "small-business", "url": "https://www.linkedin.com/jobs/collections/small-business/"},
            {"name": "climate-and-cleantech", "url": "https://www.linkedin.com/jobs/collections/climate-and-cleantech/"},
            {"name": "mobility-tech", "url": "https://www.linkedin.com/jobs/collections/mobility-tech/"},
            {"name": "yc-funded", "url": "https://www.linkedin.com/jobs/collections/yc-funded/"},
            {"name": "real-estate", "url": "https://www.linkedin.com/jobs/collections/real-estate/"},
            {"name": "top-retail", "url": "https://www.linkedin.com/jobs/collections/top-retail/"},
        ],
    },
    "openai": {
        "model": "gpt-4o",
        "prompt_dir": "~/.openclaw/data/jobhunt/prompts",
    },
    "tailor": {
        "resume_factory_path": "~/code/openclaw-tools/resume-factory",
    },
    "classify": {
        "enabled": True,
        "title_patterns": [
            "software engineer",
            "staff.*(engineer|developer)",
            "principal.*(engineer|developer|architect)",
            "founding engineer",
            "engineering manager",
            "director.*(engineering|technology|software)",
            "vp.*(engineering|technology)",
            "cto",
            "chief technology",
            "architect",
            "machine learning",
            "ml engineer",
            "ai engineer",
            "data.*(scientist|engineer)",
            "platform engineer",
            "infrastructure engineer",
            "devops",
            "sre",
            "site reliability",
            "backend engineer",
            "frontend engineer",
            "fullstack",
            "full.stack",
        ],
        "min_salary": 180000,
        "min_level": [
            "staff", "principal", "senior", "lead", "founding",
            "manager", "director", "vp", "cto", "head", "chief",
        ],
    },
}

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def load_config() -> dict:
    """Load config.json, creating it with defaults if it doesn't exist.

    Exits with code 1 if the file exists but is malformed JSON.
    Missing keys from DEFAULT_CONFIG are backfilled lazily.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(_deep_copy(DEFAULT_CONFIG))
    try:
        config = json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"[ERROR] Config file is malformed JSON: {exc}\n"
            f"        Delete {CONFIG_PATH} to re-initialise.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Backfill missing top-level keys from defaults
    changed = False
    for key, default_val in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = _deep_copy(default_val)
            changed = True
    if changed:
        save_config(config)

    return config


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


def get_openai_model(config: dict) -> str:
    """Return the configured OpenAI model or default 'gpt-4o'."""
    return config.get("openai", {}).get("model", "gpt-4o")


def get_prompt_dir(config: dict) -> Path:
    """Return the configured prompt directory as an expanded Path."""
    raw = config.get("openai", {}).get("prompt_dir", str(PROMPTS_DIR))
    return Path(raw).expanduser()


def get_resume_factory_path(config: dict) -> Path:
    """Return the configured resume-factory path as an expanded Path."""
    raw = config.get("tailor", {}).get(
        "resume_factory_path", "~/code/openclaw-tools/resume-factory"
    )
    return Path(raw).expanduser()


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


def get_capsolver_api_key() -> str | None:
    """Return the CapSolver API key from env var or macOS Keychain.

    Priority:
    1. CAPSOLVER_API_KEY environment variable
    2. macOS Keychain (service="capsolver", account="apikey")
    3. Returns None if neither is available.
    """
    import os
    import subprocess

    key = os.environ.get("CAPSOLVER_API_KEY")
    if key:
        return key.strip()

    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "capsolver", "-a", "apikey", "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None
