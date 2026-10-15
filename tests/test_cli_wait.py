"""Tests for gg wait."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

from gg_core import SessionState

run_mod = importlib.import_module("gg_core.cli.run")


def _sleeps(monkeypatch, n: int):
    """Patch time.sleep to raise KeyboardInterrupt-free StopIteration guard."""
    calls = {"n": 0}

    def fake_sleep(_seconds: float) -> None:
        calls["n"] += 1
        if calls["n"] > n:
            raise RuntimeError("sleep guard tripped")

    monkeypatch.setattr(run_mod.time, "sleep", fake_sleep)
    return calls


class TestCmdWait:
    def test_missing_session(self) -> None:
        with patch.object(run_mod, "get_pane", return_value=None):
            assert run_mod.cmd_wait("ghost", mode="idle", timeout=1) == 3

    def test_idle_waits_through_working(
        self, monkeypatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _sleeps(monkeypatch, 10)
        states = iter([SessionState.WORKING, SessionState.WORKING, SessionState.IDLE])
        with (
            patch.object(run_mod, "get_pane", return_value=MagicMock()),
            patch.object(run_mod, "_pane_fingerprint", return_value="h"),
            patch.object(run_mod, "detect_full_state", side_effect=states),
        ):
            assert run_mod.cmd_wait("proj", mode="idle") == 0
        assert "idle" in capsys.readouterr().out

    def test_blocked_matches_awaiting_input_and_failed(self, monkeypatch) -> None:
        _sleeps(monkeypatch, 10)
        states = iter([SessionState.IDLE, SessionState.FAILED])
        with (
            patch.object(run_mod, "get_pane", return_value=MagicMock()),
            patch.object(run_mod, "_pane_fingerprint", return_value="h"),
            patch.object(run_mod, "detect_full_state", side_effect=states),
        ):
            assert run_mod.cmd_wait("proj", mode="blocked") == 0

    def test_timeout_returns_1(self, monkeypatch) -> None:
        monkeypatch.setattr(run_mod.time, "sleep", lambda _s: None)
        monkeypatch.setattr(run_mod.time, "time", lambda: 1000.0)
        state = {"t": 1000.0}

        def advancing_time() -> float:
            state["t"] += 5.0
            return state["t"]

        monkeypatch.setattr(run_mod.time, "time", advancing_time)
        with (
            patch.object(run_mod, "get_pane", return_value=MagicMock()),
            patch.object(run_mod, "_pane_fingerprint", return_value="h"),
            patch.object(
                run_mod, "detect_full_state", return_value=SessionState.WORKING
            ),
        ):
            assert run_mod.cmd_wait("proj", mode="idle", timeout=10) == 1

    def test_changed_fires_on_pane_diff(self, monkeypatch) -> None:
        _sleeps(monkeypatch, 10)
        hashes = iter(["h1", "h1", "h2"])
        with (
            patch.object(run_mod, "get_pane", return_value=MagicMock()),
            patch.object(
                run_mod, "_pane_fingerprint", side_effect=lambda _p: next(hashes)
            ),
        ):
            assert run_mod.cmd_wait("proj", mode="changed") == 0

    def test_changed_never_fires_on_static_pane(self, monkeypatch) -> None:
        _sleeps(monkeypatch, 3)
        with (
            patch.object(run_mod, "get_pane", return_value=MagicMock()),
            patch.object(run_mod, "_pane_fingerprint", return_value="same"),
            pytest.raises(RuntimeError, match="sleep guard"),
        ):
            run_mod.cmd_wait("proj", mode="changed", timeout=None)

    def test_invalid_mode(self) -> None:
        with patch.object(run_mod, "get_pane", return_value=MagicMock()):
            assert run_mod.cmd_wait("proj", mode="bogus") == 2
