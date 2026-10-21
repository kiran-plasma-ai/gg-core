"""Validation and agent utilities."""

from __future__ import annotations

import re

import libtmux

from .._config import DEFAULT_AGENT, MAX_PROJECT_NAME_LENGTH, VALID_PROJECT_PATTERN
from .._errors import ValidationError

# Known agent patterns in window name (case-insensitive)
AGENT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bdsh\b|dsh-tui", re.I), "dsh"),
    (re.compile(r"\bomp\b|oh-my-pi", re.I), "omp"),
    (re.compile(r"kimi", re.I), "kimi"),
    (re.compile(r"coder", re.I), "coder"),
    (re.compile(r"grok", re.I), "grok"),
    (re.compile(r"gemini", re.I), "gemini"),
    (re.compile(r"minimax", re.I), "minimax"),
    (re.compile(r"opencode", re.I), "opencode"),
]

# Valid agents for validation
_VALID_AGENTS = frozenset(
    {
        "dsh",
        "omp",
        "kimi",
        "coder",
        "grok",
        "minimax",
        "gemini",
        "opencode",
        "custom",
    }
)


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


def match_agent_in_window(window_name: str) -> str | None:
    """Match a tmux window name against the known agent patterns.

    Args:
        window_name: Name of the tmux window (e.g., "Kimi", "Coder")

    Returns:
        Agent type string, or None when the name identifies no known agent
        (e.g. a shell wrapper around the agent).
    """
    for pattern, agent in AGENT_PATTERNS:
        if pattern.search(window_name):
            return agent
    return None


def infer_agent_from_window(window_name: str) -> str:
    """Infer agent from tmux window name.

    Args:
        window_name: Name of the tmux window (e.g., "Kimi", "Coder")

    Returns:
        Agent type string (omp, kimi, coder, grok, gemini, minimax, opencode)
    """
    return match_agent_in_window(window_name) or DEFAULT_AGENT


def window_agent_hint(session_name: str) -> str | None:
    """Agent implied by a session's tmux window name, if it identifies one.

    Args:
        session_name: Name of the tmux session

    Returns:
        Agent type string, or None when the window name is uninformative (for
        example a sandbox wrapper script), so callers can fall back to other
        evidence such as the agent's transcript.
    """
    try:
        server = libtmux.Server()
        for s in server.sessions:
            if s.session_name == session_name:
                if s.active_window and s.active_window.name:
                    return match_agent_in_window(s.active_window.name)
                break
    except Exception:
        pass
    return None


def _get_agent_from_session(session_name: str) -> str:
    """Get agent for a session by checking tmux window name."""
    return window_agent_hint(session_name) or DEFAULT_AGENT


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


# Mapping of variant names to canonical agent names
_AGENT_ALIASES: dict[str, str] = {
    "dsh": "dsh",
    "dsh-tui": "dsh",
    "dsh_tui": "dsh",
    "dst": "dsh",
    "omp": "omp",
    "oh-my-pi": "omp",
    "oh_my_pi": "omp",
    "kimi": "kimi",
    "kimi-cli": "kimi",
    "kimi-for-coding": "kimi",
    "coder": "coder",
    "coder.rs": "coder",
    "coder-rs": "coder",
    "grok": "grok",
    "grok-2": "grok",
    "grok-3": "grok",
    "gemini": "gemini",
    "gemini-pro": "gemini",
    "gemini-2": "gemini",
    "minimax": "minimax",
    "minimax-chat": "minimax",
    "opencode": "opencode",
    "open-code": "opencode",
}


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
    if agent_lower in _AGENT_ALIASES:
        return _AGENT_ALIASES[agent_lower]

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
        valid = ", ".join(sorted(_VALID_AGENTS))
        raise ValidationError(f"Unknown agent: {agent!r}. Valid agents: {valid}")
    return normalized
