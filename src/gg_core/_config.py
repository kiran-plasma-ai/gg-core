"""Configuration for gg-core.

This module contains only constants and configuration values.
No runtime logic should be here.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
from pathlib import Path

# =============================================================================
# Paths
# =============================================================================


def _get_rundir() -> Path:
    """Get the runtime directory with security validation.

    Validates that XDG_RUNTIME_DIR is in the expected location
    to prevent writing logs to attacker-controlled directories.

    Returns:
        Path to runtime directory
    """
    uid = os.getuid()
    expected = Path(f"/run/user/{uid}")

    # Validate and create expected directory if needed
    if not expected.exists():
        with contextlib.suppress(OSError):
            expected.mkdir(parents=True, exist_ok=True)

    rundir = os.environ.get("XDG_RUNTIME_DIR")
    if rundir:
        # Validate the path is in the expected location
        try:
            resolved = Path(rundir).resolve()
            # Must be a subdirectory of /run/user/<uid>/ for security
            # This prevents path traversal attacks
            resolved_str = str(resolved)
            if (
                (
                    resolved_str.startswith(f"/run/user/{uid}/")
                    or resolved_str == f"/run/user/{uid}"
                )
                and resolved.exists()
                and os.access(resolved, os.W_OK)
            ):
                return resolved
        except (OSError, ValueError, PermissionError):
            pass  # Invalid path, fall back to default

    # Fallback: ensure expected directory exists and is writable
    if expected.exists() and os.access(expected, os.W_OK):
        return expected

    # Last resort: try to create/verify
    try:
        expected.mkdir(parents=True, exist_ok=True)
        return expected
    except OSError:
        # Return expected anyway - let the actual write fail with a clear error
        return expected


RUNDIR = _get_rundir()
LOG_DIR = RUNDIR

# Installation paths
PREFIX = Path.home() / ".local"
DATA_DIR = PREFIX / "share" / "gg-core"
BIN_DIR = PREFIX / "bin"


# =============================================================================
# Agent Commands
# =============================================================================

# Default agent commands (can be overridden via env vars)
# Use GG_<AGENT>_CMD env var to override (e.g., GG_CUSTOM_CMD for "custom" agent)
DEFAULT_AGENTS: dict[str, str] = {
    "kimi": "~/.local/bin/kimi-cli -S {project} --yes",
    "coder": "~/.cargo/bin/coder -m kimi -S {project} --yolo",
    "grok": "~/.cargo/bin/coder -m grok -S {project} --yolo",
    "minimax": "~/.cargo/bin/coder -m minimax -S {project} --yolo",
    "gemini": "~/.local/bin/gemini",
    "custom": "",  # Requires GG_CUSTOM_CMD env var
}


def get_agent_command(agent: str, project: str) -> str:
    """Get the command for an agent.

    Args:
        agent: Agent name
        project: Project name (will be shell-escaped)

    Returns:
        Command string with {project} placeholder replaced and shell-escaped
    """
    env_key = f"GG_{agent.upper()}_CMD"
    cmd = os.environ.get(env_key, DEFAULT_AGENTS.get(agent, ""))
    # Shell-escape project name to prevent injection attacks
    safe_project = shlex.quote(project)
    return cmd.format(project=safe_project)


# =============================================================================
# Systemd
# =============================================================================

SYSTEMD_SERVICE_TEMPLATE = "gg@{project}.service"

# =============================================================================
# Logging
# =============================================================================

LOG_PREFIX = "gg-"  # Prefix for log files (gg-<project>.log)


# =============================================================================
# Validation
# =============================================================================

VALID_PROJECT_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$"
MAX_PROJECT_NAME_LENGTH = 64


# =============================================================================
# Timeouts (seconds)
# =============================================================================

TIMEOUT_DEFAULT = 10
TIMEOUT_SYSTEMD = 30
TIMEOUT_TMUX = 5

# Wait-for loop settings
WAIT_FOR_TIMEOUT = 10.0  # seconds to wait for condition
WAIT_FOR_INTERVAL = 0.5  # seconds between checks
WAIT_FOR_SESSION_INTERVAL = 0.2  # faster interval for session checks

# =============================================================================
# CLI Utilities
# =============================================================================

# CLI defaults (can be overridden via environment)
LOGS_DEFAULT_LINES = int(os.environ.get("GG_LOGS_LINES", 100))

# ANSI escape sequence patterns for output sanitization
# Handles CSI (Control Sequence Introducer), OSC (Operating System Command), and other sequences
ANSI_ESCAPE = re.compile(
    # OSC (Operating System Command) - window title, hyperlinks
    r"\x1b\][^\x07]*\x07"
    r"|\x1b\][^\x07]*\x1b\\"  # OSC with string terminator
    # CSI (Control Sequence Introducer) - colors, cursor movement, mode changes
    # Includes private markers (? > !) for DEC private sequences like DECAWM
    r"|\x1b\[[\?\>\<\!]*[\d;]*[a-zA-Z]"
    # 8-bit CSI equivalent
    r"|\x9b[\?\>\<\!]*[\d;]*[a-zA-Z]"
    # ESC + character - character sets, reset
    r"|\x1b[()][AB012]"
    # String terminator
    r"|\x9c"
)
