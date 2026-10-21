"""Tests for dsh session discovery, resume, and state detection."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gg_core._types import SessionState
from gg_core.core import dsh


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Give the test an isolated HOME and DSH_HOME."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("DSH_HOME", str(home / ".dsh"))
    monkeypatch.delenv("DSH_TUI_SESSION_ROOT", raising=False)
    return home


def _write_projection(
    home: Path,
    session_id: str,
    *,
    cwd: str,
    preset: str | None = "standard",
    last_prompt: int | None = None,
    created_at: int | None = None,
    phase: str | None = None,
    open_turn: bool = False,
    open_question: bool = False,
) -> None:
    cache = (
        home
        / ".dsh"
        / "storages"
        / "session_projcache"
        / "sessions"
        / f"{session_id}.json"
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    rows: dict[str, dict[str, object]] = {
        "sessionListMetadata": {
            "ver": 1,
            "seq": 1,
            "val": {"lastPromptAt": last_prompt or 0},
        },
        "agentPreset": {"ver": 1, "seq": 1, "val": preset},
        "turnBoundary": {
            "ver": 2,
            "seq": 1,
            "val": {"openTurnStartSeq": 4 if open_turn else None},
        },
    }
    if phase is not None:
        rows["workingActivity"] = {
            "ver": 6,
            "seq": 1,
            "val": {"tracker": {"phase": phase}},
        }
    if open_question:
        rows["userQuestions"] = {
            "ver": 2,
            "seq": 1,
            "val": {
                "questions": {
                    "active": [
                        {
                            "callId": "call-1",
                            "state": "open",
                            "questions": [
                                {
                                    "id": "q1",
                                    "question": "Proceed?",
                                    "options": [{"label": "Yes"}, {"label": "No"}],
                                }
                            ],
                        }
                    ],
                    "settled": [],
                }
            },
        }
    cache.write_text(
        json.dumps(
            {
                "version": 7,
                "record": {
                    "identity": {"cwd": cwd, "createdAt": created_at or 0},
                    "rows": rows,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_session_dir(
    home: Path, cwd: str, session_id: str, *, mtime: int | None = None
) -> Path:
    session_dir = home / ".dsh" / "sessions" / dsh.project_key(cwd) / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    log = session_dir / "session.v4.jsonl.zstd"
    log.write_bytes(b"")
    if mtime is not None:
        os.utime(log, (mtime, mtime))
    return session_dir


class TestProjectKey:
    def test_matches_live_directories(self):
        """The encoder matches dsh's own session directories on this host."""
        assert dsh.project_key("/home/user/projects") == "--home-user-projects--"
        assert dsh.project_key("/home/user/projects/dsh") == "--home-user-projects-dsh--"

    def test_escapes_unsafe_characters(self):
        assert dsh.project_key("/tmp/a b") == "--tmp-a~0020b--"
        assert dsh.project_key("/tmp/a~b") == "--tmp-a~007Eb--"

    def test_non_bmp_uses_utf16_code_units(self):
        """dsh's JS walk sees a surrogate pair, not one code point."""
        assert dsh.project_key("/tmp/😀") == "--tmp-~D83D~DE00--"


class TestLatestSession:
    def test_picks_newest_last_prompt(self, fake_home):
        cwd = str(fake_home / "proj")
        _write_session_dir(fake_home, cwd, "older")
        _write_session_dir(fake_home, cwd, "newer")
        _write_projection(fake_home, "older", cwd=cwd, last_prompt=100)
        _write_projection(fake_home, "newer", cwd=cwd, last_prompt=200)

        assert dsh.latest_dsh_session_id("proj") == "newer"

    def test_prefers_fresh_session_created_at(self, fake_home):
        """A just-created /new session outranks an older prompted one."""
        cwd = str(fake_home / "proj")
        _write_session_dir(fake_home, cwd, "older")
        _write_session_dir(fake_home, cwd, "fresh")
        _write_projection(fake_home, "older", cwd=cwd, last_prompt=500)
        _write_projection(fake_home, "fresh", cwd=cwd, created_at=1000)

        assert dsh.latest_dsh_session_id("proj") == "fresh"

    def test_ignores_colliding_project_key(self, fake_home):
        """A lossy projectKey collision is filtered by the recorded cwd."""
        cwd = str(fake_home / "proj")
        _write_session_dir(fake_home, cwd, "impostor")
        _write_projection(
            fake_home,
            "impostor",
            cwd=str(fake_home / "proj-other"),
            last_prompt=100,
        )

        assert dsh.latest_dsh_session_id("proj") is None

    def test_ignores_headless_session_ids(self, fake_home):
        cwd = str(fake_home / "proj")
        _write_session_dir(fake_home, cwd, "tui-session")
        _write_session_dir(fake_home, cwd, "session-headless")
        _write_projection(fake_home, "tui-session", cwd=cwd, last_prompt=100)
        _write_projection(fake_home, "session-headless", cwd=cwd, last_prompt=999)

        assert dsh.latest_dsh_session_id("proj") == "tui-session"

    def test_ignores_sessions_without_preset(self, fake_home):
        cwd = str(fake_home / "proj")
        _write_session_dir(fake_home, cwd, "tui-session")
        _write_session_dir(fake_home, cwd, "sdk-session")
        _write_projection(fake_home, "tui-session", cwd=cwd, last_prompt=100)
        _write_projection(
            fake_home, "sdk-session", cwd=cwd, preset=None, last_prompt=999
        )

        assert dsh.latest_dsh_session_id("proj") == "tui-session"

    def test_no_sessions(self, fake_home):
        assert dsh.latest_dsh_session_id("proj") is None


class TestLiveTui:
    def _write_servers(self, home: Path, entries: list[dict[str, object]]) -> None:
        path = home / ".dsh-tui" / "inject" / "servers.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entries), encoding="utf-8")

    def test_finds_live_entry_by_cwd(self, fake_home):
        cwd = str(fake_home / "proj")
        self._write_servers(
            fake_home,
            [
                {
                    "pid": os.getpid(),
                    "sessionId": "sid-1",
                    "cwd": cwd,
                    "socketPath": "/tmp/sid-1.sock",
                    "startedAt": 10,
                }
            ],
        )
        found = dsh.live_tui("proj")
        assert found is not None
        assert found.session_id == "sid-1"

    def test_ignores_dead_pid(self, fake_home):
        cwd = str(fake_home / "proj")
        self._write_servers(
            fake_home,
            [
                {
                    "pid": 2**31 - 1,
                    "sessionId": "sid-1",
                    "cwd": cwd,
                    "socketPath": "/tmp/sid-1.sock",
                }
            ],
        )
        assert dsh.live_tui("proj") is None

    def test_ignores_other_cwd(self, fake_home):
        self._write_servers(
            fake_home,
            [
                {
                    "pid": os.getpid(),
                    "sessionId": "sid-1",
                    "cwd": str(fake_home / "other"),
                    "socketPath": "/tmp/sid-1.sock",
                }
            ],
        )
        assert dsh.live_tui("proj") is None


class TestDetectState:
    def _project(self, fake_home, **kwargs) -> None:
        cwd = str(fake_home / "proj")
        _write_session_dir(fake_home, cwd, "sid")
        _write_projection(fake_home, "sid", cwd=cwd, **kwargs)

    def test_working_from_open_turn(self, fake_home):
        self._project(fake_home, phase="tool", open_turn=True)
        assert dsh.detect_dsh_full_state("proj") == SessionState.WORKING

    def test_idle_from_phase(self, fake_home):
        self._project(fake_home, phase="idle", open_turn=False)
        assert dsh.detect_dsh_full_state("proj") == SessionState.IDLE

    def test_question_form_is_not_awaiting_yet(self, fake_home):
        """gg answer cannot drive dsh forms, so never report awaiting_input."""
        self._project(
            fake_home, phase="waiting", open_question=True, open_turn=True
        )
        assert dsh.detect_dsh_full_state("proj") == SessionState.WORKING

    def test_waiting_retry_is_working(self, fake_home):
        """Waiting for a retry/first token is working, not awaiting a human."""
        self._project(fake_home, phase="waiting", open_turn=True)
        assert dsh.detect_dsh_full_state("proj") == SessionState.WORKING

    def test_waiting_without_turn_is_unknown(self, fake_home):
        self._project(fake_home, phase="waiting", open_turn=False)
        assert dsh.detect_dsh_full_state("proj") == SessionState.UNKNOWN

    def test_malformed_projection_is_ignored(self, fake_home):
        """A non-object cache must not crash session discovery."""
        cwd = str(fake_home / "proj")
        _write_session_dir(fake_home, cwd, "sid")
        cache = dsh.projection_path("sid")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text("[1, 2, 3]", encoding="utf-8")

        assert dsh.read_projection("sid") is None
        assert dsh.latest_dsh_session_id("proj") == "sid"
        assert dsh.detect_dsh_full_state("proj") == SessionState.UNKNOWN

    def test_unknown_without_cache(self, fake_home):
        cwd = str(fake_home / "proj")
        _write_session_dir(fake_home, cwd, "sid")
        assert dsh.detect_dsh_full_state("proj") == SessionState.UNKNOWN
