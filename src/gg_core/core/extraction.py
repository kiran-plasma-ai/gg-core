"""Core extraction module.

Agent output extraction and state detection from tmux pane lines.
Uses gg-core cleaning for output, raw lines for state detection.
"""

from __future__ import annotations

import re as _re

from .._config import ANSI_ESCAPE
from .._types import AgentState
from ..cleaning import _SPINNER_UNION, CleanedLine, LineType, TmuxCleaner


def extract_agent_output(
    lines: list[str],
    agent: str = "kimi",
) -> list[CleanedLine]:
    """Extract agent output after the last user input marker.

    Args:
        lines: Raw lines from tmux capture
        agent: Agent type (kimi, coder, gemini, etc.)

    Returns:
        List of CleanedLine objects after last ✨ marker
    """
    cleaner = TmuxCleaner(agent)
    cleaned = cleaner.clean_batch(lines)

    last_input_idx = -1
    for i, line in enumerate(cleaned):
        if line.line_type == LineType.INPUT_MARKER:
            last_input_idx = i

    if last_input_idx >= 0 and last_input_idx + 1 < len(cleaned):
        return cleaned[last_input_idx + 1 :]

    return [c for c in cleaned if c.is_visible]


def extract_since_last_input(
    lines: list[str],
    agent: str = "kimi",
) -> list[str]:
    """Extract cleaned text after last user input marker.

    Args:
        lines: Raw lines from tmux capture
        agent: Agent type

    Returns:
        List of cleaned text lines (excludes prompt markers)
    """
    cleaned = extract_agent_output(lines, agent)
    result = []
    for c in cleaned:
        if c.line_type == LineType.PROMPT_MARKER:
            continue
        if c.cleaned and c.is_visible:
            result.append(c.cleaned)
    return result


def detect_state_from_lines(lines: list[str]) -> AgentState:
    """Detect agent state from tmux pane lines.

    Strips ANSI first, then checks for spinners and tool calls.

    Args:
        lines: Raw lines from tmux capture

    Returns:
        AgentState: WORKING, IDLE, or UNKNOWN
    """
    if not lines:
        return AgentState.UNKNOWN

    recent = lines[-25:] if len(lines) >= 25 else lines
    stripped = [ANSI_ESCAPE.sub("", line) for line in recent]

    for line in stripped:
        if _STATE_SPINNER_RE.search(line):
            return AgentState.WORKING

    for line in stripped:
        if _STATE_TOOL_RE.search(line):
            return AgentState.WORKING

    return AgentState.IDLE


_STATE_SPINNER_RE = _re.compile(
    rf"[{''.join(_SPINNER_UNION)}]"  # Unicode braille spinners (union)
    r"|[\|/\\-]"  # ASCII line spinners
)
_STATE_TOOL_RE = _re.compile(
    r"\b(Used Shell|Used WriteFile|Used ReadFile|Used Edit|Used Grep|Used Glob|"
    r"Using Shell|Using WriteFile|Using ReadFile|Using Edit|Using Grep|Using Glob|"
    r"Tool:)"
)


def is_working_from_lines(lines: list[str]) -> bool:
    """Quick check if agent is currently working.

    Args:
        lines: Raw lines from tmux capture

    Returns:
        True if agent is working
    """
    return detect_state_from_lines(lines) == AgentState.WORKING


def is_idle_from_lines(lines: list[str]) -> bool:
    """Quick check if agent is idle.

    Args:
        lines: Raw lines from tmux capture

    Returns:
        True if agent is at prompt
    """
    return detect_state_from_lines(lines) == AgentState.IDLE


__all__ = [
    "AgentState",
    "CleanedLine",
    "LineType",
    "extract_agent_output",
    "extract_since_last_input",
    "detect_state_from_lines",
    "is_working_from_lines",
    "is_idle_from_lines",
]
