from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


def test_root_init_imports_without_package_context():
    """Pytest/importlib may load repo-root __init__.py as a plain module."""
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("fishaudio_plain_init", root / "__init__.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["fishaudio_plain_init"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.FishAudioTTSProvider().name == "fishaudio"
    assert callable(module.register)


def test_entrypoint_package_registers_native_provider():
    package = importlib.import_module("hermes_fishaudio_tts")
    assert package.FishAudioTTSProvider().name == "fishaudio"

    registered = []

    class Context:
        def register_tts_provider(self, provider):
            registered.append(provider)

    package.register(Context())
    assert len(registered) == 1
    assert registered[0].name == "fishaudio"


def test_pyproject_declares_hermes_plugin_entrypoint():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    entrypoints = pyproject["project"]["entry-points"]["hermes_agent.plugins"]
    assert entrypoints["fishaudio-tts"] == "hermes_fishaudio_tts"
