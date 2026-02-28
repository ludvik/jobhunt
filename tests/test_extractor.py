"""Tests for extractor.py: HTML stripping, hash computation, extract_jd."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.extractor import compute_hash, extract_jd, strip_html
from scripts.models import ExtractionError


# ---------------------------------------------------------------------------
# strip_html
# ---------------------------------------------------------------------------


class TestStripHtml:
    def test_strips_simple_tags(self):
        assert strip_html("<b>hello</b>") == "hello"

    def test_strips_nested_tags(self):
        html = "<div><p>text</p></div>"
        result = strip_html(html)
        assert "text" in result
        assert "<" not in result
        assert ">" not in result

    def test_inserts_newline_for_block_tags(self):
        html = "<p>first</p><p>second</p>"
        result = strip_html(html)
        assert "first" in result
        assert "second" in result
        assert "\n" in result

    def test_preserves_inline_text(self):
        html = "Look at <strong>this</strong> engineer"
        result = strip_html(html)
        assert "Look at " in result
        assert "this" in result
        assert " engineer" in result

    def test_handles_list_items(self):
        html = "<ul><li>Python</li><li>Go</li></ul>"
        result = strip_html(html)
        assert "Python" in result
        assert "Go" in result

    def test_empty_string(self):
        assert strip_html("") == ""

    def test_plain_text_unchanged(self):
        text = "just plain text"
        assert strip_html(text) == text

    def test_linkedin_style_jd(self):
        html = (
            "<div>"
            "<h2>About the role</h2>"
            "<p>We are looking for a <strong>Senior Backend Engineer</strong>.</p>"
            "<ul><li>5+ years experience</li><li>Python or Go</li></ul>"
            "</div>"
        )
        result = strip_html(html)
        assert "About the role" in result
        assert "Senior Backend Engineer" in result
        assert "5+ years experience" in result
        assert "<" not in result


# ---------------------------------------------------------------------------
# compute_hash (FR-07)
# ---------------------------------------------------------------------------


class TestComputeHash:
    def test_tc07_case(self):
        """TC-07: verify exact normalisation chain."""
        jd_text = "  <b>Engineer</b>\n\nAt Stripe. "
        h = compute_hash(jd_text)
        # Expected: strip HTML → '  Engineer\n\nAt Stripe. '
        #           collapse WS → 'engineer at stripe.'  (after lower)
        import hashlib
        expected = hashlib.md5("engineer at stripe.".encode("utf-8")).hexdigest()
        assert h == expected

    def test_normalisation_is_case_insensitive(self):
        h1 = compute_hash("Hello World")
        h2 = compute_hash("hello world")
        assert h1 == h2

    def test_normalisation_collapses_whitespace(self):
        h1 = compute_hash("hello    world")
        h2 = compute_hash("hello world")
        assert h1 == h2

    def test_normalisation_strips_leading_trailing(self):
        h1 = compute_hash("   hello world   ")
        h2 = compute_hash("hello world")
        assert h1 == h2

    def test_normalisation_strips_residual_html(self):
        h1 = compute_hash("hello <b>world</b>")
        h2 = compute_hash("hello world")
        assert h1 == h2

    def test_different_text_gives_different_hash(self):
        h1 = compute_hash("engineer at stripe")
        h2 = compute_hash("engineer at google")
        assert h1 != h2

    def test_returns_32_char_hex_string(self):
        h = compute_hash("some text")
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_string(self):
        import hashlib
        h = compute_hash("")
        expected = hashlib.md5(b"").hexdigest()
        assert h == expected

    def test_stable_across_calls(self):
        """Same input always produces same hash."""
        text = "senior backend engineer at stripe remote"
        assert compute_hash(text) == compute_hash(text)


# ---------------------------------------------------------------------------
# extract_jd (mocked Playwright page)
# ---------------------------------------------------------------------------


def _make_page(
    has_primary: bool = True,
    has_fallback: bool = True,
    show_more_visible: bool = False,
    inner_html: str = "<p>Job description text</p>",
    url: str = "https://www.linkedin.com/jobs/view/123/",
):
    """Build a mock Playwright page for extract_jd tests."""
    page = MagicMock()
    page.url = url

    # Set up wait_for_selector behaviour
    def mock_wait_for_selector(selector, timeout=None):
        if selector == ".description__text" and has_primary:
            return MagicMock()
        if selector == ".show-more-less-html__markup" and has_fallback:
            return MagicMock()
        from playwright.sync_api import TimeoutError as PwTimeout
        raise PwTimeout(f"Timeout waiting for {selector}")

    page.wait_for_selector.side_effect = mock_wait_for_selector

    # Show-more button
    show_more_btn = MagicMock()
    show_more_btn.is_visible.return_value = show_more_visible
    page.wait_for_timeout = MagicMock()

    # Container locator
    container = MagicMock()
    container.count.return_value = 1 if has_primary else 0
    container.inner_html.return_value = inner_html

    fallback_container = MagicMock()
    fallback_container.count.return_value = 1 if has_fallback else 0
    fallback_container.inner_html.return_value = inner_html

    def mock_locator(selector):
        if selector == "button.show-more-less-html__button--more":
            return show_more_btn
        if selector == ".description__text":
            return container
        if selector == ".show-more-less-html__markup":
            return fallback_container
        m = MagicMock()
        m.count.return_value = 0
        return m

    page.locator.side_effect = mock_locator

    return page


class TestExtractJd:
    def test_extracts_text_from_primary_selector(self):
        page = _make_page(inner_html="<p>Job description here</p>")
        result = extract_jd(page)
        assert "Job description here" in result
        assert "<" not in result

    def test_falls_back_to_secondary_selector(self):
        page = _make_page(has_primary=False, inner_html="<p>Fallback description</p>")
        result = extract_jd(page)
        assert "Fallback description" in result

    def test_raises_extraction_error_when_both_selectors_fail(self):
        page = _make_page(has_primary=False, has_fallback=False)
        with pytest.raises(ExtractionError):
            extract_jd(page)

    def test_raises_extraction_error_when_text_is_empty(self):
        page = _make_page(inner_html="<p>   </p>")
        with pytest.raises(ExtractionError):
            extract_jd(page)

    def test_clicks_show_more_when_visible(self):
        page = _make_page(show_more_visible=True)
        extract_jd(page)
        # show_more button should have been clicked
        show_more_btn = page.locator("button.show-more-less-html__button--more")
        show_more_btn.click.assert_called_once()

    def test_returns_plain_text_no_html_tags(self):
        html = "<h2>Role</h2><p>Build <strong>great</strong> things.</p>"
        page = _make_page(inner_html=html)
        result = extract_jd(page)
        assert "<" not in result
        assert ">" not in result
        assert "great" in result

    def test_uses_found_container_locator_when_requerying_selectors_fails(self):
        from playwright.sync_api import TimeoutError as PwTimeout

        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/123/"

        # _find_jd_container may locate a container from .description__text,
        # but repeated locator() re-query can temporarily return empty for the same
        # selector during extraction.
        container = MagicMock()
        container.count.return_value = 1
        container.inner_html.return_value = "<p>Recovered from resolved locator</p>"

        def mock_wait_for_selector(selector, timeout=None):
            if selector == ".description__text":
                return MagicMock()
            raise PwTimeout(f"Timeout waiting for {selector}")

        page.wait_for_selector.side_effect = mock_wait_for_selector

        call_state = {"description": 0}

        def mock_locator(selector):
            # First query for primary selector returns the valid container,
            # subsequent queries return empty to force fallback logic to rely on
            # the already-resolved locator.
            if selector == ".description__text":
                call_state["description"] += 1
                if call_state["description"] == 1:
                    return container
                m = MagicMock()
                m.count.return_value = 0
                m.inner_html.return_value = ""
                return m
            # fallback paths used by extract/jd fallbacks should be empty.
            if selector == "button.show-more-less-html__button--more":
                return MagicMock(is_visible=MagicMock(return_value=False), count=MagicMock(return_value=1))
            if selector == "div[role='main']":
                return MagicMock(count=MagicMock(return_value=0))
            m = MagicMock()
            m.count.return_value = 0
            m.inner_html.return_value = ""
            m.inner_text.return_value = ""
            return m

        page.locator.side_effect = mock_locator
        page.query_selector_all = MagicMock(return_value=[])
        page.wait_for_timeout = MagicMock()

        result = extract_jd(page)
        assert "Recovered from resolved locator" in result

    def test_jsonld_fallback_extracts_description(self):
        """When all DOM selectors fail, JSON-LD JobPosting description is used."""
        from playwright.sync_api import TimeoutError as PwTimeout
        import json

        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/456/"

        # All wait_for_selector calls fail — no DOM container found.
        page.wait_for_selector.side_effect = PwTimeout("Timeout")

        # Show-more button not found.
        def mock_locator(selector):
            m = MagicMock()
            m.count.return_value = 0
            m.inner_html.return_value = ""
            m.inner_text.return_value = ""
            return m

        page.locator.side_effect = mock_locator
        page.wait_for_timeout = MagicMock()

        # JSON-LD script with JobPosting description.
        ld_json = json.dumps({
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Software Engineer",
            "description": "<p>We are looking for a <b>Software Engineer</b> with experience in Python.</p>",
        })
        script_el = MagicMock()
        script_el.inner_text.return_value = ld_json
        page.query_selector_all = MagicMock(return_value=[script_el])

        result = extract_jd(page)
        assert "Software Engineer" in result
        assert "Python" in result
        assert "<" not in result  # HTML stripped

    def test_broad_section_fallback_with_keyword_scoring(self):
        """When DOM and JSON-LD fail, broad sections with JD keywords are used."""
        from playwright.sync_api import TimeoutError as PwTimeout

        page = MagicMock()
        page.url = "https://www.linkedin.com/jobs/view/789/"

        # All wait_for_selector calls fail.
        page.wait_for_selector.side_effect = PwTimeout("Timeout")

        # JSON-LD returns nothing.
        page.query_selector_all = MagicMock(return_value=[])
        page.wait_for_timeout = MagicMock()

        # Build long text with JD keywords (>300 chars required).
        jd_text = (
            "About the role\n"
            "We are looking for a Senior Engineer to join our team. "
            "Responsibilities include designing systems, writing code, "
            "and mentoring junior engineers. "
            "Qualifications: 5+ years of experience in backend development, "
            "strong knowledge of Python and distributed systems. "
            "We are a fast-growing startup focused on developer tools. "
            "This role offers competitive compensation and remote flexibility. "
            "Apply now to join our growing engineering team."
        )

        short_text = "Not a JD"

        def mock_locator(selector):
            m = MagicMock()
            # "main" selector returns a long text with JD keywords
            if selector == "main":
                m.count.return_value = 1
                m.inner_text.return_value = jd_text
                m.inner_html.return_value = ""
            elif selector == "article":
                m.count.return_value = 1
                m.inner_text.return_value = short_text
                m.inner_html.return_value = ""
            else:
                m.count.return_value = 0
                m.inner_html.return_value = ""
                m.inner_text.return_value = ""
            return m

        page.locator.side_effect = mock_locator

        result = extract_jd(page)
        assert "Responsibilities" in result
        assert "Qualifications" in result
        assert len(result) > 300
