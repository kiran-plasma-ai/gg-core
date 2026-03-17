"""CLI main entry point."""

from __future__ import annotations

import argparse
import os
import sys

from .._errors import GGError, SessionError, SessionNotFound, ValidationError
from ..core import logs
from ..core.session import (
    list_sessions,
    send_command,
    start_session,
    stop_session,
)
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

    if command == "start":
        return cmd_start(args.project, args.agent, yolo=args.yolo)
    elif command == "stop":
        return cmd_stop(args.project)
    elif command == "ps":
        return cmd_ps()
    elif command == "send":
        return cmd_send(args.project, args.message, reply=args.reply)
    elif command == "logs":
        return cmd_logs(args.project, args.lines, raw=args.raw)
    elif command == "attach":
        return cmd_attach(args.project)
    elif command == "connect":
        return cmd_connect(args.project, args.agent, yolo=args.yolo)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1


def cmd_start(project: str, agent: str, yolo: bool = False) -> int:
    """Start a new session."""
    print(f"Starting session '{project}' with {agent}...")
    start_session(project, agent, yolo=yolo)
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


def cmd_logs(project: str, lines: int = 50, raw: bool = False) -> int:
    """Show session logs."""
    # TODO: Add --raw flag support for raw tmux capture
    _ = raw  # Reserved for future use
    lines_data = logs.read_log(project, lines)

    if not lines_data:
        print(f"No logs for {project}")
        return 0

    print(f"\n{'=' * 60}")
    print(f"Project: {project}")
    print(f"{'=' * 60}\n")

    for line in lines_data:
        print(line.rstrip())

    print(f"\n{'=' * 60}\n")
    return 0


def cmd_attach(project: str) -> int:
    """Attach to a session."""
    print(f"Attaching to {project}...")
    # This replaces the process
    os.execlp("tmux", "tmux", "attach", "-t", project)
    return 0  # Never reached


def cmd_connect(project: str, agent: str, yolo: bool = False) -> int:
    """Start and attach to a session."""
    sessions = list_sessions()

    if project in sessions:
        print(f"Session '{project}' already running, attaching...")
    else:
        print(f"Starting session '{project}' with {agent}...")
        start_session(project, agent, yolo=yolo)
        print(f"✓ Started session '{project}'")

    # Attach
    os.execlp("tmux", "tmux", "attach", "-t", project)
    return 0  # Never reached
