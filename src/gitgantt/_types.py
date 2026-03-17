"""Type definitions for gg-core."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SessionInfo:
    """Information about a tmux session."""

    name: str
    exists: bool
    active: bool  # has attached pane
    log_path: Path
    log_size: int | None = None


# Valid agents (import from _config for validation constants)
VALID_AGENTS = frozenset({"kimi", "coder", "grok", "minimax", "gemini", "custom"})
