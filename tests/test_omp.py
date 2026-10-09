"""Tests for the oh-my-pi (omp) session transcript module."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from gg_core._types import AgentState
from gg_core.core.omp import (
    _encode_cwd,
    detect_omp_state,
    extract_omp_text,
    find_omp_session_path,
    is_omp_session,
    read_omp_entries,
)


def _write_session(path: Path, entries: list[dict]) -> Path:
    lines = [_TITLE_SLOT]
    lines.extend(json.dumps(e) for e in entries)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_TITLE_SLOT = (
    '{"type":"title","v":1,"title":"probe","source":"auto",'
    '"updatedAt":"2026-01-01T00:00:00.000Z","pad":"' + " " * 16 + '"}'
)


def _message(role: str, content: list[dict], stop: str | None = None) -> dict:
    message: dict = {"role": role, "content": content}
    if stop is not None:
        message["stopReason"] = stop
    return {"type": "message", "id": "a1b2c3d4", "message": message}


def _text(value: str) -> dict:
    return {"type": "text", "text": value}


class TestEncodeCwd:
    """Tests for omp's session bucket encoding."""

    def test_home_relative(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert _encode_cwd(tmp_path / "myproj") == "-myproj"
        assert _encode_cwd(tmp_path / "a" / "b") == "-a-b"

    def test_temp_relative(self):
        tmp = Path(tempfile.gettempdir())
        assert _encode_cwd(tmp / "omp-probe") == "-tmp-omp-probe"

    def test_absolute_elsewhere(self):
        assert _encode_cwd(Path("/srv/data/proj")) == "--srv-data-proj--"


class TestFindOmpSessionPath:
    """Tests for find_omp_session_path."""

    def test_no_store_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
        assert find_omp_session_path("myproj") is None

    def test_finds_newest_session(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
        bucket = tmp_path / "agent" / "sessions" / "-myproj"
        bucket.mkdir(parents=True)

        older = _write_session(bucket / "2026-01-01T00-00-00-000Z_a.jsonl", [])
        newer = _write_session(bucket / "2026-02-01T00-00-00-000Z_b.jsonl", [])
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_800_000_000, 1_800_000_000))

        assert find_omp_session_path("myproj") == newer

    def test_ignores_unrelated_project_bucket(self, monkeypatch, tmp_path):
        """A newer ``~/project`` bucket must not be returned for another project."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
        root = tmp_path / "agent" / "sessions"

        (root / "-project").mkdir(parents=True)
        (root / "-myproj").mkdir(parents=True)
        other = _write_session(root / "-project" / "s.jsonl", [])
        mine = _write_session(root / "-myproj" / "s.jsonl", [])
        # The unrelated bucket is newer, which is what used to win.
        os.utime(other, (2_000_000_000, 2_000_000_000))
        os.utime(root / "-project", (2_000_000_000, 2_000_000_000))
        os.utime(mine, (1_000_000_000, 1_000_000_000))
        os.utime(root / "-myproj", (1_000_000_000, 1_000_000_000))

        assert find_omp_session_path("myproj") == mine

    def test_working_dir_override(self, monkeypatch, tmp_path):
        """A session running in a nested dir is found via working_dir."""
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
        bucket = tmp_path / "agent" / "sessions" / "-websites-darkside-11ty"
        bucket.mkdir(parents=True)
        session = _write_session(bucket / "2026-02-01T00-00-00-000Z_b.jsonl", [])

        assert find_omp_session_path("darkside") is None
        assert (
            find_omp_session_path(
                "darkside", working_dir=str(tmp_path / "websites" / "darkside-11ty")
            )
            == session
        )


class TestReadOmpEntries:
    """Tests for read_omp_entries."""

    def test_skips_title_slot_and_malformed(self, tmp_path):
        path = tmp_path / "s.jsonl"
        path.write_text(
            _TITLE_SLOT + "\n"
            '{"type":"session","id":"abc"}\n'
            "not json\n"
            '{"type":"message","id":"x","message":{"role":"user","content":[]}}\n'
        )
        entries = read_omp_entries(path)
        assert [e.get("type") for e in entries] == ["session", "message"]

    def test_empty_file(self, tmp_path):
        path = tmp_path / "s.jsonl"
        path.write_text("")
        assert read_omp_entries(path) == []


class TestExtractOmpText:
    """Tests for extract_omp_text."""

    def test_returns_final_assistant_text(self, tmp_path):
        path = _write_session(
            tmp_path / "s.jsonl",
            [
                _message("user", [_text("list files")]),
                _message("assistant", [_text("Running ls.")], stop="toolUse"),
                _message("toolResult", [_text("total 0")]),
                _message("assistant", [{"type": "thinking", "thinking": "hmm"}, _text("Dir is empty.")], stop="stop"),
            ],
        )
        assert extract_omp_text(path) == ["Dir is empty."]

    def test_ignores_previous_turn(self, tmp_path):
        path = _write_session(
            tmp_path / "s.jsonl",
            [
                _message("user", [_text("first")]),
                _message("assistant", [_text("Old answer.")], stop="stop"),
                _message("user", [_text("second")]),
                _message("assistant", [_text("New answer.")], stop="stop"),
            ],
        )
        assert extract_omp_text(path) == ["New answer."]

    def test_multiple_text_blocks(self, tmp_path):
        path = _write_session(
            tmp_path / "s.jsonl",
            [
                _message("user", [_text("hi")]),
                _message("assistant", [_text("Part one."), _text("Part two.")], stop="stop"),
            ],
        )
        assert extract_omp_text(path) == ["Part one.", "Part two."]

    def test_empty_file(self, tmp_path):
        path = tmp_path / "s.jsonl"
        path.write_text("")
        assert extract_omp_text(path) == []


class TestDetectOmpState:
    """Tests for detect_omp_state."""

    def _state(self, tmp_path, entries: list[dict]) -> AgentState:
        return detect_omp_state(_write_session(tmp_path / "s.jsonl", entries))

    def test_pending_user_turn_is_working(self, tmp_path):
        assert self._state(
            tmp_path, [_message("user", [_text("hi")])]
        ) == AgentState.WORKING

    def test_tool_use_is_working(self, tmp_path):
        assert self._state(
            tmp_path, [_message("assistant", [{"type": "toolCall"}], stop="toolUse")]
        ) == AgentState.WORKING

    def test_running_tool_is_working(self, tmp_path):
        assert self._state(
            tmp_path,
            [
                _message("assistant", [{"type": "toolCall"}], stop="toolUse"),
                {"type": "custom", "id": "c1", "customType": "tool_execution_start"},
            ],
        ) == AgentState.WORKING

    def test_completed_turn_is_idle(self, tmp_path):
        assert self._state(
            tmp_path, [_message("assistant", [_text("Done.")], stop="stop")]
        ) == AgentState.IDLE

    def test_session_exit_is_idle(self, tmp_path):
        assert self._state(
            tmp_path,
            [
                _message("assistant", [_text("Done.")], stop="stop"),
                {"type": "custom", "id": "c2", "customType": "session_exit"},
            ],
        ) == AgentState.IDLE

    def test_non_decisive_entries_are_skipped(self, tmp_path):
        assert self._state(
            tmp_path,
            [
                _message("assistant", [_text("Done.")], stop="stop"),
                {"type": "model_change", "id": "m1", "model": "x"},
                {"type": "custom", "id": "c3", "customType": "system-prompt-digest"},
            ],
        ) == AgentState.IDLE

    def test_empty_file_is_unknown(self, tmp_path):
        path = tmp_path / "s.jsonl"
        path.write_text("")
        assert detect_omp_state(path) == AgentState.UNKNOWN


class TestIsOmpSession:
    """Tests for is_omp_session."""

    def test_no_session_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
        assert is_omp_session("myproj") is False

    def test_fresh_session_returns_true(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
        bucket = tmp_path / "agent" / "sessions" / "-myproj"
        bucket.mkdir(parents=True)
        _write_session(bucket / "2026-02-01T00-00-00-000Z_b.jsonl", [])
        assert is_omp_session("myproj") is True

    def test_stale_session_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
        bucket = tmp_path / "agent" / "sessions" / "-myproj"
        bucket.mkdir(parents=True)
        session = _write_session(bucket / "2026-02-01T00-00-00-000Z_b.jsonl", [])
        os.utime(session, (1_000_000_000, 1_000_000_000))
        assert is_omp_session("myproj") is False


class TestResolveAgent:
    """Tests for recorded-agent resolution."""

    def test_marker_takes_precedence(self, monkeypatch, tmp_path):
        from gg_core.core import session as session_mod

        monkeypatch.setattr(session_mod, "LOG_DIR", tmp_path)
        monkeypatch.setattr(session_mod, "infer_agent", lambda _project: "kimi")

        session_mod.record_agent("proj", "omp")
        assert session_mod.recorded_agent("proj") == "omp"
        assert session_mod.resolve_agent("proj") == "omp"

    def test_falls_back_to_inference(self, monkeypatch, tmp_path):
        from gg_core.core import session as session_mod

        monkeypatch.setattr(session_mod, "LOG_DIR", tmp_path)
        monkeypatch.setattr(session_mod, "infer_agent", lambda _project: "kimi")
        assert session_mod.resolve_agent("proj") == "kimi"

    def test_stop_clears_marker(self, monkeypatch, tmp_path):
        from gg_core.core import session as session_mod

        monkeypatch.setattr(session_mod, "LOG_DIR", tmp_path)
        session_mod.record_agent("proj", "omp")
        session_mod._clear_recorded_agent("proj")
        assert session_mod.recorded_agent("proj") is None
