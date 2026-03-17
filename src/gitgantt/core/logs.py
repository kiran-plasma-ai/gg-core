"""Log utilities."""

from __future__ import annotations

from pathlib import Path

from .._config import LOG_DIR
from ..core.validation import validate_project


def get_log_path(project: str) -> Path:
    """Get log file path for a project."""
    return LOG_DIR / f"gg-{project}.log"


def get_log_size(project: str) -> int | None:
    """Get log file size in bytes."""
    validate_project(project)

    log_path = get_log_path(project)

    if log_path.exists():
        try:
            return log_path.stat().st_size
        except OSError:
            pass

    return None
