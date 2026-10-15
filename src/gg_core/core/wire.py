"""Kimi-code wire.jsonl extraction.

Reads structured conversation transcripts from kimi-code's wire.jsonl files
instead of parsing tmux TUI output. Used when kimi-code is detected as the
running agent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from .._types import (
    AgentQuestion,
    AgentState,
    PendingQuestion,
    QuestionOption,
    SessionState,
)

logger = logging.getLogger(__name__)


def _get_working_dir_hash(working_dir: str) -> str:
    """Compute kimi-code working directory hash (sha256[:12])."""
    return hashlib.sha256(working_dir.encode()).hexdigest()[:12]


def find_kimi_wire_path(project: str, *, working_dir: str | None = None) -> Path | None:
    """Find the active kimi-code wire.jsonl for a project.

    Args:
        project: Project name (matches tmux session name and working dir name)
        working_dir: Optional absolute path of the real workspace directory.
            kimi-code keys its session dir by the *working directory* where
            the agent runs, which may differ from ``~/<project>`` (e.g. a
            tmux session named ``darkside`` running in
            ``~/websites/darksideofmymind-11ty``). When given, the lookup
            uses this path instead of ``~/<project>``.

    Returns:
        Path to wire.jsonl if found and readable, None otherwise
    """
    home = str(Path.home())
    project_dir = Path(working_dir) if working_dir else Path(home) / project
    wd_hash = _get_working_dir_hash(str(project_dir))

    base = Path(home) / ".kimi-code" / "sessions"
    if not base.exists():
        return None

    # Find the session directory matching this working dir hash
    try:
        candidates = [
            d for d in base.iterdir() if d.is_dir() and d.name.endswith(f"_{wd_hash}")
        ]
    except OSError:
        return None
    if not candidates:
        return None

    sessions_dir = candidates[0]
    session_dirs = [d for d in sessions_dir.iterdir() if d.is_dir()]
    if not session_dirs:
        return None

    # Pick the most recently modified session subdirectory
    latest = max(session_dirs, key=lambda d: d.stat().st_mtime)
    wire = latest / "agents" / "main" / "wire.jsonl"
    if wire.exists():
        return wire
    return None


def is_kimi_code_session(project: str) -> bool:
    """Check if a tmux session is running kimi-code (has active wire.jsonl).

    Args:
        project: Project name

    Returns:
        True if wire.jsonl exists and was modified in the last hour
    """
    wire_path = find_kimi_wire_path(project)
    if wire_path is None:
        return False
    try:
        mtime = wire_path.stat().st_mtime
        return time.time() - mtime < 3600
    except OSError:
        return False


def read_wire_events(wire_path: Path) -> list[dict]:
    """Read all JSON events from a wire.jsonl file.

    Skips malformed lines gracefully.

    Args:
        wire_path: Path to wire.jsonl

    Returns:
        List of parsed JSON event dicts
    """
    events: list[dict] = []
    try:
        with open(wire_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.debug(f"Skipping malformed wire line: {line[:80]}")
                    continue
    except OSError as e:
        logger.warning(f"Failed to read wire.jsonl: {e}")
    return events


def extract_wire_text(wire_path: Path) -> list[str]:
    """Extract latest assistant text responses from wire.jsonl.

    Returns text parts from the most recent assistant turn only
    (everything after the last user message).

    Args:
        wire_path: Path to wire.jsonl

    Returns:
        List of text strings from the latest assistant response
    """
    events = read_wire_events(wire_path)
    if not events:
        return []

    # Find the index of the last user message.  Recent kimi-code sessions may
    # use turn.prompt instead of (or in addition to) context.append_message.
    last_user_idx = -1
    for i, event in enumerate(events):
        event_type = event.get("type")
        if event_type == "context.append_message":
            if event.get("message", {}).get("role") == "user":
                last_user_idx = i
        elif event_type == "turn.prompt":
            # turn.prompt carries the user's raw input; treat it as the start
            # of a new turn, just like a user message.
            last_user_idx = i

    start_idx = last_user_idx if last_user_idx >= 0 else 0
    live_parts: list[str] = []
    finalized: list[str] = []

    for event in events[start_idx:]:
        # Live generation events: content.part
        if event.get("type") == "context.append_loop_event":
            evt = event.get("event", {})
            if evt.get("type") == "content.part":
                part = evt.get("part", {})
                if part.get("type") == "text":
                    text = part.get("text", "")
                    if text:
                        live_parts.append(text)

        # Finalized assistant messages
        elif event.get("type") == "context.append_message":
            msg = event.get("message", {})
            if msg.get("role") == "assistant":
                for item in msg.get("content", []):
                    if item.get("type") == "text":
                        text = item.get("text", "")
                        if text:
                            finalized.append(text)

    # Prefer finalized messages over live chunks to avoid duplication.
    # kimi-code typically writes both: live chunks during generation,
    # then a finalized context.append_message after step.end.
    return finalized if finalized else live_parts


def detect_wire_state(wire_path: Path) -> AgentState:
    """Detect agent state from wire.jsonl events.

    Scans for open steps (step.begin without matching step.end).
    Only considers the most recent step to avoid stale open steps
    from crashed/interrupted sessions.

    Args:
        wire_path: Path to wire.jsonl

    Returns:
        AgentState: WORKING if the most recent step is open, IDLE otherwise
    """
    events = read_wire_events(wire_path)
    if not events:
        return AgentState.UNKNOWN

    # Find step events in reverse order (most recent first)
    step_events = []
    for event in reversed(events):
        if event.get("type") != "context.append_loop_event":
            continue
        evt = event.get("event", {})
        evt_type = evt.get("type")
        if evt_type in ("step.begin", "step.end"):
            step_events.append((evt_type, evt.get("uuid")))

    if not step_events:
        return AgentState.IDLE

    # Track seen uuids to find the most recent step
    seen: set[str] = set()
    for evt_type, uuid in step_events:
        if uuid in seen:
            continue
        seen.add(uuid)
        if evt_type == "step.begin":
            return AgentState.WORKING
        elif evt_type == "step.end":
            return AgentState.IDLE

    return AgentState.IDLE


def _wire_answered_call_ids(events: list[dict]) -> set[str]:
    """Collect ids of answered tool calls (toolCallId and parentUuid)."""
    answered: set[str] = set()
    for event in events:
        if event.get("type") != "context.append_loop_event":
            continue
        evt = event.get("event", {})
        if evt.get("type") == "tool.result":
            for cid in (evt.get("toolCallId"), evt.get("parentUuid")):
                if cid:
                    answered.add(str(cid))
    return answered


def _wire_ask_calls(events: list[dict]) -> list[dict]:
    """Return AskUserQuestion tool.call events in file order."""
    calls = []
    for event in events:
        if event.get("type") != "context.append_loop_event":
            continue
        evt = event.get("event", {})
        if evt.get("type") == "tool.call" and evt.get("name") == "AskUserQuestion":
            calls.append(evt)
    return calls


def _wire_last_unanswered_ask(events: list[dict]) -> dict | None:
    """Return the most recent AskUserQuestion call with no matching result."""
    calls = _wire_ask_calls(events)
    if not calls:
        return None
    latest = calls[-1]
    call_id = str(latest.get("uuid") or latest.get("toolCallId") or "")
    if not call_id or call_id in _wire_answered_call_ids(events):
        return None
    return latest


def _build_pending_question(call: dict, source: str) -> PendingQuestion | None:
    """Interpret an AskUserQuestion/ask call's arguments."""
    args = call.get("args") or call.get("arguments") or {}
    raw_questions = args.get("questions", []) if isinstance(args, dict) else []
    questions: list[AgentQuestion] = []
    for q in raw_questions:
        text = str(q.get("question") or q.get("header") or "").strip()
        options = [
            QuestionOption(
                label=str(o.get("label") or "").strip(),
                description=str(o.get("description") or "").strip(),
            )
            for o in q.get("options", [])
            if isinstance(o, dict) and str(o.get("label") or "").strip()
        ]
        questions.append(AgentQuestion(text=text, options=options))
    call_id = str(call.get("uuid") or call.get("id") or call.get("toolCallId") or "")
    if not questions or not call_id:
        return None
    return PendingQuestion(questions=questions, source=source, call_id=call_id)


def find_wire_pending_question(wire_path: Path) -> PendingQuestion | None:
    """Return the latest unanswered AskUserQuestion in a wire.jsonl, if any."""
    events = read_wire_events(wire_path)
    if not events:
        return None
    call = _wire_last_unanswered_ask(events)
    if call is None:
        return None
    return _build_pending_question(call, "wire")


def detect_wire_full_state(wire_path: Path) -> SessionState:
    """Evidence-based session state from a kimi-code wire.jsonl.

    Precedence (newest relevant evidence wins): a failed turn, an unanswered
    question (the step asking it is still open), open step activity, then
    idle. A real user prompt newer than the last step boundary counts as
    working.
    """
    events = read_wire_events(wire_path)
    if not events:
        return SessionState.UNKNOWN

    # 1. Most recent turn: failed only if it ended failed (a newer
    # successful turn overrides an older failure)
    for event in reversed(events):
        if event.get("type") == "turn.ended":
            if event.get("reason") == "failed":
                return SessionState.FAILED
            break

    # 2. Unanswered question: its step is open, so this outranks step scan
    if _wire_last_unanswered_ask(events) is not None:
        return SessionState.AWAITING_INPUT

    # 3. Most recent step boundary
    last_step_idx = -1
    last_step_type = ""
    for idx, event in enumerate(events):
        if event.get("type") != "context.append_loop_event":
            continue
        evt = event.get("event", {})
        if evt.get("type") in ("step.begin", "step.end"):
            last_step_idx, last_step_type = idx, evt["type"]

    if last_step_idx >= 0:
        if last_step_type == "step.begin":
            return SessionState.WORKING

        # Most recent step is closed: a real user prompt after it means a
        # new turn has started even though no step.begin was written yet.
        for event in events[last_step_idx + 1 :]:
            if event.get("type") == "turn.prompt":
                items = event.get("input") or []
                first = items[0].get("text") if items else None
                if first is not None and not str(first).lstrip().startswith("<system"):
                    return SessionState.WORKING
            elif (
                event.get("type") == "context.append_message"
                and event.get("message", {}).get("role") == "user"
            ):
                content = event.get("message", {}).get("content") or []
                first = content[0].get("text") if content else None
                if first is not None and not str(first).lstrip().startswith("<system"):
                    return SessionState.WORKING
        return SessionState.IDLE

    return SessionState.IDLE
