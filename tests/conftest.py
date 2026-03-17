"""pytest configuration for gg-core."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_libtmux():
    """Mock libtmux.Server for testing."""
    with patch("gitgantt.core.tmux.libtmux") as mock:
        mock_server = MagicMock()
        mock.Server.return_value = mock_server
        yield mock_server


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for testing."""
    with patch("gitgantt.core.session.subprocess.run") as mock:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        mock.return_value = mock_result
        yield mock


@pytest.fixture
def mock_systemctl():
    """Mock systemctl commands."""
    with patch("gitgantt.core.session.run_cmd") as mock:
        mock.return_value = (True, "", "")
        yield mock


@pytest.fixture
def clean_env():
    """Provide clean environment for tests."""
    old_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(old_env)
