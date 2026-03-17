"""Tests for logs module."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from gitgantt.core import logs


class TestGetLogPath:
    """Tests for get_log_path function."""

    def test_basic_path(self):
        """Test basic log path generation."""
        path = logs.get_log_path("myproject")
        assert path.name == "gg-myproject.log"

    def test_project_in_filename(self):
        """Test project name is in filename."""
        path = logs.get_log_path("test-project")
        assert "test-project" in str(path)


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
