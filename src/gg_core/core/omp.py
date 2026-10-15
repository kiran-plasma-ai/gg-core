"""oh-my-pi (omp) session transcript extraction.

Reads structured JSONL session transcripts from omp's session store instead of
parsing the tmux TUI output. Used when an omp session is detected as the
running agent.

Storage layout (see omp ``docs/session.md``)::

    ~/.omp/agent/sessions/<encoded-cwd>/<timestamp>_<sessionId>.jsonl

``<encoded-cwd>`` is derived from the canonicalized cwd: ``-<relative>`` for
directories under home, ``-tmp-<relative>`` for directories under the temp
root, and ``--<encoded-absolute>--`` otherwise, with path separators replaced
by ``-``.

Entry semantics used here (see ``docs/session.md``):

* ``type: "message"`` entries carry an agent message; ``message.role`` is
  camelCase (``user``, ``assistant``, ``toolResult``, ...). Assistant turns
  end with ``stopReason`` either ``toolUse`` (more work coming) or ``stop``.
* ``type: "custom"`` entries include ``tool_execution_start`` while a tool
  call runs, and ``session_exit`` when the session shuts down.
* The physical first line is a fixed-width ``type: "title"`` slot; it is not
  a conversation entry.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
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

#: How long a session transcript may be untouched before it is considered stale.
_SESSION_FRESHNESS_SECONDS = 3600

#: Entry types that carry no state signal and can be skipped when scanning
#: backwards for the most recent decisive entry.
_NON_DECISIVE_TYPES = frozenset(
    {
        "title",
        "session",
        "model_change",
        "thinking_level_change",
        "service_tier_change",
        "model_usage",
        "title_change",
        "compaction",
        "branch_summary",
        "reset_boundary",
        "ttsr_injection",
        "credential_pin",
        "session_init",
        "mode_change",
        "label",
        "custom_message",
    }
)


def _agent_home() -> Path:
    """Return the omp agent state directory."""
    override = os.environ.get("PI_CODING_AGENT_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".omp" / "agent"


def _encode_cwd(cwd: Path) -> str:
    """Encode an absolute cwd into omp's session bucket name.

    Mirrors omp's ``session-paths`` encoding: home-relative dirs become
    ``-<relative>``, temp-root-relative dirs ``-tmp-<relative>``, everything
    else ``--<absolute>--``, with ``/`` replaced by ``-``.
    """

    def _rel(base: Path) -> str | None:
        try:
            rel = cwd.relative_to(base)
        except ValueError:
            return None
        return rel.as_posix().replace("/", "-")

    home_rel = _rel(Path.home())
    if home_rel is not None:
        return f"-{home_rel}"

    tmp_rel = _rel(Path(tempfile.gettempdir()))
    if tmp_rel is not None:
        return f"-tmp-{tmp_rel}"

    absolute = cwd.as_posix().strip("/").replace("/", "-")
    return f"--{absolute}--"


def _candidate_cwds(project: str, working_dir: str | None) -> list[Path]:
    """Return candidate cwds for a project, canonicalized first.

    Args:
        project: Project name, used for the default ``~/<project>`` workspace.
        working_dir: Explicit workspace path, when it differs from ``~/<project>``.

    Returns:
        Deduplicated candidate paths in preference order.
    """
    raw = Path(working_dir) if working_dir else Path.home() / project
    candidates: list[Path] = []
    for path in (raw, Path(raw).resolve()):
        if path not in candidates:
            candidates.append(path)
    return candidates


def _session_bucket(project: str, working_dir: str | None) -> Path | None:
    """Return the newest session bucket directory for a project, if any."""
    sessions_root = _agent_home() / "sessions"
    if not sessions_root.is_dir():
        return None

    candidates = _candidate_cwds(project, working_dir)

    best: Path | None = None
    best_mtime = -1.0
    for cwd in candidates:
        bucket = sessions_root / _encode_cwd(cwd)
        if not bucket.is_dir():
            continue
        try:
            mtime = bucket.stat().st_mtime
        except OSError:
            continue
        if mtime > best_mtime:
            best = bucket
            best_mtime = mtime
    return best


def find_omp_session_path(
    project: str, *, working_dir: str | None = None
) -> Path | None:
    """Find the newest omp session JSONL for a project.

    Args:
        project: Project name (matches tmux session name and, by default,
            the ``~/<project>`` working directory).
        working_dir: Optional absolute path of the real workspace directory.
            omp keys its session bucket by the working directory where the
            agent runs, which may differ from ``~/<project>``.

    Returns:
        Path to the session ``.jsonl`` if found, else None.
    """
    bucket = _session_bucket(project, working_dir)
    if bucket is None:
        return None
    try:
        files = [f for f in bucket.iterdir() if f.is_file() and f.suffix == ".jsonl"]
    except OSError:
        return None
    if not files:
        return None
    try:
        return max(files, key=lambda f: f.stat().st_mtime)
    except OSError:
        return None


def is_omp_session(project: str, *, working_dir: str | None = None) -> bool:
    """Return True if a fresh omp session transcript exists for a project."""
    path = find_omp_session_path(project, working_dir=working_dir)
    if path is None:
        return False
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return False
    return (time.time() - mtime) < _SESSION_FRESHNESS_SECONDS


def read_omp_entries(session_path: Path) -> list[dict]:
    """Read all JSON entries from an omp session JSONL file.

    Skips the physical fixed-width ``title`` slot and any malformed lines.

    Args:
        session_path: Path to the session ``.jsonl``.

    Returns:
        List of parsed entry dicts.
    """
    entries: list[dict] = []
    try:
        with open(session_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug(f"Skipping malformed omp entry: {line[:80]}")
                    continue
                if entry.get("type") == "title" and "id" not in entry:
                    # Fixed-width title slot written ahead of the header.
                    continue
                entries.append(entry)
    except OSError as e:
        logger.warning(f"Failed to read omp session file: {e}")
    return entries


def _assistant_text(message: dict) -> list[str]:
    """Extract non-empty text blocks from an assistant message."""
    return [
        block.get("text", "")
        for block in message.get("content", [])
        if block.get("type") == "text" and block.get("text")
    ]


def extract_omp_text(session_path: Path) -> list[str]:
    """Extract the latest assistant text response from an omp session.

    Looks at entries after the last user message and returns the text blocks
    of the final assistant message that carries prose, mirroring what the
    user sees as the answer for the turn.

    Args:
        session_path: Path to the session ``.jsonl``.

    Returns:
        List of text strings from the latest assistant response.
    """
    entries = read_omp_entries(session_path)
    if not entries:
        return []

    last_user_idx = -1
    for i, entry in enumerate(entries):
        if entry.get("type") != "message":
            continue
        if entry.get("message", {}).get("role") == "user":
            last_user_idx = i

    start = last_user_idx if last_user_idx >= 0 else 0
    latest: list[str] = []
    for entry in entries[start:]:
        if entry.get("type") != "message":
            continue
        message = entry.get("message", {})
        if message.get("role") != "assistant":
            continue
        text = _assistant_text(message)
        if text:
            latest = text
    return latest


def _state_of_entry(entry: dict) -> AgentState | None:
    """Return the state implied by one entry, or None if not decisive."""
    entry_type = entry.get("type")

    if entry_type == "message":
        message = entry.get("message", {})
        role = message.get("role")
        if role in ("user", "toolResult", "bashExecution", "pythonExecution"):
            # Awaiting or mid-turn model output.
            return AgentState.WORKING
        if role == "assistant":
            if message.get("stopReason") == "toolUse":
                return AgentState.WORKING
            return AgentState.IDLE
        return None

    if entry_type == "custom":
        custom_type = entry.get("customType")
        if custom_type == "tool_execution_start":
            return AgentState.WORKING
        if custom_type == "session_exit":
            return AgentState.IDLE
        return None

    if entry_type in _NON_DECISIVE_TYPES:
        return None

    return None


def detect_omp_state(session_path: Path) -> AgentState:
    """Detect agent state from an omp session transcript.

    Scans backwards for the most recent decisive entry: a running tool or a
    pending assistant turn means WORKING, a completed assistant turn or a
    recorded session exit means IDLE.

    Args:
        session_path: Path to the session ``.jsonl``.

    Returns:
        AgentState: WORKING, IDLE, or UNKNOWN when undecidable.
    """
    entries = read_omp_entries(session_path)
    if not entries:
        return AgentState.UNKNOWN

    for entry in reversed(entries):
        state = _state_of_entry(entry)
        if state is not None:
            return state

    return AgentState.UNKNOWN


def _omp_ask_calls(entries: list[dict]) -> list[dict]:
    """Return ``ask`` toolCall blocks in file order."""
    calls = []
    for entry in entries:
        if entry.get("type") != "message":
            continue
        message = entry.get("message", {})
        if message.get("role") != "assistant":
            continue
        for block in message.get("content", []):
            if block.get("type") == "toolCall" and block.get("name") == "ask":
                calls.append(block)
    return calls


def _omp_answered_call_ids(entries: list[dict]) -> set[str]:
    """Collect toolCallIds answered by a toolResult."""
    answered: set[str] = set()
    for entry in entries:
        if entry.get("type") != "message":
            continue
        message = entry.get("message", {})
        if message.get("role") == "toolResult" and message.get("toolCallId"):
            answered.add(str(message["toolCallId"]))
    return answered


def _omp_last_unanswered_ask(entries: list[dict]) -> dict | None:
    """Return the most recent ``ask`` call with no matching toolResult."""
    calls = _omp_ask_calls(entries)
    if not calls:
        return None
    latest = calls[-1]
    call_id = str(latest.get("id") or "")
    if not call_id or call_id in _omp_answered_call_ids(entries):
        return None
    return latest


def _omp_build_pending_question(call: dict) -> PendingQuestion | None:
    """Interpret an ``ask`` call's arguments."""
    arguments = call.get("arguments")
    raw_questions = (
        arguments.get("questions", []) if isinstance(arguments, dict) else []
    )
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
    call_id = str(call.get("id") or "")
    if not questions or not call_id:
        return None
    return PendingQuestion(questions=questions, source="omp-session", call_id=call_id)


def find_omp_pending_question(session_path: Path) -> PendingQuestion | None:
    """Return the latest unanswered ``ask`` in an omp session, if any."""
    entries = read_omp_entries(session_path)
    if not entries:
        return None
    call = _omp_last_unanswered_ask(entries)
    if call is None:
        return None
    return _omp_build_pending_question(call)


def detect_omp_full_state(session_path: Path) -> SessionState:
    """Evidence-based session state from an omp session JSONL.

    Precedence (newest relevant evidence wins): a failed assistant turn, an
    unanswered ``ask`` (its turn is still open), open activity, then idle.
    """
    entries = read_omp_entries(session_path)
    if not entries:
        return SessionState.UNKNOWN

    # 1. Most recent terminal assistant turn: failed only if it carries an
    # errorMessage (a newer successful turn overrides an older failure)
    for entry in reversed(entries):
        if entry.get("type") != "message":
            continue
        message = entry.get("message", {})
        if message.get("role") == "assistant" and message.get("stopReason"):
            if message.get("errorMessage"):
                return SessionState.FAILED
            break

    # 2. Unanswered question: the turn asking it is open, outranking activity
    if _omp_last_unanswered_ask(entries) is not None:
        return SessionState.AWAITING_INPUT

    # 3. Most recent decisive activity
    for entry in reversed(entries):
        state = _state_of_entry(entry)
        if state is None:
            continue
        if state == AgentState.WORKING:
            return SessionState.WORKING
        return SessionState.IDLE

    return SessionState.UNKNOWN
