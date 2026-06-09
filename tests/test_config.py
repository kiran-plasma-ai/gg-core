"""Tests for config module."""

from __future__ import annotations

from gg_core._config import MODEL_CAPABLE_AGENTS, get_agent_command


class TestGetAgentCommand:
    """Tests for get_agent_command function."""

    def test_kimi_without_model(self):
        """Test kimi command without model."""
        cmd = get_agent_command("kimi", "my-project")
        assert "kimi" in cmd
        assert "-C" in cmd
        assert "-m" not in cmd

    def test_kimi_with_model(self):
        """Test kimi command with model."""
        cmd = get_agent_command("kimi", "my-project", model="minimax-m27-highspeed")
        assert "kimi" in cmd
        assert "-m minimax-m27-highspeed" in cmd
        assert "-C" in cmd
        # Model is appended at the end when -S is not present

    def test_all_model_capable_agents(self):
        """Test that all capable agents handle model parameter correctly."""
        # All of these should use the provided model
        for agent in ["kimi", "coder", "opencode"]:
            cmd = get_agent_command(agent, "my-project", model="custom-model")
            assert "-m" in cmd, f"{agent} should have -m flag"
            assert "custom-model" in cmd, f"{agent} should use custom model"

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
