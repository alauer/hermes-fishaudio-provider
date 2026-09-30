"""Test-only helper that loads the repo-root ``__init__.py`` as a plain module.

The plugin's canonical layout places ``__init__.py`` and ``provider.py``
at the repo root (no surrounding package). For the directory-copy plugin
path, ``hermes plugins install <ref>`` copies this layout verbatim and
expects the plugin to register itself through ``plugin.register()``.
For the pip entry-point path, the ``hermes_agent.plugins`` entry point
resolves to ``provider:register`` and is loaded by setuptools as a top-level
module.

Either way, the test suite needs to load this layout as an importable
module. This fixture mimics what ``hermes_cli.plugins.PluginManager`` does
when it discovers the plugin in a temporary ``HERMES_HOME``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def pytest_configure(config):
    """Put the plugin root on ``sys.path`` so ``from provider import ...`` works.

    The plugin's ``__init__.py`` does a top-level ``from provider import ...``;
    in a real install ``provider`` is a top-level module (py-modules), so it
    works. In a test run, the tests directory is on ``sys.path`` but not the
    repo root; add the repo root so the plugin's own imports resolve.
    """
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)


@pytest.fixture(scope="session")
def plugin_module(plugin_root: Path):
    """Load the repo-root ``__init__.py`` as a plain importable module."""
    name = "hermes_fishaudio_provider_testplugin"
    spec = importlib.util.spec_from_file_location(
        name,
        plugin_root / "__init__.py",
        submodule_search_locations=[str(plugin_root)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def provider_module(plugin_module, plugin_root):
    """The ``provider`` module as a plain importable Python module.

    Used by tests that exercise pure helpers (``_sanitize_extra``,
    ``_build_body``, ``_redact``, ``_https_enforced``, ...) directly,
    without going through the plugin's ``register()`` entry point.
    """
    name = "hermes_fishaudio_provider_testprovider"
    spec = importlib.util.spec_from_file_location(
        name,
        str(plugin_root / "provider.py"),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Make sure each test starts with a known-empty Fish Audio env.

    Tests that need a key set it explicitly. This guarantees no real key
    leaks into a test by accident and no real network call is made.
    """
    for var in ("FISH_AUDIO_API_KEY", "FISHAUDIO_API_KEY", "FISH_API_KEY",
                "FISH_AUDIO_API_BASE"):
        monkeypatch.delenv(var, raising=False)
    yield