"""Tests for session management."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from gg_core._errors import (
    SessionError,
    SessionExists,
    SessionNotFound,
    ValidationError,
)
from gg_core.core import session as session_module
from gg_core.core.session import (
    ensure_kimi_workspace_trust,
    kimi_trust_dir,
    kimi_workspace_trust_key,
    run_cmd,
    send_command,
    start_session,
    stop_session,
)


@pytest.fixture(autouse=True)
def _isolate_log_dir(tmp_path, monkeypatch):
    """Keep log and agent-marker writes out of the real runtime directory."""
    monkeypatch.setattr(session_module, "LOG_DIR", tmp_path)
    return tmp_path


class TestKimiWorkspaceTrust:
    """Tests for kimi-code workspace-trust pre-seeding."""

    def test_key_matches_live_gateway_record(self):
        """Key derivation must match kimi-code's own records on the gateway."""
        # Observed: ~/.kimi-code/workspace-trust/wd_gg-docent_6c233232a2e3
        # for root /home/user/gg-docent
        assert (
            kimi_workspace_trust_key("/home/user/gg-docent")
            == "wd_gg-docent_6c233232a2e3"
        )
        assert (
            kimi_workspace_trust_key("/home/user/websites")
            == "wd_websites_f915b85ff427"
        )

    def test_slug_normalization(self):
        """Slug rules mirror kimi-code workdir-slug.ts."""
        # Uppercase and spaces fold to a lowercase dash slug
        key = kimi_workspace_trust_key("/home/u/Some Project")
        assert key.startswith("wd_some-project_")
        assert len(key) == len("wd_some-project_") + 12

    def test_seed_writes_record(self, tmp_path, monkeypatch):
        """ensure_kimi_workspace_trust writes the record file."""
        monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproj"
        project_dir.mkdir()

        ensure_kimi_workspace_trust("myproj")

        trust_dir = kimi_trust_dir()
        record = trust_dir / kimi_workspace_trust_key(str(project_dir))
        assert record.exists()
        payload = json.loads(record.read_text(encoding="utf-8"))
        assert payload["root"] == str(project_dir)
        assert isinstance(payload["trustedAt"], int)

    def test_seed_idempotent(self, tmp_path, monkeypatch):
        """Seeding twice must not overwrite an existing record."""
        monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        project_dir = tmp_path / "myproj"
        project_dir.mkdir()

        ensure_kimi_workspace_trust("myproj")
        record = kimi_trust_dir() / kimi_workspace_trust_key(str(project_dir))
        original = record.read_text(encoding="utf-8")

        ensure_kimi_workspace_trust("myproj")
        assert record.read_text(encoding="utf-8") == original

    @patch("gg_core.core.session.ensure_kimi_workspace_trust")
    @patch("gg_core.core.session.wait_for", return_value=True)
    @patch("gg_core.core.session.run_cmd", return_value=(True, "", ""))
    @patch("gg_core.core.session.get_tmux")
    def test_seed_skips_non_kimi(
        self, mock_get_tmux, mock_run_cmd, mock_wait_for, mock_seed, tmp_path
    ):
        """Trust seeding is skipped for non-kimi agents."""
        # coder etc. do not use kimi-code's workspace-trust feature.
        mock_tmux = MagicMock()
        mock_tmux.has_session.side_effect = [False, True, True]
        mock_get_tmux.return_value = mock_tmux

        start_session("coderproj", "coder")

        mock_seed.assert_not_called()


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

    @patch("gg_core.core.session.get_tmux")
    @patch("gg_core.core.session.run_cmd")
    @patch("gg_core.core.session.wait_for")
    def test_start_success(
        self, mock_wait_for, mock_run_cmd, mock_get_tmux, tmp_path, monkeypatch
    ):
        """Test successful session start."""
        # Setup mocks: initial check returns False, later checks return True.
        mock_tmux = MagicMock()
        mock_tmux.has_session.side_effect = [False, True, True]
        mock_get_tmux.return_value = mock_tmux

        mock_run_cmd.return_value = (True, "", "")
        mock_wait_for.return_value = True  # Session appears

        # Mock LOG_DIR to tmp_path; isolate kimi-code trust seeding too
        monkeypatch.setattr(session_module, "LOG_DIR", tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path))

        # Start session
        start_session("testproj", "kimi")

        # Verify calls - should reset-failed, stop, set-env, start
        calls = mock_run_cmd.call_args_list
        assert len(calls) >= 4  # reset-failed, stop, set-env, start

        # kimi sessions must have their workspace trust pre-seeded so the
        # "Trust this folder?" prompt never blocks headless startup.
        trust_dir = tmp_path / "workspace-trust"  # KIMI_CODE_HOME=tmp_path
        records = list(trust_dir.glob("wd_testproj_*"))
        assert records, f"expected a trust record for testproj in {trust_dir}"
        payload = json.loads(records[0].read_text(encoding="utf-8"))
        assert payload["root"] == str(tmp_path / "testproj")

    @patch("gg_core.core.session.get_tmux")
    @patch("gg_core.core.session.run_cmd")
    @patch("gg_core.core.session.wait_for")
    def test_start_records_agent_marker(
        self, mock_wait_for, mock_run_cmd, mock_get_tmux, tmp_path
    ):
        """Starting a session records the agent for later resolution."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.side_effect = [False, True, True]
        mock_get_tmux.return_value = mock_tmux
        mock_run_cmd.return_value = (True, "", "")
        mock_wait_for.return_value = True

        start_session("markerproj", "omp")

        assert session_module.recorded_agent("markerproj") == "omp"
        assert session_module.agent_marker_path("markerproj").parent == tmp_path

    @patch("gg_core.core.session.get_tmux")
    @patch("gg_core.core.session.run_cmd")
    def test_start_session_exists(self, mock_run_cmd, mock_get_tmux):
        """Test starting session that already exists."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = True
        mock_get_tmux.return_value = mock_tmux

        with pytest.raises(SessionExists):
            start_session("testproj", "kimi")

    @patch("gg_core.core.session.get_tmux")
    @patch("gg_core.core.session.run_cmd")
    def test_start_invalid_project(self, mock_run_cmd, mock_get_tmux):
        """Test starting session with invalid project name."""
        with pytest.raises(ValidationError):
            start_session("invalid;name", "kimi")

    @patch("gg_core.core.session.get_tmux")
    @patch("gg_core.core.session.run_cmd")
    @patch("gg_core.core.session.wait_for")
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

    @patch("gg_core.core.session.get_tmux")
    @patch("gg_core.core.session.run_cmd")
    @patch("gg_core.core.session.wait_for")
    @patch("gg_core.core.session.time")
    def test_start_session_dies_immediately(
        self,
        mock_time,
        mock_wait_for,
        mock_run_cmd,
        mock_get_tmux,
        tmp_path,
        monkeypatch,
    ):
        """Test session that exits right after appearing."""
        mock_tmux = MagicMock()
        # Initial check: no session. After wait_for reports success, verify
        # check finds the session has already died.
        mock_tmux.has_session.side_effect = [False, False]
        mock_get_tmux.return_value = mock_tmux

        mock_run_cmd.return_value = (True, "", "")
        mock_wait_for.return_value = True

        monkeypatch.setattr(session_module, "LOG_DIR", tmp_path)

        with pytest.raises(SessionError) as exc_info:
            start_session("testproj", "kimi")

        assert "exited immediately" in str(exc_info.value)
        assert "Agent command:" in str(exc_info.value)


class TestStopSession:
    """Tests for stop_session function."""

    @patch("gg_core.core.session.get_tmux")
    @patch("gg_core.core.session.run_cmd")
    def test_stop_success(self, mock_run_cmd, mock_get_tmux):
        """Test successful session stop."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = True
        mock_get_tmux.return_value = mock_tmux

        mock_run_cmd.return_value = (True, "", "")

        stop_session("testproj")

        # Should call systemctl stop
        mock_run_cmd.assert_called()

    @patch("gg_core.core.session.get_tmux")
    @patch("gg_core.core.session.run_cmd")
    def test_stop_clears_agent_marker(self, mock_run_cmd, mock_get_tmux):
        """Stopping a session removes its recorded-agent marker."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = True
        mock_get_tmux.return_value = mock_tmux
        mock_run_cmd.return_value = (True, "", "")

        session_module.record_agent("markerproj", "kimi")
        assert session_module.recorded_agent("markerproj") == "kimi"

        stop_session("markerproj")

        assert session_module.recorded_agent("markerproj") is None

    @patch("gg_core.core.session.get_tmux")
    def test_stop_not_exists(self, mock_get_tmux):
        """Test stopping session that doesn't exist."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = False
        mock_get_tmux.return_value = mock_tmux

        with pytest.raises(SessionNotFound):
            stop_session("testproj")


class TestSendCommand:
    """Tests for send_command function."""

    @patch("gg_core.core.session.get_tmux")
    def test_send_success(self, mock_get_tmux):
        """Test successful command send."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = True
        mock_tmux.send_keys.return_value = None
        mock_get_tmux.return_value = mock_tmux

        send_command("testproj", "echo hello")

        mock_tmux.send_keys.assert_called_once_with(
            "testproj", "echo hello", literal=True
        )

    @patch("gg_core.core.session.get_tmux")
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


class TestDarwinSession:
    """Tests for macOS direct-tmux session path."""

    @patch("gg_core.core.session._use_launchd", return_value=True)
    @patch("gg_core.core.session._start_session_darwin")
    @patch("gg_core.core.session.get_tmux")
    def test_start_session_dispatch_darwin(
        self, mock_get_tmux, mock_darwin_start, mock_use
    ):
        """start_session dispatches to _start_session_darwin on macOS."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = False
        mock_get_tmux.return_value = mock_tmux

        start_session("testproj", "kimi")

        mock_darwin_start.assert_called_once()

    @patch("gg_core.core.session._use_launchd", return_value=True)
    @patch("gg_core.core.session._stop_session_darwin")
    @patch("gg_core.core.session.get_tmux")
    def test_stop_session_dispatch_darwin(
        self, mock_get_tmux, mock_darwin_stop, mock_use
    ):
        """stop_session dispatches to _stop_session_darwin on macOS."""
        mock_tmux = MagicMock()
        mock_tmux.has_session.return_value = True
        mock_get_tmux.return_value = mock_tmux

        stop_session("testproj")

        mock_darwin_stop.assert_called_once_with("testproj")
