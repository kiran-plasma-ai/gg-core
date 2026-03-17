"""Validation utilities."""

from __future__ import annotations

import re

from .._config import MAX_PROJECT_NAME_LENGTH, VALID_PROJECT_PATTERN
from .._errors import ValidationError
from .._types import VALID_AGENTS


def validate_project(name: str) -> None:
    """Validate a project name.

    Args:
        name: Project name to validate

    Raises:
        ValidationError: If name is invalid
    """
    if not name:
        raise ValidationError("Project name cannot be empty")

    if len(name) > MAX_PROJECT_NAME_LENGTH:
        raise ValidationError(f"Project name too long (max {MAX_PROJECT_NAME_LENGTH})")

    if not re.match(VALID_PROJECT_PATTERN, name):
        raise ValidationError(
            f"Invalid project name: {name!r}. "
            "Use only letters, numbers, underscores, and hyphens. "
            "Must start with a letter or number."
        )


def validate_agent(agent: str) -> str:
    """Validate and normalize agent name.

    Args:
        agent: Agent name to validate

    Returns:
        Normalized agent name

    Raises:
        ValidationError: If agent is unknown
    """
    agent = agent.lower().strip()

    if agent not in VALID_AGENTS:
        raise ValidationError(
            f"Unknown agent: {agent!r}. Valid agents: {', '.join(sorted(VALID_AGENTS))}"
        )

    return agent
