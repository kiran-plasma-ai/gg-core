#!/usr/bin/env python3
"""
Registry Generator

Generates REGISTRY.md from gg-core project structure.
Provides a complete overview of modules, CLI commands, and architecture.

Usage:
    python scripts/generate-registry.py [--verbose] [--check]

Options:
    --verbose    Show detailed output
    --check      Run validation checks after generation
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Add src to path for imports
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))


def get_modules() -> dict[str, ModuleInfo]:
    """Collect module information from the source tree."""
    modules: dict[str, ModuleInfo] = {}
    src_dir = ROOT_DIR / "src" / "gg_core"

    # Core modules (top-level _*.py)
    for mod in src_dir.glob("_*.py"):
        name = mod.stem
        # Skip __init__ files entirely
        if name == "__init__" or name.startswith("__"):
            continue
        if name.startswith("_"):
            name = name[1:]  # Remove leading underscore
        if not name:
            continue
        modules[name] = ModuleInfo(
            name=name,
            path=mod.relative_to(ROOT_DIR),
            purpose=get_module_purpose(mod),
            layer="Core",
        )

    # Also include top-level modules without underscore prefix (e.g., cleaning.py)
    for mod in src_dir.glob("*.py"):
        name = mod.stem
        if name == "__init__" or name.startswith("__"):
            continue
        if name.startswith("_"):
            continue  # Skip _*.py files (already handled)
        if name in modules:
            continue  # Already added
        modules[name] = ModuleInfo(
            name=name,
            path=mod.relative_to(ROOT_DIR),
            purpose=get_module_purpose(mod),
            layer="Core",
        )

    # Core submodules
    core_dir = src_dir / "core"
    if core_dir.exists():
        for mod in core_dir.glob("*.py"):
            if mod.stem == "__init__":
                continue
            modules[mod.stem] = ModuleInfo(
                name=mod.stem,
                path=mod.relative_to(ROOT_DIR),
                purpose=get_module_purpose(mod),
                layer="Core",
            )

    # CLI modules
    cli_dir = src_dir / "cli"
    if cli_dir.exists():
        for mod in cli_dir.glob("*.py"):
            if mod.stem == "__init__":
                continue
            modules[f"cli_{mod.stem}"] = ModuleInfo(
                name=mod.stem,
                path=mod.relative_to(ROOT_DIR),
                purpose=get_module_purpose(mod),
                layer="CLI",
            )

    return modules


def get_module_purpose(path: Path) -> str:
    """Extract purpose from module docstring."""
    try:
        content = path.read_text()
        # Find first docstring
        if '"""' in content:
            start = content.index('"""') + 3
            end = content.index('"""', start)
            doc = content[start:end].strip()
            # Get first line
            first_line = doc.split("\n")[0].strip()
            # Truncate if too long
            if len(first_line) > 80:
                return first_line[:77] + "..."
            return first_line
    except (ValueError, OSError):
        pass
    return f"{path.stem} module"


def get_cli_commands() -> list[CommandInfo]:
    """Extract CLI commands from parser.py."""
    parser_path = ROOT_DIR / "src" / "gg_core" / "cli" / "parser.py"
    commands: list[CommandInfo] = []

    try:
        content = parser_path.read_text()
        # Find add_parser calls - handle both inline and variable patterns
        # Pattern 1: subparsers.add_parser("name", help="desc")
        # Pattern 2: name_parser = subparsers.add_parser("name", help="desc")
        import re

        # Match both patterns
        pattern = r'add_parser\s*\(\s*["\']([^"\']+)["\']\s*,\s*help\s*=\s*["\']([^"\']+)["\']'
        matches = re.findall(pattern, content)

        for cmd, desc in matches:
            commands.append(CommandInfo(name=cmd, description=desc))

    except (ValueError, OSError):
        pass

    return commands


def get_agents() -> dict[str, str]:
    """Get configured agents from _config.py."""
    # Read directly from the file to avoid import issues
    config_path = ROOT_DIR / "src" / "gg_core" / "_config.py"
    agents: dict[str, str] = {}
    try:
        content = config_path.read_text()
        # Find DEFAULT_AGENTS dict - simple line by line parsing
        in_agents = False
        for line in content.split("\n"):
            if "DEFAULT_AGENTS" in line and "=" in line:
                in_agents = True
                continue
            if in_agents:
                if line.strip() == "}":
                    break
                if '"' in line and ":" in line:
                    # Extract key
                    key_match = re.search(r'"([^"]+)"\s*:', line)
                    if key_match:
                        key = key_match.group(1)
                        # Extract value - everything between : and comma or end of line
                        val_part = line.split(":", 1)[1].strip()
                        # Remove trailing comma and anything after # (comments)
                        if "#" in val_part:
                            val_part = val_part.split("#")[0].strip()
                        val = val_part.rstrip(",").strip().strip('"').rstrip('"')
                        if val:
                            agents[key] = val
    except (ValueError, OSError):
        pass
    return agents


def generate_registry() -> str:
    """Generate the registry markdown content."""
    modules = get_modules()
    commands = get_cli_commands()
    agents = get_agents()

    output = []
    output.append("# gg-core Registry\n")
    output.append("\n")
    output.append(
        "Complete architecture overview of gg-core - a minimal Python library for tmux-based AI agent session management.\n"
    )
    output.append("\n")
    output.append(
        "> **AGENT INSTRUCTION**: When working on gg-core, prefer using the core library functions (start_session, send_command, etc.) over CLI commands for programmatic access. Follow the module structure documented below.\n"
    )
    output.append("\n")

    # Layer Architecture
    output.append("## Module Architecture\n")
    output.append("\n")
    output.append("| Module | Layer | Purpose |\n")
    output.append("|--------|-------|--------|\n")

    layers = {"Core": [], "CLI": []}
    for name, mod in sorted(modules.items()):
        layers[mod.layer].append((name, mod))

    for _layer, mods in layers.items():
        for _, mod in mods:
            output.append(f"| {mod.name} | {mod.layer} | {mod.purpose} |\n")

    output.append("\n")

    # CLI Commands
    output.append("## CLI Commands\n")
    output.append("\n")
    output.append("| Command | Description |\n")
    output.append("|---------|-------------|\n")

    for cmd in commands:
        output.append(f"| `{cmd.name}` | {cmd.description} |\n")

    output.append("\n")

    # Agents
    output.append("## Supported Agents\n")
    output.append("\n")
    output.append("| Agent | Default Command |\n")
    output.append("|-------|----------------|\n")

    for agent, cmd in agents.items():
        output.append(f"| {agent} | `{cmd}` |\n")

    output.append("\n")

    # Dependencies
    output.append("## Dependencies\n")
    output.append("\n")
    output.append("```\n")

    # Read pyproject.toml for deps
    pyproject = ROOT_DIR / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        in_deps = False
        for line in content.split("\n"):
            if "dependencies" in line and "[" in line:
                in_deps = True
                continue
            if in_deps:
                if line.strip() == "]":
                    break
                if '"' in line:
                    dep = line.strip().strip('",')
                    output.append(f"gg-core: {dep}\n")

    output.append("```\n")
    output.append("\n")

    # File Structure
    output.append("## File Structure\n")
    output.append("\n")
    output.append("```\n")
    output.append("gg-core/\n")

    # Walk src directory
    src_dir = ROOT_DIR / "src" / "gg_core"
    dirs_shown: set[str] = set()

    for path in sorted(src_dir.rglob("*.py")):
        rel = path.relative_to(src_dir)
        parts = rel.parts
        if parts[-1] == "__init__.py":
            continue  # Skip __init__ files

        # Show directory when first encountered
        for i in range(len(parts) - 1):
            dir_name = parts[i]
            if dir_name not in dirs_shown:
                output.append(f"  {dir_name}/\n")
                dirs_shown.add(dir_name)

        indent = "  " * len(parts)
        output.append(f"{indent}{parts[-1]}\n")

    output.append("```\n")
    output.append("\n")

    # Test Coverage
    output.append("## Test Coverage\n")
    output.append("\n")
    output.append("| Module | Tests |\n")
    output.append("|--------|-------|\n")

    tests_dir = ROOT_DIR / "tests"
    for test_file in sorted(tests_dir.glob("test_*.py")):
        mod_name = test_file.stem.replace("test_", "")
        # Count tests
        content = test_file.read_text()
        test_count = content.count("def test_")
        output.append(f"| {mod_name} | {test_count} tests |\n")

    output.append("\n")

    # Footer
    output.append("---\n")
    output.append("\n")
    output.append("*Auto-generated by scripts/generate-registry.py*\n")

    return "".join(output)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate gg-core registry")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show detailed output"
    )
    parser.add_argument(
        "-c", "--check", action="store_true", help="Run validation checks"
    )
    args = parser.parse_args()

    if args.verbose:
        print("Generating gg-core registry...")

    try:
        content = generate_registry()

        # Write to file
        output_path = ROOT_DIR / "REGISTRY.md"
        output_path.write_text(content)

        print(f"Registry generated at {output_path}")

        if args.verbose:
            # Count modules
            modules = get_modules()
            commands = get_cli_commands()
            agents = get_agents()

            print(f"  Found {len(modules)} modules")
            print(f"  Found {len(commands)} CLI commands")
            print(f"  Found {len(agents)} agents")

        if args.check:
            print("Running validation checks...")
            # Basic validation
            modules = get_modules()
            commands = get_cli_commands()

            if not modules:
                print("ERROR: No modules found")
                return 1

            if not commands:
                print("ERROR: No CLI commands found")
                return 1

            print("Validation passed!")

        return 0

    except Exception as e:
        print(f"ERROR: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


# Data structures
class ModuleInfo:
    def __init__(self, name: str, path: Path, purpose: str, layer: str):
        self.name = name
        self.path = path
        self.purpose = purpose
        self.layer = layer


class CommandInfo:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description


if __name__ == "__main__":
    sys.exit(main())
