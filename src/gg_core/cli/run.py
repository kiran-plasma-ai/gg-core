"""CLI main entry point."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .._config import (
    ANSI_ESCAPE,
    DATA_DIR,
    DEFAULT_AGENT,
    LOGS_DEFAULT_LINES,
    find_omp_binary,
)
from .._errors import (
    GGError,
    MessageTooLong,
    SessionError,
    SessionNotFound,
    ValidationError,
)
from .._types import AgentQuestion, PendingQuestion, SessionState
from .._version import version_string
from ..cleaning import LineType, TmuxCleaner
from ..core.session import (
    list_sessions,
    send_command,
    start_session,
    stop_session,
)
from ..core.status import detect_full_state, get_pending_question
from ..core.tmux import get_pane
from ..core.validation import validate_agent, validate_project
from .parser import create_parser


def run() -> int:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()

    try:
        return _dispatch(args)
    except ValidationError as e:
        print(f"Validation error: {e}", file=sys.stderr)
        return 2
    except SessionNotFound as e:
        print(f"Session not found: {e}", file=sys.stderr)
        return 3
    except SessionError as e:
        print(f"Session error: {e}", file=sys.stderr)
        return 4
    except GGError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    """Dispatch to command handler."""
    command = args.command

    dispatch_table: dict[str, Callable[[], int]] = {
        "start": lambda: cmd_start(
            args.project, args.agent, model=args.model, yolo=args.yolo, auto=args.auto
        ),
        "stop": lambda: cmd_stop(args.project),
        "ps": cmd_ps,
        "send": lambda: cmd_send(
            args.project, args.message, reply=args.reply, no_queue=args.no_queue
        ),
        "answer": lambda: cmd_answer(args.project, list(args.answers)),
        "logs": lambda: cmd_logs(
            args.project,
            args.lines,
            raw=args.raw,
            agent=args.agent,
            ts=args.ts,
            since=args.since,
            follow=args.follow,
            as_json=args.json,
        ),
        "attach": lambda: cmd_attach(args.project),
        "connect": lambda: cmd_connect(
            args.project, args.agent, model=args.model, yolo=args.yolo, auto=args.auto
        ),
        "doctor": lambda: cmd_doctor(fix=args.fix),
    }

    handler = dispatch_table.get(command)
    if handler is None:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1
    return handler()


def cmd_start(
    project: str,
    agent: str,
    model: str | None = None,
    yolo: bool = False,
    auto: bool = False,
) -> int:
    """Start a new session."""
    model_str = f" ({model})" if model else ""
    mode_str = ""
    if auto:
        mode_str = " [auto]"
    elif yolo:
        mode_str = " [yolo]"
    print(f"Starting session '{project}' with {agent}{model_str}{mode_str}...")
    start_session(project, agent, model=model, yolo=yolo, auto=auto)
    print(f"✓ Started session '{project}'")
    return 0


def cmd_stop(project: str) -> int:
    """Stop a session."""
    print(f"Stopping session '{project}'...")
    stop_session(project)
    print(f"✓ Stopped session '{project}'")
    return 0


def cmd_ps() -> int:
    """List all sessions."""
    sessions = list_sessions()

    if not sessions:
        print("No active sessions")
        return 0

    print("Active sessions:")
    for name in sessions:
        print(f"  • {name}")
    return 0


def _queue_dir() -> Path:
    d = DATA_DIR / "send-queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _queue_path(project: str) -> Path:
    return _queue_dir() / f"{project}.json"


def _queue_load(project: str) -> list[str]:
    """Return queued messages for a project (oldest first)."""
    try:
        data = json.loads(_queue_path(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [str(m) for m in data]


def _queue_append(project: str, message: str) -> int:
    """Append a message to the project queue; return the pending count."""
    messages = _queue_load(project)
    messages.append(message)
    _queue_path(project).write_text(
        json.dumps(messages, ensure_ascii=False), encoding="utf-8"
    )
    return len(messages)


def _queue_clear(project: str) -> None:
    with contextlib.suppress(OSError):
        _queue_path(project).unlink()


def _deliver_queued(project: str) -> int:
    """Deliver queued messages in order; return how many were sent.

    An over-limit queued message is reported and skipped (the limit may
    have changed after queueing); it does not block the rest of the queue.
    """
    queued = _queue_load(project)
    if not queued:
        return 0
    _queue_clear(project)
    delivered = 0
    for message in queued:
        try:
            send_command(project, message)
        except MessageTooLong as e:
            print(f"error: queued message dropped: {e}", file=sys.stderr)
            continue
        delivered += 1
    return delivered


def _safe_full_state(project: str) -> SessionState:
    """Best-effort full state; UNKNOWN when detection itself fails."""
    try:
        return detect_full_state(project)
    except Exception as e:
        print(f"warning: state detection failed ({e}); sending blind", file=sys.stderr)
        return SessionState.UNKNOWN


def cmd_send(
    project: str, message: str, reply: bool = False, no_queue: bool = False
) -> int:
    """Send a command to a session, without typing into a modal form.

    When the session is awaiting input (an unanswered ask/approval form is
    up), typing would be swallowed by the form: the message is queued
    instead and delivered by the next ``gg send``/``gg answer`` once the
    form clears. ``--no-queue`` refuses instead.
    """
    validate_project(project)
    if reply:
        message = f"[Reply] {message}"

    state = _safe_full_state(project)
    if state == SessionState.AWAITING_INPUT:
        if no_queue:
            print(
                f"Session '{project}' is awaiting input (unanswered question). "
                f"Nothing sent. Answer with: gg answer {project} "
                f"(or dismiss the form with Escape, then resend)",
                file=sys.stderr,
            )
            return 1
        pending = get_pending_question(project)
        question_text = ""
        if pending and pending.questions:
            question_text = pending.questions[0].text
        count = _queue_append(project, message)
        print(f"Session '{project}' is awaiting input: {question_text}")
        print(
            f"Queued message ({count} pending). It delivers on the next "
            f"gg send/answer once the form clears."
        )
        print(f"Answer now with: gg answer {project}")
        return 0

    delivered = _deliver_queued(project)
    if delivered:
        print(f"✓ Delivered {delivered} queued message(s) to {project}")

    send_command(project, message)
    print(f"✓ Sent to {project}")
    return 0


def _resolve_answer(question: AgentQuestion, answer: str) -> str:
    """Map one answer arg to the text to type: option index, label, or free text."""
    stripped = answer.strip()
    if stripped.isdigit():
        idx = int(stripped)
        if not 1 <= idx <= len(question.options):
            raise ValidationError(
                f"option {idx} out of range (1..{len(question.options)}) "
                f"for: {question.text or '(no text)'}"
            )
        return question.options[idx - 1].label
    for option in question.options:
        if option.label.lower() == stripped.lower():
            return option.label
    return answer


def _print_pending_question(pending: PendingQuestion) -> None:
    """Render a pending question form for the terminal."""
    for i, question in enumerate(pending.questions, start=1):
        header = question.text or "(no question text)"
        print(f"Q{i}: {header}")
        for j, option in enumerate(question.options, start=1):
            desc = f" — {option.description}" if option.description else ""
            print(f"  {j}) {option.label}{desc}")
        if not question.options:
            print("  (free-text answer)")


def cmd_answer(project: str, answers: list[str]) -> int:
    """Answer the agent's pending question, then deliver queued messages.

    With no answers, prints the pending form. Otherwise expects one answer
    per question: a 1-based option index, an option label, or free text.
    """
    validate_project(project)
    if get_pane(project) is None:
        print(f"Session not found: {project}", file=sys.stderr)
        return 3

    pending = get_pending_question(project)
    if pending is None:
        state = _safe_full_state(project)
        print(
            f"No pending question in '{project}' (state: {state.value})",
            file=sys.stderr,
        )
        return 1

    if not answers:
        _print_pending_question(pending)
        print(
            "\nAnswer with: gg answer <project> <option...> "
            "(1-based index, label, or free text — one per question)"
        )
        return 0

    if len(answers) != len(pending.questions):
        _print_pending_question(pending)
        print(
            f"\nThis form has {len(pending.questions)} question(s); "
            f"got {len(answers)} answer(s).",
            file=sys.stderr,
        )
        return 2

    resolved = [
        _resolve_answer(question, answer)
        for question, answer in zip(pending.questions, answers, strict=False)
    ]
    for text in resolved:
        send_command(project, text)

    # The answered form may have been blocking queued messages.
    time.sleep(1.0)
    delivered = _deliver_queued(project)
    if delivered:
        print(f"✓ Delivered {delivered} queued message(s) to {project}")

    print(f"✓ Answered {project}")
    return 0


_SINCE_RE = re.compile(r"^(\d+)([smhd])$")


def _parse_since(since: str) -> str:
    """Validate a ``--since`` duration and return tmux start syntax.

    Accepts e.g. ``30s``, ``5m``, ``2h``, ``1d`` (tmux >= 3.2 time syntax).
    """
    m = _SINCE_RE.match(since.strip().lower())
    if not m:
        raise ValidationError(
            f"invalid --since {since!r}: expected e.g. 30s, 5m, 2h, 1d"
        )
    return f"-{m.group(1)}{m.group(2)}"


_SINCE_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _since_seconds(since: str) -> int:
    """Return the --since duration in seconds."""
    m = _SINCE_RE.match(since.strip().lower())
    assert m is not None  # callers validate via _parse_since first
    return int(m.group(1)) * _SINCE_UNIT_SECONDS[m.group(2)]


def _since_empty_warning(pane: object, since_seconds: int) -> str:
    """Explain an empty --since result instead of implying silence.

    tmux timestamps scrollback lines when they are created; a TUI that
    redraws in place creates no new lines, so a busy session can have zero
    lines "newer than 2m" while its screen changes constantly.
    """
    window = getattr(pane, "window", None)
    activity = getattr(window, "window_activity", None)
    hint = "Use --follow to watch live output."
    if activity:
        age = int(time.time()) - int(activity)
        if age <= since_seconds:
            return (
                f"pane was active {age}s ago, but tmux has no scrollback "
                f"lines newer than the requested window: TUI redraws in "
                f"place do not create new lines. {hint}"
            )
    return (
        "no pane lines newer than the requested window (tmux timestamps "
        f"lines when they are created; in-place TUI output matches "
        f"nothing). {hint}"
    )


def _ts_now() -> str:
    """Local timestamp for ``--ts`` prefixes."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _visible_lines(lines_data: list[str], agent: str, raw: bool) -> list[str]:
    """Return the printable lines for a capture (raw or agent-cleaned)."""
    if raw:
        return [ANSI_ESCAPE.sub("", line).rstrip() for line in lines_data]

    try:
        validate_agent(agent)
    except ValidationError:
        agent = "generic"

    cleaner = TmuxCleaner(agent)
    # Use clean_batch so the typing-region filter is applied.
    cleaned_lines = cleaner.clean_batch(lines_data)

    out: list[str] = []
    empty_line_count = 0
    for cleaned in cleaned_lines:
        # Skip separators and status bars
        if cleaned.line_type in {LineType.SEPARATOR, LineType.STATUS_BAR}:
            empty_line_count = 0
            continue

        if not cleaned.is_visible:
            continue

        if cleaned.line_type == LineType.PROMPT_MARKER:
            out.extend(["", "", cleaned.cleaned])
            empty_line_count = 0
        elif cleaned.cleaned:
            # Regular content - emit pending empty lines first (max 2)
            out.extend([""] * min(empty_line_count, 2))
            out.append(cleaned.cleaned)
            empty_line_count = 0
        else:
            # Empty line - count but don't emit yet
            empty_line_count += 1
    return out


def _logs_json(
    project: str,
    visible: list[str],
    ts: bool,
    raw: bool,
    warning: str | None = None,
) -> str:
    """Serialize one capture batch as a stable JSON object."""
    stamp = _ts_now() if ts else None
    payload: dict = {
        "project": project,
        "captured_at": _ts_now(),
        "raw": raw,
        "lines": [{"text": line, "ts": stamp} for line in visible],
    }
    if warning:
        payload["warning"] = warning
    return json.dumps(payload, ensure_ascii=False)


def _logs_follow(
    project: str,
    capture: Callable[[], list[str]],
    *,
    raw: bool,
    agent: str,
    ts: bool,
    as_json: bool,
) -> int:
    """Stream new pane output until Ctrl-C."""
    prev: list[str] = []
    print(f"Following {project} (Ctrl-C to stop)", file=sys.stderr)
    try:
        while True:
            current = capture()
            new = current[len(prev) :] if current[: len(prev)] == prev else current
            prev = current
            if new:
                visible = _visible_lines(new, agent, raw)
                if visible:
                    if as_json:
                        print(_logs_json(project, visible, ts, raw), flush=True)
                    else:
                        stamp = f"{_ts_now()} " if ts else ""
                        for line in visible:
                            print(f"{stamp}{line}")
                        sys.stdout.flush()
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0


def cmd_logs(
    project: str,
    lines: int = LOGS_DEFAULT_LINES,
    raw: bool = False,
    agent: str = "generic",
    ts: bool = False,
    since: str | None = None,
    follow: bool = False,
    as_json: bool = False,
) -> int:
    """Show session logs using direct tmux capture.

    Args:
        project: Project name
        lines: Number of lines to capture (ignored with ``--since``)
        raw: If True, show raw output without cleaning
        agent: Agent type for cleaning (kimi, coder, etc.)
        ts: Prefix lines with the capture timestamp
        since: Only capture output newer than this (e.g. ``5m``, ``2h``)
        follow: Stream new output until Ctrl-C
        as_json: Emit one JSON object per capture batch instead of text
    """
    start: int | str = _parse_since(since) if since is not None else -lines

    pane = get_pane(project)

    if not pane:
        if as_json:
            print(json.dumps({"project": project, "error": "session not found"}))
        else:
            print(f"Session not found: {project}", file=sys.stderr)
        return 3

    def capture() -> list[str]:
        try:
            # The libtmux stub types `start` as int | "-", but tmux >= 3.2
            # also accepts relative time strings ("-5m"), which libtmux
            # passes through verbatim.
            data = pane.capture_pane(
                start=start,  # type: ignore[arg-type]
                join_wrapped=not raw,
                escape_sequences=True,
            )
        except Exception as e:
            raise GGError(f"Failed to capture pane: {e}") from e
        return data or []

    if follow:
        return _logs_follow(
            project, capture, raw=raw, agent=agent, ts=ts, as_json=as_json
        )

    lines_data = capture()
    warning: str | None = None
    if not lines_data:
        if since is not None:
            warning = _since_empty_warning(pane, _since_seconds(since))
        if as_json:
            print(_logs_json(project, [], ts, raw, warning=warning))
        else:
            if warning:
                print(f"warning: {warning}", file=sys.stderr)
            age = f" in the last {since}" if since else ""
            print(f"No output for {project}{age}")
        return 0

    visible = _visible_lines(lines_data, agent, raw)
    if since is not None and not visible:
        warning = (
            f"{len(lines_data)} captured line(s) within the window were "
            f"all filtered out by cleaning (agent={agent}); "
            f"try --raw or -a <agent>"
        )
    if as_json:
        print(_logs_json(project, visible, ts, raw, warning=warning))
        return 0
    if warning:
        print(f"warning: {warning}", file=sys.stderr)

    print(f"\n{'=' * 60}")
    print(f"Project: {project}")
    print(f"{'=' * 60}\n")

    stamp = f"{_ts_now()} " if ts else ""
    for line in visible:
        print(f"{stamp}{line}")

    print(f"\n{'=' * 60}\n")
    return 0


def _attach_to_session(project: str) -> None:
    """Attach/switch to a tmux session.

    If the current process is already running inside a tmux client
    (``TMUX`` environment variable is set), use ``switch-client`` so we
    reuse the existing client instead of creating a nested attach. This
    avoids detaching the client from other sessions and making them look
    like they were closed.
    """
    validate_project(project)  # Security: validate project name before passing to tmux
    if os.environ.get("TMUX"):
        print(f"Switching to {project}...")
        os.execlp("tmux", "tmux", "switch-client", "-t", project)
    else:
        print(f"Attaching to {project}...")
        os.execlp("tmux", "tmux", "attach", "-t", project)


def cmd_attach(project: str) -> int:
    """Attach to a session."""
    _attach_to_session(project)
    return 0  # Never reached


def cmd_connect(
    project: str,
    agent: str,
    model: str | None = None,
    yolo: bool = False,
    auto: bool = False,
) -> int:
    """Start and attach to a session."""
    sessions = list_sessions()

    if project in sessions:
        print(f"Session '{project}' already running, attaching...")
    else:
        model_str = f" ({model})" if model else ""
        mode_str = ""
        if auto:
            mode_str = " [auto]"
        elif yolo:
            mode_str = " [yolo]"
        print(f"Starting session '{project}' with {agent}{model_str}{mode_str}...")
        start_session(project, agent, model=model, yolo=yolo, auto=auto)
        print(f"✓ Started session '{project}'")

    _attach_to_session(project)
    return 0  # Never reached


def cmd_doctor(fix: bool = False) -> int:
    """Check gg-core installation health.

    Verifies:
    - gg wrapper is installed and executable
    - systemd service template exists
    - tmux is available
    - kimi-code is available (for kimi agent)
    - config files are valid
    - gg-core module can be imported

    Args:
        fix: If True, attempt to fix detected issues

    Returns:
        0 if healthy, 1 if issues found
    """
    issues: list[str] = []
    fixes: list[str] = []

    print("gg-core doctor")
    print("=" * 50)
    print(f"version: {version_string()}")

    # 1. Check gg wrapper
    gg_path = shutil.which("gg")
    if gg_path:
        print(f"✓ gg wrapper: {gg_path}")
    else:
        print("✗ gg wrapper: not found in PATH")
        issues.append("gg wrapper not in PATH")
        if fix:
            local_bin = Path.home() / ".local" / "bin"
            local_bin.mkdir(parents=True, exist_ok=True)
            src = Path(__file__).parent.parent.parent.parent / "bin" / "gg"
            if src.exists():
                dst = local_bin / "gg"
                shutil.copy2(src, dst)
                dst.chmod(0o755)
                fixes.append(f"Installed gg wrapper to {dst}")
                print("  → Fixed: installed gg wrapper")
            else:
                fixes.append("Could not find gg wrapper source")
                print("  → Could not fix: source not found")

    # 2. Check systemd service
    service_path = Path.home() / ".config" / "systemd" / "user" / "gg@.service"
    if service_path.exists():
        print(f"✓ systemd service: {service_path}")
    else:
        print("✗ systemd service: not installed")
        issues.append("systemd service not installed")
        if fix:
            service_path.parent.mkdir(parents=True, exist_ok=True)
            src = Path(__file__).parent.parent.parent.parent / "systemd" / "gg@.service"
            if src.exists():
                shutil.copy2(src, service_path)
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
                fixes.append(f"Installed systemd service to {service_path}")
                print("  → Fixed: installed systemd service")
            else:
                fixes.append("Could not find service template source")
                print("  → Could not fix: source not found")

    # 3. Check tmux
    tmux_path = shutil.which("tmux")
    if tmux_path:
        print(f"✓ tmux: {tmux_path}")
    else:
        print("✗ tmux: not found")
        issues.append("tmux not installed")

    # 4. Check agent binaries. The configured default agent is required;
    # other agents are optional.
    def _which(name: str) -> Path | None:
        found = shutil.which(name)
        return Path(found) if found else None

    agent_binaries: dict[str, list[Path | None]] = {
        # find_omp_binary covers both install layouts (standalone / bun package)
        # and PATH, so doctor agrees with the command the sessions actually run.
        "omp": [find_omp_binary()],
        "kimi": [_which("kimi"), Path.home() / ".kimi-code" / "bin" / "kimi"],
    }
    for agent, candidates in agent_binaries.items():
        found = next((c for c in candidates if c and c.exists()), None)
        if found:
            print(f"✓ {agent}: {found}")
        elif agent == DEFAULT_AGENT:
            print(f"✗ {agent} (default agent): not found")
            issues.append(f"{agent} (default agent) not installed")
        else:
            print(f"- {agent}: not found (optional)")

    # 5. Check gg-core module import
    try:
        import gg_core  # type: ignore[import-untyped]

        print(f"✓ gg-core module: {gg_core.__version__}")
    except ImportError as e:
        print(f"✗ gg-core module: import failed ({e})")
        issues.append(f"gg-core import failed: {e}")

    # 6. Check the default agent's config
    config_path = (
        Path.home() / ".omp" / "agent" / "config.yml"
        if DEFAULT_AGENT == "omp"
        else Path.home() / ".kimi-code" / "config.toml"
    )
    if config_path.exists():
        print(f"✓ {DEFAULT_AGENT} config: {config_path}")
    else:
        print(f"- {DEFAULT_AGENT} config: not found ({config_path})")

    # Summary
    print("=" * 50)
    if not issues:
        print("All checks passed!")
        return 0

    print(f"Found {len(issues)} issue(s):")
    for issue in issues:
        print(f"  - {issue}")

    if fixes:
        print(f"\nApplied {len(fixes)} fix(es):")
        for fix_msg in fixes:
            print(f"  - {fix_msg}")

    return 1
