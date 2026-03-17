"""Configuration for gg-core.

This module contains only constants and configuration values.
No runtime logic should be here.
"""

from __future__ import annotations

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

    rundir = os.environ.get("XDG_RUNTIME_DIR")
    if rundir:
        # Validate the path is in the expected location
        try:
            resolved = Path(rundir).resolve()
            # Only allow if it's exactly the expected path
            if resolved == expected:
                return resolved
        except (OSError, ValueError):
            pass  # Invalid path, fall back to default

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

# ANSI escape sequence patterns for output sanitization
# Handles CSI (Control Sequence Introducer) and OSC (Operating System Command)
ANSI_ESCAPE = re.compile(
    r"\x1b\][^\x07]*\x07"  # OSC: ]0;title\x07, ]8;;url\x07
    r"|\x1b\[[0-9;]*[a-zA-Z]"  # CSI: colors, cursor movement
    r"|\x1b[()][AB012]"  # ESC (: RIS, SCUS, etc
)
