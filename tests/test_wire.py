"""Tests for wire.jsonl extraction module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from gg_core._types import AgentState
from gg_core.core.wire import (
    detect_wire_state,
    extract_wire_text,
    find_kimi_wire_path,
    is_kimi_code_session,
    read_wire_events,
)


class TestFindKimiWirePath:
    """Tests for find_kimi_wire_path."""

    def test_no_kimi_code_dir(self, monkeypatch):
        """Return None when .kimi-code/sessions doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("HOME", tmpdir)
            assert find_kimi_wire_path("testproj") is None

    def test_no_matching_hash(self, monkeypatch):
        """Return None when no session dir matches the working dir hash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions = Path(tmpdir) / ".kimi-code" / "sessions"
            sessions.mkdir(parents=True)
            # Create a dummy dir with wrong hash
            (sessions / "wd_test_000000000000").mkdir()
            monkeypatch.setenv("HOME", tmpdir)
            assert find_kimi_wire_path("testproj") is None

    def test_finds_wire_jsonl(self, monkeypatch):
        """Return wire.jsonl path when session exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            sessions = home / ".kimi-code" / "sessions"
            sessions.mkdir(parents=True)

            # Compute expected hash for <home>/myproject
            import hashlib

            wd_hash = hashlib.sha256(str(home / "myproject").encode()).hexdigest()[:12]
            sess_dir = sessions / f"wd_myproject_{wd_hash}"
            sess_dir.mkdir()

            # Create session subdir with wire.jsonl
            (sess_dir / "session_abc").mkdir()
            wire = sess_dir / "session_abc" / "agents" / "main" / "wire.jsonl"
            wire.parent.mkdir(parents=True)
            wire.write_text('{"type":"metadata"}\n')

            monkeypatch.setenv("HOME", tmpdir)
            result = find_kimi_wire_path("myproject")
            assert result == wire

    def test_finds_wire_by_working_dir_override(self, monkeypatch):
        """Return wire.jsonl when working_dir differs from ~/project.

        Regression: a tmux session may be named ``darkside`` while kimi-code
        runs in ``~/websites/darksideofmymind-11ty``. The session dir is keyed
        by the real working directory, so the lookup must accept it.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            sessions = home / ".kimi-code" / "sessions"
            sessions.mkdir(parents=True)

            import hashlib

            real_cwd = home / "websites" / "darksideofmymind-11ty"
            wd_hash = hashlib.sha256(str(real_cwd).encode()).hexdigest()[:12]
            sess_dir = sessions / f"wd_darksideofmymind-11ty_{wd_hash}"
            sess_dir.mkdir(parents=True)

            (sess_dir / "session_abc").mkdir()
            wire = sess_dir / "session_abc" / "agents" / "main" / "wire.jsonl"
            wire.parent.mkdir(parents=True)
            wire.write_text('{"type":"metadata"}\n')

            monkeypatch.setenv("HOME", tmpdir)
            # Project-name lookup alone misses (session lives under websites/).
            assert find_kimi_wire_path("darkside") is None
            # Working-dir override finds it.
            result = find_kimi_wire_path("darkside", working_dir=str(real_cwd))
            assert result == wire


class TestReadWireEvents:
    """Tests for read_wire_events."""

    def test_reads_valid_json(self, tmp_path):
        """Read valid JSON lines from wire.jsonl."""
        wire = tmp_path / "wire.jsonl"
        wire.write_text(
            '{"type":"metadata"}\n'
            '{"type":"context.append_message","message":{"role":"user"}}\n'
        )
        events = read_wire_events(wire)
        assert len(events) == 2
        assert events[0]["type"] == "metadata"
        assert events[1]["type"] == "context.append_message"

    def test_skips_malformed_lines(self, tmp_path):
        """Skip malformed lines without crashing."""
        wire = tmp_path / "wire.jsonl"
        wire.write_text('{"type":"metadata"}\nthis is not json\n{"type":"ok"}\n')
        events = read_wire_events(wire)
        assert len(events) == 2
        assert events[0]["type"] == "metadata"
        assert events[1]["type"] == "ok"

    def test_empty_file(self, tmp_path):
        """Return empty list for empty file."""
        wire = tmp_path / "wire.jsonl"
        wire.write_text("")
        events = read_wire_events(wire)
        assert events == []


class TestExtractWireText:
    """Tests for extract_wire_text."""

    def test_extracts_latest_assistant_text(self, tmp_path):
        """Extract text from the latest assistant response."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "hello"}],
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "a"},
            },
            {
                "type": "context.append_loop_event",
                "event": {
                    "type": "content.part",
                    "part": {"type": "text", "text": "Hi there!"},
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.end", "uuid": "a"},
            },
            {
                "type": "context.append_message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "second"}],
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "b"},
            },
            {
                "type": "context.append_loop_event",
                "event": {
                    "type": "content.part",
                    "part": {"type": "text", "text": "Second response."},
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.end", "uuid": "b"},
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = extract_wire_text(wire)
        assert result == ["Second response."]

    def test_extracts_multiple_content_parts(self, tmp_path):
        """Extract multiple content.part texts from a single turn."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "hello"}],
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {
                    "type": "content.part",
                    "part": {"type": "text", "text": "Part one."},
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {
                    "type": "content.part",
                    "part": {"type": "text", "text": "Part two."},
                },
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = extract_wire_text(wire)
        assert result == ["Part one.", "Part two."]

    def test_ignores_think_blocks(self, tmp_path):
        """Ignore think content, only extract text."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "hello"}],
                },
            },
            {
                "type": "context.append_message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "think", "think": "thinking..."},
                        {"type": "text", "text": "Final answer."},
                    ],
                },
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = extract_wire_text(wire)
        assert result == ["Final answer."]

    def test_no_user_message_returns_all(self, tmp_path):
        """If no user message, return all assistant text."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "First."},
                    ],
                },
            },
            {
                "type": "context.append_message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Second."},
                    ],
                },
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = extract_wire_text(wire)
        assert result == ["First.", "Second."]

    def test_empty_file(self, tmp_path):
        """Return empty list for empty file."""
        wire = tmp_path / "wire.jsonl"
        wire.write_text("")
        assert extract_wire_text(wire) == []

    def test_prefers_finalized_over_live_parts(self, tmp_path):
        """When both live parts and finalized message exist, prefer finalized."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "hello"}],
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "a"},
            },
            {
                "type": "context.append_loop_event",
                "event": {
                    "type": "content.part",
                    "part": {"type": "text", "text": "Live chunk one."},
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {
                    "type": "content.part",
                    "part": {"type": "text", "text": "Live chunk two."},
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.end", "uuid": "a"},
            },
            {
                "type": "context.append_message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "Finalized answer."},
                    ],
                },
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = extract_wire_text(wire)
        assert result == ["Finalized answer."]

    def test_turn_prompt_as_user_boundary(self, tmp_path):
        """turn.prompt should be treated as a user message boundary."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_message",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "old question"}],
                },
            },
            {
                "type": "context.append_message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Old answer."}],
                },
            },
            {
                "type": "turn.prompt",
                "input": [{"type": "text", "text": "new question"}],
            },
            {
                "type": "context.append_loop_event",
                "event": {
                    "type": "content.part",
                    "part": {"type": "text", "text": "New answer."},
                },
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")

        result = extract_wire_text(wire)
        assert result == ["New answer."]


class TestDetectWireState:
    """Tests for detect_wire_state."""

    def test_open_step_working(self, tmp_path):
        """WORKING when step.begin has no matching step.end."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "abc"},
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        assert detect_wire_state(wire) == AgentState.WORKING

    def test_closed_step_idle(self, tmp_path):
        """IDLE when step.begin has matching step.end."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "abc"},
            },
            {
                "type": "context.append_loop_event",
                "event": {
                    "type": "content.part",
                    "part": {"type": "text", "text": "hi"},
                },
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.end", "uuid": "abc"},
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        assert detect_wire_state(wire) == AgentState.IDLE

    def test_multiple_steps(self, tmp_path):
        """Most recent step determines state, ignoring stale open steps."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "a"},
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.end", "uuid": "a"},
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "b"},
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "c"},
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.end", "uuid": "c"},
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        # Most recent step (c) is closed, so IDLE despite stale open step (b)
        assert detect_wire_state(wire) == AgentState.IDLE

    def test_stale_open_step_ignored(self, tmp_path):
        """Stale open steps from crashed sessions are ignored."""
        wire = tmp_path / "wire.jsonl"
        events = [
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "stale"},
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.begin", "uuid": "current"},
            },
            {
                "type": "context.append_loop_event",
                "event": {"type": "step.end", "uuid": "current"},
            },
        ]
        wire.write_text("\n".join(json.dumps(e) for e in events) + "\n")
        assert detect_wire_state(wire) == AgentState.IDLE

    def test_empty_file(self, tmp_path):
        """UNKNOWN for empty file."""
        wire = tmp_path / "wire.jsonl"
        wire.write_text("")
        assert detect_wire_state(wire) == AgentState.UNKNOWN


class TestIsKimiCodeSession:
    """Tests for is_kimi_code_session."""

    def test_no_wire_returns_false(self, monkeypatch):
        """Return False when no wire.jsonl exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setenv("HOME", tmpdir)
            assert is_kimi_code_session("testproj") is False

    def test_stale_wire_returns_false(self, monkeypatch):
        """Return False when wire.jsonl is older than 1 hour."""
        import time

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            sessions = home / ".kimi-code" / "sessions"
            sessions.mkdir(parents=True)

            import hashlib

            wd_hash = hashlib.sha256(str(home / "myproject").encode()).hexdigest()[:12]
            sess_dir = sessions / f"wd_myproject_{wd_hash}"
            sess_dir.mkdir()
            (sess_dir / "sess").mkdir()
            wire = sess_dir / "sess" / "agents" / "main" / "wire.jsonl"
            wire.parent.mkdir(parents=True)
            wire.write_text('{"type":"metadata"}\n')

            # Set mtime to 2 hours ago
            old_time = time.time() - 7200
            import os

            os.utime(wire, (old_time, old_time))

            monkeypatch.setenv("HOME", tmpdir)
            assert is_kimi_code_session("myproject") is False

    def test_recent_wire_returns_true(self, monkeypatch):
        """Return True when wire.jsonl was modified recently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            sessions = home / ".kimi-code" / "sessions"
            sessions.mkdir(parents=True)

            import hashlib

            wd_hash = hashlib.sha256(str(home / "myproject").encode()).hexdigest()[:12]
            sess_dir = sessions / f"wd_myproject_{wd_hash}"
            sess_dir.mkdir()
            (sess_dir / "sess").mkdir()
            wire = sess_dir / "sess" / "agents" / "main" / "wire.jsonl"
            wire.parent.mkdir(parents=True)
            wire.write_text('{"type":"metadata"}\n')

            monkeypatch.setenv("HOME", tmpdir)
            assert is_kimi_code_session("myproject") is True
