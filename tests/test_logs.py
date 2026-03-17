"""Tests for logs module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from gitgantt._errors import ValidationError
from gitgantt.core import logs


class TestGetLogPath:
    """Tests for get_log_path function."""

    def test_basic_path(self):
        """Test basic log path generation."""
        # The function uses LOG_DIR from _config which is imported at module load
        # Just test the path structure
        path = logs.get_log_path("myproject")
        assert path.name == "gg-myproject.log"

    def test_project_in_filename(self):
        """Test project name is in filename."""
        path = logs.get_log_path("test-project")
        assert "test-project" in str(path)


class TestReadLog:
    """Tests for read_log function."""

    def test_empty_for_nonexistent(self):
        """Test empty list for nonexistent file."""
        # Patch the get_log_path function to return nonexistent path
        with patch.object(
            logs, "get_log_path", return_value=Path("/nonexistent/myproject.log")
        ):
            result = logs.read_log("myproject")
            assert result == []

    def test_read_lines(self):
        """Test reading lines from file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            f.write("line1\nline2\nline3\n")
            temp_path = Path(f.name)

        try:
            with patch.object(logs, "get_log_path", return_value=temp_path):
                result = logs.read_log("myproject")
                assert len(result) == 3
                assert "line1" in result[0]
        finally:
            temp_path.unlink()

    def test_respects_line_limit(self):
        """Test line limit is respected."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            for i in range(100):
                f.write(f"line{i}\n")
            temp_path = Path(f.name)

        try:
            with patch.object(logs, "get_log_path", return_value=temp_path):
                result = logs.read_log("myproject", lines=10)
                assert len(result) == 10
        finally:
            temp_path.unlink()

    def test_invalid_project_raises(self):
        """Test invalid project name raises ValidationError."""
        with pytest.raises(ValidationError):
            logs.read_log("")


class TestGetLogSize:
    """Tests for get_log_size function."""

    def test_nonexistent_file(self):
        """Test None for nonexistent file."""
        with patch.object(
            logs, "get_log_path", return_value=Path("/nonexistent/myproject.log")
        ):
            result = logs.get_log_size("myproject")
            assert result is None

    def test_existing_file(self):
        """Test returns file size for existing file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
            f.write("test content")
            temp_path = Path(f.name)

        try:
            with patch.object(logs, "get_log_path", return_value=temp_path):
                result = logs.get_log_size("myproject")
                assert result is not None
                assert result > 0
        finally:
            temp_path.unlink()
