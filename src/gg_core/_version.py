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

    Resolves from git first; falls back to ``_commit.txt`` (stamped by
    ``make install``/deploy for machines that receive the source without
    a ``.git`` directory). Returns ``"unknown"`` when neither exists.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            timeout=5,
            check=False,
            text=True,
        )
        commit = result.stdout.strip()
        if result.returncode == 0 and commit:
            return commit
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        from . import _commit

        if _commit.COMMIT:
            return _commit.COMMIT
    except (ImportError, AttributeError):
        pass
    return "unknown"


def version_string() -> str:
    """Human-readable version, e.g. ``gg-core 0.2.0 (95c747b)``."""
    return f"gg-core {__version__} ({get_commit()})"
