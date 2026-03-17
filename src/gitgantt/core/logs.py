"""Log reading utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .._config import LOG_DIR
from ..core.validation import validate_project


def get_log_path(project: str) -> Path:
    """Get log file path for a project."""
    return LOG_DIR / f"gg-{project}.log"


def read_log(project: str, lines: int = 50) -> list[str]:
    """Read lines from log file.

    Args:
        project: Project name
        lines: Number of lines to read

    Returns:
        List of lines (newest last)
    """
    validate_project(project)

    log_path = get_log_path(project)

    if not log_path.exists():
        return []

    try:
        with open(log_path, "r", errors="replace") as f:
            all_lines = f.readlines()
            return all_lines[-lines:] if len(all_lines) > lines else all_lines
    except OSError:
        return []


def get_log_size(project: str) -> Optional[int]:
    """Get log file size in bytes."""
    validate_project(project)

    log_path = get_log_path(project)

    if log_path.exists():
        try:
            return log_path.stat().st_size
        except OSError:
            pass

    return None
