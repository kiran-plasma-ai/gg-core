"""Thin wrapper around libtmux.

Provides a clean interface for tmux operations.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import libtmux
from libtmux import exc as libtmux_exc

from .._config import LOG_PREFIX
from .._errors import TmuxError
from .._types import SessionInfo

logger = logging.getLogger(__name__)


class Tmux:
    """Thin wrapper around libtmux.

    This is NOT a full abstraction - it wraps libtmux with better
    error handling and convenience methods.
    """

    def __init__(self) -> None:
        self._server = libtmux.Server()

    # -------------------------------------------------------------------------
    # Session operations
    # -------------------------------------------------------------------------

    def has_session(self, name: str) -> bool:
        """Check if session exists."""
        return self._server.has_session(name)

    def list_sessions(self) -> list[str]:
        """List all session names."""
        return [s.session_name for s in self._server.sessions if s.session_name]

    def get_session(self, name: str) -> libtmux.Session | None:
        """Get session by name, or None if not found."""
        for s in self._server.sessions:
            if s.session_name == name:
                return s
        return None

    # -------------------------------------------------------------------------
    # Pane operations
    # -------------------------------------------------------------------------

    def capture_pane(self, session: str, lines: int = 50) -> list[str]:
        """Capture pane content.

        Args:
            session: Session name
            lines: Number of lines to capture

        Returns:
            List of lines from the pane

        Raises:
            TmuxError: If session not found or capture fails
        """
        s = self.get_session(session)
        if not s:
            raise TmuxError(f"Session not found: {session}")

        # Get active pane (prefer attached, fall back to first)
        pane = self._get_active_pane(s)
        if not pane:
            raise TmuxError(f"No pane found in session: {session}")

        try:
            return pane.capture_pane(start=-lines, join_wrapped=True)
        except libtmux_exc.LibTmuxException as e:
            raise TmuxError(f"Failed to capture pane: {e}") from e

    def send_keys(self, session: str, keys: str) -> None:
        """Send keys to session.

        Args:
            session: Session name
            keys: Keys to send (Enter is automatically added)

        Raises:
            TmuxError: If session not found or send fails
        """
        s = self.get_session(session)
        if not s:
            raise TmuxError(f"Session not found: {session}")

        pane = self._get_active_pane(s)
        if not pane:
            raise TmuxError(f"No pane found in session: {session}")

        try:
            pane.send_keys(keys)
        except libtmux_exc.LibTmuxException as e:
            raise TmuxError(f"Failed to send keys: {e}") from e

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _get_active_pane(self, session: libtmux.Session) -> libtmux.Pane | None:
        """Get the active pane from a session."""
        # Prefer attached window/pane
        try:
            if session.active_window and session.active_window.active_pane:
                return session.active_window.active_pane
        except AttributeError:
            pass

        # Fall back to first window/pane
        try:
            if session.windows and session.windows[0].panes:
                return session.windows[0].panes[0]
        except (AttributeError, IndexError):
            pass

        return None

    def get_session_info(self, name: str, log_dir: Path) -> SessionInfo:
        """Get information about a session."""
        s = self.get_session(name)

        exists = s is not None
        active = False

        if s:
            try:
                active = bool(s.active_window and s.active_window.active_pane)
            except AttributeError:
                active = False

        log_path = log_dir / f"{LOG_PREFIX}{name}.log"
        log_size = None
        if log_path.exists():
            try:
                log_size = log_path.stat().st_size
            except OSError as e:
                logger.warning(f"Failed to get log file size for {log_path}: {e}")

        return SessionInfo(
            name=name,
            exists=exists,
            active=active,
            log_path=log_path,
            log_size=log_size,
        )


# Singleton with lru_cache for thread-safety
@lru_cache(maxsize=1)
def _get_tmux_impl() -> Tmux | None:
    """Get cached Tmux instance. Returns None on failure."""
    try:
        return Tmux()
    except Exception:
        logger.error("Failed to initialize Tmux")
        return None


def get_tmux() -> Tmux:
    """Get the singleton Tmux instance.

    Uses lru_cache for simple, safe singleton pattern.
    Raises RuntimeError if Tmux initialization failed.
    """
    tmux = _get_tmux_impl()
    if tmux is None:
        raise RuntimeError("Tmux initialization failed - is tmux installed?")
    return tmux


def get_pane(session: str) -> libtmux.Pane | None:
    """Get the active pane for a session.

    Use this to capture pane content directly:
        pane = get_pane("myproject")
        if pane:
            lines = pane.capture_pane(start='-', end='-')

    Args:
        session: Session name

    Returns:
        libtmux Pane object, or None if session/pane not found
    """
    tmux = get_tmux()
    s = tmux.get_session(session)
    if not s:
        return None
    return tmux._get_active_pane(s)


def capture_pane(session: str, lines: int = 50) -> list[str]:
    """Capture pane output for a session.

    Args:
        session: Session name
        lines: Number of lines to capture

    Returns:
        List of captured lines (from history, last N)
    """
    pane = get_pane(session)
    if not pane:
        return []

    all_lines = pane.capture_pane(start="-", join_wrapped=True)
    return all_lines[-lines:] if len(all_lines) > lines else all_lines


def send_keys(session: str, keys: str) -> bool:
    """Send keys to a session.

    Args:
        session: Session name
        keys: Keys to send

    Returns:
        True if successful
    """
    pane = get_pane(session)
    if not pane:
        return False

    try:
        pane.send_keys(keys)
        return True
    except Exception:
        return False
