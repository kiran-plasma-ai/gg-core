"""Version and build identity for gg-core."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

__version__ = "0.2.0"

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=1)
def get_commit() -> str:
    """Short git commit of the running gg-core checkout.

    Returns ``"unknown"`` when the source tree is not a git checkout or git
    is unavailable (e.g. an installed wheel).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            timeout=5,
            check=False,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else "unknown"


def version_string() -> str:
    """Human-readable version, e.g. ``gg-core 0.2.0 (95c747b)``."""
    return f"gg-core {__version__} ({get_commit()})"
