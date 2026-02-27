"""JD match analysis: structured review of tailored resume vs JD.

FR-37: Produces analysis.md with Match Score, Strengths, Gaps, Interview Talking Points.
Fails gracefully — logs warning on error, returns empty string.
"""

from __future__ import annotations

from jobhunt.utils import log_warn


def run_analysis(
    jd_text: str,
    tailored_md: str,
    *,
    prompt_template: str,
    client,
    model: str,
    job_title: str = "",
    company: str = "",
) -> str:
    """Run JD match analysis via OpenAI. Returns markdown string.

    On any failure, logs a warning and returns empty string (best-effort).
    """
    from jobhunt.openai_client import analyze_fit

    try:
        result = analyze_fit(
            jd_text,
            tailored_md,
            prompt_template=prompt_template,
            client=client,
            model=model,
            job_title=job_title,
            company=company,
        )
        return result
    except Exception as exc:
        log_warn(f"Analysis generation failed: {exc}")
        return ""
