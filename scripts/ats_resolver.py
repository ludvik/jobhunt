"""ats_resolver.py — ATS platform detection and iframe extraction helpers.

Provides:
- classify_ats_from_url(url) -> platform name string
- choose_primary_ats_iframe(src_list) -> best iframe src or None
- IFRAME_EXTRACT_JS — JS snippet to collect all iframe srcs via browser eval
- load_ats_cache() / save_ats_cache() / update_ats_cache() — persistent host cache
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# ── Cache path ────────────────────────────────────────────────────────────────
ATS_CACHE_PATH: Path = (
    Path.home() / ".openclaw" / "data" / "jobhunt" / "ats-host-cache.json"
)

# ── ATS domain patterns (ordered: most specific first) ────────────────────────
# Each entry: (platform_name, list_of_domain_substrings)
_ATS_DOMAIN_PATTERNS: list[tuple[str, list[str]]] = [
    ("greenhouse",      ["greenhouse.io", "boards.greenhouse", "job-boards.greenhouse"]),
    ("lever",           ["lever.co", "jobs.lever.co"]),
    ("ashby",           ["ashbyhq.com", "jobs.ashbyhq.com"]),
    ("workday",         ["myworkdayjobs.com", "workday.com/en-us/pages"]),
    ("icims",           ["icims.com", "careers.icims.com"]),
    ("successfactors",  ["successfactors.com", "sapsf.com"]),
    ("oracle_hcm",      ["oraclecloud.com", "oracle.com/orc", "taleo.net"]),
    ("smartrecruiters", ["smartrecruiters.com"]),
    ("rippling",        ["rippling.com"]),
    ("bamboohr",        ["bamboohr.com"]),
]

# Regex patterns for path-based detection (applied after domain match fails)
_ATS_PATH_PATTERNS: list[tuple[str, str]] = [
    ("greenhouse",      r"/jobs/\d+"),
    ("lever",           r"/apply/"),
    ("workday",         r"/job/\w+/apply"),
    ("icims",           r"/connect/\w+/job"),
]


def classify_ats_from_url(url: str) -> str:
    """Identify the ATS platform from a URL string.

    Returns one of:
        greenhouse | lever | ashby | workday | icims | successfactors |
        oracle_hcm | smartrecruiters | rippling | bamboohr | generic
    """
    if not url:
        return "generic"

    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()
        full = url.lower()
    except Exception:
        return "generic"

    # 1. Domain substring match (most reliable)
    for platform, domains in _ATS_DOMAIN_PATTERNS:
        for domain in domains:
            if domain in netloc or domain in full:
                return platform

    # 2. Path regex fallback
    for platform, pattern in _ATS_PATH_PATTERNS:
        if re.search(pattern, path, re.IGNORECASE):
            return platform

    return "generic"


def choose_primary_ats_iframe(src_list: list[str]) -> str | None:
    """Select the best ATS iframe src from a list of iframe src values.

    Preference order:
    1. Known ATS platforms (first match wins, ordered by _ATS_DOMAIN_PATTERNS priority)
    2. First non-empty src as fallback
    Returns None if src_list is empty.
    """
    if not src_list:
        return None

    srcs = [s for s in src_list if s and s.strip() and s.strip() != "about:blank"]
    if not srcs:
        return None

    # Score each src by platform priority index (lower = better known)
    def _priority(src: str) -> int:
        platform = classify_ats_from_url(src)
        if platform == "generic":
            return len(_ATS_DOMAIN_PATTERNS) + 1  # lowest priority
        for idx, (name, _) in enumerate(_ATS_DOMAIN_PATTERNS):
            if name == platform:
                return idx
        return len(_ATS_DOMAIN_PATTERNS)

    return min(srcs, key=_priority)


# ── JS snippet for browser eval ───────────────────────────────────────────────
IFRAME_EXTRACT_JS: str = (
    "Array.from(document.querySelectorAll('iframe'))"
    ".map(f => f.src || f.getAttribute('src') || '')"
    ".filter(s => s.length > 0)"
)
"""JS expression that collects all iframe srcs on the current page.

Usage in apply agent:
    srcs = browser(action="act", request={"kind": "evaluate",
                   "fn": IFRAME_EXTRACT_JS}, ...)
"""


# ── Persistent cache helpers ──────────────────────────────────────────────────

def load_ats_cache() -> dict:
    """Load the ATS host cache from disk. Returns empty dict if missing/corrupt."""
    if not ATS_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(ATS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ats_cache(cache: dict) -> None:
    """Persist the ATS host cache to disk."""
    ATS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ATS_CACHE_PATH.write_text(
        json.dumps(cache, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def update_ats_cache(
    host: str,
    platform: str,
    iframe_src: str = "",
) -> None:
    """Upsert a host -> platform mapping into the ATS host cache.

    Args:
        host:       Bare hostname, e.g. "sofi.com"
        platform:   ATS platform name, e.g. "greenhouse"
        iframe_src: The full iframe src URL that confirmed the platform (optional)
    """
    if not host or not platform:
        return

    cache = load_ats_cache()
    cache[host] = {
        "platform": platform,
        "iframe_src": iframe_src,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_ats_cache(cache)


def get_ats_hint_for_url(job_url: str) -> dict | None:
    """Return the cached ATS entry for the given job URL's host, or None."""
    if not job_url:
        return None
    try:
        host = urlparse(job_url).netloc.lower()
    except Exception:
        return None
    if not host:
        return None
    cache = load_ats_cache()
    return cache.get(host)
