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


class SessionState(str, Enum):
    """Evidence-based session state for supervisors.

    Derived from structured transcripts only (kimi ``wire.jsonl`` / omp
    session JSONL); the pane is used solely as a working/idle fallback and
    never as evidence for ``awaiting_input`` or ``failed``.
    """

    WORKING = "working"
    IDLE = "idle"
    AWAITING_INPUT = "awaiting_input"  # Unanswered ask / AskUserQuestion
    FAILED = "failed"  # Failed assistant turn carrying an error
    UNKNOWN = "unknown"


@dataclass
class QuestionOption:
    """One selectable option of an agent question."""

    label: str
    description: str = ""


@dataclass
class AgentQuestion:
    """A single question inside a pending agent form."""

    text: str
    options: list[QuestionOption]


@dataclass
class PendingQuestion:
    """An unanswered agent question currently blocking the session."""

    questions: list[AgentQuestion]
    source: str  # "wire" | "omp-session"
    call_id: str  # ask toolCall id / AskUserQuestion uuid


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
