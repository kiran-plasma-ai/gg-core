"""Tests for config module."""

from __future__ import annotations

import shutil
from pathlib import Path

from gg_core._config import (
    DEFAULT_AGENT,
    DEFAULT_AGENTS,
    MODEL_CAPABLE_AGENTS,
    default_omp_command,
    find_omp_binary,
    get_agent_command,
)


class TestGetAgentCommand:
    """Tests for get_agent_command function."""

    def test_kimi_without_model(self):
        """Test kimi command without model."""
        cmd = get_agent_command("kimi", "my-project")
        assert "kimi" in cmd
        assert "-c" in cmd
        assert "-m" not in cmd

    def test_kimi_with_model(self):
        """Test kimi command with model."""
        cmd = get_agent_command("kimi", "my-project", model="minimax-m27-highspeed")
        assert "kimi" in cmd
        assert "-m minimax-m27-highspeed" in cmd
        assert "-c" in cmd
        # Model is appended at the end when -S is not present

    def test_all_model_capable_agents(self):
        """Test that all capable agents handle model parameter correctly."""
        # All of these should use the provided model
        for agent in ["omp", "kimi", "coder", "opencode"]:
            cmd = get_agent_command(agent, "my-project", model="custom-model")
            assert "custom-model" in cmd, f"{agent} should use custom model"

    def test_omp_without_model(self):
        """Test omp command without model."""
        cmd = get_agent_command("omp", "my-project")
        assert "omp" in cmd
        assert "-c" in cmd
        assert "--model" not in cmd

    def test_omp_with_model(self):
        """Test omp uses its --model flag, not -m."""
        cmd = get_agent_command("omp", "my-project", model="deepseek/deepseek-v4-flash")
        assert "--model deepseek/deepseek-v4-flash" in cmd

    def test_omp_auto_mode(self):
        """Test omp starts in auto-approve mode."""
        cmd = get_agent_command("omp", "my-project", auto=True)
        assert "--auto-approve" in cmd

    def test_omp_model_capable(self):
        """Test omp is registered as model-capable."""
        assert "omp" in MODEL_CAPABLE_AGENTS

    def test_default_agent_is_configured_agent(self):
        """The default agent must reference a configured agent command."""
        assert DEFAULT_AGENT in DEFAULT_AGENTS
        assert DEFAULT_AGENTS[DEFAULT_AGENT]

    def test_model_replacement_for_coder(self):
        """Test that coder replaces default model rather than adding duplicate."""
        # coder has `-m kimi` in default, should replace with custom model
        cmd = get_agent_command("coder", "my-project", model="gpt-4")
        assert cmd.count("-m") == 1, "Should have exactly one -m flag"
        assert "-m gpt-4" in cmd
        assert "-m kimi" not in cmd

    def test_model_capable_agents_set(self):
        """Test MODEL_CAPABLE_AGENTS contains expected agents."""
        assert "kimi" in MODEL_CAPABLE_AGENTS
        assert "opencode" in MODEL_CAPABLE_AGENTS
        assert "coder" in MODEL_CAPABLE_AGENTS
        # gemini is not model-capable
        assert "gemini" not in MODEL_CAPABLE_AGENTS

    def test_model_shell_escaping(self):
        """Test that model name is shell-escaped."""
        # This should not raise an error and should escape properly
        cmd = get_agent_command("kimi", "my-project", model="model-with-chars")
        assert "-m model-with-chars" in cmd

    def test_kimi_auto_mode(self):
        """Test kimi starts in auto permission mode."""
        cmd = get_agent_command("kimi", "my-project", auto=True)
        assert "--auto" in cmd
        assert cmd.index("--auto") < cmd.index(" -c")  # space avoids matching "kimi-code"

    def test_kimi_auto_false(self):
        """Test kimi does not add --auto by default."""
        cmd = get_agent_command("kimi", "my-project")
        assert "--auto" not in cmd

    def test_auto_mode_with_model(self):
        """Test auto mode and model can be combined for kimi."""
        cmd = get_agent_command("kimi", "my-project", model="custom", auto=True)
        assert "--auto" in cmd
        assert "-m custom" in cmd
        assert "-c" in cmd

    def test_shlex_quoting_for_project_with_spaces(self):
        """Project names with spaces are safely quoted."""
        cmd = get_agent_command("coder", "my project", model="custom")
        assert "'my project'" in cmd or '"my project"' in cmd
        assert "-S" in cmd
        assert "-m custom" in cmd


class TestOmpBinaryLookup:
    """The omp command must match how the host installs omp."""

    def test_prefers_standalone_binary(self, monkeypatch, tmp_path):
        """~/.local/bin/omp (standalone release) wins over the bun package."""
        (tmp_path / ".local" / "bin").mkdir(parents=True)
        (tmp_path / ".local" / "bin" / "omp").write_text("#!/bin/sh\n")
        (tmp_path / ".bun" / "bin").mkdir(parents=True)
        (tmp_path / ".bun" / "bin" / "omp").write_text("")
        monkeypatch.setenv("HOME", str(tmp_path))

        assert find_omp_binary() == tmp_path / ".local" / "bin" / "omp"
        assert default_omp_command() == f"{tmp_path}/.local/bin/omp -c"

    def test_falls_back_to_bun_package(self, monkeypatch, tmp_path):
        """The bun-script install layout keeps working (dev machine)."""
        (tmp_path / ".bun" / "bin").mkdir(parents=True)
        (tmp_path / ".bun" / "bin" / "omp").write_text("")
        monkeypatch.setenv("HOME", str(tmp_path))

        assert find_omp_binary() == tmp_path / ".bun" / "bin" / "omp"
        assert default_omp_command() == f"{tmp_path}/.bun/bin/omp -c"

    def test_path_only_install(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(
            shutil, "which", lambda name: "/opt/omp/bin/omp" if name == "omp" else None
        )
        assert find_omp_binary() == Path("/opt/omp/bin/omp")

    def test_absent_everywhere(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(shutil, "which", lambda name: None)
        assert find_omp_binary() is None
        assert default_omp_command() == "omp -c"
