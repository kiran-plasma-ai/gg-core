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

    def test_negative_timeout_rejected(self, fake_session: dict[str, MagicMock]) -> None:
        from gg_core._errors import ValidationError

        with pytest.raises(ValidationError, match="timeout"):
            restart_session("proj", timeout=-1)
        fake_session["start_session"].assert_not_called()

    def test_session_dying_during_wait_is_restarted(
        self, fake_session: dict[str, MagicMock]
    ) -> None:
        """A pane vanishing mid-wait must not fail the restart."""
        from gg_core._errors import SessionNotFound

        fake_session["tmux"].has_session.return_value = True
        fake_session["resolve_agent"].return_value = "omp"
        fake_session["detect_state"].side_effect = [
            AgentState.WORKING,
            SessionNotFound("gone"),
        ]

        assert restart_session("proj", timeout=60.0) is True
        fake_session["start_session"].assert_called_once_with("proj", "omp")

    def test_stop_sessionnotfound_treated_as_stopped(
        self, fake_session: dict[str, MagicMock]
    ) -> None:
        """A pane killed with a shared tmux server must not abort the restart."""
        from gg_core._errors import SessionNotFound

        fake_session["tmux"].has_session.return_value = True
        fake_session["detect_state"].return_value = AgentState.IDLE
        fake_session["stop_session"].side_effect = SessionNotFound("gone")

        assert restart_session("proj") is True
        fake_session["start_session"].assert_called_once()

    def test_invalid_project_rejected(self, fake_session: dict[str, MagicMock]) -> None:
        from gg_core._errors import ValidationError

        with pytest.raises(ValidationError):
            restart_session("bad name!")
        fake_session["start_session"].assert_not_called()


class TestRestartCommand:
    def _cmd(self):
        return run_mod.cmd_restart

    def _patch_restart_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> dict[str, list[str]]:
        """Record prepare/start call order; prepare controls skip/fail per project."""
        events: dict[str, list[str]] = {"prepares": [], "starts": []}

        def fake_prepare(project, timeout, force):
            events["prepares"].append(project)
            if project == "skipme":
                return None
            if project == "boom":
                raise run_mod.GGError("prepare failed")
            return "omp"

        monkeypatch.setattr(run_mod, "prepare_restart", fake_prepare)
        monkeypatch.setattr(
            run_mod,
            "start_session",
            lambda project, agent: events["starts"].append(project),
        )
        return events

    def test_all_restarts_every_running_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(run_mod, "list_sessions", lambda: ["a", "b"])
        events = self._patch_restart_pipeline(monkeypatch)

        assert self._cmd()([], all_sessions=True) == 0
        assert events == {"prepares": ["a", "b"], "starts": ["a", "b"]}

    def test_two_phase_stops_all_before_starting_any(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No session may be started before every target was prepared/stopped."""
        monkeypatch.setattr(run_mod, "list_sessions", lambda: ["a", "b"])
        events = self._patch_restart_pipeline(monkeypatch)

        order: list[str] = []

        def tracking_prepare(project, timeout, force):
            order.append(f"prepare:{project}")
            return "omp"

        def tracking_start(project, agent):
            order.append(f"start:{project}")

        monkeypatch.setattr(run_mod, "prepare_restart", tracking_prepare)
        monkeypatch.setattr(run_mod, "start_session", tracking_start)

        assert self._cmd()(["a", "b"]) == 0
        assert order == ["prepare:a", "prepare:b", "start:a", "start:b"]

    def test_all_rejects_project_names(self) -> None:
        assert self._cmd()(["a"], all_sessions=True) == 2

    def test_no_targets_is_usage_error(self) -> None:
        assert self._cmd()([]) == 2

    def test_all_with_no_running_sessions(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(run_mod, "list_sessions", lambda: [])
        assert self._cmd()([], all_sessions=True) == 0
        assert "No running sessions" in capsys.readouterr().out

    def test_skip_and_failure_yield_exit_1_and_never_start(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(run_mod, "list_sessions", lambda: ["ok", "skipme", "boom"])
        events = self._patch_restart_pipeline(monkeypatch)

        assert self._cmd()([], all_sessions=True) == 1
        assert events["starts"] == ["ok"]
        err = capsys.readouterr().err
        assert "skipped" in err
        assert "boom" in err

    def test_invalid_name_fails_before_touching_sessions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bad name must abort the batch before phase 1 stops anything."""
        from gg_core._errors import ValidationError

        monkeypatch.setattr(
            run_mod, "list_sessions", lambda: ["ok", "bad name!"]
        )
        prepared: list[str] = []
        monkeypatch.setattr(
            run_mod,
            "prepare_restart",
            lambda project, timeout, force: prepared.append(project) or "omp",
        )

        with pytest.raises(ValidationError):
            self._cmd()([], all_sessions=True)
        assert prepared == []

    def test_default_timeout_passed_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from gg_core.core.session import RESTART_WAIT_TIMEOUT

        seen: dict[str, float] = {}

        def fake_prepare(project, timeout, force):
            seen["timeout"] = timeout
            return "omp"

        monkeypatch.setattr(run_mod, "prepare_restart", fake_prepare)
        monkeypatch.setattr(run_mod, "start_session", lambda project, agent: None)
        assert self._cmd()(["a"]) == 0
        assert seen["timeout"] == RESTART_WAIT_TIMEOUT

    def test_custom_timeout_passed_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, float] = {}

        def fake_prepare(project, timeout, force):
            seen["timeout"] = timeout
            return "omp"

        monkeypatch.setattr(run_mod, "prepare_restart", fake_prepare)
        monkeypatch.setattr(run_mod, "start_session", lambda project, agent: None)
        assert self._cmd()(["a"], timeout=30.0) == 0
        assert seen["timeout"] == 30.0

    def test_duplicate_projects_restarted_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`gg restart web web` must not double-process the target."""
        events: dict[str, list[str]] = {"prepares": [], "starts": []}
        monkeypatch.setattr(
            run_mod,
            "prepare_restart",
            lambda project, timeout, force: events["prepares"].append(project) or "omp",
        )
        monkeypatch.setattr(
            run_mod,
            "start_session",
            lambda project, agent: events["starts"].append(project),
        )

        assert self._cmd()(["web", "web"]) == 0
        assert events == {"prepares": ["web"], "starts": ["web"]}

    def test_dispatch_wiring(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """parser -> _dispatch -> cmd_restart must reach the real handler args."""
        seen: dict[str, object] = {}

        def fake_cmd_restart(projects, *, all_sessions, force, timeout):
            seen.update(
                projects=projects,
                all_sessions=all_sessions,
                force=force,
                timeout=timeout,
            )
            return 0

        monkeypatch.setattr(run_mod, "cmd_restart", fake_cmd_restart)
        args = run_mod.create_parser().parse_args(
            ["restart", "a", "b", "--force", "--timeout", "15"]
        )
        assert run_mod._dispatch(args) == 0
        assert seen == {
            "projects": ["a", "b"],
            "all_sessions": False,
            "force": True,
            "timeout": 15.0,
        }


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
