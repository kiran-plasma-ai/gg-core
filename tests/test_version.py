"""Tests for version identity."""

from gg_core import __version__, get_commit, version_string
from gg_core._version import _REPO_ROOT


def test_version_matches_package_metadata() -> None:
    assert __version__ == "0.2.0"
    assert __version__ in version_string()


def test_commit_is_short_hex_or_unknown() -> None:
    commit = get_commit()
    assert commit == "unknown" or (
        len(commit) >= 4 and all(c in "0123456789abcdef" for c in commit)
    )


def test_version_string_format() -> None:
    s = version_string()
    assert s.startswith("gg-core ")
    assert "(" in s and s.endswith(")")


def test_repo_root_is_source_tree() -> None:
    assert (_REPO_ROOT / "pyproject.toml").exists()
