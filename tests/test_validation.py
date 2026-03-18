"""Tests for validation module."""

from __future__ import annotations

import pytest

from gg_core._errors import ValidationError
from gg_core.core.validation import validate_agent, validate_project


class TestValidateProject:
    """Tests for validate_project function."""

    def test_valid_simple_name(self):
        """Test simple valid project name."""
        validate_project("myproject")
        validate_project("test123")
        validate_project("project_name")
        validate_project("project-name")

    def test_valid_with_numbers(self):
        """Test project name with numbers."""
        validate_project("project123")
        validate_project("123project")

    def test_valid_max_length(self):
        """Test project name at max length."""
        name = "a" * 64
        validate_project(name)

    def test_empty_name_raises(self):
        """Test empty name raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_project("")

    def test_too_long_raises(self):
        """Test name too long raises ValidationError."""
        name = "a" * 65
        with pytest.raises(ValidationError, match="too long"):
            validate_project(name)

    def test_invalid_chars_raises(self):
        """Test invalid characters raise ValidationError."""
        with pytest.raises(ValidationError, match="Invalid project name"):
            validate_project("test;rm -rf")
        with pytest.raises(ValidationError, match="Invalid project name"):
            validate_project("test$var")
        with pytest.raises(ValidationError, match="Invalid project name"):
            validate_project("test space")

    def test_starts_with_hyphen_raises(self):
        """Test name starting with hyphen."""
        with pytest.raises(ValidationError, match="Invalid project name"):
            validate_project("-startswithhyphen")

    def test_starts_with_underscore_raises(self):
        """Test name starting with underscore."""
        with pytest.raises(ValidationError, match="Invalid project name"):
            validate_project("_startswithunderscore")

    def test_path_traversal_raises(self):
        """Test path traversal attempts."""
        with pytest.raises(ValidationError, match="Invalid project name"):
            validate_project("../etc")
        with pytest.raises(ValidationError, match="Invalid project name"):
            validate_project("..")


class TestValidateAgent:
    """Tests for validate_agent function."""

    def test_valid_agents(self):
        """Test valid agent names."""
        assert validate_agent("kimi") == "kimi"
        assert validate_agent("coder") == "coder"
        assert validate_agent("grok") == "grok"
        assert validate_agent("minimax") == "minimax"
        assert validate_agent("gemini") == "gemini"
        assert validate_agent("custom") == "custom"

    def test_case_normalized(self):
        """Test agent name is normalized to lowercase."""
        assert validate_agent("KIMI") == "kimi"
        assert validate_agent("Coder") == "coder"
        assert validate_agent("  grok  ") == "grok"

    def test_invalid_agent_raises(self):
        """Test invalid agent raises ValidationError."""
        with pytest.raises(ValidationError, match="Unknown agent"):
            validate_agent("invalid")
        with pytest.raises(ValidationError, match="Unknown agent"):
            validate_agent("")
