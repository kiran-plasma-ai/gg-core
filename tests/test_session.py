"""Tests for session management."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gitgantt._errors import (
    SessionError,
    SessionExists,
    SessionNotFound,
    ValidationError,
)
from gitgantt.core import session as session_module
from gitgantt.core.session import run_cmd, start_session, stop_session, send_command


class TestRunCmd:
    """Tests for run_cmd function."""

    def test_success(self, mock_subprocess):
        """Test successful command execution."""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "output"
        mock_subprocess.return_value.stderr = ""

        success, stdout, stderr = run_cmd(["echo", "hello"])

        assert success is True
        assert stdout == "output"
        assert stderr == ""

    def test_failure(self, mock_subprocess):
        """Test failed command execution."""
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stdout = ""
        mock_subprocess.return_value.stderr = "error"

        success, stdout, stderr = run_cmd(["false"])

        assert success is False
        assert stderr == "error"

    def test_timeout(self, mock_subprocess):
        """Test command timeout."""
        mock_subprocess.side_effect = session_module.subprocess.TimeoutExpired("cmd", 1)

        success, stdout, stderr = run_cmd(["sleep", "10"], timeout=1)

        assert success is False
        assert stderr == "Timeout"

    def test_not_found(self, mock_subprocess):
        """Test command not found."""
        mock_subprocess.side_effect = FileNotFoundError("cmd not found")

        success, stdout, stderr = run_cmd(["nonexistent"])

        assert success is False
        assert "not found" in stderr

    def test_check_raises(self, mock_subprocess):
        """Test check=True raises on failure."""
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stderr = "error"

        with pytest.raises(SessionError) as exc_info:
            run_cmd(["false"], check=True)

        assert "Command failed" in str(exc_info.value)


class TestStartSession:
    """Tests for start_session function."""

    @patch("gitgantt.core.session.get_tmux")
    @patch("gitgantt.core.session.run_cmd")
    @patch("gitgantt.core.session.wait_for")
    def test_start_success(
        self, mock_wait_for, mock_run_cmd, mock_get_tmux, tmp_path, monkeypatch
    ):
        """Test successful session start."""
        # Setup mocks
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = False
        mock_get_tmux.return_value = mock_tmux

        mock_run_cmd.return_value = (True, "", "")
        mock_wait_for.return_value = True  # Session appears

        # Mock LOG_DIR to tmp_path
        monkeypatch.setattr(session_module, "LOG_DIR", tmp_path)

        # Start session
        start_session("testproj", "kimi")

        # Verify calls - should reset-failed, stop, set-env, start
        calls = mock_run_cmd.call_args_list
        assert len(calls) >= 4  # reset-failed, stop, set-env, start

    @patch("gitgantt.core.session.get_tmux")
    @patch("gitgantt.core.session.run_cmd")
    def test_start_session_exists(self, mock_run_cmd, mock_get_tmux):
        """Test starting session that already exists."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = True
        mock_get_tmux.return_value = mock_tmux

        with pytest.raises(SessionExists):
            start_session("testproj", "kimi")

    @patch("gitgantt.core.session.get_tmux")
    @patch("gitgantt.core.session.run_cmd")
    def test_start_invalid_project(self, mock_run_cmd, mock_get_tmux):
        """Test starting session with invalid project name."""
        with pytest.raises(ValidationError):
            start_session("invalid;name", "kimi")

    @patch("gitgantt.core.session.get_tmux")
    @patch("gitgantt.core.session.run_cmd")
    @patch("gitgantt.core.session.wait_for")
    def test_start_timeout(
        self, mock_wait_for, mock_run_cmd, mock_get_tmux, tmp_path, monkeypatch
    ):
        """Test session start timeout."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = False
        mock_get_tmux.return_value = mock_tmux

        mock_run_cmd.return_value = (True, "", "")
        mock_wait_for.return_value = False  # Session never appears

        monkeypatch.setattr(session_module, "LOG_DIR", tmp_path)

        with pytest.raises(SessionError) as exc_info:
            start_session("testproj", "kimi")

        assert "tmux session not found" in str(exc_info.value)


class TestStopSession:
    """Tests for stop_session function."""

    @patch("gitgantt.core.session.get_tmux")
    @patch("gitgantt.core.session.run_cmd")
    def test_stop_success(self, mock_run_cmd, mock_get_tmux):
        """Test successful session stop."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = True
        mock_get_tmux.return_value = mock_tmux

        mock_run_cmd.return_value = (True, "", "")

        stop_session("testproj")

        # Should call systemctl stop
        mock_run_cmd.assert_called()

    @patch("gitgantt.core.session.get_tmux")
    def test_stop_not_exists(self, mock_get_tmux):
        """Test stopping session that doesn't exist."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = False
        mock_get_tmux.return_value = mock_tmux

        with pytest.raises(SessionNotFound):
            stop_session("testproj")


class TestSendCommand:
    """Tests for send_command function."""

    @patch("gitgantt.core.session.get_tmux")
    def test_send_success(self, mock_get_tmux):
        """Test successful command send."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = True
        mock_tmux.send_keys.return_value = None
        mock_get_tmux.return_value = mock_tmux

        send_command("testproj", "echo hello")

        mock_tmux.send_keys.assert_called_once_with("testproj", "echo hello")

    @patch("gitgantt.core.session.get_tmux")
    def test_send_not_exists(self, mock_get_tmux):
        """Test sending to session that doesn't exist."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = False
        mock_get_tmux.return_value = mock_tmux

        with pytest.raises(SessionNotFound):
            send_command("testproj", "echo hello")

    def test_send_invalid_project(self):
        """Test sending to invalid project name."""
        with pytest.raises(ValidationError):
            send_command("invalid;name", "echo hello")
