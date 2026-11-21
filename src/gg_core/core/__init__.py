"""Core business logic."""

from .._config import LOG_DIR
from .._types import (
    AgentQuestion,
    AgentState,
    PendingQuestion,
    ProjectStatus,
    QuestionOption,
    SessionState,
)
from .dedup import Deduplicator, get_dedup
from .dsh import (
    candidate_sessions,
    detect_dsh_full_state,
    latest_dsh_session_id,
    live_tui,
    project_key,
)
from .extraction import (
    CleanedLine,
    LineType,
    check_project_quota_error,
    check_quota_error,
    detect_quota_error,
    detect_state_from_lines,
    extract_agent_output,
    extract_since_last_input,
    get_latest_response,
    is_idle_from_lines,
    is_working_from_lines,
)
from .hosts import HostConfig, collect_all_ps, load_hosts
from .logs import get_log_path, get_log_size
from .omp import (
    detect_omp_full_state,
    detect_omp_state,
    extract_omp_text,
    find_omp_pending_question,
    find_omp_session_path,
    is_omp_session,
    read_omp_entries,
)
from .session import (
    agent_marker_path,
    agent_preference,
    detect_state,
    get_session_info,
    is_idle,
    is_working,
    list_sessions,
    recorded_agent,
    resolve_agent,
    resolve_project_agent,
    restart_session,
    send_command,
    set_agent_preference,
    start_session,
    stop_session,
)
from .status import (
    detect_full_state,
    discover_projects,
    get_pending_question,
    get_project_status,
    get_projects_status,
    wait_for_state,
)
from .tmux import Tmux, capture_pane, get_pane, get_tmux, send_keys
from .validation import (
    DEFAULT_AGENT,
    infer_agent,
    infer_agent_from_window,
    match_agent_in_window,
    normalize_agent,
    validate_agent,
    validate_project,
    window_agent_hint,
)
from .wire import (
    detect_wire_full_state,
    detect_wire_state,
    extract_wire_text,
    find_kimi_wire_path,
    find_wire_pending_question,
    is_kimi_code_session,
    read_wire_events,
)

__all__ = [
    # State
    "SessionState",
    "PendingQuestion",
    "AgentQuestion",
    "QuestionOption",
    # Tmux
    "Tmux",
    "get_tmux",
    "get_pane",
    "capture_pane",
    "send_keys",
    # Session
    "start_session",
    "stop_session",
    "restart_session",
    "send_command",
    "list_sessions",
    "get_session_info",
    "agent_marker_path",
    "recorded_agent",
    "resolve_agent",
    "agent_preference",
    "resolve_project_agent",
    "set_agent_preference",
    # dsh sessions
    "candidate_sessions",
    "latest_dsh_session_id",
    "live_tui",
    "project_key",
    "detect_dsh_full_state",
    # State
    "AgentState",
    "SessionState",
    "detect_state",
    "is_working",
    "is_idle",
    # Hosts
    "HostConfig",
    "load_hosts",
    "collect_all_ps",
    # Status / orchestration
    "ProjectStatus",
    "get_project_status",
    "get_projects_status",
    "wait_for_state",
    "discover_projects",
    "detect_full_state",
    "get_pending_question",
    # Extraction
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
    "detect_wire_full_state",
    "find_wire_pending_question",
    "is_kimi_code_session",
    # omp session transcript
    "find_omp_session_path",
    "read_omp_entries",
    "extract_omp_text",
    "detect_omp_state",
    "detect_omp_full_state",
    "find_omp_pending_question",
    "is_omp_session",
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
    "match_agent_in_window",
    "window_agent_hint",
    "DEFAULT_AGENT",
    # Config
    "LOG_DIR",
    # Deduplication
    "Deduplicator",
    "get_dedup",
]
