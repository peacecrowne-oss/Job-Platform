"""Tests for app.sanitization.sanitize_html (STORY-047)."""

from __future__ import annotations

from app.sanitization import sanitize_html


def test_none_in_none_out() -> None:
    assert sanitize_html(None) is None


def test_plain_text_passes_through_unchanged() -> None:
    assert sanitize_html("Plain text, no markup at all.") == "Plain text, no markup at all."


def test_script_tag_and_its_content_are_stripped() -> None:
    result = sanitize_html("<p>Hi <script>alert(1)</script>there</p>")
    assert "<script" not in result
    assert "alert(1)" not in result
    assert "Hi" in result and "there" in result


def test_inline_event_handler_attribute_is_stripped() -> None:
    result = sanitize_html('<p onclick="evil()">text</p>')
    assert "onclick" not in result
    assert "evil()" not in result
    assert "text" in result


def test_javascript_uri_href_is_dropped() -> None:
    result = sanitize_html('<a href="javascript:alert(1)">click</a>')
    assert "javascript:" not in result
    assert "click" in result


def test_legitimate_link_preserves_href_and_forces_safe_rel() -> None:
    result = sanitize_html('<a href="https://example.com/job/1">apply</a>')
    assert 'href="https://example.com/job/1"' in result
    assert 'rel="noopener noreferrer"' in result


def test_legitimate_formatting_tags_are_preserved() -> None:
    result = sanitize_html("<p>Responsibilities:</p><ul><li>One</li><li>Two</li></ul>")
    assert "<p>Responsibilities:</p>" in result
    assert "<ul><li>One</li><li>Two</li></ul>" in result


def test_disallowed_tag_is_stripped_but_its_text_content_kept() -> None:
    result = sanitize_html("<style>body{display:none}</style><p>visible</p>")
    assert "<style" not in result
    assert "visible" in result


def test_heading_tags_are_stripped_but_text_content_kept() -> None:
    # STORY-048: headings aren't in the allow-list -- externally-sourced
    # content rendered via dangerouslySetInnerHTML must never be able to
    # inject a second <h1> or an out-of-order heading into the page's own
    # heading hierarchy. Stripped like a generic disallowed tag (text kept),
    # not like <script>/<style> (content removed entirely).
    result = sanitize_html("<h1>Big Title</h1><p>body</p>")
    assert "<h1" not in result
    assert "Big Title" in result
    assert "<p>body</p>" in result


def test_entirely_malicious_input_sanitizes_to_empty_string() -> None:
    assert sanitize_html("<script>alert(1)</script>") == ""


def test_empty_string_stays_empty_string() -> None:
    assert sanitize_html("") == ""
