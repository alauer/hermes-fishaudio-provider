from __future__ import annotations

import shutil
from pathlib import Path


def test_plugin_manager_loads_native_provider(tmp_path: Path, monkeypatch):
    from agent import tts_registry
    from hermes_cli.plugins import PluginManager

    source = Path(__file__).resolve().parents[1]
    home = tmp_path / "hermes-home"
    target = home / "plugins" / "fishaudio-tts"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__"))
    (home / "config.yaml").write_text(
        """plugins:
  enabled:
    - fishaudio-tts
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    tts_registry._reset_for_tests()
    try:
        manager = PluginManager()
        manager.discover_and_load(force=True)
        loaded = manager._plugins.get("fishaudio-tts")
        assert loaded is not None
        assert loaded.enabled is True, loaded.error
        provider = tts_registry.get_provider("fishaudio")
        assert provider is not None
        assert provider.name == "fishaudio"
    finally:
        tts_registry._reset_for_tests()
