"""dsh (DeepSeek Harness) session discovery and resume helpers.

``dsh-tui`` persists one session log per *working directory*, but its
``--resume`` / ``-c`` flags are **global**: they mean "the last session
anywhere", not "the last session in this project".  gg therefore resolves
the project's newest persisted TUI session itself and passes its id
explicitly (see :func:`latest_dsh_session_id`).

The resolver deliberately treats two on-disk artifacts as internal, versioned
data and fails soft when they are missing or malformed:

- ``$DSH_HOME/sessions/<project-key>/<session-id>/`` — the persisted session
  directories (``project-key`` mirrors dsh's own ``projectKey`` encoding);
- ``$DSH_HOME/storages/session_projcache/sessions/<session-id>.json`` — the
  plain-JSON projection cache used to recognise TUI sessions and read their
  live state.

Nothing here writes to a session log or talks to a running TUI.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._types import SessionState

logger = logging.getLogger(__name__)

# dsh's projectKey() keeps these ASCII characters and escapes everything else
# as ``~<4-hex-digit code point>``. The readable part is truncated to 251
# characters (leaving room for the ``--`` wrapper and filesystem limits).
_SAFE_CHAR = re.compile(r"[A-Za-z0-9._-]")
_MAX_PROJECT_KEY = 251


@dataclass(frozen=True)
class DshTui:
    """A live dsh-tui process discovered through its injection endpoint."""

    pid: int
    session_id: str
    cwd: str
    socket_path: str
    started_at: int | None = None


@dataclass(frozen=True)
class DshSession:
    """One persisted dsh session directory for a project."""

    session_id: str
    path: Path
    last_prompt_at: int | None = None
    created_at: int | None = None
    cwd: str | None = None
    agent_preset: str | None = None
    has_projection: bool = False
    mtime_ns: int = 0


def dsh_home() -> Path:
    """Return the active DSH home (``$DSH_HOME`` or ``~/.dsh``)."""
    override = os.environ.get("DSH_HOME")
    return Path(override) if override else Path.home() / ".dsh"


def project_dir(project: str) -> Path:
    """Return the working directory gg uses for a project (``~/<project>``)."""
    return Path.home() / project


def _project_dirs(project: str) -> list[Path]:
    """Return the logical and resolved forms of a project directory."""
    logical = project_dir(project)
    directories = [logical]
    try:
        resolved = logical.resolve()
    except OSError:
        resolved = logical
    if resolved != logical:
        directories.append(resolved)
    return directories


def _utf16_units(text: str) -> list[int]:
    """Return UTF-16 code units, matching JavaScript's ``charCodeAt``."""
    encoded = text.encode("utf-16-le")
    return [
        int.from_bytes(encoded[index : index + 2], "little")
        for index in range(0, len(encoded), 2)
    ]


def project_key(cwd: str) -> str:
    """Encode a working directory the way dsh's session store does.

    Mirrors ``projectKey()`` in
    ``@deepseek-ai/dsh-session-persistence-jsonl``: path separators collapse
    to one ``-``, safe ASCII characters survive, everything else becomes
    ``~XXXX`` (uppercase hex), and the result is wrapped in ``--``.

    The encoding walks UTF-16 code units, not Unicode code points, because
    dsh's JavaScript uses ``charCodeAt``. A non-BMP character therefore
    becomes two escapes (a surrogate pair), exactly as dsh writes it.

    Args:
        cwd: Absolute working directory.

    Returns:
        The project directory name under the dsh session root.
    """
    parts: list[str] = []
    separator = False
    for code_unit in _utf16_units(cwd):
        char = chr(code_unit)
        if char in "/\\:":
            if not separator:
                parts.append("-")
            separator = True
        elif char != "~" and _SAFE_CHAR.fullmatch(char):
            parts.append(char)
            separator = False
        else:
            parts.append(f"~{code_unit:04X}")
            separator = False
    readable = "".join(parts).lstrip("-") or "root"
    return f"--{readable[:_MAX_PROJECT_KEY]}--"


def session_root() -> Path:
    """Return the dsh session root (``$DSH_TUI_SESSION_ROOT`` or DSH home)."""
    override = os.environ.get("DSH_TUI_SESSION_ROOT")
    return Path(override) if override else dsh_home() / "sessions"


def projection_path(session_id: str) -> Path:
    """Return the projection-cache path for one session id."""
    return (
        dsh_home()
        / "storages"
        / "session_projcache"
        / "sessions"
        / f"{session_id}.json"
    )


def read_projection(session_id: str) -> dict[str, Any] | None:
    """Read a session's projection cache as a flat row map.

    Each row's ``val`` is returned under its row key; the session identity is
    returned under ``_identity``. Returns None when the cache is absent or
    malformed — callers must treat the cache as optional evidence.
    """
    try:
        data = json.loads(projection_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    record = data.get("record")
    if not isinstance(record, dict):
        return None
    rows = record.get("rows")
    if not isinstance(rows, dict):
        return None
    values: dict[str, Any] = {}
    for key, row in rows.items():
        if isinstance(row, dict) and "val" in row:
            values[key] = row["val"]
    identity = record.get("identity")
    if isinstance(identity, dict):
        values["_identity"] = identity
    return values


def _directory_mtime_ns(path: Path) -> int:
    """Return the newest mtime among a session directory's files."""
    newest = 0
    try:
        for child in path.iterdir():
            if not child.is_file():
                continue
            try:
                newest = max(newest, child.stat().st_mtime_ns)
            except OSError:
                continue
    except OSError:
        return 0
    return newest


def _session_from_dir(path: Path) -> DshSession | None:
    """Build one :class:`DshSession` from a session directory."""
    rows = read_projection(path.name)
    last_prompt_at: int | None = None
    created_at: int | None = None
    session_cwd: str | None = None
    agent_preset: str | None = None
    if rows is not None:
        metadata = rows.get("sessionListMetadata")
        if isinstance(metadata, dict):
            raw = metadata.get("lastPromptAt")
            if isinstance(raw, (int, float)):
                last_prompt_at = int(raw)
        identity = rows.get("_identity")
        if isinstance(identity, dict):
            raw_created = identity.get("createdAt")
            if isinstance(raw_created, (int, float)):
                created_at = int(raw_created)
            raw_cwd = identity.get("cwd")
            session_cwd = raw_cwd if isinstance(raw_cwd, str) else None
        preset = rows.get("agentPreset")
        agent_preset = preset if isinstance(preset, str) else None
    return DshSession(
        session_id=path.name,
        path=path,
        last_prompt_at=last_prompt_at,
        created_at=created_at,
        cwd=session_cwd,
        agent_preset=agent_preset,
        has_projection=rows is not None,
        mtime_ns=_directory_mtime_ns(path),
    )


def candidate_sessions(project: str) -> list[DshSession]:
    """Return persisted TUI sessions for a project, newest first.

    Headless ids (``session-*``) and sessions whose projection cache exists
    but records no agent preset (headless/ACP/SDK) are skipped: resuming them
    would start a TUI on a non-TUI session. A session with no cache at all is
    kept, since the cache is optional evidence.
    """
    root = session_root()
    seen: set[str] = set()
    sessions: list[DshSession] = []
    targets: set[str] = set()
    for cwd in _project_dirs(project):
        targets.add(str(cwd))
        targets.add(os.path.realpath(str(cwd)))
    for cwd in _project_dirs(project):
        directory = root / project_key(str(cwd))
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or entry.name in seen:
                continue
            seen.add(entry.name)
            if entry.name.startswith("session-"):
                continue
            session = _session_from_dir(entry)
            if session is None:
                continue
            if session.has_projection and session.agent_preset is None:
                continue
            # projectKey is lossy (`a-b` and `a/b` collide), so verify the
            # session's recorded cwd when the projection cache provides one.
            if session.cwd and os.path.realpath(session.cwd) not in targets:
                continue
            sessions.append(session)
    sessions.sort(
        key=lambda item: (
            max(item.last_prompt_at or 0, item.created_at or 0),
            item.mtime_ns,
        ),
        reverse=True,
    )
    return sessions


def latest_dsh_session_id(project: str) -> str | None:
    """Return the project's newest persisted TUI session id, if any."""
    sessions = candidate_sessions(project)
    return sessions[0].session_id if sessions else None


def _pid_alive(pid: int) -> bool:
    """Return whether a process id is still alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _servers_path() -> Path:
    """Return dsh-tui's injection discovery file path."""
    return Path.home() / ".dsh-tui" / "inject" / "servers.json"


def live_tui(project: str) -> DshTui | None:
    """Return a live dsh-tui for a project, if one is running outside tmux.

    The injection discovery file lists every running TUI (``pid``,
    ``sessionId``, ``cwd``, ``socketPath``). A dead pid is ignored; the
    newest matching live entry wins.
    """
    try:
        data = json.loads(_servers_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    targets: set[str] = set()
    for directory in _project_dirs(project):
        targets.add(str(directory))
        try:
            targets.add(str(directory.resolve()))
        except OSError:
            continue
    best: DshTui | None = None
    for entry in data:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("pid")
        session_id = entry.get("sessionId")
        cwd = entry.get("cwd")
        socket_path = entry.get("socketPath")
        if (
            not isinstance(pid, int)
            or not isinstance(session_id, str)
            or not isinstance(cwd, str)
            or not isinstance(socket_path, str)
            or not _pid_alive(pid)
        ):
            continue
        try:
            resolved_cwd = str(Path(cwd).resolve())
        except OSError:
            resolved_cwd = cwd
        if cwd not in targets and resolved_cwd not in targets:
            continue
        started_at = entry.get("startedAt")
        candidate = DshTui(
            pid=pid,
            session_id=session_id,
            cwd=cwd,
            socket_path=socket_path,
            started_at=started_at if isinstance(started_at, int) else None,
        )
        if best is None or (candidate.started_at or 0) > (best.started_at or 0):
            best = candidate
    return best


def detect_dsh_full_state(project: str) -> SessionState:
    """Evidence-based state for a dsh-tui session.

    Only ``working``/``idle``/``unknown`` are reported for now. dsh's
    ask/approval panels are not yet drainable by ``gg answer``, so claiming
    ``awaiting_input`` would make ``gg send`` queue messages that never flush.
    A pending form is therefore reported as ``working`` while its turn is open
    (or ``unknown`` when the cache carries no open-turn evidence).
    """
    tui = live_tui(project)
    session_id = tui.session_id if tui is not None else latest_dsh_session_id(project)
    if session_id is None:
        return SessionState.UNKNOWN
    rows = read_projection(session_id)
    if rows is None:
        return SessionState.UNKNOWN

    phase: str | None = None
    activity = rows.get("workingActivity")
    if isinstance(activity, dict):
        tracker = activity.get("tracker")
        if isinstance(tracker, dict):
            raw_phase = tracker.get("phase")
            phase = raw_phase if isinstance(raw_phase, str) else None

    boundary = rows.get("turnBoundary")
    open_turn = (
        isinstance(boundary, dict) and boundary.get("openTurnStartSeq") is not None
    )
    if open_turn or phase in ("thinking", "tool"):
        return SessionState.WORKING
    if phase in ("idle", "done"):
        return SessionState.IDLE
    return SessionState.UNKNOWN
