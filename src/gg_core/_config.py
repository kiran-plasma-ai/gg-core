"""Configuration for gg-core.

This module contains only constants and configuration values.
No runtime logic should be here.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import shutil
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

def find_omp_binary() -> Path | None:
    """Return the installed omp binary for this host, if any.

    omp ships both as a standalone binary (``~/.local/bin/omp``, the gateway
    install) and as a bun-script package (``~/.bun/bin/omp``, the development
    machine), so the path is discovered rather than hardcoded.

    Returns:
        Path to the binary, or None when it is only available on PATH.
    """
    for candidate in (
        Path.home() / ".local" / "bin" / "omp",
        Path.home() / ".bun" / "bin" / "omp",
    ):
        if candidate.exists():
            return candidate
    found = shutil.which("omp")
    return Path(found) if found else None


def default_omp_command() -> str:
    """Return the default omp command for this host.

    Ends in ``-c`` (continue the most recent session in the working directory).
    Falls back to a bare ``omp`` so a PATH-only install still works.
    """
    binary = find_omp_binary()
    return f"{binary} -c" if binary else "omp -c"


# Default agent commands (can be overridden via env vars)
# Use GG_<AGENT>_CMD env var to override (e.g., GG_CUSTOM_CMD for "custom" agent)
# Use {project} placeholder for project name, {model} placeholder for model selection
DEFAULT_AGENTS: dict[str, str] = {
    "omp": default_omp_command(),
    "kimi": "~/.kimi-code/bin/kimi -c",
    "coder": "~/.cargo/bin/coder -m kimi -S {project} --yolo",
    "grok": "~/.cargo/bin/coder -m grok -S {project} --yolo",
    "minimax": "~/.cargo/bin/coder -m minimax -S {project} --yolo",
    "gemini": "~/.local/bin/gemini",
    "opencode": "~/.local/bin/opencode",
    "custom": "",  # Requires GG_CUSTOM_CMD env var
}

# Agent used when none is given on the command line. Set GG_DEFAULT_AGENT to
# switch the whole installation to a different agent (e.g. GG_DEFAULT_AGENT=kimi
# for the previous kimi-code default), or pass an agent explicitly to
# ``gg start`` / ``gg connect``.
DEFAULT_AGENT: str = (os.environ.get("GG_DEFAULT_AGENT") or "omp").strip().lower()

# Agents that support model selection (kimi/coder via -m, omp via --model)
MODEL_CAPABLE_AGENTS: frozenset[str] = frozenset({"kimi", "coder", "opencode", "omp"})


def get_agent_command(
    agent: str, project: str, model: str | None = None, *, auto: bool = False
) -> str:
    """Get the command for an agent.

    Args:
        agent: Agent name
        project: Project name (will be shell-escaped)
        model: Optional model to use (e.g., "minimax-m27-highspeed")
        auto: Start the agent in auto/YOLO mode (agent-specific flag)

    Returns:
        Command string with placeholders replaced and shell-escaped
    """
    env_key = f"GG_{agent.upper()}_CMD"
    template = os.environ.get(env_key, DEFAULT_AGENTS.get(agent, ""))

    # Expand ~ to the real home directory before shell processing.  Otherwise
    # shlex.quote() would wrap the path in single quotes and disable tilde
    # expansion when systemd/tmux later invokes the command.
    template = os.path.expanduser(template)

    # Shell-escape project name to prevent injection attacks, then format the
    # template. We parse with shlex so quoted arguments survive mutation.
    safe_project = shlex.quote(project)
    cmd = template.format(project=safe_project)
    parts = shlex.split(cmd)

    # Handle model selection for capable agents
    if model and agent in MODEL_CAPABLE_AGENTS:
        safe_model = shlex.quote(model)
        if "-m" in parts:
            idx = parts.index("-m")
            parts[idx + 1] = safe_model
        elif "-S" in parts:
            idx = parts.index("-S")
            parts.insert(idx, "-m")
            parts.insert(idx + 1, safe_model)
        elif "-C" in parts:
            # kimi: insert -m <model> before -C
            idx = parts.index("-C")
            parts.insert(idx, "-m")
            parts.insert(idx + 1, safe_model)
        elif "--model" in parts or agent == "omp":
            # omp uses --model; replace an existing value or append
            if "--model" in parts:
                parts[parts.index("--model") + 1] = safe_model
            else:
                parts.extend(["--model", safe_model])
        else:
            # Fallback: append at end (for opencode)
            parts.extend(["-m", safe_model])

    # Add agent-specific auto/YOLO startup flag.
    # coder/grok/minimax already default to --yolo in DEFAULT_AGENTS.
    # gemini and opencode have no standard flag.
    if auto:
        if agent == "kimi":
            parts.insert(1, "--auto")
        elif agent == "omp":
            parts.insert(1, "--auto-approve")

    return " ".join(shlex.quote(p) for p in parts)


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
LOGS_DEFAULT_LINES = int(os.environ.get("GG_LOGS_LINES", "100"))

# Maximum message length for `gg send` / send_command. Messages beyond this
# length are silently truncated to prevent abuse.
SEND_MESSAGE_MAX_LENGTH = 10000

# ANSI escape sequence patterns for output sanitization
# Handles CSI, OSC, and other terminal escape sequences
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
