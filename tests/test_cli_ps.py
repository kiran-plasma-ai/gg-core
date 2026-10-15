"""Tests for rich gg ps output and --json."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from gg_core import SessionState

run_mod = importlib.import_module("gg_core.cli.run")


def _session_mock(created: int, activity: int, cwd: str) -> tuple[MagicMock, MagicMock]:
    session = MagicMock()
    session.session_created = created
    window = MagicMock()
    window.window_activity = activity
    session.active_window = window
    pane = MagicMock()
    pane.pane_current_path = cwd
    return session, pane


class TestFmtDuration:
    def test_units(self) -> None:
        assert run_mod._fmt_duration(None) == "?"
        assert run_mod._fmt_duration(45) == "45s"
        assert run_mod._fmt_duration(600) == "10m"
        assert run_mod._fmt_duration(7200) == "2h"
        assert run_mod._fmt_duration(200000) == "2d"


class TestCmdPs:
    def test_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(run_mod, "list_sessions", return_value=[]):
            assert run_mod.cmd_ps() == 0
        assert "No active sessions" in capsys.readouterr().out

    def test_table_columns(self, capsys: pytest.CaptureFixture[str]) -> None:
        session, pane = _session_mock(created=1000, activity=1800, cwd="/home/u/proj")
        tmux = MagicMock()
        tmux.get_session.return_value = session
        now = 2000
        with (
            patch.object(run_mod, "list_sessions", return_value=["proj"]),
            patch.object(run_mod, "resolve_agent", return_value="omp"),
            patch.object(run_mod, "detect_full_state", return_value=SessionState.WORKING),
            patch.object(run_mod, "get_tmux", return_value=tmux),
            patch.object(run_mod, "get_pane", return_value=pane),
            patch.object(run_mod.time, "time", return_value=now),
        ):
            assert run_mod.cmd_ps() == 0
        out = capsys.readouterr().out
        header = out.splitlines()[0].split()
        assert header == ["HOST", "PROJECT", "AGENT", "STATE", "IDLE", "AGE", "DIR"]
        row = out.splitlines()[2].split()
        assert row[1] == "proj"
        assert row[2] == "omp"
        assert row[3] == "working"
        assert row[4] == "3m"  # 2000-1800=200s -> 3m
        assert row[5] == "16m"  # 2000-1000=1000s -> 16m
        assert row[6] == "/home/u/proj"

    def test_json_shape(self, capsys: pytest.CaptureFixture[str]) -> None:
        session, pane = _session_mock(created=1000, activity=1900, cwd="/x")
        tmux = MagicMock()
        tmux.get_session.return_value = session
        with (
            patch.object(run_mod, "list_sessions", return_value=["proj"]),
            patch.object(run_mod, "resolve_agent", return_value="kimi"),
            patch.object(run_mod, "detect_full_state", return_value=SessionState.AWAITING_INPUT),
            patch.object(run_mod, "get_tmux", return_value=tmux),
            patch.object(run_mod, "get_pane", return_value=pane),
            patch.object(run_mod.time, "time", return_value=2000),
            patch.object(run_mod.socket, "gethostname", return_value="host1"),
        ):
            assert run_mod.cmd_ps(as_json=True) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["host"] == "host1"
        assert payload["sessions"][0] == {
            "project": "proj",
            "host": "host1",
            "agent": "kimi",
            "state": "awaiting_input",
            "idle_seconds": 100,
            "age_seconds": 1000,
            "dir": "/x",
        }

    def test_metadata_failure_yields_nulls(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        tmux = MagicMock()
        tmux.get_session.side_effect = RuntimeError("no server")
        with (
            patch.object(run_mod, "list_sessions", return_value=["proj"]),
            patch.object(run_mod, "resolve_agent", return_value="omp"),
            patch.object(run_mod, "detect_full_state", return_value=SessionState.UNKNOWN),
            patch.object(run_mod, "get_tmux", return_value=tmux),
            patch.object(run_mod, "get_pane", return_value=None),
        ):
            assert run_mod.cmd_ps(as_json=True) == 0
        row = json.loads(capsys.readouterr().out)["sessions"][0]
        assert row["idle_seconds"] is None
        assert row["age_seconds"] is None
        assert row["dir"] is None
        assert row["state"] == "unknown"
