"""Tests for pipeline.py — config loading, DB helpers, dry-run mode."""

from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest
import yaml

# Import pipeline module functions directly
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.pipeline import (
    _deep_merge,
    get_eligible_jobs,
    get_job,
    get_job_status,
    get_tailored_jobs,
    load_agent_config,
    load_config,
    load_prompt,
    run_agent,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_skill_dir(tmp_path: Path) -> Path:
    """Minimal skill dir with config.yaml and agent prompts."""
    cfg = {
        "pipeline": {
            "limit": 10,
            "tailor_timeout": 600,
            "apply_timeout": 1200,
            "thinking_level": "low",
        },
        "fetch": {"limit": 30, "lookback": 14},
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg))
    (tmp_path / "agents" / "tailor").mkdir(parents=True)
    (tmp_path / "agents" / "apply").mkdir(parents=True)
    (tmp_path / "agents" / "tailor" / "task_prompt.md").write_text(
        "Tailor job $job_id for $company at $skill_dir"
    )
    (tmp_path / "agents" / "apply" / "task_prompt.md").write_text(
        "Apply job $job_id with resume $resume_path"
    )
    (tmp_path / "agents" / "tailor" / "config.yaml").write_text(
        yaml.dump({"tailor_timeout": 600, "thinking_level": "low"})
    )
    (tmp_path / "agents" / "apply" / "config.yaml").write_text(
        yaml.dump({"apply_timeout": 1200, "thinking_level": "low"})
    )
    return tmp_path


@pytest.fixture()
def tmp_data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "logs").mkdir()
    (data / "resumes").mkdir()
    (data / "agents" / "tailor").mkdir(parents=True)
    (data / "agents" / "apply").mkdir(parents=True)
    return data


@pytest.fixture()
def tmp_db(tmp_data_dir: Path) -> Path:
    """SQLite DB with jobs table and sample rows."""
    db_path = tmp_data_dir / "scripts.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE jobs (
                id INTEGER PRIMARY KEY,
                platform TEXT,
                platform_id TEXT,
                title TEXT,
                company TEXT,
                job_url TEXT,
                status TEXT DEFAULT 'new',
                fetched_at TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO jobs (id, platform, platform_id, title, company, job_url, status, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "linkedin", "job1", "Engineer", "Acme", "https://acme.com/1", "new", "2026-02-28T00:00:00Z"),
                (2, "linkedin", "job2", "Manager", "Beta", "https://beta.com/2", "new", "2026-02-28T00:01:00Z"),
                (3, "linkedin", "job3", "Scientist", "Gamma", "https://gamma.com/3", "tailored", "2026-02-28T00:02:00Z"),
                (4, "linkedin", "job4", "Director", "Delta", "https://delta.com/4", "applied", "2026-02-28T00:03:00Z"),
            ]
        )
    return db_path


# ── Config loading ────────────────────────────────────────────────────────────

class TestLoadConfig:
    def test_loads_skill_dir_defaults(self, tmp_skill_dir: Path, tmp_data_dir: Path):
        cfg = load_config(tmp_skill_dir, tmp_data_dir)
        assert cfg["pipeline"]["tailor_timeout"] == 600
        assert cfg["pipeline"]["limit"] == 10

    def test_data_dir_overrides_skill_dir(self, tmp_skill_dir: Path, tmp_data_dir: Path):
        override = {"pipeline": {"tailor_timeout": 300}}
        (tmp_data_dir / "config.yaml").write_text(yaml.dump(override))
        cfg = load_config(tmp_skill_dir, tmp_data_dir)
        assert cfg["pipeline"]["tailor_timeout"] == 300
        # Other keys preserved from skill-dir default
        assert cfg["pipeline"]["limit"] == 10

    def test_deep_merge_nested(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99}}
        merged = _deep_merge(base, override)
        assert merged["a"]["x"] == 1
        assert merged["a"]["y"] == 99
        assert merged["b"] == 3

    def test_missing_skill_cfg(self, tmp_path: Path, tmp_data_dir: Path):
        """No skill config.yaml → empty dict, no crash."""
        cfg = load_config(tmp_path, tmp_data_dir)
        assert isinstance(cfg, dict)

    def test_missing_data_cfg(self, tmp_skill_dir: Path, tmp_data_dir: Path):
        """No data config.yaml → skill defaults only."""
        cfg = load_config(tmp_skill_dir, tmp_data_dir)
        assert cfg["pipeline"]["limit"] == 10


# ── Prompt loading ────────────────────────────────────────────────────────────

class TestLoadPrompt:
    def test_skill_dir_fallback(self, tmp_skill_dir: Path, tmp_data_dir: Path):
        prompt = load_prompt(
            "tailor",
            {"job_id": 42, "company": "TestCo", "skill_dir": "/skill"},
            data_dir=tmp_data_dir,
            skill_dir=tmp_skill_dir,
        )
        assert "42" in prompt
        assert "TestCo" in prompt

    def test_data_dir_override(self, tmp_skill_dir: Path, tmp_data_dir: Path):
        override_prompt = "OVERRIDE prompt for job $job_id"
        (tmp_data_dir / "agents" / "tailor" / "task_prompt.md").write_text(override_prompt)
        prompt = load_prompt(
            "tailor",
            {"job_id": 7},
            data_dir=tmp_data_dir,
            skill_dir=tmp_skill_dir,
        )
        assert "OVERRIDE" in prompt
        assert "7" in prompt

    def test_missing_prompt_raises(self, tmp_path: Path, tmp_data_dir: Path):
        with pytest.raises(FileNotFoundError):
            load_prompt("tailor", {}, data_dir=tmp_data_dir, skill_dir=tmp_path)

    def test_variable_substitution(self, tmp_skill_dir: Path, tmp_data_dir: Path):
        prompt = load_prompt(
            "apply",
            {"job_id": 5, "resume_path": "/data/resumes/5/tailored.md"},
            data_dir=tmp_data_dir,
            skill_dir=tmp_skill_dir,
        )
        assert "/data/resumes/5/tailored.md" in prompt


# ── Agent config loading ──────────────────────────────────────────────────────

class TestLoadAgentConfig:
    def test_role_overrides_global(self, tmp_skill_dir: Path, tmp_data_dir: Path):
        global_cfg = {"pipeline": {"tailor_timeout": 600, "thinking_level": "low"}}
        agent_cfg = load_agent_config("tailor", global_cfg, tmp_data_dir, tmp_skill_dir)
        assert agent_cfg["tailor_timeout"] == 600
        assert agent_cfg["thinking_level"] == "low"

    def test_data_dir_role_override(self, tmp_skill_dir: Path, tmp_data_dir: Path):
        (tmp_data_dir / "agents" / "tailor" / "config.yaml").write_text(
            yaml.dump({"tailor_timeout": 120})
        )
        global_cfg = {"pipeline": {"tailor_timeout": 600}}
        agent_cfg = load_agent_config("tailor", global_cfg, tmp_data_dir, tmp_skill_dir)
        assert agent_cfg["tailor_timeout"] == 120


# ── DB helpers ────────────────────────────────────────────────────────────────

class TestDBHelpers:
    def test_get_eligible_jobs_returns_new(self, tmp_db: Path):
        jobs = get_eligible_jobs(tmp_db, limit=10)
        assert all(j["status"] == "new" for j in jobs)
        assert len(jobs) == 2

    def test_get_eligible_jobs_respects_limit(self, tmp_db: Path):
        jobs = get_eligible_jobs(tmp_db, limit=1)
        assert len(jobs) == 1

    def test_get_tailored_jobs_requires_artifact(self, tmp_db: Path, tmp_data_dir: Path):
        # Job 3 is tailored but has no artifact yet
        jobs = get_tailored_jobs(tmp_db, limit=10, data_dir=tmp_data_dir)
        assert len(jobs) == 0

        # Create artifact
        resume_dir = tmp_data_dir / "resumes" / "3"
        resume_dir.mkdir(parents=True)
        (resume_dir / "tailored.md").write_text("# Resume")
        jobs = get_tailored_jobs(tmp_db, limit=10, data_dir=tmp_data_dir)
        assert len(jobs) == 1
        assert jobs[0]["id"] == 3

    def test_get_tailored_jobs_zero_limit(self, tmp_db: Path, tmp_data_dir: Path):
        jobs = get_tailored_jobs(tmp_db, limit=0, data_dir=tmp_data_dir)
        assert jobs == []

    def test_get_job_found(self, tmp_db: Path):
        job = get_job(tmp_db, 1)
        assert job is not None
        assert job["title"] == "Engineer"

    def test_get_job_not_found(self, tmp_db: Path):
        job = get_job(tmp_db, 999)
        assert job is None

    def test_get_job_status(self, tmp_db: Path):
        assert get_job_status(tmp_db, 1) == "new"
        assert get_job_status(tmp_db, 3) == "tailored"
        assert get_job_status(tmp_db, 4) == "applied"
        assert get_job_status(tmp_db, 999) is None

    def test_get_eligible_excludes_non_new(self, tmp_db: Path):
        jobs = get_eligible_jobs(tmp_db, limit=10)
        ids = [j["id"] for j in jobs]
        assert 3 not in ids  # tailored
        assert 4 not in ids  # applied


# ── Dry-run mode ──────────────────────────────────────────────────────────────

class TestRunAgent:
    def test_dry_run_returns_dry_run_dict(self):
        import logging
        log = logging.getLogger("test")
        result = run_agent(
            session_id="test-tailor-1",
            prompt="test prompt",
            timeout=60,
            thinking="low",
            dry_run=True,
            log=log,
        )
        assert result == {"dry_run": True}
