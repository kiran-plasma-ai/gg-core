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
from ._types import SessionInfo, SessionState
from .core.session import (
    get_session_info,
    list_sessions,
    send_command,
    start_session,
    stop_session,
)
from .core.validation import validate_agent, validate_project

__version__ = "0.1.0"

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
    "SessionState",
    # Core functions
    "validate_project",
    "validate_agent",
    "get_agent_command",
    "start_session",
    "stop_session",
    "send_command",
    "list_sessions",
    "get_session_info",
]
