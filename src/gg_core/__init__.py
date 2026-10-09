"""gg-core - GitGantt session management core.

A thin wrapper around libtmux for session management.
"""

from ._config import ANSI_ESCAPE, get_agent_command
from ._errors import (
    GGError,
    QuotaExceeded,
    SessionError,
    SessionExists,
    SessionNotFound,
    TmuxError,
    ValidationError,
)
from ._types import AgentState, ProjectStatus, SessionInfo
from .cleaning import CleanedLine, LineType
from .core import (
    DEFAULT_AGENT,
    Deduplicator,
    agent_marker_path,
    check_project_quota_error,
    check_quota_error,
    detect_omp_state,
    detect_quota_error,
    detect_state,
    detect_state_from_lines,
    detect_wire_state,
    discover_projects,
    extract_agent_output,
    extract_omp_text,
    extract_since_last_input,
    extract_wire_text,
    find_kimi_wire_path,
    find_omp_session_path,
    get_dedup,
    get_latest_response,
    get_pane,
    get_project_status,
    get_projects_status,
    get_session_info,
    infer_agent,
    infer_agent_from_window,
    is_idle,
    is_idle_from_lines,
    is_kimi_code_session,
    is_omp_session,
    is_working,
    is_working_from_lines,
    list_sessions,
    match_agent_in_window,
    normalize_agent,
    read_omp_entries,
    read_wire_events,
    recorded_agent,
    resolve_agent,
    send_command,
    start_session,
    stop_session,
    validate_agent,
    validate_project,
    wait_for_state,
    window_agent_hint,
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
    "QuotaExceeded",
    # Types
    "SessionInfo",
    "ProjectStatus",
    "AgentState",
    "CleanedLine",
    "LineType",
    # Utilities
    "ANSI_ESCAPE",
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
    "agent_marker_path",
    "recorded_agent",
    "resolve_agent",
    # Status / orchestration
    "get_project_status",
    "get_projects_status",
    "wait_for_state",
    "discover_projects",
    # State detection
    "detect_state",
    "is_working",
    "is_idle",
    # Extraction (from lines)
    "extract_agent_output",
    "extract_since_last_input",
    "get_latest_response",
    "detect_state_from_lines",
    "is_working_from_lines",
    "is_idle_from_lines",
    "detect_quota_error",
    "check_quota_error",
    "check_project_quota_error",
    # Wire (kimi-code)
    "find_kimi_wire_path",
    "read_wire_events",
    "extract_wire_text",
    "detect_wire_state",
    "is_kimi_code_session",
    # omp session transcript
    "find_omp_session_path",
    "read_omp_entries",
    "extract_omp_text",
    "detect_omp_state",
    "is_omp_session",
    # Agent inference
    "infer_agent",
    "infer_agent_from_window",
    "match_agent_in_window",
    "window_agent_hint",
    "normalize_agent",
    "DEFAULT_AGENT",
    # Deduplication
    "Deduplicator",
    "get_dedup",
]
