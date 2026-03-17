"""Type definitions for gg-core."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SessionInfo:
    """Information about a tmux session."""

    name: str
    exists: bool
    active: bool  # has attached pane
    log_path: Path
    log_size: Optional[int] = None


@dataclass
class SessionState:
    """Current state of a session."""

    name: str
    running: bool
    idle: bool
    at_prompt: bool
    last_activity: Optional[str] = None


VALID_AGENTS = frozenset({"kimi", "coder", "grok", "minimax", "gemini", "custom"})

# Project name validation
VALID_PROJECT_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$"
MAX_PROJECT_NAME_LENGTH = 64
