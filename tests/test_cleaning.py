"""Tests for cleaning module."""

from __future__ import annotations

import pytest

from gg_core.cleaning import (
    CleanedLine,
    KimiHandler,
    LineType,
    TmuxCleaner,
    clean_logs,
    get_visible_logs,
)


class TestTmuxCleaner:
    """Tests for TmuxCleaner class."""

    def test_ansi_stripping(self):
        """Test ANSI escape sequences are stripped."""
        cleaner = TmuxCleaner("generic")

        # CSI sequences
        assert cleaner._strip_ansi("\x1b[31mred\x1b[0m") == "red"
        # OSC sequences
        assert cleaner._strip_ansi("\x1b]0;title\x07text") == "text"
        # Combined
        assert cleaner._strip_ansi("\x1b[1;32mgreen\x1b[0m") == "green"

    def test_null_byte_filtering(self):
        """Test null bytes are filtered."""
        cleaner = TmuxCleaner("generic")

        assert cleaner._strip_ansi("hello\x00world") == "helloworld"
        assert cleaner._strip_ansi("\x00\x00") == ""

    def test_line_classification_empty(self):
        """Test empty line classification."""
        cleaner = TmuxCleaner("generic")

        assert cleaner._classify("") == LineType.EMPTY
        assert cleaner._classify("   ") == LineType.EMPTY

    def test_line_classification_content(self):
        """Test content line classification."""
        cleaner = TmuxCleaner("generic")

        assert cleaner._classify("Hello world") == LineType.CONTENT

    def test_line_classification_continuation(self):
        """Test continuation line classification."""
        cleaner = TmuxCleaner("generic")

        assert cleaner._classify("  indented") == LineType.CONTINUATION

    def test_line_classification_separator(self):
        """Test separator line classification."""
        cleaner = TmuxCleaner("generic")

        assert cleaner._classify("─" * 20) == LineType.SEPARATOR

    def test_line_classification_bullet(self):
        """Test bullet line classification."""
        cleaner = TmuxCleaner("generic")

        assert cleaner._classify("• item") == LineType.BULLET

    def test_clean_line_returns_cleanedline(self):
        """Test clean_line returns CleanedLine."""
        cleaner = TmuxCleaner("generic")

        result = cleaner.clean_line("Hello")

        assert isinstance(result, CleanedLine)
        assert result.cleaned == "Hello"
        assert result.line_type == LineType.CONTENT

    def test_visible_property(self):
        """Test is_visible property."""
        cleaner = TmuxCleaner("generic")

        content = cleaner.clean_line("Hello")
        assert content.is_visible is True

        empty = cleaner.clean_line("")
        assert empty.is_visible is True


class TestKimiHandler:
    """Tests for KimiHandler."""

    def test_spinner_removal(self):
        """Test spinner characters are removed."""
        handler = KimiHandler()

        line, lt = handler.filter_line("test⠋", LineType.CONTENT)
        assert "⠋" not in line

    def test_prompt_marker(self):
        """Test prompt markers are detected."""
        handler = KimiHandler()

        assert "💫" in handler.PROMPT_MARKERS


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_clean_logs(self):
        """Test clean_logs function."""
        lines = ["Hello", "World", ""]
        cleaned = clean_logs(lines)

        assert len(cleaned) == 3
        assert cleaned[0].cleaned == "Hello"

    def test_get_visible_logs(self):
        """Test get_visible_logs function."""
        lines = ["Hello", "", "World"]
        visible = get_visible_logs(lines)

        assert visible == ["Hello", "World"]


class TestLineType:
    """Tests for LineType enum."""

    def test_line_type_values(self):
        """Test LineType has expected values."""
        assert LineType.EMPTY is not None
        assert LineType.CONTENT is not None
        assert LineType.SPINNER is not None


class TestCleanedLine:
    """Tests for CleanedLine dataclass."""

    def test_is_visible_content(self):
        """Test is_visible for content."""
        line = CleanedLine(
            original="hello",
            cleaned="hello",
            line_type=LineType.CONTENT,
        )
        assert line.is_visible is True

    def test_is_visible_empty(self):
        """Test is_visible for empty."""
        line = CleanedLine(
            original="",
            cleaned="",
            line_type=LineType.EMPTY,
        )
        assert line.is_visible is True

    def test_frozen_immutable(self):
        """Test CleanedLine is frozen (immutable)."""
        line = CleanedLine(
            original="hello",
            cleaned="hello",
            line_type=LineType.CONTENT,
        )

        with pytest.raises(AttributeError):
            line.cleaned = "changed"
