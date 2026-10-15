"""CLI parser setup."""

from __future__ import annotations

import argparse

from .._config import DEFAULT_AGENT, LOGS_DEFAULT_LINES
from .._version import version_string


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="gg",
        description="GitGantt session management - tmux-based AI agent sessions",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=version_string(),
        help="Show gg-core version and git commit, then exit",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # start command
    start_parser = subparsers.add_parser(
        "start",
        help="Start a new session",
    )
    start_parser.add_argument("project", help="Project name")
    start_parser.add_argument(
        "agent",
        nargs="?",
        default=DEFAULT_AGENT,
        help=(
            "Agent to use (default: $GG_DEFAULT_AGENT or omp; "
            "e.g. omp, kimi, coder, opencode)"
        ),
    )
    start_parser.add_argument(
        "--model",
        "-m",
        dest="model",
        help="Model to use (e.g., deepseek/deepseek-v4-pro) - omp, kimi, coder, opencode",
    )
    start_parser.add_argument("--yolo", action="store_true", help="Enable YOLO mode")
    start_parser.add_argument(
        "--auto",
        action="store_true",
        help="Start in auto permission mode (kimi --auto / omp --auto-approve)",
    )

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
        default=DEFAULT_AGENT,
        help="Agent type for cleaning (omp, kimi, coder, etc.)",
    )
    logs_parser.add_argument(
        "--ts", action="store_true", help="Prefix lines with capture timestamp"
    )
    logs_parser.add_argument(
        "--since",
        help="Only capture output newer than this (e.g. 30s, 5m, 2h, 1d)",
    )
    logs_parser.add_argument(
        "--follow",
        "-f",
        action="store_true",
        help="Stream new output until Ctrl-C",
    )
    logs_parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of text"
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
    connect_parser.add_argument(
        "agent",
        nargs="?",
        default=DEFAULT_AGENT,
        help="Agent to use (default: $GG_DEFAULT_AGENT or omp)",
    )
    connect_parser.add_argument(
        "--model",
        "-m",
        dest="model",
        help="Model to use (e.g., deepseek/deepseek-v4-pro) - omp, kimi, coder, opencode",
    )
    connect_parser.add_argument("--yolo", action="store_true", help="Enable YOLO mode")
    connect_parser.add_argument(
        "--auto",
        action="store_true",
        help="Start in auto permission mode (kimi --auto / omp --auto-approve)",
    )

    # doctor command
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check gg-core installation health",
    )
    doctor_parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to fix detected issues",
    )

    return parser
