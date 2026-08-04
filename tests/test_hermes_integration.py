from __future__ import annotations

import shutil
from pathlib import Path


def test_v020_plugin_manager_dispatch_and_voice_contract(tmp_path: Path, monkeypatch):
    from agent import tts_registry
    from hermes_cli.plugins import PluginManager
    from tools import tts_tool

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
        monkeypatch.setattr(
            provider,
            "synthesize",
            lambda text, output_path, **kwargs: output_path,
        )
        # PluginManager above already completed discovery and registered the
        # exact provider under test. Dispatch normally calls the process-global
        # discovery helper as a safety net; in this isolated test that would
        # create a second manager and replace the patched provider instance.
        monkeypatch.setattr(
            "hermes_cli.plugins._ensure_plugins_discovered",
            lambda *args, **kwargs: None,
        )
        output_path = str(tmp_path / "fishaudio-v020.mp3")
        assert tts_tool._dispatch_to_plugin_provider(
            text="Hermes v0.20 compatibility",
            output_path=output_path,
            provider="fishaudio",
            tts_config={},
        ) == output_path
        assert tts_tool._plugin_provider_is_voice_compatible("fishaudio") is True
    finally:
        tts_registry._reset_for_tests()
