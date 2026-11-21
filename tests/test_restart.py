"""Tests for restart_session and the ``gg restart`` command."""

from __future__ import annotations

import argparse
import importlib
from unittest.mock import MagicMock

import pytest

from gg_core._types import AgentState
from gg_core.cli.parser import create_parser
from gg_core.core import session as session_mod
from gg_core.core.session import restart_session

run_mod = importlib.import_module("gg_core.cli.run")

run_mod_session_names = [
    "get_tmux",
    "detect_state",
    "resolve_agent",
    "resolve_project_agent",
    "stop_session",
    "start_session",
]


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Patch every collaborator restart_session touches."""
    mocks: dict[str, MagicMock] = {}
    for name in run_mod_session_names:
        mock = MagicMock(name=name)
        monkeypatch.setattr(session_mod, name, mock)
        mocks[name] = mock
    tmux = MagicMock(name="tmux")
    mocks["get_tmux"].return_value = tmux
    mocks["tmux"] = tmux
    return mocks


class _FakeTime:
    """time module shim: monotonic advances by step, sleep is a no-op."""

    def __init__(self, step: float = 0.0) -> None:
        self._now = 0.0
        self._step = step

    def monotonic(self) -> float:
        self._now += self._step
        return self._now

    def sleep(self, _seconds: float) -> None:
        return None


class TestRestartSession:
    def test_idle_session_restarts_with_recorded_agent(
        self, fake_session: dict[str, MagicMock]
    ) -> None:
        fake_session["tmux"].has_session.return_value = True
        fake_session["detect_state"].return_value = AgentState.IDLE
        fake_session["resolve_agent"].return_value = "omp"

        assert restart_session("proj") is True
        fake_session["stop_session"].assert_called_once_with("proj")
        fake_session["start_session"].assert_called_once_with("proj", "omp")

    def test_waits_while_working_then_restarts(
        self, fake_session: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_session["tmux"].has_session.return_value = True
        fake_session["detect_state"].side_effect = [
            AgentState.WORKING,
            AgentState.WORKING,
            AgentState.IDLE,
        ]
        fake_session["resolve_agent"].return_value = "kimi"
        monkeypatch.setattr(session_mod, "time", _FakeTime(step=2.0))

        assert restart_session("proj", timeout=10.0) is True
        assert fake_session["detect_state"].call_count == 3
        fake_session["stop_session"].assert_called_once_with("proj")
        fake_session["start_session"].assert_called_once_with("proj", "kimi")

    def test_times_out_and_skips_working_session(
        self, fake_session: dict[str, MagicMock], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_session["tmux"].has_session.return_value = True
        fake_session["detect_state"].return_value = AgentState.WORKING
        monkeypatch.setattr(session_mod, "time", _FakeTime(step=5.0))

        assert restart_session("proj", timeout=5.0) is False
        fake_session["stop_session"].assert_not_called()
        fake_session["start_session"].assert_not_called()

    def test_force_restarts_without_waiting(self, fake_session: dict[str, MagicMock]) -> None:
        fake_session["tmux"].has_session.return_value = True
        fake_session["detect_state"].return_value = AgentState.WORKING

        assert restart_session("proj", force=True) is True
        fake_session["detect_state"].assert_not_called()
        fake_session["stop_session"].assert_called_once_with("proj")
        fake_session["start_session"].assert_called_once_with("proj", fake_session["resolve_agent"].return_value)

    def test_not_running_session_is_started(
        self, fake_session: dict[str, MagicMock]
    ) -> None:
        fake_session["tmux"].has_session.return_value = False
        fake_session["resolve_project_agent"].return_value = "dsh"

        assert restart_session("proj") is True
        fake_session["stop_session"].assert_not_called()
        fake_session["start_session"].assert_called_once_with("proj", "dsh")

    def test_invalid_project_rejected(self, fake_session: dict[str, MagicMock]) -> None:
        from gg_core._errors import ValidationError

        with pytest.raises(ValidationError):
            restart_session("bad name!")
        fake_session["start_session"].assert_not_called()


class TestRestartCommand:
    def _cmd(self):
        return run_mod.cmd_restart

    def test_all_restarts_every_running_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(run_mod, "list_sessions", lambda: ["a", "b"])
        restarted: list[str] = []
        monkeypatch.setattr(
            run_mod,
            "restart_session",
            lambda project, timeout, force: restarted.append(project) or True,
        )

        assert self._cmd()([], all_sessions=True) == 0
        assert restarted == ["a", "b"]

    def test_all_rejects_project_names(self) -> None:
        assert self._cmd()(["a"], all_sessions=True) == 2

    def test_no_targets_is_usage_error(self) -> None:
        assert self._cmd()([]) == 2

    def test_all_with_no_running_sessions(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(run_mod, "list_sessions", lambda: [])
        assert self._cmd()([], all_sessions=True) == 0
        assert "No running sessions" in capsys.readouterr().out

    def test_skip_yields_exit_1_and_continues(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        done: list[str] = []

        def fake_restart(project, timeout, force):
            if project == "busy":
                return False
            done.append(project)
            return True

        monkeypatch.setattr(run_mod, "restart_session", fake_restart)

        assert self._cmd()(["ok", "busy"]) == 1
        assert done == ["ok"]
        assert "skipped" in capsys.readouterr().err

    def test_default_timeout_passed_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from gg_core.core.session import RESTART_WAIT_TIMEOUT

        seen: dict[str, float] = {}

        def fake_restart(project, timeout, force):
            seen["timeout"] = timeout
            return True

        monkeypatch.setattr(run_mod, "restart_session", fake_restart)
        assert self._cmd()(["a"]) == 0
        assert seen["timeout"] == RESTART_WAIT_TIMEOUT


class TestRestartParser:
    def test_parse_projects(self) -> None:
        args: argparse.Namespace = create_parser().parse_args(["restart", "a", "b"])
        assert args.projects == ["a", "b"]
        assert args.all_sessions is False
        assert args.force is False
        assert args.timeout is None

    def test_parse_flags(self) -> None:
        args: argparse.Namespace = create_parser().parse_args(
            ["restart", "--all", "--force", "--timeout", "30"]
        )
        assert args.projects == []
        assert args.all_sessions is True
        assert args.force is True
        assert args.timeout == 30.0
