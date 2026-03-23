"""Tests for cleaning module."""

from __future__ import annotations

import pytest

from gg_core.cleaning import (
    CleanedLine,
    KimiHandler,
    LineType,
    OpenCodeHandler,
    TmuxCleaner,
    clean_logs,
    get_handler,
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


class TestOpenCodeHandler:
    """Tests for OpenCodeHandler."""

    def test_handler_inheritance(self):
        """Test OpenCodeHandler inherits from KimiHandler."""
        handler = get_handler("opencode")
        assert isinstance(handler, OpenCodeHandler)
        assert isinstance(handler, KimiHandler)

    def test_prompt_marker(self):
        """Test OpenCode has no visible prompt marker."""
        handler = OpenCodeHandler()
        # OpenCode uses colored border instead of visible prompt marker
        assert handler.PROMPT_MARKERS == ()

    def test_spinner_inherited(self):
        """Test spinner characters are inherited from KimiHandler."""
        handler = OpenCodeHandler()
        # OpenCode uses braille spinners like kimi
        assert "⠋" in handler.SPINNER_CHARS
        assert "⠙" in handler.SPINNER_CHARS

    def test_activity_patterns_inherited(self):
        """Test activity patterns are inherited from KimiHandler."""
        handler = OpenCodeHandler()
        # Thinking... should be filtered
        line, lt = handler.filter_line("Thinking...", LineType.CONTENT)
        assert lt == LineType.EMPTY
        assert line == ""

    def test_tool_call_conversion(self):
        """Test bullet tool calls are converted to Tool: prefix."""
        cleaner = TmuxCleaner("opencode")
        cleaned = cleaner.clean_line("• Used WriteFile (test.py)")
        assert cleaned.cleaned == "Tool: Used WriteFile (test.py)"
        assert cleaned.line_type == LineType.TOOL_CALL

    def test_border_separator_classification(self):
        """Test OpenCode's colored border (┃) is classified as SEPARATOR."""
        cleaner = TmuxCleaner("opencode")
        # OpenCode uses colored left border (┃) not a prompt marker
        cleaned = cleaner.clean_line("┃ Ask anything...")
        assert cleaned.line_type == LineType.SEPARATOR

    def test_tool_icon_conversion(self):
        """Test OpenCode's tool icons are converted to Tool: prefix."""
        cleaner = TmuxCleaner("opencode")
        # Test $ icon for bash/shell commands
        cleaned = cleaner.clean_line("$ cargo check -p coder")
        assert cleaned.cleaned == "Tool: cargo check -p coder"
        assert cleaned.line_type == LineType.TOOL_CALL
        # Test ✱ icon for glob/search
        cleaned = cleaner.clean_line('✱ Glob "tasks/*.md" (40 matches)')
        assert cleaned.cleaned == 'Tool: Glob "tasks/*.md" (40 matches)'
        assert cleaned.line_type == LineType.TOOL_CALL
        # Test ▣ icon for build
        cleaned = cleaner.clean_line("▣ Build · MiniMax-M2.7-highspeed")
        assert cleaned.cleaned == "Tool: Build · MiniMax-M2.7-highspeed"
        assert cleaned.line_type == LineType.TOOL_CALL

    def test_knight_rider_blocks_in_spinner_union(self):
        """Test Knight Rider block characters are in spinner union for state detection."""
        from gg_core.cleaning import _SPINNER_UNION
        # Knight Rider blocks indicate activity in OpenCode
        assert "■" in _SPINNER_UNION  # Black square
        assert "⬝" in _SPINNER_UNION  # Small black square
        assert "⬥" in _SPINNER_UNION  # Black diamond
        assert "◆" in _SPINNER_UNION  # Black diamond (filled)

    def test_status_bar_filtering(self):
        """Test OpenCode status bar is filtered out."""
        cleaner = TmuxCleaner("opencode")
        # Full status line with Knight Rider
        cleaned = cleaner.clean_line(
            '■■■⬝⬝⬝⬝⬝  esc interrupt                                              tab agents  ctrl+p commands'
        )
        assert cleaned.line_type == LineType.STATUS_BAR
        # Individual keybinding hints
        assert cleaner.clean_line('esc interrupt').line_type == LineType.STATUS_BAR
        assert cleaner.clean_line('tab agents').line_type == LineType.STATUS_BAR
        assert cleaner.clean_line('ctrl+p commands').line_type == LineType.STATUS_BAR
        # But normal content should pass through
        assert cleaner.clean_line('Normal content').line_type == LineType.CONTENT

    def test_user_input_conversion(self):
        """Test ✨ is converted to User: prefix."""
        cleaner = TmuxCleaner("opencode")
        cleaned = cleaner.clean_line("✨ Create a function")
        assert cleaned.cleaned == "User: Create a function"
        assert cleaned.line_type == LineType.INPUT_MARKER


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
