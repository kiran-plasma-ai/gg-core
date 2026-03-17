"""Tmux output cleaning for gg-core.

Provides agent-aware cleaning of tmux pane output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class LineType(Enum):
    """Classification of line content."""

    EMPTY = auto()
    SEPARATOR = auto()
    PROMPT_MARKER = auto()  # 💫
    INPUT_MARKER = auto()  # ✨
    TOOL_CALL = auto()
    STATUS_BAR = auto()
    SPINNER = auto()
    BULLET = auto()
    CONTINUATION = auto()
    CONTENT = auto()


@dataclass(frozen=True)
class CleanedLine:
    """Immutable cleaned line with metadata."""

    original: str
    cleaned: str
    line_type: LineType
    agent: str = "generic"

    @property
    def is_visible(self) -> bool:
        """Whether this line should be visible in output."""
        return self.line_type in {
            LineType.CONTENT,
            LineType.BULLET,
            LineType.PROMPT_MARKER,
            LineType.INPUT_MARKER,
            LineType.TOOL_CALL,
            LineType.CONTINUATION,
        }


class AgentHandler:
    """Base handler for agent-specific cleaning."""

    # Subclasses should override these
    SPINNER_CHARS: str = ""
    PROMPT_MARKERS: tuple[str, ...] = ()
    STATUS_PATTERNS: list[re.Pattern] = []

    def filter_line(self, line: str, line_type: LineType) -> tuple[str, LineType]:
        """Apply agent-specific filtering.

        Returns filtered line and potentially changed line type.
        """
        # Remove spinner characters
        for c in self.SPINNER_CHARS:
            line = line.replace(c, "")

        # Check for prompt markers
        if not line.strip():
            return line, LineType.EMPTY

        # Check status patterns
        for pattern in self.STATUS_PATTERNS:
            if pattern.match(line):
                return "", LineType.STATUS_BAR

        return line, line_type


class KimiHandler(AgentHandler):
    """Handler for kimi-cli output."""

    SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣷⣯⣟⡿⢿⣻⣽⣾🌑🌒🌓🌔🌕🌖🌗🌘"
    PROMPT_MARKERS = ("💫",)
    STATUS_PATTERNS = [
        re.compile(r"^yolo\s+agent.*", re.IGNORECASE),
        re.compile(r"^ctrl-j:.*", re.IGNORECASE),
    ]


class CoderHandler(AgentHandler):
    """Handler for coder.rs output."""

    SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇"
    PROMPT_MARKERS = ("coder>", "...>")
    STATUS_PATTERNS = []


class GrokHandler(AgentHandler):
    """Handler for grok output."""

    SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇"
    PROMPT_MARKERS = ()
    STATUS_PATTERNS = []


class GeminiHandler(AgentHandler):
    """Handler for gemini output."""

    SPINNER_CHARS = ""
    PROMPT_MARKERS = ("gemini>",)
    STATUS_PATTERNS = []


class GenericHandler(AgentHandler):
    """Handler for unknown agents."""

    pass


# Handler registry
_HANDLERS: dict[str, type[AgentHandler]] = {
    "kimi": KimiHandler,
    "coder": CoderHandler,
    "grok": GrokHandler,
    "minimax": CoderHandler,  # Same as coder
    "gemini": GeminiHandler,
    "custom": GenericHandler,
}


def get_handler(agent: str) -> AgentHandler:
    """Get handler for agent type."""
    handler_class = _HANDLERS.get(agent, GenericHandler)
    return handler_class()


class TmuxCleaner:
    """Tmux output cleaner with agent-specific handling."""

    # ANSI patterns
    _ANSI_CSI = re.compile(r"\x1b\[[\?\>\<!]*[0-9;]*[A-Za-z]")
    _ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
    _ANSI_TITLE = re.compile(r"\x1bk.*?\x1b\\")
    _ANSI_OTHER = re.compile(r"\x1b[()\]}#~]|\x08")

    # Character sets
    _SEPARATOR_CHARS = frozenset("─━═─┃│┊┈┼┤├┬┴┌┐└┘ ║╭╮╯╰╱╲╳")
    _BULLET_CHARS = frozenset("•·▪")

    def __init__(self, agent: str = "generic"):
        self.agent = agent
        self._handler = get_handler(agent)

    def clean_line(self, raw_line: str) -> CleanedLine:
        """Clean a single line."""
        original = raw_line.rstrip("\n\r")

        # Strip ANSI
        cleaned = self._strip_ansi(original)

        # Classify
        line_type = self._classify(cleaned)

        # Apply agent filters
        cleaned, line_type = self._handler.filter_line(cleaned, line_type)

        # Final cleanup
        cleaned = cleaned.strip()

        return CleanedLine(
            original=original,
            cleaned=cleaned,
            line_type=line_type,
            agent=self.agent,
        )

    def clean_batch(self, lines: list[str]) -> list[CleanedLine]:
        """Clean multiple lines."""
        return [self.clean_line(line) for line in lines]

    def get_visible(self, lines: list[str]) -> list[str]:
        """Get visible lines only."""
        cleaned = self.clean_batch(lines)
        return [line.cleaned for line in cleaned if line.is_visible and line.cleaned]

    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape sequences."""
        text = self._ANSI_OSC.sub("", text)
        text = self._ANSI_CSI.sub("", text)
        text = self._ANSI_TITLE.sub("", text)
        text = self._ANSI_OTHER.sub("", text)
        return text

    def _classify(self, line: str) -> LineType:
        """Classify a cleaned line."""
        if not line:
            return LineType.EMPTY

        # Check for separator characters only
        if self._SEPARATOR_CHARS.intersection(line):
            return LineType.SEPARATOR

        # Check for bullets
        if line[0] in self._BULLET_CHARS:
            return LineType.BULLET

        # Check for continuation (indented)
        if line and line[0] in " \t":
            return LineType.CONTINUATION

        # Check for prompt markers
        for marker in self._handler.PROMPT_MARKERS:
            if marker in line:
                return LineType.PROMPT_MARKER

        # Check for input marker
        if "✨" in line:
            return LineType.INPUT_MARKER

        return LineType.CONTENT


# Convenience function
def clean_logs(lines: list[str], agent: str = "generic") -> list[CleanedLine]:
    """Clean tmux log lines.

    Args:
        lines: Raw lines from tmux pane
        agent: Agent type (kimi, coder, etc.)

    Returns:
        List of CleanedLine objects
    """
    cleaner = TmuxCleaner(agent)
    return cleaner.clean_batch(lines)


def get_visible_logs(lines: list[str], agent: str = "generic") -> list[str]:
    """Get visible cleaned log lines.

    Args:
        lines: Raw lines from tmux pane
        agent: Agent type (kimi, coder, etc.)

    Returns:
        List of visible cleaned lines
    """
    cleaner = TmuxCleaner(agent)
    return cleaner.get_visible(lines)
