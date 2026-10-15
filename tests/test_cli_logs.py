"""Tests for gg logs CLI flags (--since/--ts/--follow/--json)."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from gg_core._errors import ValidationError

run_mod = importlib.import_module("gg_core.cli.run")
_logs_json = run_mod._logs_json
_parse_since = run_mod._parse_since
_visible_lines = run_mod._visible_lines
cmd_logs = run_mod.cmd_logs


class TestParseSince:
    """--since duration parsing."""

    def test_valid_units(self) -> None:
        assert _parse_since("30s") == "-30s"
        assert _parse_since("5m") == "-5m"
        assert _parse_since("2h") == "-2h"
        assert _parse_since("1d") == "-1d"
        assert _parse_since(" 10M ") == "-10m"

    @pytest.mark.parametrize("bad", ["", "5", "m", "5x", "-5m", "soon"])
    def test_invalid_rejected(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            _parse_since(bad)


class TestVisibleLines:
    """Raw vs cleaned line pipelines."""

    def test_raw_strips_ansi(self) -> None:
        assert _visible_lines(["\x1b[31mred\x1b[0m"], "generic", raw=True) == ["red"]

    def test_cleaned_generic(self) -> None:
        out = _visible_lines(["hello world"], "generic", raw=False)
        assert out == ["hello world"]

    def test_invalid_agent_falls_back_to_generic(self) -> None:
        out = _visible_lines(["hello"], "not-an-agent", raw=False)
        assert out == ["hello"]


class TestLogsJson:
    """JSON output shape."""

    def test_shape(self) -> None:
        payload = json.loads(_logs_json("proj", ["a", ""], ts=False, raw=False))
        assert payload["project"] == "proj"
        assert payload["raw"] is False
        assert [ln["text"] for ln in payload["lines"]] == ["a", ""]
        assert all(ln["ts"] is None for ln in payload["lines"])
        assert "captured_at" in payload

    def test_ts_populated_when_requested(self) -> None:
        payload = json.loads(_logs_json("proj", ["a"], ts=True, raw=True))
        assert payload["lines"][0]["ts"] is not None


def _mock_pane(captures: list) -> MagicMock:
    pane = MagicMock()
    pane.capture_pane.side_effect = captures
    return pane


class TestCmdLogs:
    """cmd_logs dispatch behaviour with a mocked pane."""

    def test_missing_session_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("gg_core.cli.run.get_pane", return_value=None):
            assert cmd_logs("ghost") == 3
        assert "not found" in capsys.readouterr().err

    def test_missing_session_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("gg_core.cli.run.get_pane", return_value=None):
            assert cmd_logs("ghost", as_json=True) == 3
        payload = json.loads(capsys.readouterr().out)
        assert payload == {"project": "ghost", "error": "session not found"}

    def test_since_passes_time_start_to_capture(self) -> None:
        pane = _mock_pane([["line1"]])
        with patch("gg_core.cli.run.get_pane", return_value=pane):
            assert cmd_logs("proj", since="5m", raw=True) == 0
        _, kwargs = pane.capture_pane.call_args
        assert kwargs["start"] == "-5m"
        assert kwargs["join_wrapped"] is False

    def test_default_uses_line_count(self) -> None:
        pane = _mock_pane([["line1"]])
        with patch("gg_core.cli.run.get_pane", return_value=pane):
            assert cmd_logs("proj", lines=42, raw=True) == 0
        _, kwargs = pane.capture_pane.call_args
        assert kwargs["start"] == -42

    def test_invalid_since_exits_2(self) -> None:
        with pytest.raises(ValidationError):
            cmd_logs("proj", since="bogus")

    def test_ts_prefixes_lines(self, capsys: pytest.CaptureFixture[str]) -> None:
        pane = _mock_pane([["line1"]])
        with patch("gg_core.cli.run.get_pane", return_value=pane):
            assert cmd_logs("proj", raw=True, ts=True) == 0
        out = capsys.readouterr().out
        prefixed = [ln for ln in out.splitlines() if "line1" in ln]
        assert len(prefixed) == 1
        # "YYYY-MM-DD HH:MM:SS line1"
        assert prefixed[0].endswith(" line1") and len(prefixed[0]) == len("line1") + 20

    def test_capture_failure_raises_ggerror(self) -> None:
        pane = _mock_pane([RuntimeError("boom")])
        with (
            patch("gg_core.cli.run.get_pane", return_value=pane),
            pytest.raises(Exception, match="Failed to capture pane"),
        ):
            cmd_logs("proj", raw=True)

    def test_follow_streams_new_batches(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """follow prints only new lines and stops on KeyboardInterrupt."""
        batches = [["a"], ["a", "b"], ["a", "b", "c"]]
        pane = _mock_pane(batches)
        sleeps = iter([None, None, KeyboardInterrupt()])

        def fake_sleep(_seconds: float) -> None:
            nxt = next(sleeps)
            if isinstance(nxt, KeyboardInterrupt):
                raise nxt

        monkeypatch.setattr(run_mod.time, "sleep", fake_sleep)
        with patch("gg_core.cli.run.get_pane", return_value=pane):
            assert cmd_logs("proj", raw=True, follow=True) == 0

        out_lines = [
            ln for ln in capsys.readouterr().out.splitlines() if ln in {"a", "b", "c"}
        ]
        # 'a' printed on first full-capture batch, then only the deltas b and c
        assert out_lines == ["a", "b", "c"]

    def test_follow_json_emits_jsonl(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        batches = [["a"], ["a", "b"]]
        pane = _mock_pane(batches)
        sleeps = iter([None, KeyboardInterrupt()])

        def fake_sleep(_seconds: float) -> None:
            nxt = next(sleeps)
            if isinstance(nxt, KeyboardInterrupt):
                raise nxt

        monkeypatch.setattr(run_mod.time, "sleep", fake_sleep)
        with patch("gg_core.cli.run.get_pane", return_value=pane):
            assert cmd_logs("proj", raw=True, follow=True, as_json=True) == 0

        json_lines = [
            ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")
        ]
        assert len(json_lines) == 2
        for ln in json_lines:
            payload = json.loads(ln)
            assert payload["project"] == "proj"
