"""Cross-host aggregation for gg ps --all / gg hosts.

The host list lives in ~/.config/gg-core/hosts.toml (override with the
GG_HOSTS environment variable):

    [[hosts]]
    name = "workstation"
    ssh = ""                          # empty = this host
    dir = ""                          # cwd for remote gg invocation
    enabled = true

    # [[hosts]]
    # name = "gateway"
    # ssh = "gateway"                 # ssh alias
    # dir = "~/gg-channels"
    # enabled = true

`gg ps --all` runs `gg ps --json` on each enabled host via BatchMode ssh
and merges the results; one unreachable host never fails the run.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .._errors import ValidationError

try:
    import tomllib  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - Python < 3.11
    tomllib = None

_CONFIG_ENV = "GG_HOSTS"
_CONFIG_DIR = Path.home() / ".config" / "gg-core"

_TEMPLATE = '''\
# gg-core host registry: consumed by `gg hosts` and `gg ps --all`.
# `ssh` is an ssh alias (BatchMode, no interactive prompts); empty = this
# host. `dir` is the working directory for the remote gg invocation.

[[hosts]]
name = "{hostname}"
ssh = ""            # local
dir = ""
enabled = true

# [[hosts]]
# name = "gateway"
# ssh = "gateway"
# dir = "~/gg-channels"
# enabled = true

# [[hosts]]
# name = "workstation"
# ssh = "workstation"
# dir = "/home/user/gg-core"
# enabled = true
'''


@dataclass(frozen=True)
class HostConfig:
    """One entry from hosts.toml."""

    name: str
    ssh: str  # empty = local host
    dir: str
    enabled: bool = True

    @property
    def is_local(self) -> bool:
        return self.ssh == ""


def hosts_config_path() -> Path:
    """Return the hosts config path (GG_HOSTS env overrides the default)."""
    override = os.environ.get(_CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    return _CONFIG_DIR / "hosts.toml"


def ensure_hosts_config() -> Path:
    """Create the config with the local host plus commented examples if absent."""
    path = hosts_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_TEMPLATE.format(hostname=socket.gethostname()), encoding="utf-8")
    return path


def load_hosts(*, enabled_only: bool = False) -> list[HostConfig]:
    """Parse hosts.toml into HostConfig entries.

    Raises:
        ValidationError: when the file is missing/unreadable/malformed
    """
    if tomllib is None:
        raise ValidationError("hosts config requires Python 3.11+ (tomllib)")
    path = hosts_config_path()
    if not path.exists():
        raise ValidationError(f"hosts config not found: {path} (run: gg hosts)")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ValidationError(f"cannot read hosts config {path}: {e}") from e

    raw_hosts = data.get("hosts")
    if not isinstance(raw_hosts, list):
        raise ValidationError(f"hosts config {path} has no [[hosts]] table")

    hosts: list[HostConfig] = []
    for i, raw in enumerate(raw_hosts):
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            raise ValidationError(f"hosts config entry #{i + 1} lacks a name")
        host = HostConfig(
            name=str(raw["name"]).strip(),
            ssh=str(raw.get("ssh") or "").strip(),
            dir=str(raw.get("dir") or "").strip(),
            enabled=bool(raw.get("enabled", True)),
        )
        if enabled_only and not host.enabled:
            continue
        hosts.append(host)
    return hosts


def check_host(host: HostConfig, *, timeout: int = 8) -> tuple[bool, str]:
    """Return (reachable, detail) for a host. Local is always reachable."""
    if host.is_local:
        return True, "local"
    if shutil.which("ssh") is None:
        return False, "ssh not installed"
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                f"ConnectTimeout={timeout}",
                host.ssh,
                "true",
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if result.returncode == 0:
        return True, "ok"
    detail = (result.stderr or result.stdout or "ssh failed").strip().splitlines()
    return False, detail[-1] if detail else "ssh failed"


def fetch_remote_ps(host: HostConfig, *, timeout: int = 20) -> dict:
    """Run `gg ps --json` on a remote host and return its parsed payload.

    Raises:
        ValidationError: on ssh failure or unparseable output
    """
    if host.is_local:
        raise ValidationError("fetch_remote_ps is for remote hosts only")
    remote_cmd = "gg ps --json"
    if host.dir:
        remote_cmd = f"cd {shlex.quote(host.dir)} && {remote_cmd}"
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                host.ssh,
                remote_cmd,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ValidationError(f"{host.name}: {e}") from e
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "remote gg failed").strip()
        raise ValidationError(f"{host.name}: {detail.splitlines()[-1]}")
    try:
        payload: dict = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ValidationError(
            f"{host.name}: unparseable gg ps --json output: {e}"
        ) from e
    return payload


def collect_all_ps(local_rows: list[dict]) -> list[dict]:
    """Merge local ps rows with every enabled remote host.

    Each entry is either {"name", "ssh", "sessions"} or, for a host that
    could not be queried, {"name", "ssh", "error"}. One unreachable host
    never fails the rest.
    """
    hosts = load_hosts(enabled_only=True)
    results: list[dict] = []
    for host in hosts:
        if host.is_local:
            results.append({"name": host.name, "ssh": "", "sessions": local_rows})
            continue
        try:
            payload = fetch_remote_ps(host)
        except ValidationError as e:
            results.append({"name": host.name, "ssh": host.ssh, "error": str(e)})
            continue
        sessions = payload.get("sessions")
        if not isinstance(sessions, list):
            results.append(
                {
                    "name": host.name,
                    "ssh": host.ssh,
                    "error": "remote returned no sessions list",
                }
            )
            continue
        results.append({"name": host.name, "ssh": host.ssh, "sessions": sessions})
    return results
