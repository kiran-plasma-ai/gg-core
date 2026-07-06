"""Tests for tmux module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gg_core._errors import TmuxError
from gg_core.core.tmux import Tmux


class TestTmux:
    """Tests for Tmux class."""

    def test_has_session_true(self, mock_libtmux):
        """Test has_session returns True when session exists."""
        mock_libtmux.has_session.return_value = True
        tmux = Tmux()
        assert tmux.has_session("myproject") is True

    def test_has_session_false(self, mock_libtmux):
        """Test has_session returns False when session doesn't exist."""
        mock_libtmux.has_session.return_value = False
        tmux = Tmux()
        assert tmux.has_session("myproject") is False

    def test_list_sessions(self, mock_libtmux):
        """Test list_sessions returns session names."""
        mock_session = MagicMock()
        mock_session.session_name = "session1"
        mock_libtmux.sessions = [mock_session]

        tmux = Tmux()
        result = tmux.list_sessions()
        assert result == ["session1"]

    def test_list_sessions_filters_none(self, mock_libtmux):
        """Test list_sessions filters None session names."""
        mock_session = MagicMock()
        mock_session.session_name = None
        mock_libtmux.sessions = [mock_session]

        tmux = Tmux()
        result = tmux.list_sessions()
        assert result == []

    def test_get_session_found(self, mock_libtmux):
        """Test get_session returns session when found."""
        mock_session = MagicMock()
        mock_session.session_name = "myproject"
        mock_libtmux.sessions = [mock_session]

        tmux = Tmux()
        result = tmux.get_session("myproject")
        assert result is not None

    def test_get_session_not_found(self, mock_libtmux):
        """Test get_session returns None when not found."""
        mock_libtmux.sessions = []

        tmux = Tmux()
        result = tmux.get_session("nonexistent")
        assert result is None


class TestTmuxCapture:
    """Tests for capture_pane method."""

    def test_capture_pane_success(self, mock_libtmux):
        """Test successful pane capture."""
        mock_session = MagicMock()
        mock_session.session_name = "myproject"
        mock_pane = MagicMock()
        mock_pane.capture_pane.return_value = ["line1", "line2"]
        mock_session.active_window.active_pane = mock_pane
        mock_libtmux.sessions = [mock_session]

        tmux = Tmux()
        result = tmux.capture_pane("myproject")
        assert result == ["line1", "line2"]

    def test_capture_pane_session_not_found(self, mock_libtmux):
        """Test capture_pane raises when session not found."""
        mock_libtmux.sessions = []

        tmux = Tmux()
        with pytest.raises(TmuxError, match="Session not found"):
            tmux.capture_pane("nonexistent")


class TestTmuxSendKeys:
    """Tests for send_keys method."""

    def test_send_keys_success(self, mock_libtmux):
        """Test successful send_keys types text and submits with carriage return."""
        mock_session = MagicMock()
        mock_session.session_name = "myproject"
        mock_pane = MagicMock()
        mock_session.active_window.active_pane = mock_pane
        mock_libtmux.sessions = [mock_session]

        tmux = Tmux()
        tmux.send_keys("myproject", "ls")

        mock_pane.send_keys.assert_called_once_with("ls\r", literal=False, enter=False)

    def test_send_keys_literal(self, mock_libtmux):
        """Test send_keys with literal=True for multi-line text."""
        mock_session = MagicMock()
        mock_session.session_name = "myproject"
        mock_pane = MagicMock()
        mock_session.active_window.active_pane = mock_pane
        mock_libtmux.sessions = [mock_session]

        tmux = Tmux()
        tmux.send_keys("myproject", "line1\nline2", literal=True)

        mock_pane.send_keys.assert_called_once_with("line1\nline2\r", literal=True, enter=False)

    def test_send_keys_strips_trailing_newlines(self, mock_libtmux):
        """Trailing newlines are stripped so they don't insert blank lines."""
        mock_session = MagicMock()
        mock_session.session_name = "myproject"
        mock_pane = MagicMock()
        mock_session.active_window.active_pane = mock_pane
        mock_libtmux.sessions = [mock_session]

        tmux = Tmux()
        tmux.send_keys("myproject", "ls\n\r")

        mock_pane.send_keys.assert_called_once_with("ls\r", literal=False, enter=False)

    def test_send_keys_session_not_found(self, mock_libtmux):
        """Test send_keys raises when session not found."""
        mock_libtmux.sessions = []

        tmux = Tmux()
        with pytest.raises(TmuxError, match="Session not found"):
            tmux.send_keys("nonexistent", "ls")


class TestTmuxGetSessionInfo:
    """Tests for get_session_info method."""

    def test_get_session_info_exists(self, mock_libtmux):
        """Test get_session_info for existing session."""
        mock_session = MagicMock()
        mock_session.session_name = "myproject"
        mock_session.active_window = MagicMock()
        mock_session.active_window.active_pane = MagicMock()
        mock_libtmux.sessions = [mock_session]

        tmux = Tmux()
        info = tmux.get_session_info("myproject", Path("/tmp"))

        assert info.name == "myproject"
        assert info.exists is True
        assert info.active is True

    def test_get_session_info_not_exists(self, mock_libtmux):
        """Test get_session_info for nonexistent session."""
        mock_libtmux.sessions = []

        tmux = Tmux()
        info = tmux.get_session_info("nonexistent", Path("/tmp"))

        assert info.name == "nonexistent"
        assert info.exists is False
        assert info.active is False
