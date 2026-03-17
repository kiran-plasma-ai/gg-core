"""Session lifecycle management.

Handles start/stop of agent sessions via tmux + systemd.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

from .._config import (
    TIMEOUT_DEFAULT,
    TIMEOUT_SYSTEMD,
    get_agent_command,
    LOG_DIR,
    SYSTEMD_SERVICE_TEMPLATE,
)
from .._errors import SessionError, SessionExists, SessionNotFound
from .tmux import get_tmux
from .validation import validate_agent, validate_project

logger = logging.getLogger(__name__)


def run_cmd(
    cmd: list[str],
    timeout: int = TIMEOUT_DEFAULT,
    check: bool = False,
) -> tuple[bool, str, str]:
    """Run a command.

    Args:
        cmd: Command as list
        timeout: Timeout in seconds
        check: Raise on non-zero exit

    Returns:
        (success, stdout, stderr)
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        success = result.returncode == 0

        if check and not success:
            raise SessionError(
                f"Command failed: {' '.join(cmd)}\nstderr: {result.stderr}"
            )

        return success, result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out: {' '.join(cmd)}")
        return False, "", "Timeout"
    except FileNotFoundError:
        return False, "", f"Command not found: {cmd[0]}"


def wait_for(condition, timeout: float = 10.0, interval: float = 0.5) -> bool:
    """Wait for condition to become true."""
    start = time.time()
    while time.time() - start < timeout:
        if condition():
            return True
        time.sleep(interval)
    return False


# =============================================================================
# Session Operations
# =============================================================================


def start_session(
    project: str,
    agent: str = "kimi",
    *,
    yolo: bool = False,
) -> None:
    """Start a new session.

    Args:
        project: Project name
        agent: Agent to use
        yolo: Enable YOLO mode (auto-approval)

    Raises:
        ValidationError: If project or agent is invalid
        SessionExists: If session already running
        SessionError: If start fails
    """
    validate_project(project)
    agent = validate_agent(agent)

    tmux = get_tmux()

    if tmux.has_session(project):
        raise SessionExists(f"Session already running: {project}")

    # Get agent command
    agent_cmd = get_agent_command(agent, project)
    if yolo and agent in ("coder", "grok", "minimax"):
        agent_cmd += " --yolo"

    # Clear log file
    log_path = LOG_DIR / f"gg-{project}.log"
    try:
        log_path.write_text("")
    except OSError as e:
        raise SessionError(f"Cannot write to log: {e}")

    # Set up systemd environment
    os.environ["AGENT_CMD"] = agent_cmd
    run_cmd(
        ["systemctl", "--user", "set-environment", f"AGENT_CMD={agent_cmd}"],
        check=True,
    )

    # Start systemd service
    service = SYSTEMD_SERVICE_TEMPLATE.format(project=project)
    run_cmd(
        ["systemctl", "--user", "start", service],
        timeout=TIMEOUT_SYSTEMD,
        check=True,
    )

    # Wait for tmux session
    if not wait_for(lambda: tmux.has_session(project), timeout=10, interval=0.2):
        run_cmd(["systemctl", "--user", "stop", service])
        raise SessionError("Service started but tmux session not found")

    logger.info(f"Started session '{project}' with {agent}")


def stop_session(project: str) -> None:
    """Stop a session.

    Args:
        project: Project name

    Raises:
        ValidationError: If project name is invalid
        SessionNotFound: If session not running
    """
    validate_project(project)

    tmux = get_tmux()

    if not tmux.has_session(project):
        raise SessionNotFound(f"Session not running: {project}")

    # Stop systemd service
    service = SYSTEMD_SERVICE_TEMPLATE.format(project=project)
    run_cmd(
        ["systemctl", "--user", "stop", service],
        timeout=TIMEOUT_SYSTEMD,
        check=False,
    )

    logger.info(f"Stopped session '{project}'")


def send_command(project: str, message: str) -> None:
    """Send a command to a session.

    Args:
        project: Project name
        message: Command to send

    Raises:
        ValidationError: If project name is invalid
        SessionNotFound: If session not running
    """
    validate_project(project)

    tmux = get_tmux()

    if not tmux.has_session(project):
        raise SessionNotFound(f"Session not running: {project}")

    tmux.send_keys(project, message)


def list_sessions() -> list[str]:
    """List all gg sessions.

    Returns:
        List of session names
    """
    tmux = get_tmux()
    return tmux.list_sessions()


def get_session_info(project: str) -> dict:
    """Get info about a session.

    Args:
        project: Project name

    Returns:
        Dict with session info
    """
    validate_project(project)

    tmux = get_tmux()
    info = tmux.get_session_info(project, LOG_DIR)

    return {
        "project": info.name,
        "exists": info.exists,
        "active": info.active,
        "log_path": str(info.log_path),
        "log_size": info.log_size,
    }
