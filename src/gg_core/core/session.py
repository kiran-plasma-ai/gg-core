"""Session lifecycle management.

Handles start/stop of agent sessions via tmux + systemd (Linux) or launchd (macOS).
"""

from __future__ import annotations

import logging
import os
import plistlib
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tmux import Tmux

from .._config import (
    ANSI_ESCAPE,
    LOG_DIR,
    LOG_PREFIX,
    SEND_MESSAGE_MAX_LENGTH,
    SYSTEMD_SERVICE_TEMPLATE,
    TIMEOUT_DEFAULT,
    TIMEOUT_SYSTEMD,
    TIMEOUT_TMUX,
    WAIT_FOR_INTERVAL,
    WAIT_FOR_SESSION_INTERVAL,
    WAIT_FOR_TIMEOUT,
    get_agent_command,
)
from .._errors import SessionError, SessionExists, SessionNotFound, TmuxError
from .._types import AgentState, SessionInfo
from .extraction import detect_state_from_lines
from .tmux import get_tmux
from .validation import validate_agent, validate_project

logger = logging.getLogger(__name__)


def _use_launchd() -> bool:
    """True when running on macOS, where launchd replaces systemd."""
    return sys.platform == "darwin"


def _has_yolo_flag(cmd: str) -> bool:
    """Check if command already has a YOLO flag."""
    try:
        args = shlex.split(cmd)
        return any(arg in ("--yolo", "-y", "--yes") for arg in args)
    except ValueError:
        return "--yolo" in cmd  # fallback


# =============================================================================
# macOS launchd support
# =============================================================================

_LAUNCHD_DOMAIN = "user/{uid}"
_LAUNCHD_LABEL = "com.gg.project.{project}"


def _launchd_plist_path(project: str) -> Path:
    """Path to the launchd plist for a project."""
    return Path.home() / "Library" / "LaunchAgents" / f"com.gg.project.{project}.plist"


def _launchd_label(project: str) -> str:
    """The launchd label for a project's agent."""
    return _LAUNCHD_LABEL.format(project=project)


def _launchd_domain() -> str:
    """The launchd domain for the current user."""
    return _LAUNCHD_DOMAIN.format(uid=os.getuid())


def _start_session_launchd(project: str, agent_cmd: str, tmux: Tmux) -> None:
    """Start a session via macOS launchd."""
    import shutil as _shutil

    # Ensure Homebrew and ~/.kimi-code/bin are on PATH so libtmux finds tmux
    # and the agent binary is resolvable.
    _brew = "/opt/homebrew/bin"
    _kimi_bin = str(Path.home() / ".kimi-code" / "bin")
    _existing = os.environ.get("PATH", "")
    _needed = [p for p in (_brew, _kimi_bin) if p not in _existing]
    if _needed:
        os.environ["PATH"] = ":".join(_needed + [_existing])
    tmux_bin = _shutil.which("tmux") or "/opt/homebrew/bin/tmux"
    home = str(Path.home())

    plist: dict = {
        "Label": _launchd_label(project),
        "RunAtLoad": True,
        "EnvironmentVariables": {
            "PATH": f"/opt/homebrew/bin:{home}/.kimi-code/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": home,
        },
        "ProgramArguments": [
            "/bin/bash",
            "-c",
            (
                f"mkdir -p {shlex.quote(home + '/' + project)}; "
                f"cd {shlex.quote(home + '/' + project)}; "
                f"{tmux_bin} kill-session -t {shlex.quote(project)} 2>/dev/null; "
                f"{tmux_bin} new-session -d -s {shlex.quote(project)} "
                f"-c {shlex.quote(home + '/' + project)} "
                f"{shlex.quote(agent_cmd)}"
            ),
        ],
    }

    plist_path = _launchd_plist_path(project)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plistlib.dumps(plist))

    run_cmd(
        ["launchctl", "bootstrap", _launchd_domain(), str(plist_path)],
        timeout=TIMEOUT_SYSTEMD,
        check=True,
    )

    if not wait_for(
        lambda: tmux.has_session(project),
        timeout=WAIT_FOR_TIMEOUT,
        interval=WAIT_FOR_SESSION_INTERVAL,
    ):
        _stop_session_launchd(project)
        raise SessionError(
            f"launchd started but tmux session not found. "
            f"Check: launchctl list | grep {_launchd_label(project)}"
        )

    time.sleep(0.5)
    if not tmux.has_session(project):
        _stop_session_launchd(project)
        raise SessionError(
            f"Tmux session for '{project}' exited immediately. "
            f"Agent command: {agent_cmd}."
        )

    plist_path.unlink(missing_ok=True)


def _stop_session_launchd(project: str) -> None:
    """Stop a launchd-managed session."""
    label = _launchd_label(project)
    domain = f"{_launchd_domain()}/{label}"
    run_cmd(
        ["launchctl", "bootout", domain],
        check=False,
    )
    _launchd_plist_path(project).unlink(missing_ok=True)
    # Fallback: kill tmux directly
    run_cmd(["tmux", "kill-session", "-t", project], timeout=TIMEOUT_TMUX, check=False)


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
            check=False,
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
    try:
        old_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (OSError, ValueError):
        # Cannot set handler - proceed without it
        old_handler = None

    try:
        start = time.time()
        while time.time() - start < timeout:
            if condition():
                return True
            time.sleep(interval)
        return False
    finally:
        if old_handler is not None:
            try:
                signal.signal(signal.SIGINT, old_handler)
            except (OSError, ValueError) as e:
                logger.error(f"Failed to restore SIGINT handler: {e}")


# =============================================================================
# Session Operations
# =============================================================================


def start_session(
    project: str,
    agent: str = "kimi",
    *,
    model: str | None = None,
    yolo: bool = False,
    auto: bool = False,
) -> None:
    """Start a new session.

    Args:
        project: Project name
        agent: Agent to use
        model: Optional model to use (e.g., "minimax-m27-highspeed")
        yolo: Enable YOLO mode (auto-approval). Deprecated for kimi; use ``auto``.
        auto: Start agent in auto permission mode (kimi-code ``--auto``).

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

    # Get agent command (with optional model and auto mode)
    agent_cmd = get_agent_command(agent, project, model=model, auto=auto)
    if not agent_cmd:
        raise SessionError(f"No command configured for agent: {agent}")
    if yolo and not _has_yolo_flag(agent_cmd):
        agent_cmd += " --yolo"

    # Dispatch to platform-specific session manager
    if _use_launchd():
        _start_session_launchd(project, agent_cmd, tmux=tmux)
        logger.info(f"Started session '{project}' with {agent} (launchd)")
        return

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
    success, stdout, stderr = run_cmd(
        ["systemctl", "--user", "reset-failed", service], check=False
    )
    if not success:
        logger.warning(f"Failed to reset-failed {service}: {stderr}")

    success, stdout, stderr = run_cmd(
        ["systemctl", "--user", "stop", service], check=False
    )
    if not success:
        logger.warning(f"Failed to stop {service}: {stderr}")

    # Create a per-service drop-in with the agent command instead of using
    # ``systemctl set-environment`` which is user-global and races when
    # multiple sessions are started concurrently.
    systemd_dir = Path.home() / ".config" / "systemd" / "user"
    override_dir = systemd_dir / f"{service}.d"
    try:
        override_dir.mkdir(parents=True, exist_ok=True)
        (override_dir / "agent.conf").write_text(
            f"[Service]\nEnvironment=AGENT_CMD={shlex.quote(agent_cmd)}\n"
        )
    except OSError:
        # Fall back to global set-environment on filesystem error (e.g. tests
        # without a real home directory, read-only filesystems).
        logger.debug(
            "Cannot create systemd override dir for %s, falling back to set-environment",
            service,
        )
        run_cmd(
            ["systemctl", "--user", "set-environment", f"AGENT_CMD={agent_cmd}"],
            check=True,
        )
    else:
        # Reload so systemd picks up the new drop-in
        run_cmd(
            ["systemctl", "--user", "daemon-reload"],
            timeout=TIMEOUT_SYSTEMD,
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

    # Verify the session stays alive briefly.  If the agent command exits
    # immediately (bad binary path, missing dependencies, etc.), the tmux
    # session will disappear right after creation.
    time.sleep(0.5)
    if not tmux.has_session(project):
        run_cmd(["systemctl", "--user", "stop", service], check=False)
        raise SessionError(
            f"Tmux session for '{project}' exited immediately. "
            f"Agent command: {agent_cmd}. "
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

    if _use_launchd():
        _stop_session_launchd(project)
        logger.info(f"Stopped session '{project}'")
        return

    # Stop systemd service first so ExecStop can cleanly kill tmux.
    # If we kill tmux first, systemd's ExecStop fails and the service
    # enters a failed state.
    service = SYSTEMD_SERVICE_TEMPLATE.format(project=project)
    run_cmd(
        ["systemctl", "--user", "stop", service],
        timeout=TIMEOUT_SYSTEMD,
        check=False,
    )

    # Fallback: kill tmux directly if it's still running
    run_cmd(
        ["tmux", "kill-session", "-t", project],
        timeout=TIMEOUT_TMUX,
        check=False,
    )

    # Clean up any failed state from the stop
    run_cmd(
        ["systemctl", "--user", "reset-failed", service],
        timeout=TIMEOUT_SYSTEMD,
        check=False,
    )

    # Remove per-service drop-in so stale agent commands don't linger
    override_dir = (
        Path.home() / ".config" / "systemd" / "user" / f"{service}.d"
    )
    try:
        if override_dir.exists():
            (override_dir / "agent.conf").unlink(missing_ok=True)
            override_dir.rmdir()
    except OSError as e:
        logger.debug(f"Could not remove override dir for {service}: {e}")

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

    # Sanitize message to prevent ANSI injection attacks
    # Also limit length to prevent abuse
    sanitized = ANSI_ESCAPE.sub("", message)
    if len(sanitized) > SEND_MESSAGE_MAX_LENGTH:
        sanitized = sanitized[:SEND_MESSAGE_MAX_LENGTH]
        logger.warning(
            "Message truncated to %s chars for %s",
            SEND_MESSAGE_MAX_LENGTH,
            project,
        )

    tmux.send_keys(project, sanitized, literal=True)


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


# =============================================================================
# State Detection
# =============================================================================


def detect_state(project: str) -> AgentState:
    """Detect current agent state for a session.

    Uses wire.jsonl for kimi-code sessions when available, otherwise falls
    back to tmux pane capture.

    Args:
        project: Project name

    Returns:
        AgentState: WORKING, IDLE, or UNKNOWN

    Raises:
        ValidationError: If project name is invalid
        SessionNotFound: If session not running
    """
    validate_project(project)

    tmux = get_tmux()

    if not tmux.has_session(project):
        raise SessionNotFound(f"Session not running: {project}")

    # Try wire.jsonl first for kimi-code sessions
    from .validation import infer_agent
    from .wire import detect_wire_state, find_kimi_wire_path, is_kimi_code_session

    if infer_agent(project) == "kimi" and is_kimi_code_session(project):
        wire_path = find_kimi_wire_path(project)
        if wire_path is not None:
            state = detect_wire_state(wire_path)
            logger.debug(f"Detected wire state for {project}: {state.value}")
            return state

    # Fallback: tmux pane capture
    try:
        lines = tmux.capture_pane(project, lines=50)
    except TmuxError:
        logger.debug(f"Failed to capture pane for {project}")
        return AgentState.UNKNOWN

    state = detect_state_from_lines(lines)
    logger.debug(f"Detected tmux state for {project}: {state.value}")
    return state


def is_working(project: str) -> bool:
    """Quick check if agent is currently working.

    Args:
        project: Project name

    Returns:
        True if agent is working
    """
    try:
        return detect_state(project) == AgentState.WORKING
    except SessionNotFound:
        return False


def is_idle(project: str) -> bool:
    """Quick check if agent is idle (at prompt).

    Args:
        project: Project name

    Returns:
        True if agent is at prompt and ready for input
    """
    try:
        return detect_state(project) == AgentState.IDLE
    except SessionNotFound:
        return False
