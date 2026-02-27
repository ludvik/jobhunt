"""OpenAI API integration: key resolution, retry, prompt loading.

FR-33: Key from macOS Keychain first, fallback to OPENAI_API_KEY env.
FR-34: Prompt templates loaded from configurable directory.
NFR-02: Retry with exponential backoff on 429/5xx.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

from jobhunt.utils import log_warn

# ---------------------------------------------------------------------------
# Key resolution (FR-33)
# ---------------------------------------------------------------------------


def resolve_openai_key() -> str:
    """Resolve OpenAI API key: macOS Keychain first, then env var.

    Raises RuntimeError if neither source provides a key.
    Never logs the key value.
    """
    # 1. macOS Keychain
    from jobhunt.credentials import read_keychain

    key = read_keychain("openai")
    if isinstance(key, str) and key:
        return key

    # 2. Environment variable fallback
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key

    raise RuntimeError(
        "OpenAI API key not found (keychain and OPENAI_API_KEY missing)"
    )


# ---------------------------------------------------------------------------
# Prompt template loading (FR-34)
# ---------------------------------------------------------------------------


def load_prompt_template(path: Path | str) -> str:
    """Read a prompt template file. Raises FileNotFoundError if missing."""
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Prompt template not found: {p}")
    return p.read_text()


def render_prompt(template: str, **kwargs: str) -> str:
    """Replace {{variable}} placeholders in a template string."""
    result = template
    for key, value in kwargs.items():
        result = result.replace("{{" + key + "}}", value)
    return result


def prompt_version(template_text: str) -> str:
    """Return SHA-256 hex digest of prompt text (for meta.json tracking)."""
    return hashlib.sha256(template_text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# OpenAI API calls with retry (NFR-02)
# ---------------------------------------------------------------------------

_RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_BACKOFF = (1, 2, 4)


def _make_client(api_key: str):
    """Create an OpenAI client instance."""
    import openai

    return openai.OpenAI(api_key=api_key)


def call_openai(
    prompt: str,
    model: str,
    client,
    *,
    system_prompt: str | None = None,
) -> str:
    """Single LLM call with retry on transient failures.

    Returns the assistant's message content string.
    Raises on persistent failure after retries.
    """
    import openai

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    last_exc = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
            )
            return response.choices[0].message.content.strip()
        except openai.APIStatusError as exc:
            if exc.status_code in _RETRIABLE_STATUS_CODES:
                last_exc = exc
                if attempt < _MAX_ATTEMPTS - 1:
                    log_warn(
                        f"OpenAI {exc.status_code} on attempt {attempt + 1}/{_MAX_ATTEMPTS}, "
                        f"retrying in {_BACKOFF[attempt]}s..."
                    )
                    time.sleep(_BACKOFF[attempt])
                continue
            raise
        except openai.APIConnectionError as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                log_warn(
                    f"OpenAI connection error on attempt {attempt + 1}/{_MAX_ATTEMPTS}, "
                    f"retrying in {_BACKOFF[attempt]}s..."
                )
                time.sleep(_BACKOFF[attempt])
            continue

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# High-level prompt call functions
# ---------------------------------------------------------------------------


def classify_jd(
    jd_text: str,
    *,
    prompt_template: str,
    client,
    model: str,
    job_title: str = "",
    company: str = "",
) -> str:
    """Classify JD text into one of: ai, ic, mgmt, venture.

    Returns the canonical direction string.
    Raises ValueError if the model returns an invalid classification.
    """
    prompt = render_prompt(
        prompt_template,
        jd_text=jd_text,
        job_title=job_title,
        company=company,
    )
    raw = call_openai(prompt, model, client)

    # Try to extract JSON first
    import json

    try:
        data = json.loads(raw)
        direction = data.get("direction", "").strip().lower()
    except (json.JSONDecodeError, AttributeError):
        direction = raw.strip().lower()

    # Validate
    valid = {"ai", "ic", "mgmt", "venture"}
    # Try regex extraction as last resort
    if direction not in valid:
        match = re.search(r"\b(ai|ic|mgmt|venture)\b", direction)
        if match:
            direction = match.group(1)

    if direction not in valid:
        raise ValueError(
            f"Invalid classification response: {raw!r}. Expected one of: {valid}"
        )

    return direction


def rewrite_resume(
    jd_text: str,
    base_resume: str,
    *,
    prompt_template: str,
    client,
    model: str,
    job_title: str = "",
    company: str = "",
    base_name: str = "",
) -> str:
    """Call OpenAI to rewrite a base resume for the given JD.

    Returns the tailored markdown string.
    """
    prompt = render_prompt(
        prompt_template,
        jd_text=jd_text,
        base_resume=base_resume,
        job_title=job_title,
        company=company,
        base_name=base_name,
    )
    return call_openai(prompt, model, client)


def analyze_fit(
    jd_text: str,
    tailored_resume: str,
    *,
    prompt_template: str,
    client,
    model: str,
    job_title: str = "",
    company: str = "",
) -> str:
    """Call OpenAI to produce a structured match analysis.

    Returns markdown with Match Score, Strengths, Gaps, Interview Talking Points.
    """
    prompt = render_prompt(
        prompt_template,
        jd_text=jd_text,
        tailored_resume=tailored_resume,
        job_title=job_title,
        company=company,
    )
    return call_openai(prompt, model, client)
