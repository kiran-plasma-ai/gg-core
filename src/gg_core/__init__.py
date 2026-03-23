"""gg-core - GitGantt session management core.

A thin wrapper around libtmux for session management.
"""

from ._config import get_agent_command
from ._errors import (
    GGError,
    SessionError,
    SessionExists,
    SessionNotFound,
    TmuxError,
    ValidationError,
)
from ._types import AgentState, SessionInfo
from .cleaning import CleanedLine, LineType
from .core import (
    DEFAULT_AGENT,
    Deduplicator,
    detect_state,
    detect_state_from_lines,
    extract_agent_output,
    extract_since_last_input,
    get_dedup,
    get_pane,
    get_session_info,
    infer_agent,
    infer_agent_from_window,
    is_idle,
    is_idle_from_lines,
    is_working,
    is_working_from_lines,
    list_sessions,
    normalize_agent,
    send_command,
    start_session,
    stop_session,
    validate_agent,
    validate_project,
)

__version__ = "0.2.0"

__all__ = [
    # Errors
    "GGError",
    "ValidationError",
    "SessionError",
    "SessionExists",
    "SessionNotFound",
    "TmuxError",
    # Types
    "SessionInfo",
    "AgentState",
    "CleanedLine",
    "LineType",
    # Tmux
    "get_pane",
    # Core functions
    "validate_project",
    "validate_agent",
    "get_agent_command",
    "start_session",
    "stop_session",
    "send_command",
    "list_sessions",
    "get_session_info",
    # State detection
    "detect_state",
    "is_working",
    "is_idle",
    # Extraction (from lines)
    "extract_agent_output",
    "extract_since_last_input",
    "detect_state_from_lines",
    "is_working_from_lines",
    "is_idle_from_lines",
    # Agent inference
    "infer_agent",
    "infer_agent_from_window",
    "normalize_agent",
    "DEFAULT_AGENT",
    # Deduplication
    "Deduplicator",
    "get_dedup",
]
