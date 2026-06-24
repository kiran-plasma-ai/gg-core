"""CLI main entry point."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

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
            args.project, args.agent, model=args.model, yolo=args.yolo, auto=args.auto
        ),
        "stop": lambda: cmd_stop(args.project),
        "ps": cmd_ps,
        "send": lambda: cmd_send(args.project, args.message, reply=args.reply),
        "logs": lambda: cmd_logs(
            args.project, args.lines, raw=args.raw, agent=args.agent
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
    project: str,
    agent: str,
    model: str | None = None,
    yolo: bool = False,
    auto: bool = False,
) -> int:
    """Start and attach to a session."""
    validate_project(project)  # Security: validate project name before passing to tmux
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

    # Attach
    os.execlp("tmux", "tmux", "attach", "-t", project)
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

    # 4. Check kimi-code
    kimi_path = shutil.which("kimi")
    if not kimi_path:
        # Try default location
        default_kimi = Path.home() / ".kimi-code" / "bin" / "kimi"
        if default_kimi.exists():
            kimi_path = str(default_kimi)
    if kimi_path:
        print(f"✓ kimi-code: {kimi_path}")
    else:
        print("✗ kimi-code: not found")
        issues.append("kimi-code not installed")

    # 5. Check gg-core module import
    try:
        import gg_core  # type: ignore[import-untyped]
        print(f"✓ gg-core module: {gg_core.__version__}")
    except ImportError as e:
        print(f"✗ gg-core module: import failed ({e})")
        issues.append(f"gg-core import failed: {e}")

    # 6. Check config
    config_path = Path.home() / ".kimi-code" / "config.toml"
    if config_path.exists():
        print(f"✓ kimi config: {config_path}")
    else:
        print("✗ kimi config: not found")
        issues.append("kimi config not found")

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
