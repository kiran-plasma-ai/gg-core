"""Core extraction module.

Agent output extraction and state detection from tmux pane lines.
Uses gg-core cleaning for output, raw lines for state detection.
"""

from __future__ import annotations

import logging
import re as _re

from .._config import ANSI_ESCAPE
from .._errors import TmuxError
from .._types import AgentState
from ..cleaning import (
    _INPUT_HEADER_RE,
    _SPINNER_UNION,
    CleanedLine,
    LineType,
    TmuxCleaner,
)

logger = logging.getLogger(__name__)


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

    if last_input_idx >= 0:
        # There is at least one INPUT_MARKER in the capture.
        # Return only the lines that come *after* the last one.
        result_lines = [
            CleanedLine(
                original=c.original,
                cleaned=ANSI_ESCAPE.sub("", c.cleaned),
                line_type=c.line_type,
                agent=c.agent,
            )
            for c in cleaned[last_input_idx + 1 :]
        ]
    else:
        # No INPUT_MARKER at all — return all visible lines as a fallback.
        result_lines = [
            CleanedLine(
                original=c.original,
                cleaned=ANSI_ESCAPE.sub("", c.cleaned),
                line_type=c.line_type,
                agent=c.agent,
            )
            for c in cleaned
            if c.is_visible
        ]

    result_lines = _filter_styled_lines(result_lines)

    # Safety net: filter any CONTENT/CONTINUATION lines that appear after
    # the last input header.  This catches typing text that clean_batch's
    # state tracking might have missed (e.g. because an intermediate line
    # broke the filter_wrapped state).
    last_header_idx = -1
    for i, line in enumerate(result_lines):
        original = ANSI_ESCAPE.sub("", line.original)
        if _INPUT_HEADER_RE.match(original):
            last_header_idx = i

    if last_header_idx >= 0:
        result_lines = [
            CleanedLine(
                original=line.original,
                cleaned="",
                line_type=LineType.EMPTY,
                agent=line.agent,
            )
            if i > last_header_idx
            and line.line_type in (LineType.CONTENT, LineType.CONTINUATION)
            else line
            for i, line in enumerate(result_lines)
        ]

    return result_lines


_STYLE_RE = _re.compile(
    r"\x1b\[[0-9;]*[23]m"  # italic, dim
    r"|\x1b\[38;5;244m"  # grey color
)
_LEADING_RESET = _re.compile(r"^\x1b\[0m")


def _filter_styled_lines(
    lines: list[CleanedLine],
) -> list[CleanedLine]:
    """Remove styled (grey/italic/dim) lines that represent internal agent notes.

    Lines with ANSI italic (3), dim (2), or grey (38;5;244) codes are filtered out.
    Reset codes (0) at line start are ignored since they don't style the line itself.
    This removes grey italic "thinking" lines from voice output.
    """
    filtered = []
    for c in lines:
        original = _LEADING_RESET.sub("", c.original)
        if _STYLE_RE.search(original):
            continue
        filtered.append(c)
    return filtered


def extract_since_last_input(
    lines: list[str],
    agent: str = "kimi",
) -> list[str]:
    """Extract cleaned text after last user input marker.

    Args:
        lines: Raw lines from tmux capture
        agent: Agent type

    Returns:
        List of cleaned text lines (excludes prompt markers and styled lines)
    """
    cleaned = extract_agent_output(lines, agent)
    result = []
    for c in cleaned:
        if c.line_type == LineType.PROMPT_MARKER:
            continue
        if c.cleaned and c.is_visible:
            result.append(c.cleaned)
    return result


def get_latest_response(
    project: str,
    agent: str = "kimi",
) -> list[str]:
    """Get the latest agent response for a project.

    Uses wire.jsonl for kimi-code sessions when available, otherwise falls
    back to tmux pane capture and cleaning.

    Args:
        project: Project name
        agent: Agent type

    Returns:
        List of response text strings
    """
    from .validation import normalize_agent, validate_project
    from .wire import extract_wire_text, find_kimi_wire_path

    validate_project(project)

    if normalize_agent(agent) == "kimi":
        wire_path = find_kimi_wire_path(project)
        if wire_path is not None:
            try:
                return extract_wire_text(wire_path)
            except OSError as e:
                logger.warning(f"Wire read failed for {project}: {e}")

    # Fallback: tmux capture + cleaning
    from .tmux import get_tmux

    tmux = get_tmux()
    try:
        lines = tmux.capture_pane(project, lines=50)
    except (TmuxError, OSError) as e:
        logger.warning(f"Failed to capture pane for {project}: {e}")
        return []
    return extract_since_last_input(lines, agent)


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

    state_check_window = 25
    recent = (
        lines[-state_check_window:]
        if len(lines) >= state_check_window
        else lines
    )
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
    "get_latest_response",
    "detect_state_from_lines",
    "is_working_from_lines",
    "is_idle_from_lines",
]
