"""CLI main entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable

from .._config import ANSI_ESCAPE, LOGS_DEFAULT_LINES
from .._errors import GGError, SessionError, SessionNotFound, ValidationError
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


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text.

    This prevents ANSI escape injection attacks where malicious
    terminal output could execute commands or manipulate display.
    Handles both CSI (colors, cursor) and OSC (window titles, hyperlinks).

    Args:
        text: Text that may contain ANSI codes

    Returns:
        Text with ANSI codes removed
    """
    return ANSI_ESCAPE.sub("", text)


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
            args.project, args.agent, model=args.model, yolo=args.yolo
        ),
        "stop": lambda: cmd_stop(args.project),
        "ps": cmd_ps,
        "send": lambda: cmd_send(args.project, args.message, reply=args.reply),
        "logs": lambda: cmd_logs(
            args.project, args.lines, raw=args.raw, agent=args.agent
        ),
        "attach": lambda: cmd_attach(args.project),
        "connect": lambda: cmd_connect(
            args.project, args.agent, model=args.model, yolo=args.yolo
        ),
    }

    handler = dispatch_table.get(command)
    if handler is None:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1
    return handler()


def cmd_start(
    project: str, agent: str, model: str | None = None, yolo: bool = False
) -> int:
    """Start a new session."""
    model_str = f" ({model})" if model else ""
    print(f"Starting session '{project}' with {agent}{model_str}...")
    start_session(project, agent, model=model, yolo=yolo)
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

    send_command(project, message)
    print(f"✓ Sent to {project}: {message}")
    return 0


def _print_raw_logs(lines_data: list[str]) -> None:
    """Print raw log lines with ANSI stripped."""
    for line in lines_data:
        print(ANSI_ESCAPE.sub("", line).rstrip())


def _print_cleaned_logs(lines_data: list[str], agent: str) -> None:
    """Print cleaned log lines with agent-aware formatting."""
    try:
        validate_agent(agent)
    except ValidationError:
        agent = "generic"

    cleaner = TmuxCleaner(agent)
    # Use clean_batch so the typing-region filter is applied.
    cleaned_lines = cleaner.clean_batch(lines_data)

    empty_line_count = 0
    for cleaned in cleaned_lines:
        # Skip separators and status bars
        if cleaned.line_type in {LineType.SEPARATOR, LineType.STATUS_BAR}:
            empty_line_count = 0
            continue

        if not cleaned.is_visible:
            continue

        if cleaned.line_type == LineType.PROMPT_MARKER:
            print()
            print()
            print(cleaned.cleaned)
            empty_line_count = 0
        elif cleaned.cleaned:
            # Regular content - print pending empty lines first (max 2)
            for _ in range(min(empty_line_count, 2)):
                print()
            print(cleaned.cleaned)
            empty_line_count = 0
        else:
            # Empty line - count but don't print yet
            empty_line_count += 1


def cmd_logs(
    project: str,
    lines: int = LOGS_DEFAULT_LINES,
    raw: bool = False,
    agent: str = "generic",
) -> int:
    """Show session logs using direct tmux capture.

    Args:
        project: Project name
        lines: Number of lines to capture
        raw: If True, show raw output without cleaning
        agent: Agent type for cleaning (kimi, coder, etc.)
    """
    pane = get_pane(project)

    if not pane:
        print(f"Session not found: {project}")
        return 1

    try:
        if raw:
            # Raw capture with ANSI codes preserved
            lines_data = pane.capture_pane(
                start=-lines, escape_sequences=True
            )
        else:
            # Capture with wrapped lines joined, ANSI preserved for cleaning
            lines_data = pane.capture_pane(
                start=-lines, join_wrapped=True, escape_sequences=True
            )
    except Exception as e:
        print(f"Failed to capture pane: {e}")
        return 1

    if not lines_data:
        print(f"No output for {project}")
        return 0

    print(f"\n{'=' * 60}")
    print(f"Project: {project}")
    print(f"{'=' * 60}\n")

    if raw:
        _print_raw_logs(lines_data)
    else:
        _print_cleaned_logs(lines_data, agent)

    print(f"\n{'=' * 60}\n")
    return 0


def cmd_attach(project: str) -> int:
    """Attach to a session."""
    validate_project(project)  # Security: validate project name before passing to tmux
    print(f"Attaching to {project}...")
    # This replaces the process
    os.execlp("tmux", "tmux", "attach", "-t", project)
    return 0  # Never reached


def cmd_connect(
    project: str, agent: str, model: str | None = None, yolo: bool = False
) -> int:
    """Start and attach to a session."""
    validate_project(project)  # Security: validate project name before passing to tmux
    sessions = list_sessions()

    if project in sessions:
        print(f"Session '{project}' already running, attaching...")
    else:
        model_str = f" ({model})" if model else ""
        print(f"Starting session '{project}' with {agent}{model_str}...")
        start_session(project, agent, model=model, yolo=yolo)
        print(f"✓ Started session '{project}'")

    # Attach
    os.execlp("tmux", "tmux", "attach", "-t", project)
    return 0  # Never reached
