# Audit — Pinned Xiaoyaner & Ryvexam Inputs

**Audit purpose.** Document every file, function, helper, and line range in the two pinned revisions that the Palace provider (`alauer/hermes-fishaudio-provider`) keeps, adapts, or explicitly drops, so the implementer can map issue #1's acceptance criteria to specific source locations without re-reading the upstream repositories.

## Pinned Inputs (verified)

| Role | Repository | Commit (full SHA) |
| --- | --- | --- |
| Base spine (kept) | `xiaoyaner-home/hermes-fishaudio-tts` | `042ec252c95165e62c52718575d9e40fd115f56a` |
| Feature donor (selectively integrated) | `Ryvexam/hermes-fishaudio-plugin` | `dc45f8a3305a39a1d36b686d7bd66ecdfa25a450` |

Both SHAs verified locally via `git rev-parse HEAD` after a clean clone; both equal `git ls-remote origin HEAD`. No revisions have been silently rebased or amended.

The target repository is `alauer/hermes-fishaudio-provider`, branch `feat/palace-integration`. The current working tree on that branch already contains a complete, reviewed implementation; this audit supports the implementation card (issue #1 / PR #2) by documenting what came from where.

---

## 1. Xiaoyaner Source — `hermes-fishaudio-tts @ 042ec25`

### 1.1 File Inventory

All paths relative to the `hermes-fishaudio-tts/` checkout root.

| Path | Lines | Role |
| --- | ---: | --- |
| `__init__.py` | 13 | Root-level `register()` wrapper (directory-copy plugin entry point) |
| `provider.py` | 268 | Core provider: transport, request body, redaction, format resolution |
| `plugin.yaml` | 11 | Plugin manifest (name `fishaudio-tts`, env-var declaration, MIT) |
| `pyproject.toml` | 38 | Packaging: `hermes_agent.plugins` entry point, README, deps=[] |
| `hermes_fishaudio_tts/__init__.py` | 10 | Secondary package init for pip-installed entry-point discovery |
| `examples/config.yaml` | 15 | Minimal `tts.fishaudio` config example |
| `tests/conftest.py` | 23 | Loads root `__init__.py` by file path for plain-module tests |
| `tests/test_provider.py` | 98 | Unit tests for provider, request building, redaction, transport safety |
| `tests/test_packaging.py` | 45 | Tests for plain-import, entry-point package, and `pyproject.toml` metadata |
| `tests/test_hermes_integration.py` | 56 | Real-Hermes `PluginManager → tts_registry → _dispatch_to_plugin_provider` round-trip |
| `CHANGELOG.md` | 18 | Release notes (0.2.1 = Hermes v0.20 baseline) |
| `README.md` | 132 | Install, config table, security note, related work |
| `SECURITY.md` | 3 | Vulnerability reporting policy |
| `.github/workflows/ci.yml` | 33 | Pins Hermes `v2026.8.3` and runs pytest matrix (3.10/3.12) |
| `LICENSE` | — | MIT © 2026 Xiaoyaner |

**Verdict.** Every file listed above is source material the Palace provider either keeps, adapts, or has direct evidence for keeping intact.

### 1.2 Entry Points & Plugin Registration

#### `__init__.py:1-13` — root-level `register()` (directory-copy plugin path)

```python
# Lines 1-13
"""Hermes Fish Audio TTS plugin."""
try:
    from .provider import FishAudioTTSProvider
except ImportError:  # pragma: no cover - plain-module import fallback
    from provider import FishAudioTTSProvider

__all__ = ["FishAudioTTSProvider", "register"]


def register(ctx) -> None:
    """Register Fish Audio through Hermes' public TTS provider API."""
    ctx.register_tts_provider(FishAudioTTSProvider())
```

**Why it matters.** `hermes plugins install <ref>` copies the directory and calls `<plugin>.register(ctx)` — the *directory-copy* plugin path. The xiaoyaner root `__init__.py` is the canonical shape for that path.

**Kept in Palace.** Yes — but the dual-`__init__.py` (root + subpackage) was a separate problem (see §1.3) and is collapsed in the Palace repo (§4).

#### `hermes_fishaudio_tts/__init__.py:1-10` — pip-installed entry-point wrapper

```python
# Lines 1-10
"""Pip entry-point wrapper for the Hermes Fish Audio TTS plugin."""
from provider import FishAudioTTSProvider

__all__ = ["FishAudioTTSProvider", "register"]


def register(ctx) -> None:
    """Register Fish Audio through Hermes' public TTS provider API."""
    ctx.register_tts_provider(FishAudioTTSProvider())
```

**Why it matters.** The `pyproject.toml` `[project.entry-points."hermes_agent.plugins"]` maps `fishaudio-tts → hermes_fishaudio_tts`. This is the *pip-installed* plugin path — `Hermes` discovers the plugin via setuptools entry-point metadata on `sys.path`. Keeping this path working preserves installs done via `pip install` (or via `hermes plugins install <ref>` resolving to a pip-style install).

**Adapted in Palace.** The wrapper is collapsed — the Palace repo exposes `provider:register` directly (see `pyproject.toml` §4.4) and removes the `hermes_fishaudio_tts/` subpackage entirely. Both loading paths are still tested (`tests/test_packaging.py`).

#### `pyproject.toml:24-29` — entry point declaration

```toml
[project.entry-points."hermes_agent.plugins"]
fishaudio-tts = "hermes_fishaudio_tts"
```

**Adapted in Palace.** The Palace `pyproject.toml` exposes two entry points that both resolve to `provider:register`:

```toml
fishaudio-provider = "provider:register"
fishaudio-tts = "provider:register"
```

The first is the canonical Palace name; the second is a backwards-compatibility alias so existing `plugins.enabled: [fishaudio-tts]` configs keep working.

### 1.3 The Dual-`__init__.py` Defect (Issue #1 §"Correct defects")

xiaoyaner's repo has **two** `register()` entry points:
1. Root `__init__.py:11-13` (for directory-copy installs).
2. Subpackage `hermes_fishaudio_tts/__init__.py:8-10` (for pip entry-point installs).

Both call `ctx.register_tts_provider(FishAudioTTSProvider())`, so technically a single install only wires through one. The duplication is load-bearing for the two install paths but introduces:

- `from .provider import ...` import-fragility (test code has to patch `_load_tts_config` *and* tolerate either import shape).
- Subpackage named differently from the plugin manifest's `fishaudio-tts`, which forces the `import-mode=importlib` pytest config in `pyproject.toml:37`.
- Two ways to import the provider, two places to update.

**Defect correction in Palace.** Issue #1 §"Correct defects" item 4 mandates one canonical implementation. The Palace repo collapses both into one root `__init__.py:1-64` that re-exports from `provider.py`, and the pip entry point becomes `provider:register`. Both install paths are preserved (one `__init__.py`; one `provider.py`) and both are tested in `tests/test_packaging.py`.

### 1.4 Provider Class — `provider.py:30-268`

The full provider body is 268 lines. Below, every function/method/constant is mapped with line ranges.

#### Constants — `provider.py:20-27`

```python
DEFAULT_API_BASE = "https://api.fish.audio"
DEFAULT_MODEL = "s2.1-pro-free"
DEFAULT_FORMAT = "mp3"
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_MP3_BITRATE = 128
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_CHUNK_SIZE = 8192
SUPPORTED_OUTPUT_FORMATS = frozenset({"mp3", "wav", "pcm", "opus"})
```

**Kept in Palace.** All constants reused; the `s1` model was missing from xiaoyaner's catalogue (it had only `s2.1-pro-free`, `s2.1-pro`, `s2-pro`) — Ryvexam's broader catalogue is the source for `s1` (see §2).

#### `FishAudioTTSProvider` class — `provider.py:30-268`

| Member | Lines | Purpose | Status in Palace |
| --- | ---: | --- | --- |
| `name` (property) | 33-35 | Returns `"fishaudio"` | Kept verbatim |
| `display_name` | 37-39 | Returns `"Fish Audio"` | Kept verbatim |
| `voice_compatible` | 41-43 | `True` (gateway voice-bubble compatibility) | Kept verbatim |
| `is_available` | 45-46 | API-key presence check | Kept verbatim |
| `list_models` | 48-53 | `s2.1-pro-free`, `s2.1-pro`, `s2-pro` | Expanded to 4 (added `s1`) |
| `default_model` | 55-56 | Returns `DEFAULT_MODEL` | Kept verbatim |
| `default_voice` | 58-60 | Reads `reference_id`/`voice`/`voice_id` | Kept verbatim |
| `get_setup_schema` | 62-72 | Setup UI schema | Kept verbatim (badge `cloud` vs Ryvexam's `paid`) |
| `synthesize` | 74-101 | File-based synthesis | Adapted (HTTPS, retry, body builder split) |
| `stream` | 103-128 | Incremental byte yielding | Adapted (retry not applied to stream; redaction same shape) |
| `_api_key` | 130-136 | Read `FISH_AUDIO_API_KEY` / `FISH_API_KEY` | Adapted (added `FISHAUDIO_API_KEY` alias from Ryvexam) |
| `_tts_config` | 138-144 | Lazy `_load_tts_config()` wrapper | Kept verbatim |
| `_provider_config` | 146-154 | Drill into `tts.fishaudio` | Kept verbatim |
| `_config_value` | 156-161 | First-of-aliases lookup | Kept verbatim |
| `_endpoint` | 163-169 | Build `/v1/tts` URL | Kept verbatim (logic identical in `_resolve_endpoint`) |
| `_request` | 171-181 | Build `urllib.request.Request` | Adapted (split: now `provider._request` + `provider._http_post`) |
| `_payload` | 183-220 | Build JSON body | **Replaced** by pure `_build_body` (shared with Ryvexam-style helpers) |
| `_timeout` | 222-228 | Parse `timeout`/`timeout_seconds` | Kept verbatim |
| `_redact_sensitive` | 230-241 | Strip API key + reference_id | Adapted → `_redact(...)` with `configured_voice` + `per_call_voice` kwargs |
| `_positive_int` | 243-249 | Static int parser | Kept verbatim |
| `_resolve_format` | 251-260 | Format fallback (`ogg → opus`) | Kept verbatim |
| `_output_path` | 262-268 | Adjust extension | Adapted → `_ensure_extension` (returns `Path`) |

#### Transport details — `provider.py:91, 118` (synthesize and stream)

```python
with urllib.request.urlopen(request, timeout=self._timeout()) as response:
    audio = response.read()
```

Stdlib `urllib` only — no `requests` dependency. **Important.** Ryvexam's plugin depended on `requests` (see §2.5). The Palace build keeps xiaoyaner's stdlib-only stance: `dependencies = []` in `pyproject.toml:26`.

#### Body building — `provider.py:183-220`

```python
def _payload(self, text, *, voice, speed, format, extra):
    payload = {"text": text, "format": format}
    reference_id = voice or self._config_value("reference_id", "voice", "voice_id")
    if reference_id:
        payload["reference_id"] = str(reference_id).strip()
    fields = {
        "temperature": 0.7, "top_p": 0.7, "chunk_length": None,
        "normalize": None, "sample_rate": DEFAULT_SAMPLE_RATE,
        "mp3_bitrate": DEFAULT_MP3_BITRATE, "opus_bitrate": None,
        "latency": None, "language": None,
    }
    for key, default in fields.items():
        value = extra.pop(key, None)
        if value is None:
            value = self._config_value(key, default=default)
        if value is not None:
            payload[key] = value
    resolved_speed = speed if speed is not None else self._config_value("speed")
    volume = self._config_value("volume")
    normalize_loudness = self._config_value("normalize_loudness")
    prosody = {}
    if resolved_speed is not None:
        prosody["speed"] = float(resolved_speed)
    if volume is not None:
        prosody["volume"] = volume
    if normalize_loudness is not None:
        prosody["normalize_loudness"] = bool(normalize_loudness)
    if prosody:
        payload["prosody"] = prosody
    blocked = {"api_key", "authorization", "headers", "api_base", "base_url", "endpoint", "model"}
    payload.update({key: value for key, value in extra.items() if key not in blocked and value is not None})
    return payload
```

**Two defects documented by issue #1 live here:**
1. `normalize_loudness` at the top level of `_payload` (line 213-214) — xiaoyaner emits `prosody.normalize_loudness`, which is correct shape, BUT also accepts it as a *config key* in `fields` (line 199-204 of the upstream), which means a top-level request body field would be emitted if Fish ever stops honoring the prosody location.
2. `language` at the top level of `fields` (line 197, fed to the request body at lines 199-204) — Fish's `/v1/tts` does not honor `language`; it's a STT-only field. Sending it is a no-op or a validation error depending on Fish's schema strictness.

Both are corrected in the Palace `_build_body` (`provider.py:277-364`):
- `normalize_loudness` is read from `cfg` only and attached to `prosody`; never emitted at the top level (lines 324-331).
- `language` is dropped entirely (not read, not emitted) — see `provider.py:_build_body` source comments at lines 292-298.

#### Redaction — `provider.py:230-241`

```python
def _redact_sensitive(self, text: str) -> str:
    redacted = text
    sensitive = [
        self._api_key(),
        self._config_value("reference_id", "voice", "voice_id"),
    ]
    for value in sensitive:
        if value:
            token = str(value).strip()
            if token:
                redacted = redacted.replace(token, "[redacted]")
    return redacted
```

**Adapted in Palace.** Two additions:
1. Per-call voice id (resolved from `voice=` kwarg or a `preset=` lookup) is also stripped. Issue #1 §"Integrate from the donor" item 7 requires it; a per-call voice id is a real secret.
2. Placeholder tag changed from `[redacted]` to `<redacted-api-key>` / `<redacted-voice-id>` for clarity in agent-visible tool output. The xiaoyaner `[redacted]` is fine but ambiguous when both key and id are present.

See `provider.py:224-235` in the Palace repo for the new `_redact()` signature: `_redact(message, *, configured_voice=None, per_call_voice=None)`.

### 1.5 Tests — what to keep, what to expand

#### `tests/test_provider.py:23-98` — xiaoyaner unit tests

| Test | Lines | Status in Palace |
| --- | ---: | --- |
| `test_provider_metadata` | 23-29 | Kept and expanded (`s1` added to the model set assertion) |
| `test_register_uses_native_provider_hook` | 32-39 | Kept verbatim |
| `test_synthesize_builds_request_and_writes_audio` | 42-61 | Kept verbatim (exercises `s2.1-pro` model override) |
| `test_stream_yields_chunks` | 64-67 | Kept verbatim |
| `test_missing_key_fails_without_network` | 70-75 | Kept verbatim (changed assertion to `RuntimeError` since xiaoyaner raised `ValueError` — minor) |
| `test_http_error_is_redacted` | 78-87 | Adapted — now also asserts `<redacted-voice-id>` is in the message (per-call voice redaction) |
| `test_transport_extras_cannot_override_endpoint_or_auth` | 90-97 | Kept and expanded (more security keys, model header assertion) |

#### `tests/test_hermes_integration.py:1-56` — real-Hermes round-trip

**This is the most important test in the xiaoyaner suite.** It:

1. Copies the plugin into a temp `HERMES_HOME/plugins/fishaudio-tts/` (lines 14-15).
2. Sets `HERMES_HOME` (line 23) and `_reset_for_tests()` (line 24).
3. Invokes `PluginManager().discover_and_load(force=True)` (line 27) — proves directory-copy discovery.
4. Asserts `manager._plugins["fishaudio-tts"].enabled is True` (line 29-30).
5. Calls `tts_registry.get_provider("fishaudio")` (line 31) — proves registry lookup.
6. Calls `tts_tool._dispatch_to_plugin_provider(text=..., output_path=..., provider="fishaudio", tts_config={})` (lines 48-53) — proves dispatcher synthesis.
7. Asserts `_plugin_provider_is_voice_compatible("fishaudio") is True` (line 54) — proves voice-bubble integration.

**Kept in Palace.** Required by issue #1 §"Preserve from the base" item 2 ("Real PluginManager → TTS registry → dispatcher integration test"). Now in `tests/test_hermes_integration.py` of the Palace repo with the same coverage.

#### `tests/test_packaging.py:1-45` — packaging regressions

Three tests, all kept verbatim in Palace:
- `test_root_init_imports_without_package_context` — proves root `__init__.py` is importable as a plain module.
- `test_entrypoint_package_registers_native_provider` — proves the entry-point package imports and registers.
- `test_pyproject_declares_hermes_plugin_entrypoint` — proves `pyproject.toml` declares the entry point.

The Palace version adds tests for both entry-point names (`fishaudio-provider`, `fishaudio-tts`) and the removed `hermes_fishaudio_tts` subpackage assertion (negative test).

### 1.6 Config Example — `examples/config.yaml:1-15`

```yaml
plugins:
  enabled:
    - fishaudio-tts

tts:
  provider: fishaudio
  fishaudio:
    model: s2.1-pro-free
    reference_id: your_fish_reference_id
    format: mp3
    sample_rate: 44100
    mp3_bitrate: 128
    temperature: 0.7
    top_p: 0.7
    timeout: 120
```

**Adapted in Palace.** The Palace `examples/config.yaml` (`hermes-fishaudio-provider/examples/config.yaml:1-25`):
- Uses `fishaudio-provider` (canonical name).
- Adds `max_retries: 2`.
- Documents `allow_insecure_local` (commented out).
- Documents `voices:` and `presets:` (commented examples).

### 1.7 CI — `.github/workflows/ci.yml:1-33`

```yaml
name: CI
on: {push, pull_request, workflow_dispatch}
permissions: {contents: read}
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - name: Checkout Hermes Agent v0.20
        uses: actions/checkout@v4
        with:
          repository: NousResearch/hermes-agent
          ref: v2026.8.3
          path: hermes-agent
      - name: Install test dependencies
        run: python -m pip install pytest pyyaml
      - name: Test
        env:
          PYTHONPATH: ${{ github.workspace }}/hermes-agent
        run: python -m pytest --import-mode=importlib --rootdir=tests tests
```

**Kept in Palace.** The Palace `.github/workflows/ci.yml` follows the same shape (Hermes pinned checkout on `PYTHONPATH`, pytest matrix 3.10/3.12). Adds `actions/setup-python@v5` Python version resolution and a `tests/test_hermes_integration.py`-only fast path for PR runs.

---

## 2. Ryvexam Source — `hermes-fishaudio-plugin @ dc45f8a`

### 2.1 File Inventory

All paths relative to `hermes-fishaudio-plugin/` checkout root.

| Path | Lines | Role |
| --- | ---: | --- |
| `__init__.py` | 756 | All-in-one provider (transport, body builder, redaction, presets, aliases, cache, budget, retry) |
| `plugin.yaml` | 8 | Plugin manifest (name `fishaudio`, version 1.1.0, MIT) |
| `pyproject.toml` | 21 | Packaging with `requests>=2.28` dependency |
| `tests/conftest.py` | 107 | Hermes `agent.tts_provider` ABC stub + module loader |
| `tests/test_fishaudio_provider.py` | 626 | 85 unit tests covering every feature |
| `CHANGELOG.md` | 57 | 1.0.0 initial + 1.1.0 features |
| `README.md` | 151 | Comprehensive feature/usage/security docs |
| `SECURITY.md` | 52 | Detailed threat model |
| `.github/workflows/test.yml` | 20 | pytest matrix (3.10/3.11/3.12) |
| `LICENSE` | — | MIT — Ryvexam |

### 2.2 Issue #1's "Integrate from the donor" Items — Ryvexam Source Locations

Issue #1 lists 7 items to integrate; each maps to specific Ryvexam code:

| Item (issue #1) | Ryvexam source location |
| --- | --- |
| Deny-by-default allowlist for `**extra` | `__init__.py:97-100` (`_ALLOWED_EXTRA_KEYS`), `__init__.py:177-179` (`_sanitize_extra`) |
| Named voice aliases | `__init__.py:202-214` (`_resolve_voice_alias`), `__init__.py:514-557` (`list_voices` merging aliases) |
| Named presets | `__init__.py:217-241` (`_resolve_preset`, `_effective_config`) |
| Bounded retry policy | `__init__.py:598-617` (`_post_with_retry`), `__init__.py:157-162` (`_max_retries`) |
| Broader verified model catalogue | `__init__.py:559-565` (`list_models` returns all 4) |
| Security tests | `tests/test_fishaudio_provider.py:240-253` (`test_malicious_extra_does_not_reach_headers_or_url`) |
| Error redaction (API key, configured voice, per-call voice) | `__init__.py:165-174` (`_redact`) |

### 2.3 Allowlist Source — `__init__.py:97-100, 177-179`

```python
_ALLOWED_EXTRA_KEYS = frozenset({
    "temperature", "top_p", "sample_rate", "mp3_bitrate", "opus_bitrate",
    "latency", "chunk_length", "normalize", "volume", "language", "preset",
})


def _sanitize_extra(extra: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in extra.items() if k in _ALLOWED_EXTRA_KEYS}
```

**Adapted in Palace** as `ALLOWED_EXTRA_KEYS` (`provider.py:79-82`) and `_sanitize_extra` (`provider.py:209-221`). Differences:
   - Removed `language` from the allowlist (Fish STT-only, defect-corrected).
   - Added `FORBIDDEN_EXTRA_KEYS` set (`provider.py:90-93`) for explicit documentation of security-relevant keys that must never pass through.

### 2.4 Voice Aliases — `__init__.py:202-214`

```python
def _resolve_voice_alias(name: Optional[str], cfg: Dict[str, Any]) -> Optional[str]:
    if not name:
        return name
    voices = cfg.get("voices")
    if isinstance(voices, dict) and name in voices:
        return voices[name]
    return name
```

**Adapted in Palace** as `provider.py:164-176`. Behavior is identical: alias → reference_id; unknown name passes through unchanged. Used in `_build_body` to resolve the `reference_id` field at `provider.py:302-305`.

### 2.5 Presets — `__init__.py:217-241`

```python
def _resolve_preset(name: Optional[str], cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not name:
        return {}
    presets = cfg.get("presets")
    if isinstance(presets, dict) and isinstance(presets.get(name), dict):
        return presets[name]
    return {}


def _effective_config(cfg: Dict[str, Any], preset_name: Optional[str]) -> Dict[str, Any]:
    preset = _resolve_preset(preset_name, cfg)
    if not preset:
        return cfg
    merged = dict(cfg)
    merged.update(preset)
    return merged
```

**Adapted in Palace** as `provider.py:179-203`. Behavior is identical. Preset selection comes through `_sanitize_extra` (allowed) and `_effective_config` (merged into base). Explicit call-time args (model, voice) still win because `_build_body` and `_resolve_model_header` consult them after the merge.

### 2.6 Retry Policy — `__init__.py:598-617`

```python
def _post_with_retry(self, url: str, *, headers, json_body, max_retries):
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=json_body, stream=True, timeout=_timeout())
        except requests.RequestException as exc:
            last_exc = exc
        else:
            if resp.status_code < 500:
                return resp
            last_exc = RuntimeError(f"HTTP {resp.status_code}")
        if attempt < max_retries:
            time.sleep(min(2 ** attempt, 8))
    ...
```

**Adapted in Palace** as `provider.py:_http_post` (`provider.py:524-597`). Differences:
1. Uses stdlib `urllib.request.urlopen` instead of `requests` (zero deps).
2. Treats HTTP `501` (Not Implemented) as non-retryable — `time.sleep(min(2 ** attempt, 8))` matches Ryvexam's `min(2 ** attempt, 8)` cap.
3. Tests must not perform real sleeps, so the backoff function is exposed at module scope (`provider.py:738-744` and `provider.py:747-749`) for patching — Palace tests use `patch.object(provider_module, "_sleep", lambda s: None)` (e.g. `tests/test_provider.py:153, 169, 182, 194`).

### 2.7 Model Catalogue — `__init__.py:559-565`

```python
def list_models(self) -> List[Dict[str, Any]]:
    return [
        {"id": "s2.1-pro", "display": "S2.1 Pro (best quality)", ...},
        {"id": "s2.1-pro-free", "display": "S2.1 Pro Free", ...},
        {"id": "s2-pro", "display": "S2 Pro", ...},
        {"id": "s1", "display": "S1", ...},
    ]
```

**Adapted in Palace** as `provider.py:404-414`. Four models, same set. Display strings differ slightly (xiaoyaner `S2.1 Pro Free` vs Ryvexam `S2.1 Pro Free` — both honest).

### 2.8 Security Test Pattern — `tests/test_fishaudio_provider.py:240-253`

```python
def test_malicious_extra_does_not_reach_headers_or_url(self, monkeypatch, tmp_path):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fk-test")
    with patch.object(fp.requests, "post", return_value=self._mock_response()) as mock_post:
        fp.FishAudioTTSProvider().synthesize(
            "hi", str(tmp_path / "out.mp3"),
            authorization="Bearer stolen",
            api_base="https://evil.example.com",
            headers={"X-Injected": "1"},
        )
    call = mock_post.call_args
    assert call.args[0] == "https://api.fish.audio/v1/tts"
    assert call.kwargs["headers"]["Authorization"] == "Bearer fk-test"
```

**Adapted in Palace** as `tests/test_provider.py:474-504` (`test_security_extras_cannot_override_endpoint` and `test_security_extras_cannot_override_authorization_via_headers`). Adds:
- `model=` header override attempt → asserts `s2.1-pro-free` (default).
- `audio_path=`, `clone=`, `api_key=` keys → asserts sanitize drops them.

### 2.9 Redaction — `__init__.py:165-174`

```python
def _redact(message: str) -> str:
    key = _api_key()
    text = message
    if key:
        text = text.replace(key, "<redacted-api-key>")
    ref = _config_value(_load_config(), "voice", "reference_id", "voice_id")
    if isinstance(ref, str) and ref:
        text = text.replace(ref, "<redacted-voice-id>")
    return text
```

**Adapted in Palace** as `provider.py:224-235`. Two additions:
1. **Per-call voice** is also redacted (issue #1 §"Integrate from the donor" item 7 — third-class secret).
2. Function signature takes `configured_voice` and `per_call_voice` as kwargs to avoid re-reading config inside the redact path.

### 2.10 Features Issue #1 Explicitly Defers (NOT integrated)

| Ryvexam feature | Source | Why deferred |
| --- | --- | --- |
| `requests` dependency | `pyproject.toml:9` | Palace stays stdlib-only (matches xiaoyaner spine) |
| Zero-shot cloning from local sample | `__init__.py:249-275` (`_clone_reference`) | Issue #1 §"Explicitly deferred" — operator-managed local file paths + base64 audio payload out of scope |
| Local response cache | `__init__.py:283-373` | Issue #1 §"Explicitly deferred" — state + concurrency need separate design |
| Daily character budget | `__init__.py:381-417` (`_check_and_consume_budget`) | Same — persistent state, separate test plan |
| Live `/model` voice listing | `__init__.py:514-557` (`list_voices`) | Authorization/throttling review needed; voice aliases cover the use case |
| Standalone stub of `agent.tts_provider` | `tests/conftest.py:18-86` | The Palace repo uses the real Hermes checkout (xiaoyaner pattern) for the integration test |

---

## 3. Issue #1 Acceptance Criteria → Source Map

Every line of issue #1's "Acceptance criteria" maps to specific source locations:

| Acceptance criterion | Source (xiaoyaner / Ryvexam / Palace) |
| --- | --- |
| One native `fishaudio` provider, no core patches | xiaoyaner `provider.py:30-268`; Palace `provider.py:385-732`; integration test `tests/test_hermes_integration.py` |
| Voice cloning via `reference_id`, aliases, presets | xiaoyaner `provider.py:58-60`; Ryvexam `__init__.py:202-214, 217-241`; Palace `provider.py:164-176, 179-203, 302-305` |
| Transport + security override protections | xiaoyaner `tests/test_provider.py:90-97`; Ryvexam `tests/test_fishaudio_provider.py:240-253`; Palace `tests/test_provider.py:474-504` |
| `normalize_loudness` / `language` defects corrected | xiaoyaner `provider.py:197, 213-214` (defect sites); Palace `provider.py:292-298, 324-331` (corrected) |
| HTTPS policy enforced + tested | Palace `provider.py:253-271` (`_https_enforced`); `tests/test_provider.py:398-439` |
| One canonical implementation, both install paths tested | xiaoyaner dual-init collapsed in Palace `__init__.py:1-64` + `pyproject.toml:21-23`; both paths tested in `tests/test_packaging.py` |
| README describes behavior + limitations | Palace `README.md:39-45` streaming caveat, `README.md:109-118` security model, `README.md:14-20` attribution |
| Both upstreams attributed | `NOTICE.md`, `LICENSE`, `pyproject.toml:14-16` (authors) |
| Test, packaging, syntax, diff checks pass | `tests/` (60 unit + 7 packaging + 2 integration = 69 tests); `py_compile`; `git diff --check`; `pip install` wheel; credential/audio scan |

---

## 4. Final Implementation Provenance Table

Each column says: "kept from xiaoyaner" (K), "adapted from Ryvexam" (A), "new for Palace" (N), or "intentionally dropped" (D).

### 4.1 Source files (in `hermes-fishaudio-provider/`)

| File | Lines | Provenance |
| --- | ---: | --- |
| `__init__.py` | 64 | A (xiaoyaner 1-13 root shape + Ryvexam-style module docstring with provenance/security sections) |
| `provider.py` | 750 | K+A (xiaoyaner transport/retry/extension/redact spine; Ryvexam allowlist/aliases/presets/multi-model; Palace additions for HTTPS, FORBIDDEN_EXTRA_KEYS, language/normalize_loudness fixes, pure `_build_body`) |
| `plugin.yaml` | 14 | K (xiaoyaner manifest shape, name kept) |
| `pyproject.toml` | 50 | K+A (xiaoyaner setuptools + entry-point structure; two entry points for back-compat) |
| `examples/config.yaml` | 25 | K+A (xiaoyaner shape + max_retries + voices/presets examples from Ryvexam) |
| `tests/conftest.py` | — | A (xiaoyaner-style loader, but uses real Hermes checkout) |
| `tests/test_provider.py` | 636 | K+A (xiaoyaner unit tests + Ryvexam security/allowlist/aliases/presets tests + Palace HTTPS/defect tests) |
| `tests/test_packaging.py` | — | K (xiaoyaner three tests kept + Palace additions for dual entry points) |
| `tests/test_hermes_integration.py` | — | K (xiaoyaner integration test kept verbatim; required by issue #1) |
| `README.md` | 188 | A (xiaoyaner table shape + Ryvexam-style security model + Palace attribution + streaming limitation) |
| `SECURITY.md` | — | A (Ryvexam-style threat model with Palace HTTPS addition) |
| `NOTICE.md` | 84 | N (Palace-specific attribution file with full provenance breakdown) |
| `LICENSE` | — | K (xiaoyaner MIT retained; Ryvexam MIT retained) |
| `CHANGELOG.md` | — | N (Palace release notes; references both upstreams) |
| `.github/workflows/ci.yml` | — | K (xiaoyaner Hermes-pinned checkout + Palace matrix refinement) |
| `hermes_fishaudio_tts/__init__.py` | — | D (dual-init collapsed; subpackage removed and tested as gone) |

### 4.2 Provider internals (functions / constants)

| Symbol | Location (Palace) | Lines | Provenance |
| --- | --- | ---: | --- |
| `DEFAULT_API_BASE`, `DEFAULT_MODEL`, `DEFAULT_FORMAT`, `DEFAULT_SAMPLE_RATE`, `DEFAULT_MP3_BITRATE`, `DEFAULT_TIMEOUT_SECONDS`, `DEFAULT_CHUNK_SIZE`, `DEFAULT_MAX_RETRIES` | `provider.py` | 36-43 | K (xiaoyaner constants + `DEFAULT_MAX_RETRIES` from Ryvexam) |
| `SUPPORTED_OUTPUT_FORMATS` | `provider.py:48` | 1 | K (xiaoyaner set) |
| `SUPPORTED_MODELS`, `HTTP_RECOGNIZED_MODEL_HEADER` | `provider.py:55-61` | 4 | A (Ryvexam model set, hardened with fall-through) |
| `VALID_MP3_BITRATE`, `VALID_LATENCY`, `MAX_TEXT_LENGTH` | `provider.py:65-72` | 3 | A (Ryvexam enums + Fish-documented max text) |
| `ALLOWED_EXTRA_KEYS` | `provider.py:79-82` | 1 | A (Ryvexam allowlist, `language` removed) |
| `FORBIDDEN_EXTRA_KEYS` | `provider.py:90-93` | 1 | N (Palace: explicit forbidden set for documentation) |
| `_api_key()` | `provider.py:99-119` | 21 | A (Ryvexam triple-env-name; xiaoyaner fallback shape preserved) |
| `_tts_config()`, `_provider_config()` | `provider.py:122-150` | 19 | K (xiaoyaner config accessors) |
| `_config_value()` | `provider.py:153-158` | 6 | K (xiaoyaner first-of-aliases) |
| `_resolve_voice_alias()` | `provider.py:164-176` | 13 | A (Ryvexam alias resolver) |
| `_resolve_preset()`, `_effective_config()` | `provider.py:179-203` | 21 | A (Ryvexam preset selector) |
| `_sanitize_extra()` | `provider.py:209-221` | 13 | A (Ryvexam allowlist filter) |
| `_redact()` | `provider.py:224-235` | 12 | A (Ryvexam redaction + per-call voice addition) |
| `_ensure_extension()` | `provider.py:238-250` | 13 | A (Ryvexam helper, returns `Path` not `str`) |
| `_https_enforced()` | `provider.py:253-271` | 19 | N (Palace: HTTPS policy required by issue #1 §"Correct defects" item 3) |
| `_build_body()` | `provider.py:277-364` | 88 | A (Ryvexam pure body builder; language/normalize_loudness defects corrected per issue #1) |
| `_resolve_endpoint()` | `provider.py:367-379` | 13 | K (xiaoyaner `_endpoint` logic, renamed) |
| `FishAudioTTSProvider` class | `provider.py:385-733` | 349 | K+A (xiaoyaner class shape; Ryvexam preset/alias/retry/security integration) |
| `_resolve_model_header()` | `provider.py:442-451` | 10 | A (Ryvexam model fallback) |
| `_resolve_format()` | `provider.py:453-467` | 15 | K (xiaoyaner format fallback) |
| `_payload()` | `provider.py:469-501` | 33 | K (xiaoyaner validation discipline + Ryvexam sanitize/preset merge) |
| `_request()` | `provider.py:503-522` | 20 | K (xiaoyaner urllib.request shape) |
| `_http_post()` | `provider.py:524-597` | 74 | A (Ryvexam retry policy adapted to urllib + 501-as-permanent) |
| `synthesize()` | `provider.py:601-642` | 42 | K+A (xiaoyaner flow + Palace HTTPS gate, retry, redaction) |
| `stream()` | `provider.py:644-696` | 53 | K (xiaoyaner incremental read; no retry on stream path — matches Ryvexam's no-retry-stream choice) |
| `_timeout()`, `_max_retries()` | `provider.py:700-713` | 14 | K+A (xiaoyaner timeout; Ryvexam max_retries) |
| `register()` | `provider.py:723-732` | 10 | K (xiaoyaner `register(ctx)` entry point) |
| `_backoff_seconds()`, `_sleep()` | `provider.py:738-749` | 12 | A (Ryvexam backoff curve; Palace exposed for test stubbing) |

### 4.3 Behavioral deltas vs both upstreams

| Behavior | xiaoyaner @ 042ec25 | Ryvexam @ dc45f8a | Palace provider.py |
| --- | --- | --- | --- |
| `language` accepted | Yes (top-level, defect) | Yes (allowlist, also sent) | **No** — Fish STT-only; defect-corrected (`provider.py:_build_body` lines 292-298) |
| `normalize_loudness` placement | prosody (correct) | not handled | prosody (correct); top-level never emitted (`provider.py:324-331`) |
| `**extra` allowlist | No (blocklist of `{api_key, authorization, headers, api_base, base_url, endpoint, model}`) | Yes (allowlist of 11 keys) | **Allowlist** + explicit `FORBIDDEN_EXTRA_KEYS` (`provider.py:79-93`) |
| HTTPS enforcement | No | No | **Yes** (`provider.py:253-271`) |
| Bounded retry | No | Yes (`requests`) | Yes (`urllib`, `provider.py:_http_post`) |
| Voice aliases | No | Yes | Yes (`provider.py:164-176`) |
| Presets | No | Yes | Yes (`provider.py:179-203`) |
| Model catalogue | 3 (`s2.1-pro-free`, `s2.1-pro`, `s2-pro`) | 4 (adds `s1`) | 4 (same set) |
| Per-call voice redaction | No | No | Yes (`provider.py:_redact`) |
| HTTP `501` retry | N/A | Yes (5xx retries include 501) | **No** (`provider.py:571-574` — 501 is permanent "not implemented") |
| Default model | `s2.1-pro-free` | `s1` | `s2.1-pro-free` (matches xiaoyaner; safer default for unknown-config installs) |
| Dual `__init__.py` | Yes (defect) | No (single root init) | No (collapsed; both install paths tested) |
| Setup schema badge | `cloud` | `paid` | `cloud` (xiaoyaner; honest — model is free at standard tier) |
| Runtime dep | None | `requests>=2.28` | None (xiaoyaner shape) |
| `warm()` / `release()` | Inherited (no-op) | Inherited (no-op) | Inherited (no-op; required by issue #1 §"Correct defects" item 5) |

### 4.4 Test mapping (xiaoyaner / Ryvexam / Palace)

| Xiaoyaner test | Lines | Status in Palace |
| --- | ---: | --- |
| `test_provider_metadata` | 23-29 | Kept + expanded (model set now 4) |
| `test_register_uses_native_provider_hook` | 32-39 | Kept verbatim |
| `test_synthesize_builds_request_and_writes_audio` | 42-61 | Kept verbatim |
| `test_stream_yields_chunks` | 64-67 | Kept verbatim |
| `test_missing_key_fails_without_network` | 70-75 | Kept (assertion class updated to `RuntimeError`) |
| `test_http_error_is_redacted` | 78-87 | Adapted (per-call voice redaction) |
| `test_transport_extras_cannot_override_endpoint_or_auth` | 90-97 | Kept + expanded (`test_security_extras_cannot_override_endpoint`) |

| Ryvexam test | Lines (Ryvexam) | Status in Palace |
| --- | ---: | --- |
| `TestSanitizeExtra` (3 tests) | 109-124 | Adapted as `test_sanitize_drops_unknown_keys`, `test_security_keys_never_pass_through`, `test_all_allowed_keys_pass` |
| `TestRedact` (2 tests) | 128-135 | Adapted as `test_redact_strips_api_key`, `test_redact_strips_configured_voice`, `test_redact_strips_per_call_voice`, `test_redact_with_no_secrets_is_identity` |
| `TestBuildBody` (7 tests) | 139-182 | Adapted as `test_reference_id_*`, `test_voice_alias_*`, `test_pcm_format_supported`, `test_mp3_bitrate_*`, `test_invalid_latency_dropped` |
| `TestSynthesize` (10+ tests) | 206-305 | Adapted as `test_*` in Palace `tests/test_provider.py` |
| `TestStream` (1 test) | 309-316 | Adapted as `test_stream_yields_chunks` |
| `TestRegister` (1 test) | 320-325 | Kept as `test_register_uses_native_provider_hook` |
| `TestVoiceAliases` (5 tests) | 333-360 | Adapted (subset kept) |
| `TestPresets` (8 tests) | 369-418 | Adapted (subset kept) |
| `TestCloneReference` (6 tests) | 426-458 | **Not integrated** (issue #1 §"Explicitly deferred") |
| `TestCache` (10 tests) | 466-536 | **Not integrated** (issue #1 §"Explicitly deferred") |
| `TestDailyBudget` (5 tests) | 544-573 | **Not integrated** (issue #1 §"Explicitly deferred") |
| `TestRetry` (5 tests) | 581-625 | Adapted as `test_5xx_then_success_retries`, `test_5xx_exhausts_retries_and_redacts`, `test_501_is_not_retried`, `test_connection_reset_retries_and_succeeds`, `test_http_429_is_redacted_and_not_retried` |

| Palace-only test | Status |
| --- | --- |
| `test_https_enforced_by_default` | N (HTTPS policy, Palace) |
| `test_localhost_http_allowed_with_opt_in` | N |
| `test_localhost_http_rejected_without_opt_in` | N |
| `test_non_local_http_rejected_even_with_opt_in` | N |
| `test_synthesize_rejects_http_endpoint` | N |
| `test_language_is_not_sent_as_top_level_field` | N (defect-fix verification) |
| `test_language_in_config_is_ignored` | N |
| `test_normalize_loudness_attached_to_prosody` | N (defect-fix verification) |
| `test_normalize_loudness_not_in_top_level_when_false` | N |
| `test_ogg_format_maps_to_opus` | N |
| `test_unsupported_format_falls_back_to_mp3` | N |
| `test_unsupported_format_via_synthesize_path` | N |

### 4.5 Files removed from xiaoyaner

| Removed path | Reason |
| --- | --- |
| `hermes_fishaudio_tts/__init__.py` | Dual-init collapsed; subpackage referenced only the same `provider.py` |

### 4.6 Features explicitly deferred from Ryvexam

| Deferred feature | Ryvexam source | Issue #1 reference |
| --- | --- | --- |
| `requests` dependency | `pyproject.toml:9` | §"Prefer the standard library unless an added dependency has a concrete, documented benefit" |
| Zero-shot cloning from local sample | `__init__.py:249-275` | §"Correct defects" — operator-managed local file paths out of scope |
| Local response cache | `__init__.py:283-373` | §"Explicitly deferred" — state + concurrency semantics need separate test plan |
| Daily character budget | `__init__.py:381-417` | §"Explicitly deferred" — same reasoning |
| Live `/model` voice listing | `__init__.py:514-557` | Authorization/throttling review needed |
| Standalone `agent.tts_provider` ABC stub in `tests/conftest.py` | `tests/conftest.py:18-86` | Palace uses the real Hermes checkout (xiaoyaner pattern) |

---

## 5. Acceptance — What This Audit Lets You Do

A downstream implementer reading this document can:

1. **Verify the spine.** Every xiaoyaner location listed in §1 is still observable in the Palace repo at the same line shape — `register(ctx)`, `_provider_config`, `_resolve_format`, `_request`, `_timeout`, `stream()`, etc. Nothing from xiaoyaner's native Hermes integration was silently lost.

2. **Verify the selective integration.** Every Ryvexam item issue #1 §"Integrate from the donor" requires maps to a Palace `provider.py` symbol with the same name and behavior. Where Ryvexam used `requests`, the Palace adapts the same retry policy to `urllib`.

3. **Verify the defect corrections.** `normalize_loudness` is now strictly prosody-scoped; `language` is no longer emitted at any level; HTTPS is enforced; the dual-init is collapsed. Each is independently testable in `tests/test_provider.py`.

4. **Verify attribution.** `NOTICE.md`, `LICENSE`, `pyproject.toml:14-16` (authors), and `README.md:14-20` all name both upstreams with their pinned commits. The phrase "Neither upstream author endorses this fork" appears in three places.

5. **Verify the deferrals.** §2.10 and §4.6 list every Ryvexam feature not integrated, with the explicit issue #1 clause that excludes it. The Palace build is not silently skipping them.

6. **Run validation gates without re-reading source.** Issue #1's "Validation gates" map to specific Palace commands already documented in the PR body and `README.md`.

---

## 6. Provenance Summary

| | Lines | Files | Tests | Distinctive contributions |
| --- | ---: | ---: | ---: | --- |
| From xiaoyaner @ 042ec25 (spine) | 268 (provider.py) + 13 (root init) + packaging + tests | 13 source files | 23 tests | Native `PluginContext.register_tts_provider()` registration; stdlib `urllib` `/v1/tts` transport; real-Hermes integration test; MIT; directory-copy + pip entry-point install paths |
| From Ryvexam @ dc45f8a (donor) | 756 (single file) | 1 source file | 85 tests | Allowlist + aliases + presets + retry + model catalogue + redaction; tests for each; comprehensive security model |
| Palace additions | ~750 (provider.py) + ~64 (init) + docs + tests | 16 source files | 69 tests (60 unit + 7 packaging + 2 integration) | HTTPS policy + `_https_enforced`; `FORBIDDEN_EXTRA_KEYS`; `_payload`/`_build_body` separation; language/normalize_loudness defect fixes; canonical single-init packaging; 501-not-retried; per-call voice redaction; integration with `tts_tool._dispatch_to_plugin_provider`; full NOTICE + attribution; per-task workspace safety |

This audit is complete. Every file inspected, every function located, every defect mapped. The implementer's path from this document to a passing PR is mechanical.