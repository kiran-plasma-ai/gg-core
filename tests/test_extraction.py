"""Tests for extraction module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gg_core._errors import QuotaExceeded, ValidationError
from gg_core.cleaning import LineType
from gg_core.core.extraction import (
    check_project_quota_error,
    check_quota_error,
    detect_quota_error,
    extract_agent_output,
    extract_since_last_input,
    get_latest_response,
)


class TestExtractAgentOutput:
    """Tests for extract_agent_output."""

    def test_returns_lines_after_last_input_marker(self):
        """Should return only lines after the last INPUT_MARKER."""
        lines = [
            "✨ first message",
            "",
            "Agent response to first.",
            "✨ second message",
            "",
            "Agent response to second.",
        ]
        result = extract_agent_output(lines, agent="kimi")
        # Only lines after the LAST INPUT_MARKER are returned.
        # clean_batch preserves the agent response because the empty line
        # breaks the after-* filter.
        assert len(result) == 2
        assert result[0].cleaned == ""
        assert result[0].line_type == LineType.EMPTY
        assert result[1].cleaned == "Agent response to second."

    def test_empty_list_when_input_marker_is_last_line(self):
        """When the last line is an INPUT_MARKER, result should be empty."""
        lines = [
            "Agent response.",
            "✨ hello world",
        ]
        result = extract_agent_output(lines, agent="kimi")
        assert result == []

    def test_returns_all_visible_lines_when_no_input_marker(self):
        """Fallback: return all visible lines if no INPUT_MARKER exists."""
        lines = [
            "Agent response line 1.",
            "Agent response line 2.",
        ]
        result = extract_agent_output(lines, agent="kimi")
        assert len(result) == 2
        assert result[0].cleaned == "Agent response line 1."
        assert result[1].cleaned == "Agent response line 2."

    def test_filters_typing_after_input_header(self):
        """Typing after input header should be filtered out by clean_batch."""
        lines = [
            "Agent response.",
            "",
            "── input ─────────────────────────────────────────",
            " hello world",
            "more typing",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        # Only the agent response should remain; typing is filtered by clean_batch
        assert result == ["Agent response."]


class TestExtractSinceLastInput:
    """Tests for extract_since_last_input."""

    def test_basic_extraction(self):
        """Should return cleaned text after last INPUT_MARKER."""
        lines = [
            "✨ hello world",
            "",
            "Agent response here.",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Agent response here."]

    def test_empty_when_input_marker_is_last(self):
        """Should return empty list when INPUT_MARKER is the last line."""
        lines = [
            "Some earlier output.",
            "✨ hello world",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == []

    def test_skips_prompt_markers(self):
        """PROMPT_MARKER lines should be skipped in output."""
        lines = [
            "✨ hello",
            "💫",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == []

    def test_no_input_marker_fallback(self):
        """Without any INPUT_MARKER, should return visible lines."""
        lines = [
            "Line one.",
            "Line two.",
        ]
        result = extract_since_last_input(lines, agent="kimi")
        assert result == ["Line one.", "Line two."]


class TestGetLatestResponse:
    """Tests for get_latest_response."""

    def test_invalid_project_raises(self):
        """Should raise ValidationError for invalid project names."""
        with pytest.raises(ValidationError):
            get_latest_response("../etc", agent="kimi")

    def test_wire_path_used_for_kimi(self, tmp_path):
        """When wire.jsonl exists for kimi, return wire text."""
        with patch(
            "gg_core.core.wire.find_kimi_wire_path", return_value=tmp_path / "wire.jsonl"
        ), patch(
            "gg_core.core.wire.extract_wire_text", return_value=["wire response"]
        ):
            result = get_latest_response("myproject", agent="kimi")
            assert result == ["wire response"]

    def test_wire_missing_fallback_to_tmux(self):
        """When wire.jsonl is missing, fall back to tmux capture."""
        with patch(
            "gg_core.core.wire.find_kimi_wire_path", return_value=None
        ), patch(
            "gg_core.core.tmux.get_tmux"
        ) as mock_get_tmux:
            mock_tmux = MagicMock()
            mock_tmux.capture_pane.return_value = ["✨ hello", "", "tmux response"]
            mock_get_tmux.return_value = mock_tmux

            result = get_latest_response("myproject", agent="kimi")
            assert result == ["tmux response"]

    def test_non_kimi_agent_uses_tmux_directly(self):
        """Non-kimi agents should always use tmux capture."""
        with patch(
            "gg_core.core.wire.find_kimi_wire_path"
        ) as mock_find_wire, patch(
            "gg_core.core.tmux.get_tmux"
        ) as mock_get_tmux:
            mock_tmux = MagicMock()
            mock_tmux.capture_pane.return_value = ["coder output"]
            mock_get_tmux.return_value = mock_tmux

            result = get_latest_response("myproject", agent="coder")
            mock_find_wire.assert_not_called()
            assert result == ["coder output"]

    def test_tmux_exception_returns_empty(self):
        """When tmux capture fails, return empty list with logging."""
        with patch(
            "gg_core.core.wire.find_kimi_wire_path", return_value=None
        ), patch(
            "gg_core.core.tmux.get_tmux"
        ) as mock_get_tmux:
            mock_tmux = MagicMock()
            mock_tmux.capture_pane.side_effect = OSError("tmux error")
            mock_get_tmux.return_value = mock_tmux

            result = get_latest_response("myproject", agent="kimi")
            assert result == []

    def test_wire_read_failure_fallback_to_tmux(self):
        """When wire read fails, fall back to tmux capture."""
        with patch(
            "gg_core.core.wire.find_kimi_wire_path", return_value=Path("/tmp/wire.jsonl")
        ), patch(
            "gg_core.core.wire.extract_wire_text", side_effect=OSError("read error")
        ), patch(
            "gg_core.core.tmux.get_tmux"
        ) as mock_get_tmux:
            mock_tmux = MagicMock()
            mock_tmux.capture_pane.return_value = ["fallback response"]
            mock_get_tmux.return_value = mock_tmux

            result = get_latest_response("myproject", agent="kimi")
            assert result == ["fallback response"]

    def test_agent_normalization(self):
        """Agent names should be normalized before wire detection."""
        with patch(
            "gg_core.core.wire.find_kimi_wire_path", return_value=None
        ) as mock_find_wire, patch(
            "gg_core.core.tmux.get_tmux"
        ) as mock_get_tmux:
            mock_tmux = MagicMock()
            mock_tmux.capture_pane.return_value = ["tmux response"]
            mock_get_tmux.return_value = mock_tmux

            # Capitalized "Kimi" should still trigger wire lookup
            result = get_latest_response("myproject", agent="Kimi")
            mock_find_wire.assert_called_once_with("myproject")
            assert result == ["tmux response"]


class TestQuotaDetection:
    """Tests for quota / usage-limit error detection."""

    def test_detect_quota_error_matches_usage_limit(self):
        """Detect the exact usage-limit error from wires."""
        lines = [
            "Working...",
            "Error: [provider.api_error] 403 You've reached your usage limit for this billing cycle. Your quota will be refreshed in the next cycle. Upgrade to get more: https://www.kimi.com/code/console?from=quota-upgrade",
        ]
        assert detect_quota_error(lines) is not None

    def test_detect_quota_error_with_ansi(self):
        """ANSI escapes should be stripped before matching."""
        lines = [
            "\x1b[31mError: [provider.api_error] 403 You've reached your usage limit\x1b[0m",
        ]
        assert detect_quota_error(lines) is not None

    def test_detect_quota_error_no_match(self):
        """Normal output should not match."""
        lines = ["All good.", "Done."]
        assert detect_quota_error(lines) is None

    def test_check_quota_error_raises(self):
        """check_quota_error raises QuotaExceeded."""
        lines = ["You've reached your usage limit for this billing cycle."]
        with pytest.raises(QuotaExceeded):
            check_quota_error(lines)

    @patch("gg_core.core.extraction.capture_pane")
    def test_check_project_quota_error(self, mock_capture):
        """Project-level helper captures pane and raises on quota error."""
        mock_capture.return_value = [
            "Error: [provider.api_error] 403 You've reached your usage limit"
        ]
        with pytest.raises(QuotaExceeded):
            check_project_quota_error("myproject", lines=50)
        mock_capture.assert_called_once_with("myproject", lines=50)
