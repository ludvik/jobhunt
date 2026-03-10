"""Tests for scripts/ats_resolver.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.ats_resolver import (
    ATS_CACHE_PATH,
    IFRAME_EXTRACT_JS,
    choose_primary_ats_iframe,
    classify_ats_from_url,
    get_ats_hint_for_url,
    load_ats_cache,
    save_ats_cache,
    update_ats_cache,
)


# ── classify_ats_from_url ────────────────────────────────────────────────────

class TestClassifyAtsFromUrl:
    def test_greenhouse_job_boards(self):
        url = "https://job-boards.greenhouse.io/acme/jobs/12345"
        assert classify_ats_from_url(url) == "greenhouse"

    def test_greenhouse_boards(self):
        url = "https://boards.greenhouse.io/company/jobs/999"
        assert classify_ats_from_url(url) == "greenhouse"

    def test_lever(self):
        url = "https://jobs.lever.co/acme/abc-123"
        assert classify_ats_from_url(url) == "lever"

    def test_ashby(self):
        url = "https://jobs.ashbyhq.com/company/12345"
        assert classify_ats_from_url(url) == "ashby"

    def test_workday(self):
        url = "https://acme.myworkdayjobs.com/en-US/acme_careers/job/NYC/SWE_123"
        assert classify_ats_from_url(url) == "workday"

    def test_icims(self):
        url = "https://careers.icims.com/jobs/1234/job"
        assert classify_ats_from_url(url) == "icims"

    def test_successfactors(self):
        url = "https://acme.successfactors.com/sf/careers"
        assert classify_ats_from_url(url) == "successfactors"

    def test_oracle_hcm_taleo(self):
        url = "https://acme.taleo.net/careersection/2/jobdetail.ftl?job=123"
        assert classify_ats_from_url(url) == "oracle_hcm"

    def test_generic_unknown(self):
        url = "https://careers.unknown-company.com/jobs/eng-123"
        assert classify_ats_from_url(url) == "generic"

    def test_empty_string(self):
        assert classify_ats_from_url("") == "generic"

    def test_none_like_empty(self):
        # classify_ats_from_url takes str; empty string is the falsy case
        assert classify_ats_from_url("") == "generic"

    def test_rippling(self):
        url = "https://app.rippling.com/job-board/acme/123"
        assert classify_ats_from_url(url) == "rippling"

    def test_smartrecruiters(self):
        url = "https://jobs.smartrecruiters.com/Acme/123456789"
        assert classify_ats_from_url(url) == "smartrecruiters"


# ── choose_primary_ats_iframe ────────────────────────────────────────────────

class TestChoosePrimaryAtsIframe:
    def test_empty_list(self):
        assert choose_primary_ats_iframe([]) is None

    def test_blank_only(self):
        assert choose_primary_ats_iframe(["", "about:blank"]) is None

    def test_single_known(self):
        src = "https://job-boards.greenhouse.io/acme/jobs/1"
        assert choose_primary_ats_iframe([src]) == src

    def test_prefers_greenhouse_over_generic(self):
        generic = "https://careers.acme.com/embed"
        gh = "https://boards.greenhouse.io/acme/jobs/2"
        result = choose_primary_ats_iframe([generic, gh])
        assert result == gh

    def test_prefers_greenhouse_over_lever(self):
        # greenhouse has lower index in _ATS_DOMAIN_PATTERNS
        gh = "https://job-boards.greenhouse.io/co/jobs/3"
        lv = "https://jobs.lever.co/co/abc"
        result = choose_primary_ats_iframe([lv, gh])
        assert result == gh

    def test_fallback_to_first_non_blank(self):
        srcs = ["about:blank", "", "https://some-random-site.com/apply"]
        result = choose_primary_ats_iframe(srcs)
        assert result == "https://some-random-site.com/apply"

    def test_multiple_generics_picks_first(self):
        srcs = ["https://a.com/embed", "https://b.com/embed"]
        # Both generic, should pick first (stable min)
        result = choose_primary_ats_iframe(srcs)
        assert result == srcs[0]


# ── Cache helpers ─────────────────────────────────────────────────────────────

class TestAtsCache:
    """Use a temporary cache path to avoid polluting the real cache."""

    @pytest.fixture(autouse=True)
    def tmp_cache(self, tmp_path, monkeypatch):
        tmp_cache_file = tmp_path / "ats-host-cache.json"
        monkeypatch.setattr("scripts.ats_resolver.ATS_CACHE_PATH", tmp_cache_file)
        self.cache_path = tmp_cache_file
        yield tmp_cache_file

    def test_load_missing_returns_empty(self):
        assert load_ats_cache() == {}

    def test_save_and_load(self):
        data = {"acme.com": {"platform": "greenhouse", "iframe_src": "", "updated_at": "2026-01-01T00:00:00+00:00"}}
        save_ats_cache(data)
        loaded = load_ats_cache()
        assert loaded == data

    def test_update_writes_entry(self):
        update_ats_cache("sofi.com", "greenhouse", "https://job-boards.greenhouse.io/sofi/jobs/1")
        cache = load_ats_cache()
        assert "sofi.com" in cache
        entry = cache["sofi.com"]
        assert entry["platform"] == "greenhouse"
        assert entry["iframe_src"] == "https://job-boards.greenhouse.io/sofi/jobs/1"
        assert "updated_at" in entry

    def test_update_overwrites_existing(self):
        update_ats_cache("acme.com", "lever", "")
        update_ats_cache("acme.com", "greenhouse", "https://boards.greenhouse.io/acme/jobs/99")
        cache = load_ats_cache()
        assert cache["acme.com"]["platform"] == "greenhouse"

    def test_update_ignores_empty_host(self):
        update_ats_cache("", "greenhouse", "")
        assert load_ats_cache() == {}

    def test_update_ignores_empty_platform(self):
        update_ats_cache("acme.com", "", "")
        assert load_ats_cache() == {}

    def test_get_ats_hint_returns_entry(self):
        update_ats_cache("sofi.com", "greenhouse", "https://boards.greenhouse.io/sofi/jobs/1")
        hint = get_ats_hint_for_url("https://sofi.com/careers/job/123")
        assert hint is not None
        assert hint["platform"] == "greenhouse"

    def test_get_ats_hint_returns_none_for_unknown(self):
        hint = get_ats_hint_for_url("https://unknown-company.com/jobs/1")
        assert hint is None

    def test_get_ats_hint_returns_none_for_empty(self):
        assert get_ats_hint_for_url("") is None

    def test_cache_file_is_sorted_json(self):
        update_ats_cache("z.com", "lever", "")
        update_ats_cache("a.com", "ashby", "")
        text = self.cache_path.read_text()
        data = json.loads(text)
        keys = list(data.keys())
        assert keys == sorted(keys)


# ── IFRAME_EXTRACT_JS sanity check ────────────────────────────────────────────

def test_iframe_extract_js_is_string():
    assert isinstance(IFRAME_EXTRACT_JS, str)
    assert "querySelectorAll" in IFRAME_EXTRACT_JS
    assert "iframe" in IFRAME_EXTRACT_JS
