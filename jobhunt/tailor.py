"""Resume tailoring workflow: end-to-end orchestration for one job.

FR-21/22: Input validation (job exists, jd_text non-empty).
FR-23: Base direction auto-selection or override.
FR-24/25: Tailored resume generation and persistence.
FR-26: Best-effort PDF generation via resume-factory.
FR-27: Dry-run mode (stdout only, no side effects).
FR-28: Auto status transition new→tailored on success.
FR-37: Optional match analysis.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from jobhunt.config import RESUMES_DIR, get_openai_model, get_prompt_dir, get_resume_factory_path
from jobhunt.models import TailorMeta, TailorResult
from jobhunt.openai_client import (
    classify_jd,
    load_prompt_template,
    prompt_version,
    render_prompt,
    resolve_openai_key,
    rewrite_resume,
    _make_client,
)
from jobhunt.utils import log_info, log_warn, log_error, utcnow_iso

# ---------------------------------------------------------------------------
# Base file mapping (FR-23)
# ---------------------------------------------------------------------------

BASE_FILES: dict[str, str] = {
    "ai": "base-cv-ai-engineer.md",
    "ic": "base-resume-ic.md",
    "mgmt": "base-resume-mgmt.md",
    "venture": "base-resume-venture-builder.md",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_job_context(conn, job_id: int) -> dict:
    """Load job row and validate it has non-empty jd_text.

    Raises LookupError if job not found.
    Raises ValueError if jd_text is empty.
    """
    from jobhunt.db import get_job

    job = get_job(conn, job_id)
    if job is None:
        raise LookupError(f"job not found")
    if not job.get("jd_text"):
        raise ValueError("JD text is empty")
    return job


# ---------------------------------------------------------------------------
# Base direction selection
# ---------------------------------------------------------------------------


def load_base_markdown(base: str, config: dict) -> str:
    """Load base resume markdown from resume-factory source directory."""
    filename = BASE_FILES.get(base)
    if not filename:
        raise ValueError(f"Unknown base direction: {base}")
    factory_path = get_resume_factory_path(config)
    path = factory_path / "src" / filename
    if not path.exists():
        raise FileNotFoundError(f"Base resume file not found: {path}")
    return path.read_text()


# ---------------------------------------------------------------------------
# PDF generation (FR-26, FR-35)
# ---------------------------------------------------------------------------


def generate_pdf(out_dir: Path, config: dict) -> bool:
    """Best-effort PDF generation via resume-factory.

    Returns True on success, False on failure (with warning logged).
    """
    # Check dependencies
    for tool in ("uv", "pandoc", "xelatex"):
        if not shutil.which(tool):
            log_warn(f"PDF generation failed: {tool} not found in PATH")
            return False

    factory_path = get_resume_factory_path(config)
    generate_script = factory_path / "generate_pdf.py"
    if not generate_script.exists():
        log_warn(f"PDF generation failed: {generate_script} not found")
        return False

    tailored_md = out_dir / "tailored.md"
    resume_pdf = out_dir / "resume.pdf"

    try:
        result = subprocess.run(
            ["python", str(generate_script), "--md", str(tailored_md), "--pdf", str(resume_pdf)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            log_warn(f"PDF generation failed: {result.stderr.strip()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log_warn("PDF generation failed: timeout exceeded")
        return False
    except Exception as exc:
        log_warn(f"PDF generation failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Artifact persistence (FR-25)
# ---------------------------------------------------------------------------


def write_tailored_outputs(
    out_dir: Path,
    tailored_md: str,
    meta: TailorMeta,
    analysis_text: str = "",
) -> None:
    """Write tailored.md, meta.json, and optionally analysis.md."""
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "tailored.md").write_text(tailored_md)

    meta_dict = {
        "job_id": meta.job_id,
        "base": meta.base,
        "model": meta.model,
        "created_at_utc": meta.created_at_utc,
        "tailor_prompt_version": meta.tailor_prompt_version,
        "resume_factory_cmd": meta.resume_factory_cmd,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta_dict, indent=2) + "\n")

    if analysis_text:
        (out_dir / "analysis.md").write_text(analysis_text)


# ---------------------------------------------------------------------------
# Main workflow (FR-21–FR-28, FR-37)
# ---------------------------------------------------------------------------


def run_tailor(
    conn,
    job_id: int,
    *,
    base_override: str | None,
    dry_run: bool,
    skip_analyze: bool,
    config: dict,
    classify_prompt_path: str | None = None,
    tailor_prompt_path: str | None = None,
    analyze_prompt_path: str | None = None,
) -> TailorResult:
    """End-to-end tailor workflow for a single job.

    1. Validate job context
    2. Resolve OpenAI key and create client
    3. Classify JD (or use override)
    4. Load base resume
    5. Rewrite resume via OpenAI
    6. Write artifacts (unless dry-run)
    7. Auto-transition status new→tailored (unless dry-run)
    8. Run analysis (unless skip or dry-run)
    9. Generate PDF (best-effort, unless dry-run)
    """
    # Step 1: Validate
    job = validate_job_context(conn, job_id)

    # Step 2: OpenAI setup
    api_key = resolve_openai_key()
    client = _make_client(api_key)
    model = get_openai_model(config)
    prompt_dir = get_prompt_dir(config)

    # Step 3: Classify or use override
    if base_override:
        base = base_override
    else:
        classify_path = classify_prompt_path or str(prompt_dir / "classify.md")
        classify_template = load_prompt_template(classify_path)
        base = classify_jd(
            job["jd_text"],
            prompt_template=classify_template,
            client=client,
            model=model,
            job_title=job["title"],
            company=job["company"],
        )

    # Step 4: Load base resume
    base_md = load_base_markdown(base, config)

    # Step 5: Rewrite resume
    tailor_path = tailor_prompt_path or str(prompt_dir / "tailor.md")
    tailor_template = load_prompt_template(tailor_path)
    tailored_md = rewrite_resume(
        job["jd_text"],
        base_md,
        prompt_template=tailor_template,
        client=client,
        model=model,
        job_title=job["title"],
        company=job["company"],
        base_name=base,
    )

    # Step 6: Dry-run → print and return
    if dry_run:
        print(tailored_md)
        return TailorResult(success=True, tailored_md=tailored_md, base=base, dry_run=True)

    # Step 7: Write artifacts
    out_dir = RESUMES_DIR / str(job_id)
    factory_path = get_resume_factory_path(config)
    meta = TailorMeta(
        job_id=job_id,
        base=base,
        model=model,
        created_at_utc=utcnow_iso(),
        tailor_prompt_version=prompt_version(tailor_template),
        resume_factory_cmd=f"python {factory_path}/generate_pdf.py --md tailored.md --pdf resume.pdf",
    )

    # Step 8: Analysis (before writing, so we can include it)
    analysis_text = ""
    analysis_ok = False
    if not skip_analyze:
        from jobhunt.analyzer import run_analysis

        analyze_path = analyze_prompt_path or str(prompt_dir / "analyze.md")
        try:
            analyze_template = load_prompt_template(analyze_path)
            analysis_text = run_analysis(
                job["jd_text"],
                tailored_md,
                prompt_template=analyze_template,
                client=client,
                model=model,
                job_title=job["title"],
                company=job["company"],
            )
            analysis_ok = bool(analysis_text)
        except FileNotFoundError:
            log_warn(f"Analysis prompt not found: {analyze_path}")
        except Exception as exc:
            log_warn(f"Analysis generation failed: {exc}")

    write_tailored_outputs(out_dir, tailored_md, meta, analysis_text)

    # Step 9: Auto-transition new → tailored (FR-28)
    if job["status"] == "new":
        from jobhunt.db import set_job_status

        try:
            set_job_status(conn, job_id, "tailored", current_status="new")
        except (ValueError, LookupError) as exc:
            log_warn(f"Status transition failed: {exc}")

    # Step 10: PDF generation (best-effort)
    pdf_ok = generate_pdf(out_dir, config)
    if not pdf_ok:
        print("Warning: PDF generation failed (tailored.md retained)", file=sys.stderr)

    log_info(f"Tailored resume written to {out_dir}")
    return TailorResult(
        success=True,
        tailored_md=tailored_md,
        base=base,
        pdf_ok=pdf_ok,
        analysis_ok=analysis_ok,
    )
