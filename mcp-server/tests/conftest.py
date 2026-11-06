"""Keeps every test away from the user's real ~/.config/unizo-ctem-mcp (active environment, environments file)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_home = tmp_path / "config"
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("UNIZO_CTEM_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.delenv("UNIZO_CTEM_ENVIRONMENTS_FILE", raising=False)
    return tmp_path
