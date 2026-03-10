"""CAPTCHA solving via CapSolver API.

Supports reCAPTCHA Enterprise (v2 enterprise) using CapSolver's
ReCaptchaV2EnterpriseTaskProxyLess task type.

No additional dependencies — uses `requests` (already in project deps).
API key is never hardcoded; always read from env or Keychain.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from scripts.config import get_capsolver_api_key

log = logging.getLogger("jobhunt.captcha")

_CAPSOLVER_CREATE_URL = "https://api.capsolver.com/createTask"
_CAPSOLVER_RESULT_URL = "https://api.capsolver.com/getTaskResult"
_POLL_INTERVAL_S = 3
_TIMEOUT_S = 60


def solve_recaptcha_enterprise(
    site_key: str,
    page_url: str,
    api_key: str | None = None,
) -> str | None:
    """Solve a reCAPTCHA Enterprise challenge via CapSolver.

    Args:
        site_key: The reCAPTCHA site key from the page.
        page_url: The URL of the page hosting the CAPTCHA.
        api_key:  CapSolver API key. If None, auto-reads from env/Keychain.

    Returns:
        The reCAPTCHA token string on success, or None on failure/timeout.
    """
    resolved_key = api_key or get_capsolver_api_key()
    if not resolved_key:
        log.error(
            "No CapSolver API key found. Set CAPSOLVER_API_KEY env var "
            "or store in Keychain (service=capsolver, account=apikey)."
        )
        return None

    task_id = _create_task(resolved_key, site_key, page_url)
    if not task_id:
        return None

    return _poll_result(resolved_key, task_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _create_task(api_key: str, site_key: str, page_url: str) -> str | None:
    """Submit a createTask request to CapSolver.

    Returns the task_id string, or None on error.
    """
    payload: dict[str, Any] = {
        "clientKey": api_key,
        "task": {
            "type": "ReCaptchaV3EnterpriseTaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": site_key,
            "pageAction": "apply_to_job",
        },
    }
    log.info("Creating CapSolver task for %s", page_url)
    try:
        resp = requests.post(_CAPSOLVER_CREATE_URL, json=payload, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error("CapSolver createTask request failed: %s", exc)
        return None

    data = resp.json()
    if data.get("errorId", 0) != 0:
        log.error(
            "CapSolver createTask error %s: %s",
            data.get("errorCode"),
            data.get("errorDescription"),
        )
        return None

    task_id: str = data.get("taskId", "")
    if not task_id:
        log.error("CapSolver returned no taskId: %s", data)
        return None

    log.info("CapSolver task created: %s", task_id)
    return task_id


def _poll_result(api_key: str, task_id: str) -> str | None:
    """Poll CapSolver getTaskResult until ready or timeout.

    Returns the gRecaptchaResponse token, or None on failure/timeout.
    """
    payload = {"clientKey": api_key, "taskId": task_id}
    deadline = time.monotonic() + _TIMEOUT_S

    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL_S)
        log.debug("Polling CapSolver result for task %s", task_id)
        try:
            resp = requests.post(_CAPSOLVER_RESULT_URL, json=payload, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("CapSolver getTaskResult request failed (will retry): %s", exc)
            continue

        data = resp.json()
        if data.get("errorId", 0) != 0:
            log.error(
                "CapSolver getTaskResult error %s: %s",
                data.get("errorCode"),
                data.get("errorDescription"),
            )
            return None

        status = data.get("status", "")
        if status == "ready":
            token: str | None = data.get("solution", {}).get("gRecaptchaResponse")
            if token:
                log.info("CapSolver solved CAPTCHA successfully (token length=%d)", len(token))
            else:
                log.error("CapSolver status=ready but no token in solution: %s", data)
            return token

        if status == "processing":
            log.debug("CapSolver task still processing...")
            continue

        # Unexpected status
        log.error("CapSolver unexpected status=%r: %s", status, data)
        return None

    log.error("CapSolver timed out after %ds waiting for task %s", _TIMEOUT_S, task_id)
    return None
