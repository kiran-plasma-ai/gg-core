"""CLI main entry point."""

from __future__ import annotations

import argparse
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
    DEFAULT_AGENT,
    LOGS_DEFAULT_LINES,
    SEND_MESSAGE_MAX_LENGTH,
    find_omp_binary,
)
from .._errors import GGError, SessionError, SessionNotFound, ValidationError
from .._version import version_string
from ..cleaning import LineType, TmuxCleaner
from ..core.session import (
    list_sessions,
    send_command,
    start_session,
    stop_session,
)
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
        "send": lambda: cmd_send(args.project, args.message, reply=args.reply),
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


def cmd_send(project: str, message: str, reply: bool = False) -> int:
    """Send a command to a session."""
    if reply:
        message = f"[Reply] {message}"

    if len(message) > SEND_MESSAGE_MAX_LENGTH:
        print(
            f"Warning: message exceeds {SEND_MESSAGE_MAX_LENGTH} characters "
            f"and will be truncated",
            file=sys.stderr,
        )

    send_command(project, message)
    print(f"✓ Sent to {project}: {message}")
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


def _logs_json(project: str, visible: list[str], ts: bool, raw: bool) -> str:
    """Serialize one capture batch as a stable JSON object."""
    stamp = _ts_now() if ts else None
    payload = {
        "project": project,
        "captured_at": _ts_now(),
        "raw": raw,
        "lines": [{"text": line, "ts": stamp} for line in visible],
    }
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
    if not lines_data:
        if as_json:
            print(_logs_json(project, [], ts, raw))
        else:
            print(f"No output for {project}")
        return 0

    visible = _visible_lines(lines_data, agent, raw)
    if as_json:
        print(_logs_json(project, visible, ts, raw))
        return 0

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
