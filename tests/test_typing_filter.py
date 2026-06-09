"""Integration tests for the typing-filter pipeline.

These tests verify that user typing never leaks through to the final
extract_since_last_input output, while legitimate agent output is preserved.
"""

from __future__ import annotations

import pytest

from gg_core.core.extraction import extract_since_last_input


class TestTypingFilterPipeline:
    """End-to-end tests simulating real tmux capture scenarios."""

    def test_simple_agent_response(self):
        """Basic agent response after a submitted message."""
        lines = [
            "✨ hello world",
            "",
            "This is the agent response.",
            "It spans multiple lines.",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == [
            "This is the agent response.",
            "It spans multiple lines.",
        ]

    def test_typing_at_input_header(self):
        """User typing after an input header must be fully filtered."""
        lines = [
            "Agent response here.",
            "",
            "── input ─────────────────────────────────────────",
            " hello world this is the user typing",
            "that wraps across multiple lines",
            "",
            "more typing after empty line",
            "• bullet in typing",
            "─────────────────────────",
            "✨ sparkle in typing",
            "Thinking...",
            "yolo agent | context: 45.3%",
            "singleword",
            "still typing",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response here."]

    def test_typing_at_prompt_marker(self):
        """User typing at a 💫 prompt must be fully filtered."""
        lines = [
            "✨ previous message",
            "",
            "Agent response here.",
            "",
            "💫 hello world this is the user typing",
            "that wraps across multiple lines",
            "",
            "more typing after empty line",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response here."]

    def test_prompt_alone_followed_by_typing(self):
        """Prompt marker alone on one line, typing on the next."""
        lines = [
            "✨ previous message",
            "",
            "Agent response here.",
            "",
            "💫",
            "hello world",
            "more typing",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response here."]

    def test_shell_prompt_alone_followed_by_typing(self):
        """Shell prompt '$ ' alone followed by typing."""
        lines = [
            "✨ previous message",
            "",
            "Agent response here.",
            "",
            "$ ",
            "cargo check",
            "more typing",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response here."]

    def test_typing_with_activity_pattern(self):
        """Typing that accidentally matches an activity pattern."""
        lines = [
            "✨ previous message",
            "",
            "Agent response here.",
            "",
            "💫 hello world",
            "Thinking...",
            "more typing here",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response here."]

    def test_typing_with_status_pattern(self):
        """Typing that accidentally matches a status pattern."""
        lines = [
            "✨ previous message",
            "",
            "Agent response here.",
            "",
            "── input ─────────────────────────────────────────",
            " hello world",
            "yolo agent | context: 45.3%",
            "more typing here",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response here."]

    def test_typing_with_single_word_lines(self):
        """Typing short single-word lines."""
        lines = [
            "✨ previous message",
            "",
            "Agent response here.",
            "",
            "── input ─────────────────────────────────────────",
            " hello",
            "world",
            "foo",
            "bar",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response here."]

    def test_typing_with_bullet_separator_sparkle(self):
        """Typing containing bullets, separators, and ✨ characters."""
        lines = [
            "✨ previous message",
            "",
            "Agent response here.",
            "",
            "── input ─────────────────────────────────────────",
            " hello world",
            "• bullet in typing",
            "─────────────────────────",
            "✨ sparkle in typing",
            "more typing here",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response here."]

    def test_no_leak_when_input_marker_is_last(self):
        """When INPUT_MARKER is the last line, return empty."""
        lines = [
            "Some earlier output.",
            "✨ hello world",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == []

    def test_no_input_marker_returns_visible_lines(self):
        """Fallback: when no INPUT_MARKER, return visible lines."""
        lines = [
            "Line one.",
            "Line two.",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Line one.", "Line two."]

    def test_agent_output_with_tool_calls(self):
        """Agent response with tool calls is preserved."""
        lines = [
            "✨ hello world",
            "",
            "• Used Shell (ls)",
            "Tool result here.",
            "• Used ReadFile (test.py)",
            "File content here.",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == [
            "Tool: Used Shell (ls)",
            "Tool result here.",
            "Tool: Used ReadFile (test.py)",
            "File content here.",
        ]

    def test_multiple_message_cycles(self):
        """Multiple messages and responses in one capture."""
        lines = [
            "✨ message 1",
            "",
            "Response 1.",
            "✨ message 2",
            "",
            "Response 2.",
            "── input ─────────────────────────────────────────",
            " user typing here",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        # Only content after the LAST INPUT_MARKER + input header filtering
        assert result == ["Response 2."]

    @pytest.mark.parametrize(
        "prompt",
        [
            "💫 hello typing",
            "$ cargo check",
            "$ ",
            "💫",
        ],
    )
    def test_various_prompt_markers_trigger_typing_filter(self, prompt: str):
        """All forms of prompt markers trigger typing mode."""
        lines = [
            "✨ previous",
            "",
            "Agent response.",
            "",
            prompt,
            "typing line 1",
            "typing line 2",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response."]
