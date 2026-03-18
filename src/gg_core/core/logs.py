"""Log utilities."""

from __future__ import annotations

from pathlib import Path

from .._config import LOG_DIR, LOG_PREFIX
from ..core.validation import validate_project


def get_log_path(project: str) -> Path:
    """Get log file path for a project.

    Args:
        project: Project name

    Returns:
        Path to log file

    Raises:
        ValidationError: If project name is invalid
    """
    validate_project(project)  # Ensure project name is safe
    return LOG_DIR / f"{LOG_PREFIX}{project}.log"


def get_log_size(project: str) -> int | None:
    """Get log file size in bytes.

    Args:
        project: Project name

    Returns:
        Size in bytes, or None if file doesn't exist
    """
    validate_project(project)

    log_path = get_log_path(project)

    if log_path.exists():
        try:
            return log_path.stat().st_size
        except OSError:
            pass

    return None
