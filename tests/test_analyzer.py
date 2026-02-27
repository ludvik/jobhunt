"""Tests for analyzer.py: run_analysis with mock OpenAI, graceful failure."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from jobhunt.analyzer import run_analysis


# ---------------------------------------------------------------------------
# run_analysis — success
# ---------------------------------------------------------------------------


class TestRunAnalysis:
    def test_returns_analysis_text(self):
        expected = "## Match Score\n8/10\n## Strengths\nGood\n## Gaps\nNone\n## Interview Talking Points\nQ1"
        with patch("jobhunt.openai_client.analyze_fit", return_value=expected):
            result = run_analysis(
                "JD text",
                "# Tailored Resume",
                prompt_template="Analyze: {{jd_text}} {{tailored_resume}}",
                client=MagicMock(),
                model="gpt-4o",
            )
        assert result == expected
        assert "Match Score" in result

    def test_passes_job_context(self):
        with patch("jobhunt.openai_client.analyze_fit", return_value="analysis") as mock_analyze:
            run_analysis(
                "JD text",
                "# Resume",
                prompt_template="template",
                client=MagicMock(),
                model="gpt-4o",
                job_title="Engineer",
                company="Acme",
            )
        mock_analyze.assert_called_once()
        call_kwargs = mock_analyze.call_args
        assert call_kwargs.kwargs["job_title"] == "Engineer"
        assert call_kwargs.kwargs["company"] == "Acme"


# ---------------------------------------------------------------------------
# run_analysis — graceful failure
# ---------------------------------------------------------------------------


class TestRunAnalysisFailure:
    def test_returns_empty_on_api_error(self):
        with patch("jobhunt.openai_client.analyze_fit", side_effect=Exception("API down")):
            result = run_analysis(
                "JD text",
                "# Resume",
                prompt_template="template",
                client=MagicMock(),
                model="gpt-4o",
            )
        assert result == ""

    def test_returns_empty_on_runtime_error(self):
        with patch("jobhunt.openai_client.analyze_fit", side_effect=RuntimeError("Key missing")):
            result = run_analysis(
                "JD text",
                "# Resume",
                prompt_template="template",
                client=MagicMock(),
                model="gpt-4o",
            )
        assert result == ""
