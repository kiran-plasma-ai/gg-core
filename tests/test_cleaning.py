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

    def test_status_bar_patterns(self):
        """Test newer kimi status bars are filtered."""
        handler = KimiHandler()
        # shift-tab pattern
        line, lt = handler.filter_line("shift-tab: plan mode | ctrl-o: editor", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # ctrl-o pattern
        line, lt = handler.filter_line("ctrl-o: editor", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # yolo agent pattern
        line, lt = handler.filter_line("yolo agent | context: 45.3%", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # plan agent pattern
        line, lt = handler.filter_line("plan agent (kimi-for-coding ●)", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # context pattern
        line, lt = handler.filter_line("context: 12.5%", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # background task pattern
        line, lt = handler.filter_line("⚙ bash: 2", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # Normal content should pass
        line, lt = handler.filter_line("This is normal content", LineType.CONTENT)
        assert lt == LineType.CONTENT

    def test_tool_output_patterns(self):
        """Test tool execution output is filtered."""
        handler = KimiHandler()
        # exit code
        line, lt = handler.filter_line("exit code: 0", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        line, lt = handler.filter_line("exit code: 1", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # ls total
        line, lt = handler.filter_line("total 42", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # ls -l directory entry
        line, lt = handler.filter_line("drwxr-xr-x  3 user group 4096 Jan 01 00:00 src", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # ls -l file entry
        line, lt = handler.filter_line("-rw-r--r--  1 user group  123 Jan 01 00:00 file.txt", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # diff markers
        line, lt = handler.filter_line("--- a/src/main.py", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        line, lt = handler.filter_line("+++ b/src/main.py", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        line, lt = handler.filter_line("@@ -1,5 +1,7 @@", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # stdout/stderr/output labels
        line, lt = handler.filter_line("stdout:", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        line, lt = handler.filter_line("stderr:", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        line, lt = handler.filter_line("output:", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # But normal content should pass
        line, lt = handler.filter_line("Here is the result", LineType.CONTENT)
        assert lt == LineType.CONTENT

    def test_in_progress_tool_indicators(self):
        """Test spinner-prefixed in-progress tool indicators are filtered."""
        handler = KimiHandler()
        # After spinner strip, these should be caught
        line, lt = handler.filter_line("Using Shell (cd /home/user/gg-core)", LineType.CONTENT)
        assert lt == LineType.EMPTY
        line, lt = handler.filter_line("Running ReadFile (test.py)", LineType.CONTENT)
        assert lt == LineType.EMPTY
        line, lt = handler.filter_line("Executing Python (script.py)", LineType.CONTENT)
        assert lt == LineType.EMPTY
        # With spinner prefix (as seen in real tmux output)
        line, lt = handler.filter_line("⠹ Using Shell (cd /home/user/gg-core)", LineType.CONTENT)
        assert lt == LineType.EMPTY
        line, lt = handler.filter_line("⠼ Running ReadFile (foo.py)", LineType.CONTENT)
        assert lt == LineType.EMPTY
        # Completed tool calls should NOT be filtered
        line, lt = handler.filter_line("Tool: Used Shell (cd /home)", LineType.TOOL_CALL)
        assert lt == LineType.TOOL_CALL
        # Normal content should pass
        line, lt = handler.filter_line("Here is the result", LineType.CONTENT)
        assert lt == LineType.CONTENT

    def test_activity_and_internal_patterns(self):
        """Test activity indicators and internal notes are filtered."""
        handler = KimiHandler()
        # Side question spinner
        line, lt = handler.filter_line("Side question: What do you want?", LineType.CONTENT)
        assert lt == LineType.EMPTY
        # Subagent metadata
        line, lt = handler.filter_line("subagent background (abc-123)", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # Collapsed tool calls note
        line, lt = handler.filter_line("1 more tool call ...", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        line, lt = handler.filter_line("3 more tool calls ...", LineType.CONTENT)
        assert lt == LineType.STATUS_BAR
        # Normal content should pass
        line, lt = handler.filter_line("Here is the result", LineType.CONTENT)
        assert lt == LineType.CONTENT

    def test_negative_false_positives(self):
        """Test that broad patterns do not false-positive on legitimate content."""
        handler = KimiHandler()
        # In-progress tool regex should not match prose
        line, lt = handler.filter_line("Using Python (is great)", LineType.CONTENT)
        assert lt == LineType.CONTENT, f"Expected CONTENT, got {lt}"
        line, lt = handler.filter_line("Running fast (every morning)", LineType.CONTENT)
        assert lt == LineType.CONTENT, f"Expected CONTENT, got {lt}"
        # Status patterns should not match normal content
        line, lt = handler.filter_line("Planning your trip", LineType.CONTENT)
        assert lt == LineType.CONTENT, f"Expected CONTENT, got {lt}"
        line, lt = handler.filter_line("The yolo county is nice", LineType.CONTENT)
        assert lt == LineType.CONTENT, f"Expected CONTENT, got {lt}"
        # Diff patterns should not match markdown headers
        line, lt = handler.filter_line("--- hello world", LineType.CONTENT)
        assert lt == LineType.CONTENT, f"Expected CONTENT, got {lt}"
        line, lt = handler.filter_line("+++ something", LineType.CONTENT)
        assert lt == LineType.CONTENT, f"Expected CONTENT, got {lt}"
        # Tool output patterns should not match normal content
        line, lt = handler.filter_line("Total 42 items in stock", LineType.CONTENT)
        assert lt == LineType.CONTENT, f"Expected CONTENT, got {lt}"
        # "stdout:" alone is a tool output label, but "stdout: hello" is content
        line, lt = handler.filter_line("stdout: hello", LineType.CONTENT)
        assert lt == LineType.CONTENT, f"Expected CONTENT, got {lt}"

    def test_activity_indicators_with_timing(self):
        """Test newer kimi-cli activity indicators with timing/token suffixes."""
        handler = KimiHandler()
        # Thinking... with timing info
        line, lt = handler.filter_line("Thinking... 1m 16s · 1.6k tokens", LineType.CONTENT)
        assert lt == LineType.EMPTY
        assert line == ""
        # With spinner prefix
        line, lt = handler.filter_line("⠙ Thinking... 1m 16s · 1.6k tokens", LineType.CONTENT)
        assert lt == LineType.EMPTY
        assert line == ""
        # Working... with timing
        line, lt = handler.filter_line("Working... 2m 30s · 3.2k tokens", LineType.CONTENT)
        assert lt == LineType.EMPTY
        # Reading... with timing
        line, lt = handler.filter_line("⠋ Reading... 45s · 800 tokens", LineType.CONTENT)
        assert lt == LineType.EMPTY
        # Plain variants still work
        line, lt = handler.filter_line("Thinking...", LineType.CONTENT)
        assert lt == LineType.EMPTY
        line, lt = handler.filter_line("⠹ Thinking...", LineType.CONTENT)
        assert lt == LineType.EMPTY
        # Normal content should pass
        line, lt = handler.filter_line("Here is the result", LineType.CONTENT)
        assert lt == LineType.CONTENT

    def test_activity_indicator_with_timing_breaks_state(self):
        """Test Thinking... with timing breaks wrapped-input state so response shows."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "✨ hello world",
            "⠙ Thinking... 1m 16s · 1.6k tokens",
            "Here is my response.",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.INPUT_MARKER
        # Activity indicator filtered by handler
        assert cleaned[1].line_type == LineType.EMPTY
        assert cleaned[1].cleaned == ""
        # Response preserved (state was broken by activity indicator)
        assert cleaned[2].line_type == LineType.CONTENT
        assert cleaned[2].cleaned == "Here is my response."

    def test_single_word_content_not_filtered(self):
        """Test legitimate single-word agent responses are preserved.

        Previously, the partial-word filter in KimiHandler incorrectly hid
        standalone responses like 'ok', 'yes', 'done'.
        """
        cleaner = TmuxCleaner("kimi")
        lines = [
            "✨ hello",
            "",
            "ok",
            "done",
            "yes",
            "hello",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.INPUT_MARKER
        assert cleaned[0].cleaned == "User: hello"
        # Empty line breaks the after-input state
        assert cleaned[1].line_type == LineType.EMPTY
        # All single-word responses should be preserved
        assert cleaned[2].line_type == LineType.CONTENT
        assert cleaned[2].cleaned == "ok"
        assert cleaned[3].line_type == LineType.CONTENT
        assert cleaned[3].cleaned == "done"
        assert cleaned[4].line_type == LineType.CONTENT
        assert cleaned[4].cleaned == "yes"
        assert cleaned[5].line_type == LineType.CONTENT
        assert cleaned[5].cleaned == "hello"

    def test_typing_after_input_does_not_leak(self):
        """Test that user typing after INPUT_MARKER is fully filtered.

        Previously, if a single-word typing line was filtered by the partial-word
        filter, the state machine broke and subsequent typing leaked through.
        """
        cleaner = TmuxCleaner("kimi")
        lines = [
            "✨ hello",
            "ok",
            "more typing here",
            "and here",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.INPUT_MARKER
        # All typing lines must be filtered
        for c in cleaned[1:]:
            assert c.line_type == LineType.EMPTY, (
                f"Expected EMPTY, got {c.line_type}: {c.cleaned!r}"
            )
            assert c.cleaned == ""

    def test_border_separator_patterns(self):
        """Test newer kimi page borders are filtered as separators."""
        cleaner = TmuxCleaner("kimi")
        # Pure border lines
        assert cleaner.clean_line("╰───────────────────────────────────────────────────────────────────────────────").line_type == LineType.SEPARATOR
        assert cleaner.clean_line("─╯").line_type == LineType.SEPARATOR
        assert cleaner.clean_line("╭─").line_type == LineType.SEPARATOR
        assert cleaner.clean_line("─╮").line_type == LineType.SEPARATOR
        # Normal content containing a border char should NOT be hidden
        result = cleaner.clean_line("Normal content with ─ in it")
        assert result.line_type == LineType.CONTENT
        assert result.is_visible is True

    def test_wrapped_user_input_filtered(self):
        """Test wrapped user input after INPUT_MARKER is filtered."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "✨ hello world this is a very long message",
            "that wraps to the next line without the marker",
            "",
            "Here is the agent response.",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.INPUT_MARKER
        assert cleaned[0].cleaned == "User: hello world this is a very long message"
        # Wrapped continuation should be filtered to EMPTY
        assert cleaned[1].line_type == LineType.EMPTY
        assert cleaned[1].cleaned == ""
        # Empty line breaks the "after input" state
        assert cleaned[2].line_type == LineType.EMPTY
        assert cleaned[2].cleaned == ""
        # Agent response should be preserved
        assert cleaned[3].line_type == LineType.CONTENT
        assert cleaned[3].cleaned == "Here is the agent response."

    def test_agent_response_after_input_no_gap(self):
        """Test agent response directly after input without empty line."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "✨ short message",
            "• Used Shell (ls)",  # Tool call breaks "after input" state
            "Tool result here",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.INPUT_MARKER
        assert cleaned[1].line_type == LineType.TOOL_CALL
        assert cleaned[1].cleaned == "Tool: Used Shell (ls)"
        assert cleaned[2].line_type == LineType.CONTENT
        assert cleaned[2].cleaned == "Tool result here"

    def test_multiple_wrapped_lines_after_input(self):
        """Test multiple wrapped lines after INPUT_MARKER are all filtered."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "✨ hello world this is a very long message",
            "that wraps to line two",
            "and this wraps to line three",
            "",
            "Here is the agent response.",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.INPUT_MARKER
        # Both wrapped continuations should be filtered to EMPTY
        assert cleaned[1].line_type == LineType.EMPTY
        assert cleaned[1].cleaned == ""
        assert cleaned[2].line_type == LineType.EMPTY
        assert cleaned[2].cleaned == ""
        # Empty line breaks state
        assert cleaned[3].line_type == LineType.EMPTY
        # Agent response preserved
        assert cleaned[4].line_type == LineType.CONTENT
        assert cleaned[4].cleaned == "Here is the agent response."

    def test_typing_in_progress_wrapped_lines_filtered(self):
        """Test wrapped lines after typing-in-progress prompt are filtered."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "💫 hello world this is the user typing a very long message",
            "that wraps across multiple lines without leading space",
            "  and this wraps with leading space",
            "",
            "still typing after empty line",
        ]
        cleaned = cleaner.clean_batch(lines)
        # Typing line filtered by handler
        assert cleaned[0].line_type == LineType.EMPTY
        assert cleaned[0].cleaned == ""
        # Both wrapped continuations filtered by clean_batch state
        assert cleaned[1].line_type == LineType.EMPTY
        assert cleaned[1].cleaned == ""
        assert cleaned[2].line_type == LineType.EMPTY
        assert cleaned[2].cleaned == ""
        # Empty line keeps state alive in typing mode
        assert cleaned[3].line_type == LineType.EMPTY
        assert cleaned[3].cleaned == ""
        # Typing after empty line still filtered
        assert cleaned[4].line_type == LineType.EMPTY
        assert cleaned[4].cleaned == ""

    def test_typing_after_agent_response_filtered(self):
        """Test typing wrapped lines after agent response are filtered."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "✨ previous message",
            "",
            "Agent response here.",
            "",
            "💫 hello world this is the user typing a very long message",
            "that wraps across multiple lines",
            "",
            "still typing after empty line",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.INPUT_MARKER
        assert cleaned[0].cleaned == "User: previous message"
        # Agent response preserved
        assert cleaned[2].line_type == LineType.CONTENT
        assert cleaned[2].cleaned == "Agent response here."
        # Typing line filtered
        assert cleaned[4].line_type == LineType.EMPTY
        assert cleaned[4].cleaned == ""
        # Wrapped continuation filtered
        assert cleaned[5].line_type == LineType.EMPTY
        assert cleaned[5].cleaned == ""
        # Empty line keeps typing state alive
        assert cleaned[6].line_type == LineType.EMPTY
        assert cleaned[6].cleaned == ""
        # Typing after empty line still filtered
        assert cleaned[7].line_type == LineType.EMPTY
        assert cleaned[7].cleaned == ""

    def test_activity_indicator_breaks_state(self):
        """Test activity indicator breaks wrapped-input state so response shows."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "✨ hello world",
            "⠋ Thinking...",
            "Here is my response.",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.INPUT_MARKER
        # Activity indicator filtered by handler
        assert cleaned[1].line_type == LineType.EMPTY
        assert cleaned[1].cleaned == ""
        # Response preserved (state was broken by activity indicator)
        assert cleaned[2].line_type == LineType.CONTENT
        assert cleaned[2].cleaned == "Here is my response."

    def test_input_header_filters_typing(self):
        """Test typing after kimi-cli '── input ──' header is filtered."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "Here is the agent response.",
            "",
            "── input ─────────────────────────────────────────",
            " hello world this is the user typing a very long message",
            "that wraps across multiple lines",
            "",
            "still typing after empty line",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.CONTENT
        # Input header is SEPARATOR
        assert cleaned[2].line_type == LineType.SEPARATOR
        # Typing lines filtered to EMPTY
        assert cleaned[3].line_type == LineType.EMPTY
        assert cleaned[3].cleaned == ""
        assert cleaned[4].line_type == LineType.EMPTY
        assert cleaned[4].cleaned == ""
        # Empty line keeps typing state alive
        assert cleaned[5].line_type == LineType.EMPTY
        assert cleaned[5].cleaned == ""
        # Typing after empty line still filtered
        assert cleaned[6].line_type == LineType.EMPTY
        assert cleaned[6].cleaned == ""

    def test_input_header_plan_mode(self):
        """Test plan mode '╌╌ input · plan ═════' header filters typing."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "Agent response.",
            "",
            "╌╌ input · plan ══════════════════════════════════",
            " hello world",
            "that wraps",
            "",
            "still typing after empty line",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.CONTENT
        assert cleaned[2].line_type == LineType.SEPARATOR
        assert cleaned[3].line_type == LineType.EMPTY
        assert cleaned[4].line_type == LineType.EMPTY
        assert cleaned[5].line_type == LineType.EMPTY
        assert cleaned[5].cleaned == ""
        assert cleaned[6].line_type == LineType.EMPTY
        assert cleaned[6].cleaned == ""

    def test_input_header_with_queued_messages(self):
        """Test '── input · N queued ──' header filters typing."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "Agent response.",
            "",
            "── input · 2 queued ───────────────────────────────",
            " hello world",
            "that wraps",
            "",
            "still typing after empty line",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.CONTENT
        assert cleaned[2].line_type == LineType.SEPARATOR
        assert cleaned[3].line_type == LineType.EMPTY
        assert cleaned[4].line_type == LineType.EMPTY
        assert cleaned[5].line_type == LineType.EMPTY
        assert cleaned[5].cleaned == ""
        assert cleaned[6].line_type == LineType.EMPTY
        assert cleaned[6].cleaned == ""

    def test_input_header_empty_prompt_no_leak(self):
        """Test input header with empty prompt does not filter response.

        In practice there is never agent output after the input prompt;
        the empty prompt (single space) keeps filter_wrapped alive so
        that typing which appears after it is correctly filtered.
        """
        cleaner = TmuxCleaner("kimi")
        lines = [
            "Agent response.",
            "",
            "── input ─────────────────────────────────────────",
            " ",  # empty prompt (just space)
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.CONTENT
        assert cleaned[2].line_type == LineType.SEPARATOR
        # Empty prompt line is EMPTY but keeps filter_wrapped alive
        assert cleaned[3].line_type == LineType.EMPTY
        assert cleaned[3].cleaned == ""

    def test_typing_matching_activity_indicator_does_not_leak(self):
        """User typing that matches activity patterns must not leak.

        Previously, a line like 'Thinking...' in the middle of user typing
        would break filter_wrapped because the handler filters it to EMPTY,
        causing all subsequent typing lines to leak through.
        """
        cleaner = TmuxCleaner("kimi")
        lines = [
            "── input ─────────────────────────────────────────",
            " hello world",
            "Thinking...",
            "more typing here",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.SEPARATOR
        # All typing lines must be filtered
        for c in cleaned[1:]:
            assert c.line_type == LineType.EMPTY, f"Expected EMPTY, got {c.line_type}: {c.cleaned!r}"
            assert c.cleaned == ""

    def test_typing_matching_status_pattern_does_not_leak(self):
        """User typing that matches a status pattern must not leak."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "── input ─────────────────────────────────────────",
            " hello world",
            "yolo agent | context: 45.3%",
            "more typing here",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.SEPARATOR
        for c in cleaned[1:]:
            assert c.line_type in (LineType.EMPTY, LineType.STATUS_BAR), (
                f"Expected EMPTY or STATUS_BAR, got {c.line_type}: {c.cleaned!r}"
            )
            assert c.cleaned == ""

    def test_typing_with_single_word_lines_does_not_leak(self):
        """User typing short single-word lines must not leak.

        The partial-word filter in KimiHandler can filter single-word lines
        (e.g. variable names or short commands).  That must not break the
        wrapped-input state.
        """
        cleaner = TmuxCleaner("kimi")
        lines = [
            "── input ─────────────────────────────────────────",
            " hello",
            "world",
            "foo",
            "bar",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.SEPARATOR
        for c in cleaned[1:]:
            assert c.line_type == LineType.EMPTY, f"Expected EMPTY, got {c.line_type}: {c.cleaned!r}"
            assert c.cleaned == ""

    def test_typing_at_prompt_with_activity_match_does_not_leak(self):
        """Typing after 💫 that matches an activity pattern must not leak."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "💫 hello world",
            "Thinking...",
            "more typing here",
        ]
        cleaned = cleaner.clean_batch(lines)
        for c in cleaned:
            assert c.line_type == LineType.EMPTY, f"Expected EMPTY, got {c.line_type}: {c.cleaned!r}"
            assert c.cleaned == ""

    def test_prompt_alone_followed_by_typing_filtered(self):
        """Prompt marker alone on one line followed by typing on next line."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "💫",
            "hello world",
            "more typing",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.PROMPT_MARKER
        assert cleaned[0].cleaned == "💫"
        for c in cleaned[1:]:
            assert c.line_type == LineType.EMPTY, f"Expected EMPTY, got {c.line_type}: {c.cleaned!r}"
            assert c.cleaned == ""

    def test_shell_prompt_alone_followed_by_typing_filtered(self):
        """Shell prompt '$ ' alone followed by typing on next line."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "$ ",
            "cargo check",
            "more typing",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.PROMPT_MARKER
        assert cleaned[0].cleaned == "$"
        for c in cleaned[1:]:
            assert c.line_type == LineType.EMPTY, f"Expected EMPTY, got {c.line_type}: {c.cleaned!r}"
            assert c.cleaned == ""

    def test_typing_with_bullet_does_not_leak(self):
        """User typing that includes bullet characters must not leak."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "── input ─────────────────────────────────────────",
            " hello world",
            "• this is a list item",
            "more typing here",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.SEPARATOR
        for c in cleaned[1:]:
            assert c.line_type == LineType.EMPTY, f"Expected EMPTY, got {c.line_type}: {c.cleaned!r}"
            assert c.cleaned == ""

    def test_typing_with_separator_does_not_leak(self):
        """User typing that includes separator lines must not leak."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "── input ─────────────────────────────────────────",
            " hello world",
            "─────────────────────────────────────────────────",
            "more typing here",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.SEPARATOR
        for c in cleaned[1:]:
            assert c.line_type == LineType.EMPTY, f"Expected EMPTY, got {c.line_type}: {c.cleaned!r}"
            assert c.cleaned == ""

    def test_typing_with_input_marker_character_does_not_leak(self):
        """User typing that includes ✨ character must not leak."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "── input ─────────────────────────────────────────",
            " hello world",
            "✨ something",
            "more typing here",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.SEPARATOR
        for c in cleaned[1:]:
            assert c.line_type == LineType.EMPTY, f"Expected EMPTY, got {c.line_type}: {c.cleaned!r}"
            assert c.cleaned == ""

    def test_comprehensive_typing_scenario(self):
        """Complex typing with bullets, separators, ✨, activity, and status."""
        cleaner = TmuxCleaner("kimi")
        lines = [
            "Agent response here.",
            "",
            "── input ─────────────────────────────────────────",
            " hello world",
            "this is a second line",
            "",
            "• bullet in typing",
            "─────────────────────────",
            "✨ sparkle in typing",
            "Thinking...",
            "yolo agent | context: 45.3%",
            "singleword",
            "still typing",
        ]
        cleaned = cleaner.clean_batch(lines)
        assert cleaned[0].line_type == LineType.CONTENT
        assert cleaned[0].cleaned == "Agent response here."
        assert cleaned[1].line_type == LineType.EMPTY
        assert cleaned[2].line_type == LineType.SEPARATOR
        for c in cleaned[3:]:
            assert c.line_type in (LineType.EMPTY, LineType.STATUS_BAR), (
                f"Expected EMPTY or STATUS_BAR, got {c.line_type}: {c.cleaned!r}"
            )
            assert c.cleaned == ""


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

    def test_border_with_tool_icon(self):
        """Test OpenCode border + tool icon is converted, not discarded as SEPARATOR."""
        cleaner = TmuxCleaner("opencode")
        # Bash command with left border
        cleaned = cleaner.clean_line("┃ $ cargo check -p coder")
        assert cleaned.cleaned == "Tool: cargo check -p coder"
        assert cleaned.line_type == LineType.TOOL_CALL
        # Glob with left border
        cleaned = cleaner.clean_line("┃ ✱ Glob \"src/*.py\"")
        assert cleaned.cleaned == 'Tool: Glob "src/*.py"'
        assert cleaned.line_type == LineType.TOOL_CALL
        # Build with left border
        cleaned = cleaner.clean_line("┃ ▣ Build · MiniMax")
        assert cleaned.cleaned == "Tool: Build · MiniMax"
        assert cleaned.line_type == LineType.TOOL_CALL
        # Plain border (no tool icon) should still be SEPARATOR
        cleaned = cleaner.clean_line("┃ Ask anything...")
        assert cleaned.line_type == LineType.SEPARATOR


class TestOtherHandlers:
    """Tests for Coder, Grok, and Gemini handlers."""

    def test_coder_prompt_marker_detected(self):
        """Test coder> prompt is classified as PROMPT_MARKER and typing is filtered."""
        cleaner = TmuxCleaner("coder")
        cleaned = cleaner.clean_line("coder> hello")
        assert cleaned.line_type == LineType.PROMPT_MARKER
        # Prompt marker starts typing region; subsequent lines are blanked
        batch = cleaner.clean_batch(["coder> hello", "more typing"])
        assert batch[0].line_type == LineType.PROMPT_MARKER
        assert batch[1].line_type == LineType.EMPTY

    def test_coder_continuation_prompt_detected(self):
        """Test ...> continuation prompt is classified as PROMPT_MARKER."""
        cleaner = TmuxCleaner("coder")
        cleaned = cleaner.clean_line("...> more code")
        assert cleaned.line_type == LineType.PROMPT_MARKER
        # Prompt marker starts typing region; subsequent lines are blanked
        batch = cleaner.clean_batch(["...> more code", "and more"])
        assert batch[0].line_type == LineType.PROMPT_MARKER
        assert batch[1].line_type == LineType.EMPTY

    def test_grok_prompt_marker_detected(self):
        """Grok has no prompt markers, so normal content passes."""
        cleaner = TmuxCleaner("grok")
        cleaned = cleaner.clean_line("Hello world")
        assert cleaned.line_type == LineType.CONTENT
        assert cleaned.cleaned == "Hello world"

    def test_gemini_prompt_marker_detected(self):
        """Test gemini> prompt is classified as PROMPT_MARKER."""
        cleaner = TmuxCleaner("gemini")
        cleaned = cleaner.clean_line("gemini> hello")
        assert cleaned.line_type == LineType.PROMPT_MARKER
        # Prompt marker starts typing region; subsequent lines are blanked
        batch = cleaner.clean_batch(["gemini> hello", "more typing"])
        assert batch[0].line_type == LineType.PROMPT_MARKER
        assert batch[1].line_type == LineType.EMPTY


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
        assert LineType.TOOL_CALL is not None


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
