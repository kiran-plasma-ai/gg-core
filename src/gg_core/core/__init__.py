"""Core business logic."""

from .._config import LOG_DIR
from .._types import AgentState, ProjectStatus
from .dedup import Deduplicator, get_dedup
from .extraction import (
    CleanedLine,
    LineType,
    detect_state_from_lines,
    extract_agent_output,
    extract_since_last_input,
    get_latest_response,
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
from .status import (
    discover_projects,
    get_project_status,
    get_projects_status,
    wait_for_state,
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
from .wire import (
    detect_wire_state,
    extract_wire_text,
    find_kimi_wire_path,
    is_kimi_code_session,
    read_wire_events,
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
    # Status / orchestration
    "ProjectStatus",
    "get_project_status",
    "get_projects_status",
    "wait_for_state",
    "discover_projects",
    # Extraction
    "extract_agent_output",
    "extract_since_last_input",
    "get_latest_response",
    "detect_state_from_lines",
    "is_working_from_lines",
    "is_idle_from_lines",
    # Wire (kimi-code)
    "find_kimi_wire_path",
    "read_wire_events",
    "extract_wire_text",
    "detect_wire_state",
    "is_kimi_code_session",
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
    # Deduplication
    "Deduplicator",
    "get_dedup",
]
