"""Validation and agent utilities."""

from __future__ import annotations

import re

from .._config import MAX_PROJECT_NAME_LENGTH, VALID_PROJECT_PATTERN
from .._errors import ValidationError

# Known agent patterns in window name (case-insensitive)
AGENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"kimi", re.I), "kimi"),
    (re.compile(r"coder", re.I), "coder"),
    (re.compile(r"grok", re.I), "grok"),
    (re.compile(r"gemini", re.I), "gemini"),
    (re.compile(r"minimax", re.I), "minimax"),
]

DEFAULT_AGENT = "kimi"

# Valid agents for validation
_VALID_AGENTS = frozenset({"kimi", "coder", "grok", "minimax", "gemini", "custom"})


def validate_project(name: str) -> None:
    """Validate a project name.

    Args:
        name: Project name to validate

    Raises:
        ValidationError: If name is invalid
    """
    if not name:
        raise ValidationError("Project name cannot be empty")

    if len(name) > MAX_PROJECT_NAME_LENGTH:
        raise ValidationError(f"Project name too long (max {MAX_PROJECT_NAME_LENGTH})")

    if not re.match(VALID_PROJECT_PATTERN, name):
        raise ValidationError(
            f"Invalid project name: {name!r}. "
            "Use only letters, numbers, underscores, and hyphens. "
            "Must start with a letter or number."
        )


def infer_agent_from_window(window_name: str) -> str:
    """Infer agent from tmux window name.

    Args:
        window_name: Name of the tmux window (e.g., "Kimi", "Coder")

    Returns:
        Agent type string (kimi, coder, grok, gemini, minimax)
    """
    for pattern, agent in AGENT_PATTERNS:
        if pattern.search(window_name):
            return agent
    return DEFAULT_AGENT


def _get_agent_from_session(session_name: str) -> str:
    """Get agent for a session by checking tmux window name."""
    import libtmux

    try:
        server = libtmux.Server()
        for s in server.sessions:
            if s.session_name == session_name:
                if s.active_window and s.active_window.name:
                    return infer_agent_from_window(s.active_window.name)
                break
    except Exception:
        pass
    return DEFAULT_AGENT


def infer_agent(session_name: str) -> str:
    """Infer agent type - prefers window name over session name.

    Args:
        session_name: Name of the tmux session

    Returns:
        Agent type string
    """
    # Try window name first (more accurate)
    agent = _get_agent_from_session(session_name)
    if agent != DEFAULT_AGENT:
        return agent

    # Fallback to session name pattern
    name_lower = session_name.lower()
    for pattern, agent in AGENT_PATTERNS:
        if pattern.match(name_lower):
            return agent

    return DEFAULT_AGENT


def normalize_agent(agent: str) -> str:
    """Normalize agent name to standard form.

    This is a lenient function for inference - returns DEFAULT_AGENT
    for unknown agents.

    Args:
        agent: Agent name (may be varied format)

    Returns:
        Normalized agent name
    """
    if not agent:
        return ""

    agent_lower = agent.lower().strip()

    # Direct mappings
    if agent_lower in ("kimi", "kimi-cli", "kimi-for-coding"):
        return "kimi"
    if agent_lower in ("coder", "coder.rs", "coder-rs"):
        return "coder"
    if agent_lower in ("grok", "grok-2", "grok-3"):
        return "grok"
    if agent_lower in ("gemini", "gemini-pro", "gemini-2"):
        return "gemini"
    if agent_lower in ("minimax", "minimax-chat"):
        return "minimax"

    # Try pattern match
    for pattern, result in AGENT_PATTERNS:
        if pattern.match(agent_lower):
            return result

    return agent_lower  # Return lowercase input if no match


def validate_agent(agent: str) -> str:
    """Validate and normalize agent name.

    Args:
        agent: Agent name to validate

    Returns:
        Normalized agent name

    Raises:
        ValidationError: If agent is unknown
    """
    normalized = normalize_agent(agent)
    if not normalized or normalized not in _VALID_AGENTS:
        raise ValidationError(
            f"Unknown agent: {agent!r}. Valid agents: {', '.join(sorted(_VALID_AGENTS))}"
        )
    return normalized
