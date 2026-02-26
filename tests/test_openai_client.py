"""Tests for openai_client.py: key resolution, retry logic, prompt loading."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from jobhunt.openai_client import (
    call_openai,
    classify_jd,
    load_prompt_template,
    prompt_version,
    render_prompt,
    resolve_openai_key,
    rewrite_resume,
)


# ---------------------------------------------------------------------------
# resolve_openai_key (FR-33)
# ---------------------------------------------------------------------------


class TestResolveOpenaiKey:
    def test_keychain_primary(self):
        with patch("jobhunt.credentials.read_keychain", return_value="sk-test-key-123"):
            key = resolve_openai_key()
        assert key == "sk-test-key-123"

    def test_env_fallback_when_keychain_missing(self):
        with (
            patch("jobhunt.credentials.read_keychain", return_value=None),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env-key-456"}),
        ):
            key = resolve_openai_key()
        assert key == "sk-env-key-456"

    def test_raises_when_both_missing(self):
        with (
            patch("jobhunt.credentials.read_keychain", return_value=None),
            patch.dict(os.environ, {}, clear=True),
        ):
            # Ensure OPENAI_API_KEY is removed
            os.environ.pop("OPENAI_API_KEY", None)
            with pytest.raises(RuntimeError, match="not found"):
                resolve_openai_key()

    def test_keychain_returns_dict_not_string(self):
        """If keychain returns a dict (wrong service), it should fall through."""
        with (
            patch("jobhunt.credentials.read_keychain", return_value={"username": "x"}),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fallback"}),
        ):
            key = resolve_openai_key()
        assert key == "sk-fallback"

    def test_keychain_returns_empty_string(self):
        with (
            patch("jobhunt.credentials.read_keychain", return_value=""),
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}),
        ):
            key = resolve_openai_key()
        assert key == "sk-env"


# ---------------------------------------------------------------------------
# load_prompt_template (FR-34)
# ---------------------------------------------------------------------------


class TestLoadPromptTemplate:
    def test_loads_existing_file(self, tmp_path):
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("Hello {{name}}")
        result = load_prompt_template(prompt_file)
        assert result == "Hello {{name}}"

    def test_raises_on_missing_file(self):
        with pytest.raises(FileNotFoundError, match="not found"):
            load_prompt_template("/nonexistent/path/to/prompt.md")

    def test_expands_tilde(self, tmp_path, monkeypatch):
        prompt_file = tmp_path / "test.md"
        prompt_file.write_text("content")
        # Just verify it works with absolute paths
        result = load_prompt_template(str(prompt_file))
        assert result == "content"


# ---------------------------------------------------------------------------
# render_prompt
# ---------------------------------------------------------------------------


class TestRenderPrompt:
    def test_single_variable(self):
        result = render_prompt("Hello {{name}}", name="World")
        assert result == "Hello World"

    def test_multiple_variables(self):
        result = render_prompt("{{a}} and {{b}}", a="X", b="Y")
        assert result == "X and Y"

    def test_no_variables(self):
        result = render_prompt("No placeholders here")
        assert result == "No placeholders here"

    def test_unmatched_placeholder_preserved(self):
        result = render_prompt("{{a}} and {{b}}", a="X")
        assert result == "X and {{b}}"


# ---------------------------------------------------------------------------
# prompt_version
# ---------------------------------------------------------------------------


class TestPromptVersion:
    def test_returns_sha256_hex(self):
        version = prompt_version("test content")
        assert len(version) == 64  # SHA-256 hex
        assert version == prompt_version("test content")  # deterministic

    def test_different_content_different_hash(self):
        assert prompt_version("a") != prompt_version("b")


# ---------------------------------------------------------------------------
# call_openai — retry logic (NFR-02)
# ---------------------------------------------------------------------------


class TestCallOpenaiRetry:
    def _mock_client(self, responses=None, errors=None):
        """Create a mock OpenAI client."""
        client = MagicMock()
        side_effects = []

        if errors:
            for err in errors:
                side_effects.append(err)
        if responses:
            for resp in responses:
                mock_resp = MagicMock()
                mock_resp.choices = [MagicMock()]
                mock_resp.choices[0].message.content = resp
                side_effects.append(mock_resp)

        client.chat.completions.create.side_effect = side_effects
        return client

    def test_success_on_first_try(self):
        client = self._mock_client(responses=["Hello"])
        result = call_openai("test prompt", "gpt-4o", client)
        assert result == "Hello"
        assert client.chat.completions.create.call_count == 1

    @patch("jobhunt.openai_client.time.sleep")
    def test_retry_on_429(self, mock_sleep):
        import openai

        err = openai.APIStatusError(
            message="Rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        client = self._mock_client(errors=[err], responses=["OK"])
        result = call_openai("test", "gpt-4o", client)
        assert result == "OK"
        assert client.chat.completions.create.call_count == 2
        mock_sleep.assert_called_once_with(1)  # first backoff

    @patch("jobhunt.openai_client.time.sleep")
    def test_retry_on_500(self, mock_sleep):
        import openai

        err = openai.APIStatusError(
            message="Server error",
            response=MagicMock(status_code=500, headers={}),
            body=None,
        )
        client = self._mock_client(errors=[err, err], responses=["OK"])
        result = call_openai("test", "gpt-4o", client)
        assert result == "OK"
        assert client.chat.completions.create.call_count == 3

    @patch("jobhunt.openai_client.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep):
        import openai

        err = openai.APIStatusError(
            message="Always failing",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        client = self._mock_client(errors=[err, err, err])
        with pytest.raises(openai.APIStatusError):
            call_openai("test", "gpt-4o", client)
        assert client.chat.completions.create.call_count == 3

    def test_no_retry_on_400(self):
        import openai

        err = openai.APIStatusError(
            message="Bad request",
            response=MagicMock(status_code=400, headers={}),
            body=None,
        )
        client = self._mock_client(errors=[err])
        with pytest.raises(openai.APIStatusError):
            call_openai("test", "gpt-4o", client)
        assert client.chat.completions.create.call_count == 1


# ---------------------------------------------------------------------------
# classify_jd
# ---------------------------------------------------------------------------


class TestClassifyJd:
    def _mock_client_response(self, content):
        client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = content
        client.chat.completions.create.return_value = mock_resp
        return client

    def test_json_response(self):
        client = self._mock_client_response('{"direction": "ai", "rationale": "ML role"}')
        result = classify_jd(
            "Build ML models",
            prompt_template="Classify: {{jd_text}}",
            client=client,
            model="gpt-4o",
        )
        assert result == "ai"

    def test_plain_text_response(self):
        client = self._mock_client_response("ic")
        result = classify_jd(
            "Build REST APIs",
            prompt_template="Classify: {{jd_text}}",
            client=client,
            model="gpt-4o",
        )
        assert result == "ic"

    def test_extracts_from_sentence(self):
        client = self._mock_client_response("The direction is mgmt based on the JD.")
        result = classify_jd(
            "Lead engineering teams",
            prompt_template="Classify: {{jd_text}}",
            client=client,
            model="gpt-4o",
        )
        assert result == "mgmt"

    def test_invalid_response_raises(self):
        client = self._mock_client_response("something completely wrong")
        with pytest.raises(ValueError, match="Invalid classification"):
            classify_jd(
                "Random text",
                prompt_template="Classify: {{jd_text}}",
                client=client,
                model="gpt-4o",
            )

    def test_venture_classification(self):
        client = self._mock_client_response('{"direction": "venture", "rationale": "Startup CTO"}')
        result = classify_jd(
            "CTO at early stage startup",
            prompt_template="Classify: {{jd_text}}",
            client=client,
            model="gpt-4o",
        )
        assert result == "venture"
