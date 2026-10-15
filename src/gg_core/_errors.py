"""Custom exceptions for gg-core."""

from __future__ import annotations


class GGError(Exception):
    """Base exception for gg-core."""

    pass


class ValidationError(GGError):
    """Invalid input provided."""

    pass


class SessionError(GGError):
    """Session operation failed."""

    pass


class SessionNotFound(SessionError):
    """Session does not exist."""

    pass


class SessionExists(SessionError):
    """Session already exists."""

    pass


class TmuxError(GGError):
    """Tmux operation failed."""

    pass


class QuotaExceeded(GGError):
    """Agent provider quota or usage limit reached."""

    pass


class MessageTooLong(GGError):
    """A message exceeded SEND_MESSAGE_MAX_LENGTH; nothing was sent."""

    pass
