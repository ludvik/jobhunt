"""Tests for tailor.py: validation, base loading, write outputs, status transition."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jobhunt.db import get_job, init_db, upsert_job
from jobhunt.models import JobCard, TailorMeta
from jobhunt.tailor import (
    BASE_FILES,
    generate_pdf,
    load_base_markdown,
    run_tailor,
    validate_job_context,
    write_tailored_outputs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_card(platform_id: str = "1234567890") -> JobCard:
    return JobCard(
        platform_id=platform_id,
        title="Senior ML Engineer",
        company="OpenAI",
        location="San Francisco, CA",
        posted_at=datetime(2026, 2, 20, tzinfo=timezone.utc),
        job_url=f"https://www.linkedin.com/jobs/view/{platform_id}/",
    )


def _seed_job(conn: sqlite3.Connection, jd_text: str = "Build ML models and pipelines.", status: str = "new") -> int:
    card = _make_card()
    upsert_job(conn, card, jd_text, "hash123")
    row = conn.execute("SELECT id FROM jobs WHERE platform_id = ?", (card.platform_id,)).fetchone()
    job_id = row[0]
    if status != "new":
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        conn.commit()
    return job_id


def _make_config(tmp_path: Path) -> dict:
    """Create a minimal config dict for tailor tests."""
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    factory_dir = tmp_path / "resume-factory"
    factory_dir.mkdir()
    src_dir = factory_dir / "src"
    src_dir.mkdir()

    # Write base resume files
    for base_name, filename in BASE_FILES.items():
        (src_dir / filename).write_text(f"# {base_name} base resume\n\nContent here.")

    # Write prompt templates
    (prompt_dir / "classify.md").write_text("Classify: {{jd_text}}")
    (prompt_dir / "tailor.md").write_text("Tailor {{base_resume}} for {{jd_text}}")
    (prompt_dir / "analyze.md").write_text("Analyze {{tailored_resume}} vs {{jd_text}}")

    return {
        "openai": {"model": "gpt-4o", "prompt_dir": str(prompt_dir)},
        "tailor": {"resume_factory_path": str(factory_dir)},
    }


# ---------------------------------------------------------------------------
# validate_job_context
# ---------------------------------------------------------------------------


class TestValidateJobContext:
    def test_valid_job(self, tmp_db):
        job_id = _seed_job(tmp_db)
        job = validate_job_context(tmp_db, job_id)
        assert job["jd_text"] == "Build ML models and pipelines."

    def test_missing_job_raises(self, tmp_db):
        with pytest.raises(LookupError, match="not found"):
            validate_job_context(tmp_db, 99999)

    def test_empty_jd_raises(self, tmp_db):
        card = _make_card("empty_jd_pid")
        upsert_job(tmp_db, card, "", "emptyhash")
        row = tmp_db.execute("SELECT id FROM jobs WHERE platform_id = ?", ("empty_jd_pid",)).fetchone()
        # Empty string passes CHECK but should be treated as empty
        with pytest.raises(ValueError, match="JD text is empty"):
            validate_job_context(tmp_db, row[0])

    def test_null_jd_raises(self, tmp_db):
        # Insert with NULL jd_text via raw SQL
        tmp_db.execute(
            """INSERT INTO jobs (platform, platform_id, title, company, job_url, jd_text, jd_hash, status, fetched_at)
               VALUES ('linkedin', 'null_jd', 'Title', 'Company', 'url', NULL, 'hash', 'new', '2026-01-01T00:00:00Z')""",
        )
        tmp_db.commit()
        row = tmp_db.execute("SELECT id FROM jobs WHERE platform_id = 'null_jd'").fetchone()
        with pytest.raises(ValueError, match="JD text is empty"):
            validate_job_context(tmp_db, row[0])


# ---------------------------------------------------------------------------
# load_base_markdown
# ---------------------------------------------------------------------------


class TestLoadBaseMarkdown:
    def test_loads_ai_base(self, tmp_path):
        config = _make_config(tmp_path)
        md = load_base_markdown("ai", config)
        assert "ai base resume" in md

    def test_loads_mgmt_base(self, tmp_path):
        config = _make_config(tmp_path)
        md = load_base_markdown("mgmt", config)
        assert "mgmt base resume" in md

    def test_unknown_base_raises(self, tmp_path):
        config = _make_config(tmp_path)
        with pytest.raises(ValueError, match="Unknown base"):
            load_base_markdown("unknown", config)

    def test_missing_file_raises(self, tmp_path):
        config = {
            "tailor": {"resume_factory_path": str(tmp_path / "nonexistent")},
        }
        with pytest.raises(FileNotFoundError):
            load_base_markdown("ai", config)


# ---------------------------------------------------------------------------
# write_tailored_outputs
# ---------------------------------------------------------------------------


class TestWriteTailoredOutputs:
    def test_writes_all_files(self, tmp_path):
        out_dir = tmp_path / "42"
        meta = TailorMeta(
            job_id=42,
            base="ai",
            model="gpt-4o",
            created_at_utc="2026-02-26T00:00:00Z",
            tailor_prompt_version="abc123",
            resume_factory_cmd="python generate_pdf.py",
        )
        write_tailored_outputs(out_dir, "# Tailored Resume", meta, "## Analysis")

        assert (out_dir / "tailored.md").exists()
        assert (out_dir / "meta.json").exists()
        assert (out_dir / "analysis.md").exists()

        assert (out_dir / "tailored.md").read_text() == "# Tailored Resume"
        meta_data = json.loads((out_dir / "meta.json").read_text())
        assert meta_data["job_id"] == 42
        assert meta_data["base"] == "ai"
        assert meta_data["model"] == "gpt-4o"
        assert (out_dir / "analysis.md").read_text() == "## Analysis"

    def test_no_analysis_when_empty(self, tmp_path):
        out_dir = tmp_path / "43"
        meta = TailorMeta(
            job_id=43, base="ic", model="gpt-4o",
            created_at_utc="2026-02-26", tailor_prompt_version="x", resume_factory_cmd="cmd",
        )
        write_tailored_outputs(out_dir, "# Resume", meta, "")

        assert (out_dir / "tailored.md").exists()
        assert (out_dir / "meta.json").exists()
        assert not (out_dir / "analysis.md").exists()

    def test_creates_directory(self, tmp_path):
        out_dir = tmp_path / "nested" / "dir" / "44"
        meta = TailorMeta(
            job_id=44, base="ai", model="gpt-4o",
            created_at_utc="2026-02-26", tailor_prompt_version="x", resume_factory_cmd="cmd",
        )
        write_tailored_outputs(out_dir, "# Resume", meta)
        assert out_dir.exists()


# ---------------------------------------------------------------------------
# run_tailor (integration, with mocked OpenAI)
# ---------------------------------------------------------------------------


class TestRunTailor:
    def _mock_openai_calls(self, classify_resp="ai", tailor_resp="# Tailored", analyze_resp="## Analysis"):
        """Return patches for OpenAI calls."""
        return (
            patch("jobhunt.tailor.resolve_openai_key", return_value="sk-test"),
            patch("jobhunt.tailor._make_client", return_value=MagicMock()),
            patch("jobhunt.tailor.classify_jd", return_value=classify_resp),
            patch("jobhunt.tailor.rewrite_resume", return_value=tailor_resp),
            patch("jobhunt.tailor.generate_pdf", return_value=False),
            patch("jobhunt.openai_client.analyze_fit", return_value=analyze_resp),
        )

    def test_tailor_new_job_transitions_to_tailored(self, tmp_db, tmp_path):
        config = _make_config(tmp_path)
        job_id = _seed_job(tmp_db)

        patches = self._mock_openai_calls()
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4], patches[5],
            patch("jobhunt.tailor.RESUMES_DIR", tmp_path / "resumes"),
        ):
            result = run_tailor(
                tmp_db, job_id,
                base_override=None,
                dry_run=False,
                skip_analyze=False,
                config=config,
            )

        assert result.success
        assert result.base == "ai"
        job = get_job(tmp_db, job_id)
        assert job["status"] == "tailored"

    def test_tailor_with_base_override_skips_classify(self, tmp_db, tmp_path):
        config = _make_config(tmp_path)
        job_id = _seed_job(tmp_db)

        mock_classify = MagicMock()
        with (
            patch("jobhunt.tailor.resolve_openai_key", return_value="sk-test"),
            patch("jobhunt.tailor._make_client", return_value=MagicMock()),
            patch("jobhunt.tailor.classify_jd", mock_classify),
            patch("jobhunt.tailor.rewrite_resume", return_value="# Tailored"),
            patch("jobhunt.tailor.generate_pdf", return_value=False),
            patch("jobhunt.tailor.RESUMES_DIR", tmp_path / "resumes"),
        ):
            result = run_tailor(
                tmp_db, job_id,
                base_override="mgmt",
                dry_run=False,
                skip_analyze=True,
                config=config,
            )

        assert result.success
        assert result.base == "mgmt"
        mock_classify.assert_not_called()

    def test_dry_run_no_side_effects(self, tmp_db, tmp_path, capsys):
        config = _make_config(tmp_path)
        job_id = _seed_job(tmp_db)
        resumes_dir = tmp_path / "resumes"

        with (
            patch("jobhunt.tailor.resolve_openai_key", return_value="sk-test"),
            patch("jobhunt.tailor._make_client", return_value=MagicMock()),
            patch("jobhunt.tailor.classify_jd", return_value="ic"),
            patch("jobhunt.tailor.rewrite_resume", return_value="# Dry Run Output"),
            patch("jobhunt.tailor.RESUMES_DIR", resumes_dir),
        ):
            result = run_tailor(
                tmp_db, job_id,
                base_override=None,
                dry_run=True,
                skip_analyze=False,
                config=config,
            )

        assert result.success
        assert result.dry_run
        # No files written
        assert not (resumes_dir / str(job_id)).exists()
        # Status unchanged
        job = get_job(tmp_db, job_id)
        assert job["status"] == "new"
        # Output to stdout
        captured = capsys.readouterr()
        assert "# Dry Run Output" in captured.out

    def test_retailor_preserves_non_new_status(self, tmp_db, tmp_path):
        """FR-28: Re-tailor on blocked job should not change status."""
        config = _make_config(tmp_path)
        job_id = _seed_job(tmp_db, status="blocked")

        patches = self._mock_openai_calls()
        with (
            patches[0], patches[1], patches[2], patches[3], patches[4], patches[5],
            patch("jobhunt.tailor.RESUMES_DIR", tmp_path / "resumes"),
        ):
            result = run_tailor(
                tmp_db, job_id,
                base_override="ai",
                dry_run=False,
                skip_analyze=True,
                config=config,
            )

        assert result.success
        job = get_job(tmp_db, job_id)
        assert job["status"] == "blocked"  # preserved

    def test_skip_analyze_no_analysis_file(self, tmp_db, tmp_path):
        config = _make_config(tmp_path)
        job_id = _seed_job(tmp_db)
        resumes_dir = tmp_path / "resumes"

        with (
            patch("jobhunt.tailor.resolve_openai_key", return_value="sk-test"),
            patch("jobhunt.tailor._make_client", return_value=MagicMock()),
            patch("jobhunt.tailor.classify_jd", return_value="ai"),
            patch("jobhunt.tailor.rewrite_resume", return_value="# Resume"),
            patch("jobhunt.tailor.generate_pdf", return_value=False),
            patch("jobhunt.tailor.RESUMES_DIR", resumes_dir),
        ):
            result = run_tailor(
                tmp_db, job_id,
                base_override=None,
                dry_run=False,
                skip_analyze=True,
                config=config,
            )

        assert result.success
        assert not result.analysis_ok
        assert not (resumes_dir / str(job_id) / "analysis.md").exists()

    def test_missing_job_raises(self, tmp_db, tmp_path):
        config = _make_config(tmp_path)
        with pytest.raises(LookupError, match="not found"):
            run_tailor(
                tmp_db, 99999,
                base_override=None,
                dry_run=False,
                skip_analyze=False,
                config=config,
            )

    def test_empty_jd_raises(self, tmp_db, tmp_path):
        config = _make_config(tmp_path)
        job_id = _seed_job(tmp_db, jd_text="")
        with pytest.raises(ValueError, match="JD text is empty"):
            run_tailor(
                tmp_db, job_id,
                base_override=None,
                dry_run=False,
                skip_analyze=False,
                config=config,
            )


# ---------------------------------------------------------------------------
# generate_pdf (best-effort)
# ---------------------------------------------------------------------------


class TestGeneratePdf:
    def test_missing_uv_returns_false(self, tmp_path):
        with patch("shutil.which", side_effect=lambda x: None if x == "uv" else "/usr/bin/" + x):
            result = generate_pdf(tmp_path, {"tailor": {"resume_factory_path": str(tmp_path)}})
        assert result is False

    def test_missing_pandoc_returns_false(self, tmp_path):
        with patch("shutil.which", side_effect=lambda x: None if x == "pandoc" else "/usr/bin/" + x):
            result = generate_pdf(tmp_path, {"tailor": {"resume_factory_path": str(tmp_path)}})
        assert result is False
