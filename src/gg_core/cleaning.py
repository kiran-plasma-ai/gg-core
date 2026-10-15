"""Tmux output cleaning for gg-core.

Provides agent-aware cleaning of tmux pane output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from functools import cache

from ._config import ANSI_ESCAPE


class LineType(Enum):
    """Classification of line content."""

    EMPTY = auto()
    SEPARATOR = auto()
    PROMPT_MARKER = auto()  # 💫
    INPUT_MARKER = auto()  # ✨
    TOOL_CALL = auto()
    STATUS_BAR = auto()
    BULLET = auto()
    CONTINUATION = auto()
    CONTENT = auto()


# Shared constants for state detection
# Union of all agent spinners (used for detection, not stripping)
_SPINNER_UNION = (
    "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣷⣯⣟⡿⢿⣻⣽⣾🌑🌒🌓🌔🌕🌖🌗🌘"
    "■⬝⬥◆⬩⬪"  # OpenCode Knight Rider blocks/diamonds
)

# Backward compatibility: exported for gg-channels formatters
TOOL_INDICATORS = (
    "Used Shell",
    "Used WriteFile",
    "Using Shell",
    "Tool:",
    "Running",
    "Executing",
)

# kimi-cli input section header (e.g. "── input ─────────────────")
# Also matches ASCII fallbacks like "-- input" and allows optional leading
# whitespace in case the terminal adds margin.
_INPUT_HEADER_RE = re.compile(r"^\s*[─╌\-]{2,}\s*input\b")


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
    STATUS_PATTERNS: tuple[re.Pattern[str], ...] = ()
    ACTIVITY_PATTERNS: tuple[re.Pattern[str], ...] = ()
    _spinner_table: dict[int, int | None] | None = None

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if cls.SPINNER_CHARS:
            cls._spinner_table = {ord(c): None for c in cls.SPINNER_CHARS}
        else:
            cls._spinner_table = None

    def _strip_spinners(self, line: str) -> str:
        """Remove spinner characters using a pre-built translation table."""
        if self._spinner_table is not None:
            return line.translate(self._spinner_table)
        return line

    def filter_line(self, line: str, line_type: LineType) -> tuple[str, LineType]:
        """Apply agent-specific filtering.

        Returns filtered line and potentially changed line type.
        """
        # Remove spinner characters
        line = self._strip_spinners(line)

        # Check for prompt markers
        if not line.strip():
            return line, LineType.EMPTY

        # Check status patterns
        for pattern in self.STATUS_PATTERNS:
            if pattern.match(line):
                return "", LineType.STATUS_BAR

        # Check activity indicators (e.g. "Thinking..." after spinner strip)
        if self._check_activity(line):
            return "", LineType.EMPTY

        return line, line_type

    def _check_activity(self, line: str) -> bool:
        """Return True if the line is purely an activity/internal indicator."""
        stripped_line = line.strip()
        for prefix in ("•", "·", "▸", "►", "▶", "-", "*"):
            if stripped_line.startswith(prefix):
                stripped_line = stripped_line[len(prefix) :].lstrip()
        # Strip "tool:" prefix only if the content is purely an activity indicator
        # (not a real tool call like "tool: reading files")
        if stripped_line.lower().startswith("tool:"):
            after_tool = stripped_line[5:].strip()
            if after_tool and any(p.match(after_tool) for p in self.ACTIVITY_PATTERNS):
                return True
        return any(p.match(stripped_line) for p in self.ACTIVITY_PATTERNS)


class KimiHandler(AgentHandler):
    """Handler for kimi-cli output."""

    SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣷⣯⣟⡿⢿⣻⣽⣾🌑🌒🌓🌔🌕🌖🌗🌘"
    PROMPT_MARKERS: tuple[str, ...] = ("💫", "$ ")
    STATUS_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^yolo\s+.*", re.IGNORECASE),
        re.compile(r"^plan\s+.*", re.IGNORECASE),
        re.compile(r".*ctrl-[a-z]:.*", re.IGNORECASE),  # ctrl-o:, ctrl-j:, etc.
        re.compile(r".*shift-tab:.*", re.IGNORECASE),
        re.compile(r".*context:\s*\d+\.\d+%.*", re.IGNORECASE),
        re.compile(r"^⚙\s+bash:\s*\d+.*", re.IGNORECASE),
    )
    ACTIVITY_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"^Thinking\.{3,}", re.IGNORECASE),
        re.compile(r"^Working\.{3,}", re.IGNORECASE),
        re.compile(r"^Processing\.{3,}", re.IGNORECASE),
        re.compile(r"^Composing\.{3,}", re.IGNORECASE),
        re.compile(r"^Reading\.{3,}", re.IGNORECASE),
        re.compile(r"^Parsing\.{3,}", re.IGNORECASE),
        re.compile(r"^Analyzing\.{3,}", re.IGNORECASE),
        re.compile(r"^Searching\.{3,}", re.IGNORECASE),
        re.compile(r"^Writing\.{3,}", re.IGNORECASE),
        re.compile(r"^Executing\.{3,}", re.IGNORECASE),
        re.compile(r"^Applying\.{3,}", re.IGNORECASE),
        re.compile(r"^Installing\.{3,}", re.IGNORECASE),
        re.compile(r"^Updating\.{3,}", re.IGNORECASE),
        re.compile(r"^Deleting\.{3,}", re.IGNORECASE),
        re.compile(r"^Moving\.{3,}", re.IGNORECASE),
        re.compile(r"^Copying\.{3,}", re.IGNORECASE),
        re.compile(r"^Side\s+question:.*", re.IGNORECASE),
    )
    TOOL_OUTPUT_PATTERNS: tuple[re.Pattern[str], ...] = (
        # Exit code from shell commands
        re.compile(r"^exit code:\s*\d+.*", re.IGNORECASE),
        # ls output header
        re.compile(r"^total \d+\s*$"),
        # File permissions (ls -l output)
        re.compile(r"^[drwxlst-]{10}\s+\d"),
        # Diff markers --- a/file  +++ b/file
        re.compile(r"^---\s+\S*/\S*"),
        re.compile(r"^\+\+\+\s+\S*/\S*"),
        re.compile(r"^@@ -\d+,?\d* \+\d+,?\d* @@"),
        # Common command output prefixes
        re.compile(r"^stdout:\s*$", re.IGNORECASE),
        re.compile(r"^stderr:\s*$", re.IGNORECASE),
        re.compile(r"^output:\s*$", re.IGNORECASE),
        # Subagent metadata and collapsed tool calls
        re.compile(r"^subagent\s+\w+\s*\(.*\)", re.IGNORECASE),
        re.compile(r"^\d+\s+more\s+tool\s+calls?\s*\.\.\.", re.IGNORECASE),
    )
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

    def _apply_early_filters(
        self,
        line: str,
        stripped: str,
        raw_stripped: str,
        line_type: LineType,
    ) -> tuple[str, LineType] | None:
        """Return filtered result if line should be hidden, else None."""
        # Typing in progress - when 💫 is followed by text (not just spaces)
        # but ✨ is not present (not yet submitted)
        if raw_stripped.startswith("💫") and "✨" not in line and raw_stripped != "💫":
            return "", LineType.EMPTY

        for pattern in self.STATUS_PATTERNS:
            if pattern.match(line):
                return "", LineType.STATUS_BAR

        for pattern in self.TOOL_OUTPUT_PATTERNS:
            if pattern.match(line):
                return "", LineType.STATUS_BAR

        # In-progress tool execution indicators after spinner strip.
        # Require parenthetical to contain a path-like character (/ . _ -)
        # to avoid false-positives on prose like "Using Python (is great)".
        if re.match(
            r"(Using|Running|Executing)\s+\w+\s*\([^)]*[/._-][^)]*\)", stripped
        ):
            return "", LineType.EMPTY

        return None

    # Minimum word count for a bullet line to be considered a tool call
    _MIN_TOOL_CALL_WORDS = 2

    def _apply_transforms(self, line: str, line_type: LineType) -> tuple[str, LineType]:
        """Convert markers and bullets to normalized forms."""
        if "✨" in line:
            line = line.replace("✨", "User:")
            line_type = LineType.INPUT_MARKER

        if line_type == LineType.BULLET:
            words = line.lower().split()
            if len(words) >= self._MIN_TOOL_CALL_WORDS and words[1] in self.TOOL_VERBS:
                line = "Tool: " + line[1:].lstrip()
                line_type = LineType.TOOL_CALL

        if line_type == LineType.CONTINUATION:
            stripped_lower = line.lstrip().lower()
            if any(
                stripped_lower.startswith(v + " ")
                for v in ("used", "running", "executing")
            ):
                line = "Tool: " + line.lstrip()
                line_type = LineType.TOOL_CALL

        return line, line_type

    def filter_line(self, line: str, line_type: LineType) -> tuple[str, LineType]:
        """Apply kimi-specific formatting."""
        raw_stripped = line.strip()
        line = self._strip_spinners(line)
        stripped = line.strip()

        result = self._apply_early_filters(line, stripped, raw_stripped, line_type)
        if result is not None:
            return result

        line, line_type = self._apply_transforms(line, line_type)

        if self._check_activity(line):
            return "", LineType.EMPTY

        return line, line_type


class CoderHandler(AgentHandler):
    """Handler for coder.rs output."""

    SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇"
    PROMPT_MARKERS: tuple[str, ...] = ("coder>", "...>")


class GrokHandler(AgentHandler):
    """Handler for grok output."""

    SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇"
    PROMPT_MARKERS: tuple[str, ...] = ()


class GeminiHandler(AgentHandler):
    """Handler for gemini output."""

    SPINNER_CHARS = ""
    PROMPT_MARKERS: tuple[str, ...] = ("gemini>",)


class OpenCodeHandler(KimiHandler):
    """Handler for opencode output.

    OpenCode uses similar patterns to kimi:
    - Braille spinners (⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏)
    - Tool calls with icons (✱ for glob, $ for bash, etc.)
    - Activity indicators (Thinking..., Working...)

    Key differences from kimi:
    - NO visible prompt marker (like 💫) - uses colored left border instead
    - NO distinct user input marker (like ✨) - user input appears inline
    - Uses Knight Rider style block spinners in addition to braille
    - Tool calls use icons (✱, $, ▣, etc.) instead of bullets (•)

    Note: Because OpenCode lacks a distinct user input marker,
    extract_since_last_input() will return all visible content, not just
    content since the last user message.
    """

    PROMPT_MARKERS: tuple[str, ...] = ()  # OpenCode has no visible prompt marker
    STATUS_PATTERNS: tuple[re.Pattern[str], ...] = (
        # Status bar at bottom: "esc interrupt  tab agents  ctrl+p commands"
        re.compile(r".*esc\s+interrupt.*tab\s+agents.*ctrl\+p\s+commands.*"),
        # Individual keybinding hints (with optional leading spaces)
        # "esc interrupt", "ctrl+p commands"
        re.compile(r"^\s*(esc|ctrl\+[\w+]+)\s+\w+\s*$"),
        re.compile(r"^\s*\w+\s+agents\s*$"),  # "tab agents"
    )

    # OpenCode tool icons
    _TOOL_ICONS: tuple[str, ...] = ("$", "✱", "▣")

    def _convert_tool_icon(
        self, line: str, line_type: LineType
    ) -> tuple[str, LineType]:
        """Convert tool icons ($, ✱, ▣) to Tool: prefix."""
        stripped = line.strip()
        if line_type not in (LineType.CONTENT, LineType.CONTINUATION):
            return line, line_type
        for icon in self._TOOL_ICONS:
            if stripped.startswith(icon):
                return "Tool: " + stripped[len(icon) :].strip(), LineType.TOOL_CALL
        return line, line_type

    def filter_line(self, line: str, line_type: LineType) -> tuple[str, LineType]:
        """Apply opencode-specific formatting.

        Unlike kimi, OpenCode has no visible prompt marker. The prompt is
        indicated by a colored left border (┃) which is handled as a separator.
        """
        # If the line starts with a border but contains a tool icon after it,
        # strip the border and process it as a tool call.
        stripped = line.strip()
        if stripped.startswith("┃"):
            after_border = stripped[1:].strip()
            if after_border and after_border[0] in self._TOOL_ICONS:
                line = after_border
                line_type = LineType.CONTENT
            else:
                return "", LineType.SEPARATOR

        # Use parent class for spinner stripping, tool handling, and activity filtering
        line, line_type = super().filter_line(line, line_type)

        # Convert tool icons to Tool: prefix
        line, line_type = self._convert_tool_icon(line, line_type)

        return line, line_type


class OmpHandler(KimiHandler):
    """Handler for oh-my-pi (omp) output.

    omp renders a full-screen TUI: a composer/status line pinned at the bottom
    (``π > <model> > <dir> > $0.00 ↓ ▶─0.8%──…──┃───1M─``), a startup
    logo/tip block, tool calls inside rounded boxes (``│ $ ls -la``), and
    braille/round spinners.

    omp has no visible user-input marker (submitted messages render as a
    background-tinted bubble), so precise response text should be read from
    the omp session JSONL via ``core/omp.py``. The cleaner here only removes
    TUI chrome for ``gg logs``.
    """

    PROMPT_MARKERS: tuple[str, ...] = ()  # omp has no prompt marker glyph

    STATUS_PATTERNS: tuple[re.Pattern[str], ...] = (
        # Composer/status line: "… > $0.00 ↓ ▶─0.8%──…────┃───1M─"
        re.compile(r".*\$\d+\.\d{2}\s*↓"),
        # Composer gutter and hint row
        re.compile(r"\s*╰─"),
        re.compile(r".*⇧⇥ to change thinking effort"),
        # Startup banner: tip line, logo art, version row
        re.compile(r"\s*Tip:\s"),
        re.compile(r"\s*[█▒▓▀▄▐▌]+"),
        # Tool box rules: ╭──…──╮ / ├─── Output ───┤ / ╰──…──╯
        re.compile(r"\s*[╭├╰]─.*[╮┤╯]\s*$"),
    )

    ACTIVITY_PATTERNS: tuple[re.Pattern[str], ...] = (
        # Running-tool status line: "⎋ Listing current directory files"
        re.compile(r"⎋\s"),
        # Collapsed tool summary: "📁 LS: List files in current directory"
        re.compile(r"(?:📁|⚙|✱|▣|🔧|🔍|🧠|🌐)\s+\S+:\s"),
    )

    TOOL_OUTPUT_PATTERNS: tuple[re.Pattern[str], ...] = (
        # Tool box metadata row: "⟦Wall: 0.01s | Timeout: 30s⟧"
        re.compile(r"^⟦Wall:.*⟧$"),
    ) + KimiHandler.TOOL_OUTPUT_PATTERNS

    _BOX_PREFIX_RE = re.compile(r"^\s*│\s?")
    _BOX_TOOL_RE = re.compile(r"^\s*│\s*([$✱▣])\s+(.*)$")
    _BOX_TRAILING_RE = re.compile(r"\s*│\s*$")

    def _unwrap_tool_box(self, line: str, line_type: LineType) -> tuple[str, LineType]:
        """Convert ``│ $ cmd`` rows to tool calls and strip ``│`` borders."""
        match = self._BOX_TOOL_RE.match(line)
        if match:
            body = self._BOX_TRAILING_RE.sub("", match.group(2))
            return f"Tool: {match.group(1)} {body.strip()}", LineType.TOOL_CALL

        prefix = self._BOX_PREFIX_RE.match(line)
        if prefix:
            body = self._BOX_TRAILING_RE.sub("", line[prefix.end() :])
            return body, LineType.CONTENT

        return line, line_type

    def _apply_transforms(self, line: str, line_type: LineType) -> tuple[str, LineType]:
        """Skip Kimi's continuation-to-tool-call rewrite.

        omp indents every transcript line by one space, so all prose classifies
        as CONTINUATION; Kimi's rewrite would relabel prose starting with
        "Running/Executing/Used ..." as tool calls. omp's tool calls are read
        from the tool box (``│ $ cmd``) instead.
        """
        return line, line_type

    def filter_line(self, line: str, line_type: LineType) -> tuple[str, LineType]:
        """Apply omp-specific formatting."""
        line, line_type = self._unwrap_tool_box(line, line_type)
        return super().filter_line(line, line_type)


class GenericHandler(AgentHandler):
    """Handler for unknown agents."""

    pass


# Handler registry
_HANDLERS: dict[str, type[AgentHandler]] = {
    "omp": OmpHandler,
    "kimi": KimiHandler,
    "coder": CoderHandler,
    "grok": GrokHandler,
    "minimax": CoderHandler,  # Same as coder
    "gemini": GeminiHandler,
    "opencode": OpenCodeHandler,
    "custom": GenericHandler,
}


@cache
def get_handler(agent: str) -> AgentHandler:
    """Get handler for agent type."""
    handler_class = _HANDLERS.get(agent, GenericHandler)
    return handler_class()


# Module-level cleaner cache for convenience functions
@cache
def _get_cleaner(agent: str) -> TmuxCleaner:
    """Get cached TmuxCleaner instance (thread-safe via @cache)."""
    return TmuxCleaner(agent)


class _FilterState:
    """Mutable state object for clean_batch's typing-region tracker.

    Using a dedicated class makes the state machine explicit and avoids
    juggling multiple bare boolean variables.
    """

    __slots__ = ("active", "from_typing")

    def __init__(self) -> None:
        #: True while we are inside a user-input region.
        self.active = False
        #: True when the region was started by a *typing* trigger (prompt
        #: marker or input header) rather than by a submitted INPUT_MARKER.
        #: In typing mode we are more aggressive about blanking lines.
        self.from_typing = False


class TmuxCleaner:
    """Tmux output cleaner with agent-specific handling.

    The core challenge this class solves is preventing user typing text from
    leaking into downstream consumers (Telegram, voice).  A tmux capture
    contains everything visible in the pane — agent output, prompts, status
    bars, and the user's live typing — all mixed together.

    Strategy
    --------
    1. Per-line classification (INPUT_MARKER, PROMPT_MARKER, CONTENT, etc.)
       and agent-specific filtering (spinners, activity indicators, status
       bars) via ``AgentHandler`` subclasses.

    2. Stateful batch processing (``clean_batch``) that tracks whether we are
       inside a "user input region".  A region starts when we see:
       - A submitted message (✨ INPUT_MARKER)
       - A typing prompt (💫, $ , coder>, etc.)
       - An input-section header (── input ──)

       Once inside a region, all CONTENT/CONTINUATION lines are blanked until
       a clear boundary (empty line, tool call, separator, etc.) breaks the
       state.  In *typing* mode (prompt or header) we are even more
       aggressive: bullets, separators, and even a typed ✨ character are
       blanked, because the user may paste arbitrary text.

    3. Post-processing in ``extract_agent_output`` removes lines after the
       last INPUT_MARKER and applies a secondary safety net for input headers.
    """

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
        """Clean multiple lines with stateful typing-region tracking.

        See class docstring for the high-level strategy.
        """
        results: list[CleanedLine] = []
        state = _FilterState()
        for line in lines:
            cleaned = self.clean_line(line)
            ansi_stripped = self._strip_ansi(line)
            original_type = self._classify(ansi_stripped)

            cleaned, state = self._apply_filter_state(
                cleaned=cleaned,
                raw_line=line,
                ansi_stripped=ansi_stripped,
                original_type=original_type,
                state=state,
            )
            results.append(cleaned)
        return results

    def _apply_filter_state(
        self,
        *,
        cleaned: CleanedLine,
        raw_line: str,
        ansi_stripped: str,
        original_type: LineType,
        state: _FilterState,
    ) -> tuple[CleanedLine, _FilterState]:
        """Apply one step of the filter-state machine.

        Returns the (possibly modified) cleaned line and the updated state.
        """
        # ---- 1. Detect triggers ------------------------------------------------
        is_typing = self._is_typing_line(ansi_stripped)
        is_input_header = _INPUT_HEADER_RE.match(ansi_stripped) is not None

        # ---- 2. Blank lines inside an active region ----------------------------
        # Determine which line types should be blanked while the region is
        # active.  In typing mode we blank almost everything; after a
        # submitted INPUT_MARKER we only blank CONTENT/CONTINUATION.
        blankable_types = {LineType.CONTENT, LineType.CONTINUATION}
        if state.from_typing:
            blankable_types |= {
                LineType.BULLET,
                LineType.SEPARATOR,
                LineType.INPUT_MARKER,
            }

        was_blanked = False
        if state.active and cleaned.cleaned and cleaned.line_type in blankable_types:
            cleaned = CleanedLine(
                original=cleaned.original,
                cleaned="",
                line_type=LineType.EMPTY,
                agent=cleaned.agent,
            )
            was_blanked = True

        # ---- 3. State transitions ----------------------------------------------
        if is_typing or original_type == LineType.INPUT_MARKER or is_input_header:
            # Start (or continue) a region.
            state.active = True
            # Preserve typing mode when already active; a typed ✨ character
            # must not flip us back to "submitted message" mode.
            if not state.from_typing:
                state.from_typing = is_typing or is_input_header
        elif was_blanked:
            # We just blanked a line; keep the region alive.
            pass
        elif not state.from_typing and (
            cleaned.line_type != original_type
            and original_type in (LineType.CONTENT, LineType.CONTINUATION)
        ):
            # Agent output pattern broke the region (e.g. "Thinking..." was
            # filtered to EMPTY by the handler).  Only break when we are in
            # "submitted message" mode, not typing mode.
            state.active = False
            state.from_typing = False
        elif not state.from_typing and (
            original_type not in (LineType.CONTENT, LineType.CONTINUATION)
            and not ansi_stripped.isspace()
        ):
            # Natural boundary (SEPARATOR, BULLET, TOOL_CALL, etc.) breaks
            # the region after a submitted message.  In typing mode we stay
            # active through everything.
            state.active = False
            state.from_typing = False

        return cleaned, state

    def _is_typing_line(self, ansi_stripped: str) -> bool:
        """Return True if the raw line indicates typing at a prompt.

        Prompt markers with trailing spaces (e.g. '$ ') are preserved by
        using ``lstrip()`` instead of ``strip()``.
        """
        lstrip_ansi = ansi_stripped.lstrip()
        for marker in self._handler.PROMPT_MARKERS:
            if lstrip_ansi.startswith(marker) and "✨" not in ansi_stripped:
                return True
        return False

    def get_visible(self, lines: list[str]) -> list[str]:
        """Get visible lines only."""
        cleaned = self.clean_batch(lines)
        return [line.cleaned for line in cleaned if line.is_visible and line.cleaned]

    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape sequences and filter null bytes.

        Uses ANSI_ESCAPE from _config.py for consistent handling.
        """
        # Remove ANSI escape sequences using unified pattern from _config
        text = ANSI_ESCAPE.sub("", text)
        # Filter null bytes
        text = text.replace("\x00", "")
        return text

    # Ratio threshold for classifying a line as a separator
    _SEPARATOR_RATIO = 0.5

    def _classify(self, line: str) -> LineType:
        """Classify a cleaned line."""
        result = LineType.CONTENT
        stripped = line.strip()

        if not stripped:
            result = LineType.EMPTY
        else:
            # Check for separator characters: classify as SEPARATOR only if
            # the line is primarily composed of separator characters. This
            # avoids hiding normal content that happens to contain a border char.
            sep_count = sum(1 for c in stripped if c in self._SEPARATOR_CHARS)
            if sep_count / len(stripped) >= self._SEPARATOR_RATIO:
                result = LineType.SEPARATOR
            # Check for continuation (indented with content)
            elif line[0] in " \t":
                result = LineType.CONTINUATION
            # Check for bullets
            elif line[0] in self._BULLET_CHARS:
                result = LineType.BULLET
            # Check for prompt markers
            else:
                for marker in self._handler.PROMPT_MARKERS:
                    if line.startswith(marker):
                        result = LineType.PROMPT_MARKER
                        break
                else:
                    # Check for input marker
                    if "✨" in line:
                        result = LineType.INPUT_MARKER

        return result


def clean_logs(lines: list[str], agent: str = "generic") -> list[CleanedLine]:
    """Clean tmux log lines.

    Args:
        lines: Raw lines from tmux pane
        agent: Agent type (kimi, coder, etc.)

    Returns:
        List of CleanedLine objects
    """
    return _get_cleaner(agent).clean_batch(lines)


def get_visible_logs(lines: list[str], agent: str = "generic") -> list[str]:
    """Get visible cleaned log lines.

    Args:
        lines: Raw lines from tmux pane
        agent: Agent type (kimi, coder, etc.)

    Returns:
        List of visible cleaned lines
    """
    return _get_cleaner(agent).get_visible(lines)
