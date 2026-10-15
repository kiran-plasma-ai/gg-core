"""Session lifecycle management.

Handles start/stop of agent sessions via tmux + systemd (Linux) or direct tmux (macOS).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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
from .validation import infer_agent, validate_agent, validate_project

logger = logging.getLogger(__name__)


def _use_launchd() -> bool:
    """True when running on macOS (direct tmux, no systemd)."""
    return sys.platform == "darwin"


# =============================================================================
# Per-session agent marker
#
# tmux window names are unreliable for agent inference: omp runs as a bun
# script (window name "bun") and kimi-code as a node script, so both would
# fall back to DEFAULT_AGENT. A marker file written next to the session log
# records which agent a session was actually started with, so state detection
# and response extraction stay correct even when kimi and omp sessions run
# side by side or when GG_DEFAULT_AGENT changes.
# =============================================================================

_AGENT_MARKER_SUFFIX = ".agent"


def agent_marker_path(project: str) -> Path:
    """Return the path of the recorded-agent marker for a session."""
    return LOG_DIR / f"{LOG_PREFIX}{project}{_AGENT_MARKER_SUFFIX}"


def record_agent(project: str, agent: str) -> None:
    """Record the agent a session was started with (best-effort)."""
    try:
        agent_marker_path(project).write_text(agent, encoding="utf-8")
    except OSError as e:
        logger.debug(f"Could not record agent for {project}: {e}")


def recorded_agent(project: str) -> str | None:
    """Return the recorded agent for a session, or None if not recorded."""
    path = agent_marker_path(project)
    try:
        agent = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    return agent or None


def _clear_recorded_agent(project: str) -> None:
    """Remove the recorded-agent marker for a session."""
    try:
        agent_marker_path(project).unlink(missing_ok=True)
    except OSError as e:
        logger.debug(f"Could not clear agent marker for {project}: {e}")


def resolve_agent(project: str) -> str:
    """Resolve the agent for a session.

    Prefers the agent recorded at start time, then falls back to inferring it
    from the tmux window name, and finally to the configured
    ``DEFAULT_AGENT``.

    Args:
        project: Project/session name.

    Returns:
        Normalized agent name.
    """
    validate_project(project)
    return recorded_agent(project) or infer_agent(project)


def _has_yolo_flag(cmd: str) -> bool:
    """Check if command already has a YOLO flag."""
    try:
        args = shlex.split(cmd)
        return any(arg in ("--yolo", "-y", "--yes") for arg in args)
    except ValueError:
        return "--yolo" in cmd  # fallback


# =============================================================================
# macOS support — direct tmux (no launchd needed for headless SSH use)
# =============================================================================


def _start_session_darwin(project: str, agent_cmd: str, tmux: Tmux) -> None:
    """Start a session directly via tmux (macOS).

    Launchd user agents require an active GUI (Aqua) session to bootstrap,
    which fails from SSH on a headless MacBook.  Start tmux directly instead.
    """
    _brew = "/opt/homebrew/bin"
    _kimi_bin = str(Path.home() / ".kimi-code" / "bin")
    _bun_bin = str(Path.home() / ".bun" / "bin")
    _existing = os.environ.get("PATH", "")
    _needed = [p for p in (_brew, _kimi_bin, _bun_bin) if p not in _existing]
    env = os.environ.copy()
    if _needed:
        env["PATH"] = ":".join(_needed + [_existing])

    home = str(Path.home())
    project_dir = f"{home}/{project}"

    run_cmd(["mkdir", "-p", project_dir], check=True, env=env)
    run_cmd(["tmux", "kill-session", "-t", project], check=False, env=env)
    run_cmd(
        ["tmux", "new-session", "-d", "-s", project, "-c", project_dir, agent_cmd],
        timeout=TIMEOUT_SYSTEMD,
        check=True,
        env=env,
    )

    if not wait_for(
        lambda: tmux.has_session(project),
        timeout=WAIT_FOR_TIMEOUT,
        interval=WAIT_FOR_SESSION_INTERVAL,
    ):
        raise SessionError(
            f"Tmux session for '{project}' did not start. Agent command: {agent_cmd}"
        )

    time.sleep(0.5)
    if not tmux.has_session(project):
        raise SessionError(
            f"Tmux session for '{project}' exited immediately. "
            f"Agent command: {agent_cmd}."
        )


def _stop_session_darwin(project: str) -> None:
    """Stop a directly-managed tmux session (macOS)."""
    run_cmd(["tmux", "kill-session", "-t", project], timeout=TIMEOUT_TMUX, check=False)


def run_cmd(
    cmd: list[str],
    timeout: int = TIMEOUT_DEFAULT,
    check: bool = False,
    *,
    env: dict[str, str] | None = None,
) -> tuple[bool, str, str]:
    """Run a command.

    Args:
        cmd: Command as list
        timeout: Timeout in seconds
        check: Raise on non-zero exit
        env: Optional environment dict (defaults to os.environ)

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
            env=env,
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
# kimi-code workspace trust
#
# kimi-code asks "Trust this folder?" the first time a session starts in a
# new directory. In headless deployments (gg start / adapters) nobody can
# answer, so the session stalls. There is no config toggle; trust is a
# per-folder record stored under ~/.kimi-code/workspace-trust/ named
# wd_<slug>_<sha256(root)[:12]>. We pre-seed that record so the prompt never
# appears for gg-managed sessions.
#
# Key derivation mirrors kimi-code's workspaceTrust/trustRecord.ts and
# utils/workdir-slug.ts. See AGENTS.md "kimi-code workspace trust".
# =============================================================================

_KIMI_TRUST_SCOPE_DIR = "workspace-trust"
_KIMI_SLUG_MAX = 40


def _kimi_slug(name: str) -> str:
    """Slugify a workspace name the way kimi-code does (workdir-slug.ts)."""
    slug = re.sub(r"[^a-z0-9._-]+", "-", name.lower())
    slug = re.sub(r"^-+|-+$", "", slug)
    slug = slug[:_KIMI_SLUG_MAX]
    slug = re.sub(r"^-+|-+$", "", slug)
    return slug if slug not in ("", ".", "..") else "workspace"


def kimi_workspace_trust_key(root: str) -> str:
    """Compute kimi-code's workspace-trust record key for a directory root.

    Args:
        root: Absolute path of the workspace root (e.g. the project dir).

    Returns:
        Key like ``wd_<slug>_<sha256prefix>`` used as the trust filename.
    """
    normalized = os.path.normpath(root)
    name = os.path.basename(normalized) or "workspace"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"wd_{_kimi_slug(name)}_{digest}"


def kimi_trust_dir() -> Path:
    """Return the kimi-code workspace-trust directory."""
    return (
        Path(os.environ.get("KIMI_CODE_HOME") or Path.home() / ".kimi-code")
        / _KIMI_TRUST_SCOPE_DIR
    )


def ensure_kimi_workspace_trust(project: str) -> None:
    """Pre-seed kimi-code's trust record for a project directory.

    Writes ``~/.kimi-code/workspace-trust/wd_<slug>_<sha256>`` for the
    ``~/<project>`` directory if it does not already exist, so kimi-code
    does not block on its "Trust this folder?" prompt when gg starts the
    session headlessly. Mirrors the record kimi-code itself writes on trust
    (``trustRecord.ts``): ``{"root": ..., "trustedAt": <epoch_ms>}``.

    Args:
        project: Project/session name (validated by callers).
    """
    root = os.path.normpath(str(Path.home() / project))
    trust_dir = kimi_trust_dir()
    key = kimi_workspace_trust_key(root)
    record = trust_dir / key
    if record.exists():
        return
    try:
        trust_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        record.write_text(
            json.dumps({"root": root, "trustedAt": int(time.time() * 1000)}),
            encoding="utf-8",
        )
        os.chmod(record, 0o600)
        logger.info("Seeded kimi-code workspace trust for %s (%s)", root, key)
    except OSError as e:
        logger.warning(f"Could not seed kimi-code workspace trust for {root}: {e}")


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

    # Pre-seed kimi-code's workspace trust for ~/<project> so its "Trust this
    # folder?" prompt never blocks a headless session start. Must happen before
    # the agent process launches (record is read at kimi-code startup).
    if agent == "kimi":
        ensure_kimi_workspace_trust(project)

    # Get agent command (with optional model and auto mode)
    agent_cmd = get_agent_command(agent, project, model=model, auto=auto)
    if not agent_cmd:
        raise SessionError(f"No command configured for agent: {agent}")
    if yolo and not _has_yolo_flag(agent_cmd):
        agent_cmd += " --yolo"

    # Dispatch to platform-specific session manager
    if _use_launchd():
        _start_session_darwin(project, agent_cmd, tmux=tmux)
        record_agent(project, agent)
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

    record_agent(project, agent)
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
        _stop_session_darwin(project)
        _clear_recorded_agent(project)
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
    override_dir = Path.home() / ".config" / "systemd" / "user" / f"{service}.d"
    try:
        if override_dir.exists():
            (override_dir / "agent.conf").unlink(missing_ok=True)
            override_dir.rmdir()
    except OSError as e:
        logger.debug(f"Could not remove override dir for {service}: {e}")

    _clear_recorded_agent(project)
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

    Uses the structured transcript (kimi-code ``wire.jsonl`` or omp session
    JSONL) when available, otherwise falls back to tmux pane capture.

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

    # Prefer structured transcripts: kimi-code wire.jsonl, omp session JSONL
    from .omp import detect_omp_state, find_omp_session_path, is_omp_session
    from .wire import detect_wire_state, find_kimi_wire_path, is_kimi_code_session

    agent = resolve_agent(project)

    if agent == "kimi" and is_kimi_code_session(project):
        wire_path = find_kimi_wire_path(project)
        if wire_path is not None:
            state = detect_wire_state(wire_path)
            logger.debug(f"Detected wire state for {project}: {state.value}")
            return state

    if agent == "omp" and is_omp_session(project):
        session_path = find_omp_session_path(project)
        if session_path is not None:
            state = detect_omp_state(session_path)
            logger.debug(f"Detected omp session state for {project}: {state.value}")
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
