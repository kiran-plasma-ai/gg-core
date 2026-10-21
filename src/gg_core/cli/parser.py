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
        default=None,
        help=(
            "Agent to use (default: the project's last-used agent, then "
            "$GG_DEFAULT_AGENT or omp; e.g. dsh, omp, kimi, coder)"
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
    ps_parser = subparsers.add_parser(
        "ps",
        help="List all sessions with state and activity",
    )
    ps_parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a table"
    )
    ps_parser.add_argument(
        "--all",
        action="store_true",
        help="Merge sessions from every enabled host in the hosts config",
    )

    # hosts command
    hosts_parser = subparsers.add_parser(
        "hosts",
        help="List configured hosts (creates the config on first run)",
    )
    hosts_parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a table"
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
    send_parser.add_argument(
        "--no-queue",
        action="store_true",
        help="Refuse instead of queueing when the session awaits input",
    )

    # answer command
    answer_parser = subparsers.add_parser(
        "answer",
        help="Answer the agent's pending question (or show it)",
    )
    answer_parser.add_argument("project", help="Project name")
    answer_parser.add_argument(
        "answers",
        nargs="*",
        help="Option index, option label, or free text — one per question",
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

    # wait command
    wait_parser = subparsers.add_parser(
        "wait",
        help="Block until a session is idle/blocked or its pane changes",
    )
    wait_parser.add_argument("project", help="Project name")
    wait_modes = wait_parser.add_mutually_exclusive_group(required=True)
    wait_modes.add_argument(
        "--idle", action="store_const", const="idle", dest="mode",
        help="Wait until the session is idle",
    )
    wait_modes.add_argument(
        "--blocked", action="store_const", const="blocked", dest="mode",
        help="Wait until awaiting_input or failed",
    )
    wait_modes.add_argument(
        "--changed", action="store_const", const="changed", dest="mode",
        help="Wait until the pane content changes",
    )
    wait_parser.add_argument(
        "--timeout", type=float, default=None, help="Give up after N seconds"
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
        default=None,
        help=(
            "Agent to use (default: the project's last-used agent, then "
            "$GG_DEFAULT_AGENT or omp; e.g. dsh, omp, kimi, coder)"
        ),
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
