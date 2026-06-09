#!/usr/bin/env python3
"""Debug pipeline for gg-core cleaning and extraction logic.

Run locally to inspect what the cleaning pipeline does to tmux output
without going through Telegram.

Usage:
    uv run python scripts/debug_pipeline.py <project> [lines]

Example:
    uv run python scripts/debug_pipeline.py gg-manager 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add src to path so we can import gg_core
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gg_core.cleaning import CleanedLine, LineType, TmuxCleaner
from gg_core.core.extraction import extract_agent_output, extract_since_last_input
from gg_core.core.tmux import capture_pane, get_tmux


def _line_type_emoji(line_type: LineType) -> str:
    """Return a short emoji indicator for a line type."""
    return {
        LineType.EMPTY: "⬜",
        LineType.SEPARATOR: "─",
        LineType.PROMPT_MARKER: "💫",
        LineType.INPUT_MARKER: "✨",
        LineType.TOOL_CALL: "🔧",
        LineType.STATUS_BAR: "📊",
        LineType.BULLET: "•",
        LineType.CONTINUATION: "↳",
        LineType.CONTENT: "📝",
    }.get(line_type, "❓")


def _print_section(title: str, lines: list[str], max_lines: int = 100) -> None:
    """Print a section with a header and optional truncation."""
    print(f"\n{'=' * 60}")
    print(f" {title} ({len(lines)} lines)")
    print("=" * 60)
    for i, line in enumerate(lines[:max_lines], 1):
        print(f"  {i:3d}: {line}")
    if len(lines) > max_lines:
        print(f"  ... ({len(lines) - max_lines} more lines)")


def _print_cleaned(cleaned: list[CleanedLine], max_lines: int = 100) -> None:
    """Print cleaned lines with their types and visibility."""
    print(f"\n{'=' * 60}")
    print(f" Cleaned Output ({len(cleaned)} lines)")
    print("=" * 60)
    print(f"  {'#':>3} {'Vis':>3} {'Type':<18} Cleaned")
    print(f"  {'-' * 50}")
    for i, cl in enumerate(cleaned[:max_lines], 1):
        vis = "✓" if cl.is_visible else "✗"
        emoji = _line_type_emoji(cl.line_type)
        cleaned_preview = cl.cleaned[:70] if cl.cleaned else "(empty)"
        print(f"  {i:3d} {vis:>3} {emoji} {cl.line_type.name:<14} {cleaned_preview}")
    if len(cleaned) > max_lines:
        print(f"  ... ({len(cleaned) - max_lines} more lines)")


def _print_extraction(
    extracted: list[CleanedLine], max_lines: int = 100
) -> None:
    """Print extracted lines after last input marker."""
    print(f"\n{'=' * 60}")
    print(f" Extracted (since last input) ({len(extracted)} lines)")
    print("=" * 60)
    for i, cl in enumerate(extracted[:max_lines], 1):
        vis = "✓" if cl.is_visible else "✗"
        print(f"  {i:3d} {vis} [{cl.line_type.name}] {cl.cleaned[:70]}")
    if len(extracted) > max_lines:
        print(f"  ... ({len(extracted) - max_lines} more lines)")


def _print_since_last_input(lines: list[str], max_lines: int = 100) -> None:
    """Print lines from extract_since_last_input (strings)."""
    print(f"\n{'=' * 60}")
    print(f" Since Last Input (strings) ({len(lines)} lines)")
    print("=" * 60)
    for i, line in enumerate(lines[:max_lines], 1):
        print(f"  {i:3d}: {line}")
    if len(lines) > max_lines:
        print(f"  ... ({len(lines) - max_lines} more lines)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Debug gg-core cleaning and extraction pipeline."
    )
    parser.add_argument("project", help="Tmux session/project name")
    parser.add_argument(
        "lines", nargs="?", type=int, default=50, help="Lines to capture (default: 50)"
    )
    parser.add_argument(
        "--agent", default="kimi", help="Agent type for cleaning (default: kimi)"
    )
    parser.add_argument(
        "--save", metavar="PATH", help="Save full output to file"
    )
    parser.add_argument(
        "--all", action="store_true", help="Show all lines (no truncation)"
    )
    args = parser.parse_args()

    # Check session exists
    tmux = get_tmux()
    if not tmux.has_session(args.project):
        print(f"ERROR: Session '{args.project}' not found.")
        print(f"Start it with: gg start {args.project}")
        return 1

    # Capture raw output
    raw_lines = capture_pane(args.project, lines=args.lines)
    if not raw_lines:
        print(f"ERROR: No output captured from '{args.project}'.")
        return 1

    # Run pipeline
    cleaner = TmuxCleaner(args.agent)
    cleaned = cleaner.clean_batch(raw_lines)
    extracted = extract_agent_output(raw_lines, agent=args.agent)
    since_last = extract_since_last_input(raw_lines, agent=args.agent)

    # Print results
    max_lines = 999999 if args.all else 100

    _print_section("Raw Tmux Output", raw_lines, max_lines)
    _print_cleaned(cleaned, max_lines)
    _print_extraction(extracted, max_lines)
    _print_since_last_input(since_last, max_lines)

    # Save to file if requested
    if args.save:
        path = Path(args.save)
        with open(path, "w") as f:
            f.write("RAW TMUX OUTPUT\n")
            f.write("=" * 60 + "\n")
            for line in raw_lines:
                f.write(line + "\n")
            f.write("\n\nCLEANED OUTPUT\n")
            f.write("=" * 60 + "\n")
            for cl in cleaned:
                vis = "V" if cl.is_visible else "H"
                f.write(f"[{vis}] [{cl.line_type.name}] {cl.cleaned}\n")
            f.write("\n\nEXTRACTED (since last input)\n")
            f.write("=" * 60 + "\n")
            for line in since_last:
                f.write(line + "\n")
        print(f"\n💾 Full output saved to: {path}")

    # Summary stats
    visible = sum(1 for cl in cleaned if cl.is_visible)
    print(f"\n{'=' * 60}")
    print(" Summary")
    print("=" * 60)
    print(f"  Raw lines captured:       {len(raw_lines)}")
    print(f"  Cleaned lines:            {len(cleaned)}")
    print(f"  Visible after cleaning:   {visible}")
    print(f"  Hidden after cleaning:    {len(cleaned) - visible}")
    print(f"  Extracted (since input):  {len(extracted)}")
    print(f"  Since-last-input strings: {len(since_last)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
