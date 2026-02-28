"""Tests for credentials.py: op JSON parsing, email ranking, fallback."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.credentials import (
    _get_field_value,
    _item_matches_domain,
    op_available,
    op_list_items,
    rank_by_preferred_emails,
    read_keychain,
    resolve_credential,
)
from scripts.models import Credential


# ---------------------------------------------------------------------------
# _item_matches_domain
# ---------------------------------------------------------------------------


class TestItemMatchesDomain:
    def test_exact_match(self):
        item = {"urls": [{"href": "https://www.linkedin.com/feed"}]}
        assert _item_matches_domain(item, "linkedin.com") is True

    def test_partial_match(self):
        item = {"urls": [{"href": "https://linkedin.com/"}]}
        assert _item_matches_domain(item, "linkedin.com") is True

    def test_no_match(self):
        item = {"urls": [{"href": "https://github.com/"}]}
        assert _item_matches_domain(item, "linkedin.com") is False

    def test_multiple_urls_one_matches(self):
        item = {
            "urls": [
                {"href": "https://github.com/"},
                {"href": "https://linkedin.com/"},
            ]
        }
        assert _item_matches_domain(item, "linkedin.com") is True

    def test_missing_urls_key(self):
        item = {"id": "abc"}
        assert _item_matches_domain(item, "linkedin.com") is False

    def test_null_urls(self):
        item = {"urls": None}
        assert _item_matches_domain(item, "linkedin.com") is False


# ---------------------------------------------------------------------------
# _get_field_value
# ---------------------------------------------------------------------------


class TestGetFieldValue:
    def test_match_by_id(self):
        fields = [{"id": "username", "value": "user@example.com"}]
        assert _get_field_value(fields, "username") == "user@example.com"

    def test_match_by_label(self):
        fields = [{"id": "abc", "label": "Username", "value": "user@example.com"}]
        assert _get_field_value(fields, "username") == "user@example.com"

    def test_no_match_returns_none(self):
        fields = [{"id": "note", "value": "some note"}]
        assert _get_field_value(fields, "username") is None

    def test_empty_fields(self):
        assert _get_field_value([], "username") is None


# ---------------------------------------------------------------------------
# op_available
# ---------------------------------------------------------------------------


class TestOpAvailable:
    def test_returns_true_when_found(self):
        with patch("shutil.which", return_value="/usr/local/bin/op"):
            assert op_available() is True

    def test_returns_false_when_not_found(self):
        with patch("shutil.which", return_value=None):
            assert op_available() is False


# ---------------------------------------------------------------------------
# op_list_items
# ---------------------------------------------------------------------------


class TestOpListItems:
    def test_returns_parsed_json_on_success(self, op_item_list_output):
        mock_result = MagicMock(returncode=0, stdout=op_item_list_output, stderr="")
        with patch("subprocess.run", return_value=mock_result):
            items = op_list_items()
        assert items is not None
        assert len(items) == 3
        assert items[0]["id"] == "uuid-hotmail"

    def test_returns_none_on_nonzero_exit(self):
        mock_result = MagicMock(returncode=1, stdout="", stderr="not signed in")
        with patch("subprocess.run", return_value=mock_result):
            assert op_list_items() is None

    def test_returns_none_on_malformed_json(self):
        mock_result = MagicMock(returncode=0, stdout="not-json", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            assert op_list_items() is None


# ---------------------------------------------------------------------------
# rank_by_preferred_emails
# ---------------------------------------------------------------------------


class TestRankByPreferredEmails:
    def _make_items(self):
        return [
            {"id": "uuid-gmail", "title": "LinkedIn (gmail)"},
            {"id": "uuid-hotmail", "title": "LinkedIn (hotmail)"},
        ]

    def test_hotmail_ranked_first_when_preferred(self, preferred_emails):
        items = self._make_items()

        def mock_op_get(item_id, fields="username"):
            mapping = {
                "uuid-hotmail": [{"id": "username", "value": "haomin_liu@hotmail.com"}],
                "uuid-gmail": [{"id": "username", "value": "haomin.liu@gmail.com"}],
            }
            return mapping.get(item_id)

        with patch("scripts.credentials.op_get_item", side_effect=mock_op_get):
            ranked = rank_by_preferred_emails(items, preferred_emails)

        assert ranked[0]["id"] == "uuid-hotmail"
        assert ranked[1]["id"] == "uuid-gmail"

    def test_unpreferred_item_goes_last(self, preferred_emails):
        items = [
            {"id": "uuid-unknown", "title": "Unknown"},
            {"id": "uuid-hotmail", "title": "LinkedIn (hotmail)"},
        ]

        def mock_op_get(item_id, fields="username"):
            mapping = {
                "uuid-hotmail": [{"id": "username", "value": "haomin_liu@hotmail.com"}],
                "uuid-unknown": [{"id": "username", "value": "other@example.com"}],
            }
            return mapping.get(item_id)

        with patch("scripts.credentials.op_get_item", side_effect=mock_op_get):
            ranked = rank_by_preferred_emails(items, preferred_emails)

        assert ranked[0]["id"] == "uuid-hotmail"

    def test_op_get_failure_treated_as_unpreferred(self, preferred_emails):
        items = [{"id": "uuid-hotmail"}, {"id": "uuid-gmail"}]

        with patch("scripts.credentials.op_get_item", return_value=None):
            # Should not raise; unresolvable items go to end
            ranked = rank_by_preferred_emails(items, preferred_emails)
        assert len(ranked) == 2


# ---------------------------------------------------------------------------
# resolve_credential
# ---------------------------------------------------------------------------


class TestResolveCredential:
    def test_uses_keychain_when_available(self):
        with patch("scripts.credentials.read_keychain", return_value={"username": "u", "password": "p"}):
            cred = resolve_credential("linkedin.com", [])
        assert isinstance(cred, Credential)
        assert cred.username == "u"
        assert cred.password == "p"

    def test_falls_back_to_1password_when_keychain_empty(self, capsys):
        with (
            patch("scripts.credentials.read_keychain", return_value=None),
            patch("scripts.credentials.op_available", return_value=False),
        ):
            result = resolve_credential("linkedin.com", [])
        assert result is None
        captured = capsys.readouterr()
        assert "No credentials found" in captured.err

    def test_returns_none_when_op_list_fails(self, capsys):
        with (
            patch("scripts.credentials.read_keychain", return_value=None),
            patch("scripts.credentials.op_available", return_value=True),
            patch("scripts.credentials.op_list_items", return_value=None),
        ):
            result = resolve_credential("linkedin.com", [])
        assert result is None

    def test_returns_none_when_no_matching_items(self, capsys, op_item_list_output):
        all_items = json.loads(op_item_list_output)
        with (
            patch("scripts.credentials.read_keychain", return_value=None),
            patch("scripts.credentials.op_available", return_value=True),
            patch("scripts.credentials.op_list_items", return_value=all_items),
        ):
            result = resolve_credential("example.com", [])
        assert result is None
        captured = capsys.readouterr()
        assert "No credentials found" in captured.err

    def test_returns_credential_on_success(self, op_item_list_output, preferred_emails):
        all_items = json.loads(op_item_list_output)

        def mock_op_get(item_id, fields="username"):
            if item_id == "uuid-hotmail":
                if "password" in fields:
                    return [
                        {"id": "username", "value": "haomin_liu@hotmail.com"},
                        {"id": "password", "value": "s3cr3t"},
                    ]
                return [{"id": "username", "value": "haomin_liu@hotmail.com"}]
            if item_id == "uuid-gmail":
                return [{"id": "username", "value": "haomin.liu@gmail.com"}]
            return None

        with (
            patch("scripts.credentials.read_keychain", return_value=None),
            patch("scripts.credentials.op_available", return_value=True),
            patch("scripts.credentials.op_list_items", return_value=all_items),
            patch("scripts.credentials.op_get_item", side_effect=mock_op_get),
        ):
            cred = resolve_credential("linkedin.com", preferred_emails)

        assert isinstance(cred, Credential)
        assert cred.username == "haomin_liu@hotmail.com"
        assert cred.item_id == "uuid-hotmail"
        # Never test password value directly (but verify it was resolved)
        assert cred.password is not None
