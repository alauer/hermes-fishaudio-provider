from __future__ import annotations

import shutil
from pathlib import Path


def test_plugin_manager_dispatch_and_voice_contract(tmp_path: Path, monkeypatch):
    """Real Hermes PluginManager → TTS registry → dispatcher pipeline.

    This is the most important acceptance gate: it copies the plugin into a
    temporary ``HERMES_HOME``, asks Hermes's ``PluginManager`` to discover it,
    and exercises the full ``tools.tts_tool_plugins._dispatch_to_plugin_provider``
    path with the registered provider. No mocks at this layer — the point is
    to prove the canonical layout (``__init__.py`` + ``provider.py`` + a flat
    ``plugin.yaml`` at the repo root) is what Hermes actually loads.

    The manifest ``name`` is ``fishaudio-tts`` (kept for backward compatibility
    with xiaoyaner-era operators); the canonical Palace project URL
    (``alauer/hermes-fishaudio-provider``) lives in ``pyproject.toml`` and the
    README badges. The runtime provider name ``fishaudio`` is unchanged.
    """
    from agent import tts_registry
    from hermes_cli.plugins import PluginManager
    from tools import tts_tool

    source = Path(__file__).resolve().parents[1]
    home = tmp_path / "hermes-home"
    target = home / "plugins" / "fishaudio-tts"
    shutil.copytree(
        source, target,
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", ".venv", "*.egg-info"),
    )
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
        assert loaded is not None, (
            f"plugin not discovered; available keys: {list(manager._plugins)}"
        )
        assert loaded.enabled is True, getattr(loaded, "error", None)
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

        output_path = str(tmp_path / "fishaudio-integration.mp3")
        assert tts_tool._dispatch_to_plugin_provider(
            text="Hermes PluginManager integration",
            output_path=output_path,
            provider="fishaudio",
            tts_config={},
        ) == output_path
        assert tts_tool._plugin_provider_is_voice_compatible("fishaudio") is True
    finally:
        tts_registry._reset_for_tests()


def test_plugin_loads_under_canonical_directory_name(tmp_path: Path, monkeypatch):
    """The plugin also loads when installed under the canonical directory name.

    Some operators prefer a directory called ``fishaudio-provider`` to match
    the GitHub repo slug. The same plugin.yaml (manifest name ``fishaudio-tts``)
    must still load — Hermes's discovery is keyed on the manifest name, not
    the directory name, so this is the same code path as
    ``test_plugin_manager_dispatch_and_voice_contract`` but with a different
    install directory. Verifies both install paths are first-class.
    """
    from agent import tts_registry
    from hermes_cli.plugins import PluginManager

    source = Path(__file__).resolve().parents[1]
    home = tmp_path / "hermes-home-canonical"
    target = home / "plugins" / "fishaudio-provider"
    shutil.copytree(
        source, target,
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", ".venv", "*.egg-info"),
    )
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
        assert loaded is not None, (
            f"plugin not discovered; available keys: {list(manager._plugins)}"
        )
        assert loaded.enabled is True, getattr(loaded, "error", None)
        provider = tts_registry.get_provider("fishaudio")
        assert provider is not None
        assert provider.name == "fishaudio"
    finally:
        tts_registry._reset_for_tests()