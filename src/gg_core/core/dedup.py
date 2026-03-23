"""Deduplication for tmux pane output.

Tracks seen content per session using MD5 hash with a sliding window.
Prevents re-processing/re-sending the same content across poll cycles.
"""

from __future__ import annotations

import hashlib
from collections import deque

__all__ = ["Deduplicator", "get_dedup"]


class Deduplicator:
    """Track seen content to avoid duplicates.

    Maintains a sliding window of hashes for each session. When a session
    exceeds max_size, the oldest hash is evicted automatically.

    This is content-based deduplication — the same text at any position
    in the pane buffer is considered a duplicate. This is more robust than
    position-based (cursor) deduplication which can break when panes shrink
    or buffers rotate.
    """

    def __init__(self, max_size: int = 128) -> None:
        """Initialize the deduplicator.

        Args:
            max_size: Maximum hashes to retain per session (sliding window).
        """
        self._max_size = max_size
        self._seen: dict[str, deque[str]] = {}

    def _hash(self, content: str) -> str:
        """Generate a deterministic hash for content.

        Uses MD5 truncated to 32 hex chars for speed. MD5 is fine here
        since we only need uniqueness, not cryptographic security.
        """
        return hashlib.md5(content.encode()).hexdigest()[:32]

    def check_and_add(self, session: str, content: str) -> bool:
        """Check if content is new for a session and register it.

        Side-effect: adds the content hash to the tracking window if new.

        Args:
            session: Session identifier (e.g., project name, session ID)
            content: Text content to check

        Returns:
            True if this content has not been seen for this session.
        """
        if session not in self._seen:
            self._seen[session] = deque(maxlen=self._max_size)

        h = self._hash(content)
        if h in self._seen[session]:
            return False

        self._seen[session].append(h)
        return True

    def get_new_lines(self, session: str, lines: list[str]) -> list[str]:
        """Filter a list of lines to only those not yet seen.

        Args:
            session: Session identifier
            lines: Lines to filter

        Returns:
            Only lines that are new for this session.
        """
        new_lines: list[str] = []
        for line in lines:
            if self.check_and_add(session, line):
                new_lines.append(line)
        return new_lines

    def reset(self, session: str) -> None:
        """Clear all tracked hashes for a session.

        Use this to start fresh, e.g., at the beginning of a new
        interaction cycle where old content should not block new output.

        Args:
            session: Session identifier to clear.
        """
        if session in self._seen:
            self._seen[session].clear()

    def has_session(self, session: str) -> bool:
        """Check if a session has any tracked hashes.

        Args:
            session: Session identifier.

        Returns:
            True if the session has been seen before.
        """
        return session in self._seen


# Module-level singleton — shared across all importers
_dedup = Deduplicator()


def get_dedup() -> Deduplicator:
    """Return the global Deduplicator singleton.

    All callers share the same instance, so hashes are shared across
    the process. This is the intended behavior — a hash seen in one
    module should not be re-reported by another.

    Returns:
        The global Deduplicator instance.
    """
    return _dedup
