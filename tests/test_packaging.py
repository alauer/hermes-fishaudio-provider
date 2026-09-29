from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 fallback
    import tomli as tomllib


def _load(name: str, path: Path):
    """Load a plain Python file as an importable module named *name*."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_root_init_imports_without_package_context():
    """Pytest/importlib may load the repo-root ``__init__.py`` as a plain module.

    The directory-copy plugin path uses this layout verbatim — ``__init__.py``
    and ``provider.py`` sit at the repo root, no surrounding package.
    """
    root = Path(__file__).resolve().parents[1]
    module = _load("fishaudio_plain_init", root / "__init__.py")
    assert module.FishAudioTTSProvider().name == "fishaudio"
    assert callable(module.register)


def test_provider_module_is_also_loadable_directly():
    """The pip entry-point path installs ``provider.py`` as a top-level module.

    ``pyproject.toml`` declares ``provider:register`` under the
    ``hermes_agent.plugins`` entry point group, so the file must be
    independently importable as a top-level module.
    """
    root = Path(__file__).resolve().parents[1]
    provider = _load("hermes_fishaudio_provider_packaging_probe", root / "provider.py")
    assert provider.FishAudioTTSProvider().name == "fishaudio"
    assert callable(provider.register)


def test_root_register_uses_native_provider_hook():
    """``register()`` must call ``ctx.register_tts_provider()`` exactly once."""
    root = Path(__file__).resolve().parents[1]
    module = _load("fishaudio_plain_init_register_probe", root / "__init__.py")
    registered = []

    class Context:
        def register_tts_provider(self, provider):
            registered.append(provider)

    module.register(Context())
    assert len(registered) == 1
    assert registered[0].name == "fishaudio"


def test_pyproject_declares_hermes_plugin_entrypoints():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    entrypoints = pyproject["project"]["entry-points"]["hermes_agent.plugins"]
    # Canonical Palace-maintained entry point.
    assert entrypoints["fishaudio-provider"] == "provider:register"
    # Backwards-compatible alias for legacy ``fishaudio-tts`` installs.
    assert entrypoints["fishaudio-tts"] == "provider:register"


def test_pyproject_module_target_is_loadable():
    """The entry-point target must point at a real, importable symbol."""
    root = Path(__file__).resolve().parents[1]
    provider = _load("provider", root / "provider.py")
    assert callable(provider.register)


def test_pyproject_metadata_renamed_to_alauer_slug():
    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    project = pyproject["project"]
    urls = project["urls"]
    assert project["name"] == "hermes-fishaudio-provider"
    assert "alauer/hermes-fishaudio-provider" in urls["Homepage"]
    assert "alauer/hermes-fishaudio-provider" in urls["Repository"]


def test_no_dual_init_packaging():
    """The legacy ``hermes_fishaudio_tts/__init__.py`` package wrapper is gone.

    Keeping it would split the canonical implementation across two files and
    force tests to load both — the issue explicitly requires one canonical
    implementation that works for both install paths.
    """
    root = Path(__file__).resolve().parents[1]
    assert not (root / "hermes_fishaudio_tts").exists(), (
        "legacy hermes_fishaudio_tts package directory must not exist; "
        "the canonical layout is root __init__.py + provider.py"
    )