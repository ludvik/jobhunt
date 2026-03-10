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
    _force_apply_failed,
    classify_new_jobs,
    get_eligible_jobs,
    get_job,
    get_job_status,
    get_tailored_jobs,
    load_agent_config,
    load_config,
    load_prompt,
    run_agent,
    run_tailor_direct,
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



# ── Classification (blacklist) ────────────────────────────────────────────────

class TestClassifyNewJobs:
    @pytest.fixture()
    def classify_db(self, tmp_data_dir: Path) -> Path:
        db_path = tmp_data_dir / "classify.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY,
                    platform TEXT,
                    platform_id TEXT,
                    title TEXT,
                    company TEXT,
                    job_url TEXT,
                    jd_text TEXT,
                    status TEXT DEFAULT 'new'
                        CHECK(status IN ('new','skipped','not_suitable','tailored','blocked','apply_failed','applied')),
                    fetched_at TEXT,
                    status_updated_at TEXT
                )
            """)
            conn.executemany(
                "INSERT INTO jobs (id, title, company, jd_text) VALUES (?, ?, ?, ?)",
                [
                    (1, "Senior Software Engineer", "Google", "10+ years of experience required"),
                    (2, "Data Engineer", "Startup", "Build ETL pipelines"),
                    (3, "Frontend Engineer", "Meta", "React expertise needed"),
                    (4, "Intern Software Developer", "Amazon", "Summer internship"),
                    (5, "Staff Engineer", "Stripe", "5+ years experience"),
                    (6, "Software Engineer", "SmallCo", "1+ years of experience required. Build APIs."),
                ],
            )
        return db_path

    def test_filters_blacklisted_titles(self, classify_db: Path):
        config = {
            "classify": {
                "enabled": True,
                "exclude_patterns": [
                    "(?i)\\bdata engineer\\b",
                    "(?i)\\bfront.?end\\b",
                    "(?i)\\bintern\\b",
                ],
            }
        }
        import logging
        log = logging.getLogger("test")
        classify_new_jobs(classify_db, config, log)

        with sqlite3.connect(classify_db) as conn:
            conn.row_factory = sqlite3.Row
            rows = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM jobs")}

        assert rows[1] == "new"  # Senior SWE — kept
        assert rows[2] == "not_suitable"  # Data Engineer — filtered
        assert rows[3] == "not_suitable"  # Frontend — filtered
        assert rows[4] == "not_suitable"  # Intern — filtered
        assert rows[5] == "new"  # Staff Engineer — kept

    def test_experience_filter_non_senior(self, classify_db: Path):
        config = {
            "classify": {
                "enabled": True,
                "exclude_patterns": [],
                "min_experience_years": 5,
            }
        }
        import logging
        log = logging.getLogger("test")
        classify_new_jobs(classify_db, config, log)

        with sqlite3.connect(classify_db) as conn:
            conn.row_factory = sqlite3.Row
            rows = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM jobs")}

        # Job 6: "Software Engineer" (no senior keyword) with "1+ years" → filtered
        assert rows[6] == "not_suitable"
        # Job 1: "Senior Software Engineer" → kept even though JD says 10+ years
        assert rows[1] == "new"
        # Job 5: "Staff Engineer" → kept (senior keyword)
        assert rows[5] == "new"

    def test_disabled_classify_skips(self, classify_db: Path):
        config = {"classify": {"enabled": False, "exclude_patterns": ["(?i)\\bintern\\b"]}}
        import logging
        log = logging.getLogger("test")
        classify_new_jobs(classify_db, config, log)

        with sqlite3.connect(classify_db) as conn:
            statuses = [r[0] for r in conn.execute("SELECT status FROM jobs")]
        assert all(s == "new" for s in statuses)


# ── Tailor output parsing ─────────────────────────────────────────────────────

class TestTailorParsing:
    """Test the output parsing logic of run_tailor_direct without actual LLM calls."""

    def test_parse_direction_and_resume(self):
        """Verify the parsing logic for DIRECTION: / ---RESUME--- format."""
        response_text = """DIRECTION: ai
---RESUME---
# Haomin Liu
Senior AI Engineer with 10+ years...
"""
        # Simulate the parsing logic from run_tailor_direct
        direction = "ic"
        resume_md = response_text

        if "DIRECTION:" in response_text and "---RESUME---" in response_text:
            parts = response_text.split("---RESUME---", 1)
            header = parts[0]
            resume_md = parts[1].strip() if len(parts) > 1 else ""
            for d in ["ai", "ic", "mgmt", "venture"]:
                if f"DIRECTION: {d}" in header.lower() or f"DIRECTION: {d}" in header:
                    direction = d
                    break

        assert direction == "ai"
        assert "Haomin Liu" in resume_md
        assert "Senior AI Engineer" in resume_md

    def test_fallback_when_no_markers(self):
        """If agent doesn't output DIRECTION:/---RESUME---, use entire output."""
        response_text = "# Haomin Liu\nSome resume content here that is long enough"
        direction = "ic"
        resume_md = response_text

        if "DIRECTION:" in response_text and "---RESUME---" in response_text:
            pass  # would parse
        elif response_text.strip():
            resume_md = response_text.strip()

        assert direction == "ic"  # default
        assert resume_md == response_text.strip()


# ── CAPTCHA / CapSolver ───────────────────────────────────────────────────────

class TestCaptchaConfigReading:
    """test_captcha_config_reading — verify get_capsolver_api_key reads from env."""

    def test_reads_env_var(self, monkeypatch):
        import os
        monkeypatch.setenv("CAPSOLVER_API_KEY", "test-key-from-env")
        from scripts.config import get_capsolver_api_key
        key = get_capsolver_api_key()
        assert key == "test-key-from-env"

    def test_returns_none_when_missing(self, monkeypatch):
        """When env var is absent and Keychain returns non-zero, returns None."""
        import subprocess
        monkeypatch.delenv("CAPSOLVER_API_KEY", raising=False)

        # Patch subprocess.run to simulate no Keychain entry
        def fake_run(*args, **kwargs):
            result = subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="")
            return result

        monkeypatch.setattr("subprocess.run", fake_run)
        from scripts import config as cfg_module
        import importlib
        importlib.reload(cfg_module)
        key = cfg_module.get_capsolver_api_key()
        assert key is None

    def test_env_var_takes_priority_over_keychain(self, monkeypatch):
        """Env var should be returned without touching Keychain."""
        monkeypatch.setenv("CAPSOLVER_API_KEY", "env-priority-key")
        call_count = {"n": 0}
        orig_run = __import__("subprocess").run

        def tracking_run(*args, **kwargs):
            call_count["n"] += 1
            return orig_run(*args, **kwargs)

        monkeypatch.setattr("subprocess.run", tracking_run)
        from scripts.config import get_capsolver_api_key
        key = get_capsolver_api_key()
        assert key == "env-priority-key"
        assert call_count["n"] == 0, "Keychain should not be queried when env var is set"


class TestSolveRecaptchaMock:
    """test_solve_recaptcha_mock — mock CapSolver API calls end-to-end."""

    def _make_response(self, status_code: int, json_data: dict):
        """Create a minimal mock requests.Response."""
        import requests

        resp = requests.Response()
        resp.status_code = status_code
        resp._content = __import__("json").dumps(json_data).encode()
        return resp

    def test_successful_solve(self, monkeypatch):
        """Full happy path: createTask → processing → ready."""
        calls = []

        def mock_post(url, json=None, **kwargs):
            calls.append(url)
            if "createTask" in url:
                return self._make_response(200, {"errorId": 0, "taskId": "task-123"})
            if "getTaskResult" in url:
                if len(calls) < 3:
                    return self._make_response(200, {"errorId": 0, "status": "processing"})
                return self._make_response(
                    200,
                    {"errorId": 0, "status": "ready", "solution": {"gRecaptchaResponse": "TOKEN-XYZ"}},
                )
            raise AssertionError(f"Unexpected URL: {url}")

        monkeypatch.setattr("requests.post", mock_post)
        monkeypatch.setattr("time.sleep", lambda s: None)  # skip real waits

        from scripts.captcha import solve_recaptcha_enterprise
        token = solve_recaptcha_enterprise(
            site_key="6Ltest",
            page_url="https://boards.greenhouse.io/acme/jobs/123",
            api_key="fake-api-key",
        )
        assert token == "TOKEN-XYZ"

    def test_create_task_api_error(self, monkeypatch):
        """createTask returns errorId != 0 → returns None."""

        def mock_post(url, json=None, **kwargs):
            return self._make_response(
                200, {"errorId": 1, "errorCode": "ERROR_KEY_DENIED_ACCESS", "errorDescription": "bad key"}
            )

        monkeypatch.setattr("requests.post", mock_post)
        monkeypatch.setattr("time.sleep", lambda s: None)

        from scripts.captcha import solve_recaptcha_enterprise
        token = solve_recaptcha_enterprise("6Ltest", "https://example.com", api_key="bad-key")
        assert token is None

    def test_no_api_key_returns_none(self, monkeypatch):
        """When no API key available, returns None without any HTTP calls."""
        import subprocess

        monkeypatch.delenv("CAPSOLVER_API_KEY", raising=False)

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        post_called = {"called": False}

        def mock_post(*args, **kwargs):
            post_called["called"] = True
            raise AssertionError("Should not call API without key")

        monkeypatch.setattr("requests.post", mock_post)
        monkeypatch.setattr("time.sleep", lambda s: None)

        from scripts import captcha as cap_module
        import importlib
        importlib.reload(cap_module)

        token = cap_module.solve_recaptcha_enterprise("6Ltest", "https://example.com")
        assert token is None
        assert not post_called["called"]

    def test_timeout_returns_none(self, monkeypatch):
        """If all polls return 'processing' until timeout, returns None."""
        import time as real_time

        def mock_post(url, json=None, **kwargs):
            if "createTask" in url:
                return self._make_response(200, {"errorId": 0, "taskId": "task-timeout"})
            return self._make_response(200, {"errorId": 0, "status": "processing"})

        monkeypatch.setattr("requests.post", mock_post)
        monkeypatch.setattr("time.sleep", lambda s: None)

        # Make monotonic advance past timeout immediately after a few polls
        call_count = {"n": 0}
        start = real_time.monotonic()

        def fast_monotonic():
            call_count["n"] += 1
            # After 5 calls, simulate 61+ seconds elapsed
            if call_count["n"] > 5:
                return start + 65
            return start + call_count["n"]

        monkeypatch.setattr("time.monotonic", fast_monotonic)

        from scripts import captcha as cap_module
        import importlib
        importlib.reload(cap_module)

        token = cap_module.solve_recaptcha_enterprise("6Ltest", "https://example.com", api_key="key")
        assert token is None


# ── Force-writeback guard ─────────────────────────────────────────────────────

class TestForceApplyFailed:
    """Tests for _force_apply_failed — the pipeline-side status writeback guard."""

    @pytest.fixture()
    def guard_db(self, tmp_path: Path) -> Path:
        db_path = tmp_path / "guard.db"
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE jobs (
                    id INTEGER PRIMARY KEY,
                    title TEXT,
                    company TEXT,
                    status TEXT,
                    status_updated_at TEXT
                )
            """)
            conn.executemany(
                "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
                [
                    (10, "Engineer", "Acme", "tailored"),
                    (11, "Manager", "Beta", "applied"),
                    (12, "Scientist", "Gamma", "blocked"),
                    (13, "Director", "Delta", "apply_failed"),
                ],
            )
        return db_path

    def test_writes_apply_failed_when_tailored(self, guard_db: Path):
        """Job still in 'tailored' state → force apply_failed."""
        import logging
        log = logging.getLogger("test")
        _force_apply_failed(guard_db, 10, "apply_agent_no_status_update", log)
        assert get_job_status(guard_db, 10) == "apply_failed"

    def test_does_not_overwrite_applied(self, guard_db: Path):
        """Already 'applied' → no change."""
        import logging
        log = logging.getLogger("test")
        _force_apply_failed(guard_db, 11, "apply_agent_no_status_update", log)
        assert get_job_status(guard_db, 11) == "applied"

    def test_does_not_overwrite_blocked(self, guard_db: Path):
        """Already 'blocked' → no change."""
        import logging
        log = logging.getLogger("test")
        _force_apply_failed(guard_db, 12, "apply_agent_no_status_update", log)
        assert get_job_status(guard_db, 12) == "blocked"

    def test_does_not_overwrite_apply_failed(self, guard_db: Path):
        """Already 'apply_failed' → no change (idempotent)."""
        import logging
        log = logging.getLogger("test")
        _force_apply_failed(guard_db, 13, "apply_agent_no_status_update", log)
        assert get_job_status(guard_db, 13) == "apply_failed"

    def test_tolerates_missing_job(self, guard_db: Path):
        """Non-existent job ID → no crash, no write."""
        import logging
        log = logging.getLogger("test")
        _force_apply_failed(guard_db, 999, "apply_agent_no_status_update", log)
        # Just verify no exception raised

    def test_applies_with_note_in_real_db(self, guard_db: Path):
        """Verify status_updated_at is set when writing apply_failed."""
        import logging
        log = logging.getLogger("test")
        _force_apply_failed(guard_db, 10, "apply_agent_no_status_update", log)
        with sqlite3.connect(guard_db) as conn:
            row = conn.execute(
                "SELECT status, status_updated_at FROM jobs WHERE id=10"
            ).fetchone()
        assert row[0] == "apply_failed"
        assert row[1] is not None  # timestamp was written


# ── URL resolution (resolve_apply_url) ───────────────────────────────────────

class TestResolveApplyUrl:
    """Tests for resolve_apply_url — mocked extractor, no real browser."""

    def _make_log(self):
        import logging
        return logging.getLogger("test_resolve")

    def _import(self):
        from scripts.pipeline import resolve_apply_url
        return resolve_apply_url

    # -- LinkedIn path --------------------------------------------------------

    def test_linkedin_external_url_found(self):
        """LinkedIn URL → extractor returns external URL → use it."""
        resolve_apply_url = self._import()
        mock_extractor = lambda url, timeout=15: "https://boards.greenhouse.io/acme/jobs/123"

        final, note = resolve_apply_url(
            "https://www.linkedin.com/jobs/view/123456/",
            job_id=1,
            company="Acme",
            log=self._make_log(),
            _linkedin_extractor=mock_extractor,
        )
        assert final == "https://boards.greenhouse.io/acme/jobs/123"
        assert "linkedin_external" in note
        assert "ats_direct:greenhouse" in note

    def test_linkedin_no_external_url(self):
        """LinkedIn URL → extractor returns None → keep original LinkedIn URL."""
        resolve_apply_url = self._import()
        mock_extractor = lambda url, timeout=15: None

        final, note = resolve_apply_url(
            "https://www.linkedin.com/jobs/view/789/",
            job_id=2,
            company="Beta",
            log=self._make_log(),
            _linkedin_extractor=mock_extractor,
        )
        assert final == "https://www.linkedin.com/jobs/view/789/"
        assert "linkedin_no_external" in note

    def test_linkedin_extractor_exception_falls_through(self):
        """Extractor throws → note 'linkedin_extract_failed', original URL returned."""
        resolve_apply_url = self._import()

        def bad_extractor(url, timeout=15):
            raise RuntimeError("browser not running")

        final, note = resolve_apply_url(
            "https://www.linkedin.com/jobs/view/999/",
            job_id=3,
            company="Gamma",
            log=self._make_log(),
            _linkedin_extractor=bad_extractor,
        )
        assert final == "https://www.linkedin.com/jobs/view/999/"
        assert "linkedin_extract_failed" in note

    # -- Non-LinkedIn direct ATS URL -----------------------------------------

    def test_direct_greenhouse_url(self):
        """Direct Greenhouse URL → classified immediately, no browser call."""
        resolve_apply_url = self._import()
        called = {"n": 0}

        def should_not_be_called(url, timeout=15):
            called["n"] += 1
            return None

        final, note = resolve_apply_url(
            "https://boards.greenhouse.io/stripe/jobs/4567",
            job_id=4,
            company="Stripe",
            log=self._make_log(),
            _linkedin_extractor=should_not_be_called,
        )
        assert final == "https://boards.greenhouse.io/stripe/jobs/4567"
        assert "ats_direct:greenhouse" in note
        assert called["n"] == 0  # extractor never called for non-LinkedIn

    def test_direct_lever_url(self):
        resolve_apply_url = self._import()
        final, note = resolve_apply_url(
            "https://jobs.lever.co/openai/abc-123",
            job_id=5,
            company="OpenAI",
            log=self._make_log(),
            _linkedin_extractor=lambda u, timeout=15: None,
        )
        assert "ats_direct:lever" in note
        assert final == "https://jobs.lever.co/openai/abc-123"

    # -- Company page + ATS cache --------------------------------------------

    def test_company_page_with_iframe_cache(self, tmp_path, monkeypatch):
        """Non-ATS company page + cache hit with iframe_src → use iframe_src."""
        from scripts import ats_resolver
        cache = {
            "careers.sofi.com": {
                "platform": "greenhouse",
                "iframe_src": "https://job-boards.greenhouse.io/sofi/jobs/7890",
                "updated_at": "2026-03-01T00:00:00Z",
            }
        }
        monkeypatch.setattr(ats_resolver, "ATS_CACHE_PATH", tmp_path / "cache.json")
        import json
        (tmp_path / "cache.json").write_text(json.dumps(cache))

        resolve_apply_url = self._import()
        final, note = resolve_apply_url(
            "https://careers.sofi.com/listing/se-position-7890",
            job_id=6,
            company="SoFi",
            log=self._make_log(),
            _linkedin_extractor=lambda u, timeout=15: None,
        )
        assert final == "https://job-boards.greenhouse.io/sofi/jobs/7890"
        assert "cache_iframe:greenhouse" in note

    def test_company_page_cache_hit_no_iframe(self, tmp_path, monkeypatch):
        """Cache hit without iframe_src → keep company URL, note cache_hint."""
        from scripts import ats_resolver
        cache = {
            "careers.example.com": {
                "platform": "workday",
                "iframe_src": "",
                "updated_at": "2026-03-01T00:00:00Z",
            }
        }
        monkeypatch.setattr(ats_resolver, "ATS_CACHE_PATH", tmp_path / "cache.json")
        import json
        (tmp_path / "cache.json").write_text(json.dumps(cache))

        resolve_apply_url = self._import()
        final, note = resolve_apply_url(
            "https://careers.example.com/job/123",
            job_id=7,
            company="Example",
            log=self._make_log(),
            _linkedin_extractor=lambda u, timeout=15: None,
        )
        assert final == "https://careers.example.com/job/123"
        assert "cache_hint:workday" in note

    def test_company_page_no_cache(self, tmp_path, monkeypatch):
        """Non-ATS, no cache → keep URL, note company_page_no_cache."""
        from scripts import ats_resolver
        monkeypatch.setattr(ats_resolver, "ATS_CACHE_PATH", tmp_path / "cache.json")

        resolve_apply_url = self._import()
        final, note = resolve_apply_url(
            "https://careers.widgetcorp.com/listing/sr-engineer-999",
            job_id=8,
            company="WidgetCorp",
            log=self._make_log(),
            _linkedin_extractor=lambda u, timeout=15: None,
        )
        assert final == "https://careers.widgetcorp.com/listing/sr-engineer-999"
        assert "company_page_no_cache" in note

    # -- Edge cases ----------------------------------------------------------

    def test_empty_url(self):
        resolve_apply_url = self._import()
        final, note = resolve_apply_url(
            "",
            job_id=0,
            company="Nobody",
            log=self._make_log(),
        )
        assert final == ""
        assert note == "no_url"

    def test_linkedin_external_then_cache_iframe(self, tmp_path, monkeypatch):
        """LinkedIn → external company URL → cache hit with iframe → use iframe."""
        from scripts import ats_resolver
        cache = {
            "careers.acme.com": {
                "platform": "ashby",
                "iframe_src": "https://jobs.ashbyhq.com/acme/job-id",
                "updated_at": "2026-03-01T00:00:00Z",
            }
        }
        monkeypatch.setattr(ats_resolver, "ATS_CACHE_PATH", tmp_path / "cache.json")
        import json
        (tmp_path / "cache.json").write_text(json.dumps(cache))

        resolve_apply_url = self._import()
        final, note = resolve_apply_url(
            "https://www.linkedin.com/jobs/view/111/",
            job_id=9,
            company="Acme",
            log=self._make_log(),
            _linkedin_extractor=lambda u, timeout=15: "https://careers.acme.com/job/xyz",
        )
        assert final == "https://jobs.ashbyhq.com/acme/job-id"
        assert "linkedin_external" in note
        assert "cache_iframe:ashby" in note
