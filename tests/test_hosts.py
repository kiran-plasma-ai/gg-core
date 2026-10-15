"""Tests for the hosts registry and gg ps --all merge."""

from __future__ import annotations

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

from gg_core import ValidationError
from gg_core.core.hosts import (
    HostConfig,
    check_host,
    collect_all_ps,
    hosts_config_path,
    load_hosts,
)

hosts_mod = importlib.import_module("gg_core.core.hosts")
run_mod = importlib.import_module("gg_core.cli.run")

LOCAL_CFG = '''
[[hosts]]
name = "here"
ssh = ""
dir = ""
enabled = true
'''

GATEWAY_CFG = LOCAL_CFG + '''
[[hosts]]
name = "gateway"
ssh = "gateway"
dir = "~/gg-core"
enabled = true

[[hosts]]
name = "off"
ssh = "off"
dir = ""
enabled = false
'''


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "hosts.toml"
    monkeypatch.setenv("GG_HOSTS", str(path))
    return path


class TestLoadHosts:
    def test_missing_file_raises(self, cfg) -> None:
        with pytest.raises(ValidationError, match="not found"):
            load_hosts()

    def test_local_and_remote(self, cfg) -> None:
        cfg.write_text(GATEWAY_CFG)
        hosts = load_hosts()
        assert [h.name for h in hosts] == ["here", "gateway", "off"]
        assert hosts[0].is_local
        assert not hosts[1].is_local

    def test_enabled_only(self, cfg) -> None:
        cfg.write_text(GATEWAY_CFG)
        assert [h.name for h in load_hosts(enabled_only=True)] == ["here", "gateway"]

    def test_gg_hosts_env_overrides_path(self, cfg, monkeypatch) -> None:
        other = cfg.parent / "other.toml"
        monkeypatch.setenv("GG_HOSTS", str(other))
        assert hosts_config_path() == other

    def test_malformed_raises(self, cfg) -> None:
        cfg.write_text("not = [valid")
        with pytest.raises(ValidationError):
            load_hosts()

    def test_entry_without_name_raises(self, cfg) -> None:
        cfg.write_text("[[hosts]]\nssh = 'x'\n")
        with pytest.raises(ValidationError, match="name"):
            load_hosts()


class TestCollectAllPs:
    def test_unreachable_host_never_fails_the_merge(self, cfg) -> None:
        cfg.write_text(GATEWAY_CFG)
        local_rows = [{"project": "p", "state": "idle"}]

        def fake_fetch(host: HostConfig) -> dict:
            raise ValidationError(f"{host.name}: ssh boom")

        with patch.object(hosts_mod, "fetch_remote_ps", side_effect=fake_fetch):
            merged = collect_all_ps(local_rows)

        by_name = {h["name"]: h for h in merged}
        assert by_name["here"]["sessions"] == local_rows
        assert by_name["gateway"]["error"] == "gateway: ssh boom"
        assert "off" not in by_name  # disabled hosts are skipped

    def test_remote_payload_merged(self, cfg) -> None:
        cfg.write_text(GATEWAY_CFG)
        remote = {"host": "gateway", "now": 1, "sessions": [{"project": "oil"}]}
        with patch.object(hosts_mod, "fetch_remote_ps", return_value=remote):
            merged = collect_all_ps([])
        gw = next(h for h in merged if h["name"] == "gateway")
        assert gw["sessions"] == [{"project": "oil"}]

    def test_remote_without_sessions_list_is_an_error(self, cfg) -> None:
        cfg.write_text(GATEWAY_CFG)
        with patch.object(hosts_mod, "fetch_remote_ps", return_value={}):
            merged = collect_all_ps([])
        gw = next(h for h in merged if h["name"] == "gateway")
        assert "error" in gw


class TestCheckHost:
    def test_local_always_reachable(self) -> None:
        assert check_host(HostConfig(name="x", ssh="", dir="")) == (True, "local")

    def test_ssh_failure_reported(self) -> None:
        result = MagicMock()
        result.returncode = 255
        result.stderr = "Permission denied\n"
        result.stdout = ""
        with patch.object(hosts_mod.subprocess, "run", return_value=result):
            ok, detail = check_host(HostConfig(name="x", ssh="bad", dir=""))
        assert not ok
        assert "Permission denied" in detail


class TestCmdHosts:
    def test_creates_config_and_lists(self, cfg, capsys, monkeypatch) -> None:
        monkeypatch.setattr(run_mod.socket, "gethostname", lambda: "testhost")
        assert run_mod.cmd_hosts() == 0
        out = capsys.readouterr().out
        assert "testhost" in out
        assert cfg.exists()  # created on first run


class TestCmdPsAll:
    def test_json_output(self, cfg, capsys) -> None:
        cfg.write_text(LOCAL_CFG)
        with (
            patch.object(run_mod, "list_sessions", return_value=[]),
            patch.object(run_mod, "_ps_rows", return_value=[]),
        ):
            assert run_mod.cmd_ps(as_json=True, all_hosts=True) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["hosts"][0]["name"] == "here"

    def test_unreachable_reported_on_stderr(self, cfg, capsys) -> None:
        cfg.write_text(GATEWAY_CFG)
        with (
            patch.object(run_mod, "list_sessions", return_value=[]),
            patch.object(run_mod, "_ps_rows", return_value=[]),
            patch.object(
                hosts_mod,
                "fetch_remote_ps",
                side_effect=ValidationError("gateway: down"),
            ),
        ):
            assert run_mod.cmd_ps(all_hosts=True) == 0
        assert "gateway: unreachable" in capsys.readouterr().err
