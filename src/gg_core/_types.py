"""Type definitions for gg-core."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class AgentState(Enum):
    """Agent state enumeration for session monitoring."""

    WORKING = "working"  # Agent actively processing (spinners, tool calls)
    IDLE = "idle"  # Agent at prompt, waiting for input
    UNKNOWN = "unknown"  # Cannot determine state


@dataclass
class SessionInfo:
    """Information about a tmux session."""

    name: str
    exists: bool
    active: bool  # has attached pane
    log_path: Path
    log_size: int | None = None


@dataclass
class ProjectStatus:
    """Status snapshot for a project/session.

    Used by orchestration layers (e.g. ``hand``) to monitor many projects at
    once without making multiple separate gg-core calls.
    """

    name: str
    exists: bool
    active: bool
    state: AgentState
    agent: str
    latest_response: list[str]
    log_path: Path
    log_size: int | None = None
    wire_path: Path | None = None
