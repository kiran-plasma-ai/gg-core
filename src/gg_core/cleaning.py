"""Tmux output cleaning for gg-core.

Provides agent-aware cleaning of tmux pane output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto

from ._config import ANSI_ESCAPE


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


# Shared constants for state detection
# Union of all agent spinners (used for detection, not stripping)
_SPINNER_UNION = (
    "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣷⣯⣟⡿⢿⣻⣽⣾🌑🌒🌓🌔🌕🌖🌗🌘"
    "⠋⠙⠹⠸⠼⠴⠦⠧⠇"  # coder/grok subset
)
TOOL_INDICATORS = (
    "Used Shell",
    "Used WriteFile",
    "Using Shell",
    "Tool:",
    "Running",
    "Executing",
)


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
            LineType.EMPTY,
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
    STATUS_PATTERNS: list[re.Pattern[str]] = []
    ACTIVITY_PATTERNS: list[re.Pattern[str]] = []

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

        # Check activity indicators (e.g. "Thinking..." after spinner strip)
        for pattern in self.ACTIVITY_PATTERNS:
            if pattern.match(line):
                return "", LineType.EMPTY

        return line, line_type


class KimiHandler(AgentHandler):
    """Handler for kimi-cli output."""

    SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣷⣯⣟⡿⢿⣻⣽⣾🌑🌒🌓🌔🌕🌖🌗🌘"
    PROMPT_MARKERS = ("💫",)
    STATUS_PATTERNS = [
        re.compile(r"^yolo\s+agent.*", re.IGNORECASE),
        re.compile(r"^ctrl-j:.*", re.IGNORECASE),
    ]
    SPACING_AFTER_PROMPT = 2  # Extra empty lines after 💫 for readability
    ACTIVITY_PATTERNS = [
        re.compile(r"^Thinking\.+\s*$", re.IGNORECASE),
        re.compile(r"^Working\.+\s*$", re.IGNORECASE),
        re.compile(r"^Processing\.+\s*$", re.IGNORECASE),
        re.compile(r"^Composing\.+\s*$", re.IGNORECASE),
        re.compile(r"^Reading\.+\s*$", re.IGNORECASE),
        re.compile(r"^Parsing\.+\s*$", re.IGNORECASE),
        re.compile(r"^Analyzing\.+\s*$", re.IGNORECASE),
    ]
    SPACING_AFTER_PROMPT = 2  # Extra empty lines after 💫 for readability
    TOOL_VERBS = frozenset(
        (
            "used",
            "running",
            "executing",
            "applying",
            "creating",
            "writing",
            "reading",
            "searching",
            "finding",
            "installing",
            "updating",
            "deleting",
            "moving",
            "copying",
        )
    )

    def filter_line(self, line: str, line_type: LineType) -> tuple[str, LineType]:
        """Apply kimi-specific formatting."""
        stripped = line.strip()

        # Filter out typing in progress - when 💫 is followed by text (not just spaces)
        # but ✨ is not present (not yet submitted)
        # e.g., "💫 asdasd" = typing, "💫       " = idle (show prompt marker)
        if stripped.startswith("💫") and "✨" not in line and stripped != "💫":
            return "", LineType.EMPTY

        # Filter continuation/content lines that are partial words (e.g., "aaaaaaa" after 💫 typing)
        # These are tmux-wrapped lines from user typing that don't contain spaces
        if (
            line_type in (LineType.CONTINUATION, LineType.CONTENT)
            and stripped
            and " " not in stripped
            and not any(c.isupper() or c in ".-/()[]{}" for c in stripped)
        ):
            # Looks like a partial word continuation - filter it
            return "", LineType.EMPTY

        # Strip spinner characters first so activity patterns can match
        for c in self.SPINNER_CHARS:
            line = line.replace(c, "")

        # Check status patterns
        for pattern in self.STATUS_PATTERNS:
            if pattern.match(line):
                return "", LineType.STATUS_BAR

        # Convert ✨ to User:
        if "✨" in line:
            line = line.replace("✨", "User:")
            line_type = LineType.INPUT_MARKER

        # Convert bullet to Tool: only if it's a tool call
        # Tool calls start with "• Used ...", "• Running ..." etc.
        if line_type == LineType.BULLET:
            words = line.lower().split()
            if len(words) >= 2 and words[1] in self.TOOL_VERBS:
                line = "Tool: " + line[2:]  # Remove "• " prefix
                line_type = LineType.TOOL_CALL

        # Handle continuation lines that start with tool verb
        if line_type == LineType.CONTINUATION:
            stripped = line.lstrip().lower()
            if (
                stripped.startswith("used ")
                or stripped.startswith("running ")
                or stripped.startswith("executing ")
            ):
                line = "Tool: " + line.lstrip()[2:]  # Remove "• " prefix
                line_type = LineType.TOOL_CALL

        # Check activity indicators after all transformations
        # Strip bullet/prefix chars so patterns match on the content
        stripped_line = line.strip()
        for prefix in ("•", "·", "▸", "►", "▶", "-", "*"):
            if stripped_line.startswith(prefix):
                stripped_line = stripped_line[len(prefix) :].lstrip()
        # Strip "tool:" prefix only if the content is purely an activity indicator
        # (not a real tool call like "tool: reading files")
        if stripped_line.lower().startswith("tool:"):
            after_tool = stripped_line[5:].strip()
            if after_tool and any(p.match(after_tool) for p in self.ACTIVITY_PATTERNS):
                return "", LineType.EMPTY
        for pattern in self.ACTIVITY_PATTERNS:
            if pattern.match(stripped_line):
                return "", LineType.EMPTY
        for pattern in self.ACTIVITY_PATTERNS:
            if pattern.match(stripped_line):
                return "", LineType.EMPTY
        for pattern in self.ACTIVITY_PATTERNS:
            if pattern.match(stripped_line):
                return "", LineType.EMPTY

        return line, line_type


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

    # Character sets
    _SEPARATOR_CHARS = frozenset("─━═┃│┊┤├┬┴┌┐└┘║╭╮╯╰╱╲╳")
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
        """Remove ANSI escape sequences and filter dangerous characters.

        Uses ANSI_ESCAPE from _config.py for consistent handling.
        Also filters null bytes and other control characters.
        """
        # Remove ANSI escape sequences using unified pattern from _config
        text = ANSI_ESCAPE.sub("", text)
        # Filter null bytes and other dangerous control characters
        text = text.replace("\x00", "")
        return text

    def _classify(self, line: str) -> LineType:
        """Classify a cleaned line."""
        if not line:
            return LineType.EMPTY

        # Check for separator characters only
        if self._SEPARATOR_CHARS.intersection(line):
            return LineType.SEPARATOR

        # Check for continuation (indented with content)
        if line and line[0] in " \t":
            # Whitespace-only indented lines are empty
            if not line.strip():
                return LineType.EMPTY
            return LineType.CONTINUATION

        # Check for bullets
        if line[0] in self._BULLET_CHARS:
            return LineType.BULLET

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
