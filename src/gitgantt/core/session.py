"""Session lifecycle management.

Handles start/stop of agent sessions via tmux + systemd.
"""

from __future__ import annotations

import logging
import signal
import subprocess
import time
from collections.abc import Callable

from .._config import (
    LOG_DIR,
    LOG_PREFIX,
    SYSTEMD_SERVICE_TEMPLATE,
    TIMEOUT_DEFAULT,
    TIMEOUT_SYSTEMD,
    WAIT_FOR_INTERVAL,
    WAIT_FOR_SESSION_INTERVAL,
    WAIT_FOR_TIMEOUT,
    get_agent_command,
)
from .._errors import SessionError, SessionExists, SessionNotFound
from .._types import SessionInfo
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


def wait_for(
    condition: Callable[[], bool],
    timeout: float = WAIT_FOR_TIMEOUT,
    interval: float = WAIT_FOR_INTERVAL,
) -> bool:
    """Wait for condition to become true."""
    # Ignore SIGINT during wait
    old_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        start = time.time()
        while time.time() - start < timeout:
            if condition():
                return True
            time.sleep(interval)
        return False
    finally:
        signal.signal(signal.SIGINT, old_handler)


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
    if not agent_cmd:
        raise SessionError(f"No command configured for agent: {agent}")
    # Add --yolo only if requested and not already in command
    # (defaults already include --yolo for coder/grok/minimax)
    if yolo and "--yolo" not in agent_cmd:
        agent_cmd += " --yolo"

    # Clear log file
    log_path = LOG_DIR / f"{LOG_PREFIX}{project}.log"
    try:
        log_path.write_text("")
    except OSError as e:
        raise SessionError(f"Cannot write to log: {e}") from e

    # Reset any failed/inactive state from previous runs
    # This handles the case where the service is "active (exited)" after
    # a previous session, which would prevent ExecStart from running again
    service = SYSTEMD_SERVICE_TEMPLATE.format(project=project)
    run_cmd(["systemctl", "--user", "reset-failed", service], check=False)
    run_cmd(["systemctl", "--user", "stop", service], check=False)

    # Set up systemd environment for the service
    # Note: We use systemctl set-environment which sets it in the systemd
    # user manager scope, not in os.environ of this process
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

    # Wait for tmux session to be ready
    if not wait_for(
        lambda: tmux.has_session(project),
        timeout=WAIT_FOR_TIMEOUT,
        interval=WAIT_FOR_SESSION_INTERVAL,
    ):
        run_cmd(["systemctl", "--user", "stop", service], check=False)
        raise SessionError(
            f"Service started but tmux session not found. "
            f"Check: systemctl --user status {service}"
        )

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


def get_session_info(project: str) -> SessionInfo:
    """Get info about a session.

    Args:
        project: Project name

    Returns:
        SessionInfo dataclass with session details
    """
    validate_project(project)

    tmux = get_tmux()
    return tmux.get_session_info(project, LOG_DIR)
