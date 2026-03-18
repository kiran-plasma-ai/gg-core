"""Core business logic."""

from .._config import LOG_DIR
from .._types import AgentState
from .extraction import (
    CleanedLine,
    LineType,
    detect_state_from_lines,
    extract_agent_output,
    extract_since_last_input,
    is_idle_from_lines,
    is_working_from_lines,
)
from .logs import get_log_path, get_log_size
from .session import (
    detect_state,
    get_session_info,
    is_idle,
    is_working,
    list_sessions,
    send_command,
    start_session,
    stop_session,
)
from .tmux import Tmux, capture_pane, get_pane, get_tmux, send_keys
from .validation import (
    DEFAULT_AGENT,
    infer_agent,
    infer_agent_from_window,
    normalize_agent,
    validate_agent,
    validate_project,
)

__all__ = [
    # Tmux
    "Tmux",
    "get_tmux",
    "get_pane",
    "capture_pane",
    "send_keys",
    # Session
    "start_session",
    "stop_session",
    "send_command",
    "list_sessions",
    "get_session_info",
    # State
    "AgentState",
    "detect_state",
    "is_working",
    "is_idle",
    # Extraction
    "extract_agent_output",
    "extract_since_last_input",
    "detect_state_from_lines",
    "is_working_from_lines",
    "is_idle_from_lines",
    # Cleaning types
    "CleanedLine",
    "LineType",
    # Logs
    "get_log_path",
    "get_log_size",
    # Validation & Agent
    "validate_project",
    "validate_agent",
    "normalize_agent",
    "infer_agent",
    "infer_agent_from_window",
    "DEFAULT_AGENT",
    # Config
    "LOG_DIR",
]
