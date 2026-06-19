"""Tests for project status, discovery, and orchestration helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gg_core._errors import ValidationError
from gg_core._types import AgentState, ProjectStatus
from gg_core.core.status import (
    discover_projects,
    get_project_status,
    get_projects_status,
    wait_for_state,
)


class TestDiscoverProjects:
    """Tests for discover_projects."""

    def test_discovers_nonempty_directories(self, tmp_path):
        """Return directories that contain at least one item."""
        (tmp_path / "project_a").mkdir()
        (tmp_path / "project_a" / "file.txt").write_text("hello")
        (tmp_path / "project_b").mkdir()
        (tmp_path / "project_b" / "subdir").mkdir()
        (tmp_path / "empty").mkdir()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / ".hidden" / "x").write_text("x")

        result = discover_projects(tmp_path)
        assert result == ["project_a", "project_b"]

    def test_ignores_non_directories(self, tmp_path):
        """Files in base dir are not projects."""
        (tmp_path / "not_a_project.txt").write_text("x")
        assert discover_projects(tmp_path) == []

    def test_invalid_base_dir_returns_empty(self, tmp_path):
        """Non-existent base dir returns empty list without raising."""
        assert discover_projects(tmp_path / "does_not_exist") == []

    def test_defaults_to_home(self, monkeypatch, tmp_path):
        """When base_dir is None, scan HOME."""
        (tmp_path / "myproject").mkdir()
        (tmp_path / "myproject" / "x").write_text("x")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert "myproject" in discover_projects()

    def test_marker_filter(self, tmp_path):
        """Only return directories containing the marker."""
        (tmp_path / "with_git").mkdir()
        (tmp_path / "with_git" / ".git").mkdir()
        (tmp_path / "without_git").mkdir()
        (tmp_path / "without_git" / "x").write_text("x")

        result = discover_projects(tmp_path, marker=".git")
        assert result == ["with_git"]


class TestGetProjectStatus:
    """Tests for get_project_status."""

    @patch("gg_core.core.status.get_session_info")
    @patch("gg_core.core.status.detect_state")
    @patch("gg_core.core.status.get_latest_response")
    @patch("gg_core.core.status.find_kimi_wire_path")
    def test_full_status(
        self,
        mock_find_wire,
        mock_get_response,
        mock_detect_state,
        mock_get_info,
    ):
        """Aggregate session info, state, response, and wire path."""
        log_path = Path("/tmp/gg-core/myproj/agent.log")
        wire_path = Path("/home/x/.kimi-code/sessions/wd_myproj_hash/session_x/wire.jsonl")
        mock_get_info.return_value = MagicMock(
            exists=True,
            active=True,
            log_path=log_path,
            log_size=1234,
        )
        mock_detect_state.return_value = AgentState.IDLE
        mock_get_response.return_value = ["Done."]
        mock_find_wire.return_value = wire_path

        status = get_project_status("myproj")

        assert status == ProjectStatus(
            name="myproj",
            exists=True,
            active=True,
            state=AgentState.IDLE,
            agent="kimi",
            latest_response=["Done."],
            log_path=log_path,
            log_size=1234,
            wire_path=wire_path,
        )

    @patch("gg_core.core.status.get_session_info")
    @patch("gg_core.core.status.detect_state")
    @patch("gg_core.core.status.get_latest_response")
    @patch("gg_core.core.status.find_kimi_wire_path")
    def test_no_response_when_session_missing(
        self,
        mock_find_wire,
        mock_get_response,
        mock_detect_state,
        mock_get_info,
    ):
        """Do not read responses for non-existent sessions."""
        mock_get_info.return_value = MagicMock(
            exists=False,
            active=False,
            log_path=Path("/tmp/gg-core/nope/agent.log"),
            log_size=None,
        )

        status = get_project_status("nope")

        assert status.exists is False
        assert status.state == AgentState.UNKNOWN
        mock_get_response.assert_not_called()

    def test_invalid_project_name_raises(self):
        """Invalid project names raise ValidationError."""
        with pytest.raises(ValidationError):
            get_project_status("bad;name")


class TestGetProjectsStatus:
    """Tests for get_projects_status."""

    @patch("gg_core.core.status.get_project_status")
    def test_skips_invalid_projects(self, mock_get_status):
        """Invalid project names are logged and skipped, not raised."""
        log_path = Path("/tmp/gg-core/good/agent.log")

        def side_effect(project, *, include_response=True):
            if project == "good":
                return ProjectStatus(
                    name="good",
                    exists=True,
                    active=True,
                    state=AgentState.IDLE,
                    agent="kimi",
                    latest_response=[],
                    log_path=log_path,
                    log_size=0,
                )
            raise ValidationError(f"bad name: {project}")

        mock_get_status.side_effect = side_effect

        result = get_projects_status(["good", "bad;name"])
        assert len(result) == 1
        assert result[0].name == "good"


class TestWaitForState:
    """Tests for wait_for_state."""

    @patch("gg_core.core.status.detect_state")
    @patch("gg_core.core.status.time")
    def test_returns_true_when_state_reached(self, mock_time, mock_detect_state):
        """Return True immediately when state matches."""
        mock_detect_state.return_value = AgentState.IDLE
        assert wait_for_state("proj", AgentState.IDLE, timeout=5.0) is True

    @patch("gg_core.core.status.detect_state")
    @patch("gg_core.core.status.time")
    def test_returns_false_on_timeout(self, mock_time, mock_detect_state):
        """Return False if timeout elapses before target state."""
        mock_detect_state.return_value = AgentState.WORKING
        # Simulate time advancing faster than the sleep loop.
        mock_time.monotonic.side_effect = [0.0, 0.5, 1.1]
        assert wait_for_state("proj", AgentState.IDLE, timeout=1.0, interval=0.5) is False
        assert mock_detect_state.call_count == 2

    def test_invalid_project_name_raises(self):
        """Invalid project names raise ValidationError."""
        with pytest.raises(ValidationError):
            wait_for_state("bad;name", AgentState.IDLE, timeout=0.1)

    def test_invalid_interval_raises(self):
        """Non-positive interval raises ValueError."""
        with pytest.raises(ValueError):
            wait_for_state("proj", AgentState.IDLE, interval=0.0)

    def test_invalid_timeout_raises(self):
        """Negative timeout raises ValueError."""
        with pytest.raises(ValueError):
            wait_for_state("proj", AgentState.IDLE, timeout=-1.0)
