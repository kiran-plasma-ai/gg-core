"""Tests for doctor PATH-mechanism reporting."""

from __future__ import annotations

import importlib

import pytest

run_mod = importlib.import_module("gg_core.cli.run")


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(run_mod.Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


class TestPathMechanism:
    def test_neither_when_nothing_installed(self, fake_home) -> None:
        mech, missing = run_mod._path_mechanism(fake_home)
        assert mech == "neither"
        assert len(missing) == 2

    def test_rc_block_detected(self, fake_home) -> None:
        (fake_home / ".zshenv").write_text(
            "# >>> gg-core PATH >>>\nexport PATH=...\n# <<< gg-core PATH <<<\n"
        )
        mech, missing = run_mod._path_mechanism(fake_home)
        assert mech.startswith("rc block")
        assert str(fake_home / ".zshenv") in mech
        assert missing == []

    def test_symlink_detected(self, fake_home, tmp_path) -> None:
        link = tmp_path / "gg"
        link.symlink_to("/home/u/.local/bin/gg")
        mech, _ = run_mod._path_mechanism(fake_home, symlink=link)
        assert mech.startswith("symlink")
        assert "-> /home/u/.local/bin/gg" in mech
