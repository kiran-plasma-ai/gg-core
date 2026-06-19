"""Project status, discovery, and orchestration helpers.

High-level utilities for consumers that need to monitor or orchestrate
multiple gg-core sessions (e.g. a "hand" / puppeteer layer).  These helpers
are intentionally thin wrappers around existing gg-core primitives so they
can be added without changing lower-level behavior.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .._errors import TmuxError, ValidationError
from .._types import AgentState, ProjectStatus
from .extraction import get_latest_response
from .session import detect_state, get_session_info
from .validation import infer_agent, validate_project
from .wire import find_kimi_wire_path

logger = logging.getLogger(__name__)


def get_project_status(
    project: str,
    *,
    agent: str | None = None,
    include_response: bool = True,
) -> ProjectStatus:
    """Return a status snapshot for a single project.

    Args:
        project: Project name.
        agent: Agent type override.  If None, inferred from the running session.
        include_response: Whether to fetch the latest agent response.  Setting
            this to False avoids blocking on wire/tmux reads when only state is
            needed.

    Returns:
        ProjectStatus dataclass with current state, latest response, and paths.

    Raises:
        ValidationError: If the project name is invalid.
    """
    validate_project(project)

    info = get_session_info(project)
    resolved_agent = agent or infer_agent(project)

    state = detect_state(project) if info.exists else AgentState.UNKNOWN

    latest_response: list[str] = []
    if include_response and info.exists:
        try:
            latest_response = get_latest_response(project, resolved_agent)
        except (TmuxError, OSError) as e:
            # Reading the response is best-effort for status snapshots.
            # Log the specific external failure and continue so the caller
            # still gets session state and metadata.
            logger.warning(
                f"Failed to read latest response for {project}: {e}",
                extra={"project": project, "agent": resolved_agent},
            )

    wire_path = find_kimi_wire_path(project)

    return ProjectStatus(
        name=project,
        exists=info.exists,
        active=info.active,
        state=state,
        agent=resolved_agent,
        latest_response=latest_response,
        log_path=info.log_path,
        log_size=info.log_size,
        wire_path=wire_path,
    )


def get_projects_status(
    projects: list[str],
    *,
    include_response: bool = True,
) -> list[ProjectStatus]:
    """Return status snapshots for multiple projects.

    Args:
        projects: List of project names to monitor.
        include_response: Whether to fetch latest responses for each project.

    Returns:
        List of ProjectStatus, one per requested project.  Invalid project names
        are skipped and logged instead of raising, so the caller gets as much
        data as possible.
    """
    results: list[ProjectStatus] = []
    for project in projects:
        try:
            results.append(
                get_project_status(project, include_response=include_response)
            )
        except ValidationError as e:
            logger.warning(f"Skipping invalid project name {project!r}: {e}")
        except (TmuxError, OSError) as e:
            logger.warning(
                f"Skipping status for {project}: {e}", extra={"project": project}
            )
    return results


def wait_for_state(
    project: str,
    state: AgentState,
    *,
    timeout: float | None = None,
    interval: float = 1.0,
) -> bool:
    """Block until a project reaches the requested state.

    Args:
        project: Project name.
        state: Target state (IDLE, WORKING, UNKNOWN).
        timeout: Maximum seconds to wait.  None means wait indefinitely.
        interval: Seconds between checks.

    Returns:
        True if the target state was reached, False if the timeout elapsed.

    Raises:
        ValidationError: If the project name is invalid.
    """
    validate_project(project)

    if interval <= 0:
        raise ValueError(f"interval must be positive, got {interval}")
    if timeout is not None and timeout < 0:
        raise ValueError(f"timeout must be non-negative, got {timeout}")

    start = time.monotonic()
    while True:
        current = detect_state(project)
        if current == state:
            return True

        if timeout is not None and (time.monotonic() - start) >= timeout:
            return False

        time.sleep(interval)


def discover_projects(
    base_dir: Path | str | None = None,
    *,
    marker: str | None = None,
) -> list[str]:
    """Discover project directories that look like gg-core workspaces.

    A directory is considered a project if it is a direct child of ``base_dir``,
    is not hidden, and is non-empty.  When ``marker`` is provided, the directory
    must also contain that path (typically a file like ``.git`` or
    ``pyproject.toml``).  This avoids returning every non-empty directory under
    ``base_dir``.

    Args:
        base_dir: Directory to scan.  Defaults to the user's home directory.
        marker: Optional relative path that discovered directories must contain.

    Returns:
        Sorted list of project names (directory basenames).
    """
    base_dir = Path.home() if base_dir is None else Path(base_dir)

    if not base_dir.is_dir():
        logger.warning(f" discover_projects: {base_dir} is not a directory")
        return []

    projects: list[str] = []
    for entry in base_dir.iterdir():
        if entry.is_dir() and not entry.name.startswith("."):
            try:
                if not any(entry.iterdir()):
                    continue
                if marker is not None and not (entry / marker).exists():
                    continue
                projects.append(entry.name)
            except OSError:
                continue

    projects.sort()
    return projects
