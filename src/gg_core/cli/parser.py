"""CLI parser setup."""

from __future__ import annotations

import argparse

from .._config import LOGS_DEFAULT_LINES


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="gg",
        description="GitGantt session management - tmux-based AI agent sessions",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # start command
    start_parser = subparsers.add_parser(
        "start",
        help="Start a new session",
    )
    start_parser.add_argument("project", help="Project name")
    start_parser.add_argument(
        "agent", nargs="?", default="kimi", help="Agent to use (default: kimi)"
    )
    start_parser.add_argument("--yolo", action="store_true", help="Enable YOLO mode")

    # stop command
    stop_parser = subparsers.add_parser(
        "stop",
        help="Stop a session",
    )
    stop_parser.add_argument("project", help="Project name")

    # ps command
    subparsers.add_parser(
        "ps",
        help="List all sessions",
    )

    # send command
    send_parser = subparsers.add_parser(
        "send",
        help="Send a command to a session",
    )
    send_parser.add_argument("project", help="Project name")
    send_parser.add_argument("message", help="Message to send")
    send_parser.add_argument(
        "--reply", action="store_true", help="Mark as reply to a question"
    )

    # logs command
    logs_parser = subparsers.add_parser(
        "logs",
        help="Show session logs",
    )
    logs_parser.add_argument("project", help="Project name")
    logs_parser.add_argument(
        "lines", nargs="?", type=int, default=LOGS_DEFAULT_LINES, help="Number of lines"
    )
    logs_parser.add_argument("--raw", action="store_true", help="Show raw output")
    logs_parser.add_argument(
        "--agent",
        "-a",
        default="kimi",
        help="Agent type for cleaning (kimi, coder, etc.)",
    )

    # attach command
    attach_parser = subparsers.add_parser(
        "attach",
        help="Attach to a session",
    )
    attach_parser.add_argument("project", help="Project name")

    # connect command
    connect_parser = subparsers.add_parser(
        "connect",
        help="Start and attach to a session",
    )
    connect_parser.add_argument("project", help="Project name")
    connect_parser.add_argument("agent", nargs="?", default="kimi", help="Agent to use")
    connect_parser.add_argument("--yolo", action="store_true", help="Enable YOLO mode")

    return parser
