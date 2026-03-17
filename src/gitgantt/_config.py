"""Configuration for gg-core.

This module contains only constants and configuration values.
No runtime logic should be here.
"""

from __future__ import annotations

import os
from pathlib import Path


# =============================================================================
# Paths
# =============================================================================


def _get_rundir() -> Path:
    """Get the runtime directory."""
    rundir = os.environ.get("XDG_RUNTIME_DIR")
    if not rundir:
        uid = os.getuid()
        rundir = f"/run/user/{uid}"
    return Path(rundir)


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
DEFAULT_AGENTS: dict[str, str] = {
    "kimi": "~/.local/bin/kimi-cli -S {project} --yes",
    "coder": "~/.cargo/bin/coder -m kimi -S {project} --yolo",
    "grok": "~/.cargo/bin/coder -m grok -S {project} --yolo",
    "minimax": "~/.cargo/bin/coder -m minimax -S {project} --yolo",
    "gemini": "~/.local/bin/gemini",
}


def get_agent_command(agent: str, project: str) -> str:
    """Get the command for an agent.

    Args:
        agent: Agent name
        project: Project name

    Returns:
        Command string with {project} placeholder replaced
    """
    env_key = f"GG_{agent.upper()}_CMD"
    cmd = os.environ.get(env_key, DEFAULT_AGENTS.get(agent, ""))
    return cmd.format(project=project)


# =============================================================================
# Systemd
# =============================================================================

SYSTEMD_SERVICE_TEMPLATE = "gitgantt@{project}.service"


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
