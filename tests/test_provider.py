"""Unit tests for the Fish Audio TTS provider plugin.

No real Fish Audio API key or network access is required — all HTTP
calls are mocked. Run with: ``pytest tests/``.
"""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest


class FakeResponse:
    """Minimal urllib-style response that supports ``read(size)``."""

    def __init__(self, data: bytes):
        self._stream = io.BytesIO(data)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size: int = -1):
        return self._stream.read(size)


def _http_error(code: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.fish.audio/v1/tts", code, "error", {}, io.BytesIO(body),
    )


# ---------------------------------------------------------------------------
# Plugin identity
# ---------------------------------------------------------------------------


def test_provider_metadata(plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    assert provider.name == "fishaudio"
    assert provider.display_name == "Fish Audio"
    assert provider.voice_compatible is True
    assert provider.default_model() == "s2.1-pro-free"
    ids = {m["id"] for m in provider.list_models()}
    assert ids == {"s2.1-pro", "s2.1-pro-free", "s2-pro", "s1"}


def test_register_uses_native_provider_hook(plugin_module):
    registered = []

    class Context:
        def register_tts_provider(self, provider):
            registered.append(provider)

    plugin_module.register(Context())
    assert len(registered) == 1
    assert registered[0].name == "fishaudio"


# ---------------------------------------------------------------------------
# TTS transport
# ---------------------------------------------------------------------------


def test_synthesize_builds_request_and_writes_audio(tmp_path, plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(b"ID3-realistic-test-bytes")

    config = {"fishaudio": {"reference_id": "voice-123", "model": "s2.1-pro", "temperature": 0.6}}
    with patch("hermes_cli.config.get_env_value", side_effect=lambda key: "fish-secret" if key == "FISH_AUDIO_API_KEY" else None), \
         patch("tools.tts_tool._load_tts_config", return_value=config), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.synthesize("你好", str(tmp_path / "sample.mp3"), speed=1.05)
    assert Path(result).read_bytes() == b"ID3-realistic-test-bytes"
    request = captured["request"]
    assert request.full_url == "https://api.fish.audio/v1/tts"
    assert request.headers["Authorization"] == "Bearer fish-secret"
    assert request.headers["Model"] == "s2.1-pro"
    payload = json.loads(request.data)
    assert payload["text"] == "你好"
    assert payload["reference_id"] == "voice-123"
    assert payload["temperature"] == 0.6
    assert payload["prosody"]["speed"] == 1.05


def test_stream_yields_chunks(provider_module, monkeypatch):
    provider = provider_module.FishAudioTTSProvider()
    monkeypatch.setattr(provider_module, "DEFAULT_CHUNK_SIZE", 3)
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen", return_value=FakeResponse(b"abcdefgh")):
        chunks = list(provider.stream("hello"))
    assert chunks == [b"abc", b"def", b"gh"]


def test_missing_key_fails_without_network(tmp_path, plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value=None), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen") as urlopen:
        with pytest.raises(RuntimeError, match="FISH_AUDIO_API_KEY not set"):
            provider.synthesize("hello", str(tmp_path / "sample.mp3"))
    urlopen.assert_not_called()


def test_http_4xx_is_redacted(tmp_path, plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    error = _http_error(401, b"bad key fish-secret and voice-secret")
    config = {"fishaudio": {"reference_id": "voice-secret"}}
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value=config), \
         patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="HTTP 401") as exc:
            provider.synthesize("hello", str(tmp_path / "sample.mp3"))
    message = str(exc.value)
    assert "fish-secret" not in message
    assert "voice-secret" not in message
    assert "<redacted-api-key>" in message
    assert "<redacted-voice-id>" in message


def test_http_429_is_redacted_and_not_retried(tmp_path, plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    error = _http_error(429, b"rate limited with fish-secret")
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen", side_effect=error) as urlopen:
        with pytest.raises(RuntimeError, match="HTTP 429"):
            provider.synthesize("hello", str(tmp_path / "sample.mp3"))
    # 4xx must not be retried.
    assert urlopen.call_count == 1


def test_5xx_then_success_retries(tmp_path, provider_module):
    """5xx is retryable; eventual success writes the file."""
    provider = provider_module.FishAudioTTSProvider()
    fail = _http_error(503, b"server error")
    ok = FakeResponse(b"audio")
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen", side_effect=[fail, ok]) as urlopen, \
         patch.object(provider_module, "_sleep", lambda s: None):
        out = tmp_path / "out.mp3"
        result = provider.synthesize("hello", str(out))
    assert urlopen.call_count == 2
    assert Path(result).read_bytes() == b"audio"


def test_5xx_exhausts_retries_and_redacts(tmp_path, provider_module):
    provider = provider_module.FishAudioTTSProvider()
    fail = _http_error(500, b"server fail with fish-secret")
    # ``tools.tts_tool._load_tts_config`` returns the raw ``tts:`` section;
    # ``_provider_config()`` then drills down to ``tts.fishaudio``.
    cfg = {"fishaudio": {"max_retries": 1}}
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value=cfg), \
         patch("urllib.request.urlopen", side_effect=[fail, fail]) as urlopen, \
         patch.object(provider_module, "_sleep", lambda s: None):
        with pytest.raises(RuntimeError, match="HTTP 500") as exc:
            provider.synthesize("hi", str(tmp_path / "out.mp3"))
    assert urlopen.call_count == 2  # initial + 1 retry
    assert "fish-secret" not in str(exc.value)


def test_501_is_not_retried(tmp_path, provider_module):
    provider = provider_module.FishAudioTTSProvider()
    fail = _http_error(501, b"not implemented")
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen", side_effect=fail) as urlopen, \
         patch.object(provider_module, "_sleep", lambda s: None):
        with pytest.raises(RuntimeError, match="501"):
            provider.synthesize("hi", str(tmp_path / "out.mp3"))
    assert urlopen.call_count == 1


def test_connection_reset_retries_and_succeeds(tmp_path, provider_module):
    provider = provider_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen",
               side_effect=[urllib.error.URLError("reset"), FakeResponse(b"audio")]) as urlopen, \
         patch.object(provider_module, "_sleep", lambda s: None):
        result = provider.synthesize("hi", str(tmp_path / "out.mp3"))
    assert urlopen.call_count == 2
    assert Path(result).read_bytes() == b"audio"


def test_empty_text_raises_locally(provider_module):
    provider = provider_module.FishAudioTTSProvider()
    with pytest.raises(ValueError, match="non-empty"):
        provider.synthesize("   ", "/tmp/whatever.mp3")


def test_text_over_max_length_raises_locally(provider_module):
    provider = provider_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}):
        too_long = "a" * (provider_module.MAX_TEXT_LENGTH + 1)
        with pytest.raises(ValueError, match="exceeds"):
            provider.synthesize(too_long, "/tmp/whatever.mp3")


def test_empty_response_is_rejected(tmp_path, provider_module):
    provider = provider_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen", return_value=FakeResponse(b"")):
        with pytest.raises(RuntimeError, match="empty audio response"):
            provider.synthesize("hi", str(tmp_path / "out.mp3"))


# ---------------------------------------------------------------------------
# Voice / format / model catalogue
# ---------------------------------------------------------------------------


def test_default_voice_reads_any_alias(provider_module):
    for key in ("voice", "reference_id", "voice_id"):
        cfg = {"fishaudio": {key: "vid-123"}}
        with patch("tools.tts_tool._load_tts_config", return_value=cfg):
            assert provider_module.FishAudioTTSProvider().default_voice() == "vid-123"


def test_reference_id_from_voice_arg_wins_over_config(provider_module):
    body = provider_module._build_body(
        "hi", voice="call-voice", fmt="mp3", speed=None,
        cfg={"voice": "config-voice"}, extra={},
    )
    assert body["reference_id"] == "call-voice"


def test_reference_id_from_config_used_when_no_call_arg(provider_module):
    body = provider_module._build_body(
        "hi", voice=None, fmt="mp3", speed=None,
        cfg={"reference_id": "config-voice"}, extra={},
    )
    assert body["reference_id"] == "config-voice"


def test_voice_alias_resolves_to_reference_id(provider_module):
    cfg = {"voices": {"jarvis": "ref-real-id"}}
    body = provider_module._build_body(
        "hi", voice="jarvis", fmt="mp3", speed=None, cfg=cfg, extra={},
    )
    assert body["reference_id"] == "ref-real-id"


def test_unknown_voice_name_passes_through(provider_module):
    """A raw reference_id is left alone when it isn't a known alias."""
    body = provider_module._build_body(
        "hi", voice="raw-ref-id", fmt="mp3", speed=None,
        cfg={"voices": {"jarvis": "ref-real-id"}}, extra={},
    )
    assert body["reference_id"] == "raw-ref-id"


def test_synthesize_resolves_alias_via_tool_call(tmp_path, provider_module):
    provider = provider_module.FishAudioTTSProvider()
    cfg = {"fishaudio": {"voices": {"jarvis": "ref-real-id"}}}
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value=cfg), \
         patch("urllib.request.urlopen", return_value=FakeResponse(b"audio")) as urlopen:
        provider.synthesize("hi", str(tmp_path / "out.mp3"), voice="jarvis")
    body = json.loads(urlopen.call_args[0][0].data)
    assert body["reference_id"] == "ref-real-id"


def test_pcm_format_supported(provider_module):
    body = provider_module._build_body(
        "hi", voice=None, fmt="pcm", speed=None, cfg={}, extra={},
    )
    assert body["format"] == "pcm"


def test_ogg_format_maps_to_opus(provider_module):
    """``_resolve_format`` (called via ``_payload``) maps ``ogg`` → ``opus``.

    ``_build_body`` is pure and trusts the caller has already normalized
    the format; the format conversion lives in ``_resolve_format`` so the
    conversion is testable independently of body construction.
    """
    provider = provider_module.FishAudioTTSProvider()
    assert provider._resolve_format("ogg", None) == "opus"


def test_unsupported_format_falls_back_to_mp3(provider_module):
    provider = provider_module.FishAudioTTSProvider()
    assert provider._resolve_format("flac", None) == "mp3"


def test_unsupported_format_via_synthesize_path(provider_module, tmp_path):
    """End-to-end: synthesize() with ``flac`` clamps to ``mp3``."""
    provider = provider_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen", return_value=FakeResponse(b"x")) as urlopen:
        provider.synthesize("hi", str(tmp_path / "out.mp3"), format="flac")
    body = json.loads(urlopen.call_args[0][0].data)
    assert body["format"] == "mp3"


def test_output_path_extension_is_corrected(tmp_path, provider_module):
    provider = provider_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen", return_value=FakeResponse(b"x")):
        result = provider.synthesize("hi", str(tmp_path / "out.wav"), format="mp3")
    assert result.endswith(".mp3")


def test_mp3_bitrate_validated_against_fish_enum(provider_module):
    body = provider_module._build_body(
        "hi", voice=None, fmt="mp3", speed=None, cfg={}, extra={"mp3_bitrate": 999},
    )
    assert "mp3_bitrate" not in body
    body = provider_module._build_body(
        "hi", voice=None, fmt="mp3", speed=None, cfg={}, extra={"mp3_bitrate": 192},
    )
    assert body["mp3_bitrate"] == 192


def test_invalid_latency_dropped(provider_module):
    body = provider_module._build_body(
        "hi", voice=None, fmt="mp3", speed=None, cfg={}, extra={"latency": "warp"},
    )
    assert "latency" not in body
    body = provider_module._build_body(
        "hi", voice=None, fmt="mp3", speed=None, cfg={}, extra={"latency": "normal"},
    )
    assert body["latency"] == "normal"


def test_unknown_model_falls_back_to_default(provider_module):
    provider = provider_module.FishAudioTTSProvider()
    assert provider._resolve_model_header("not-a-real-model", {}) == "s2.1-pro-free"


def test_model_arg_overrides_config(provider_module):
    provider = provider_module.FishAudioTTSProvider()
    assert provider._resolve_model_header("s1", {"model": "s2.1-pro"}) == "s1"


# ---------------------------------------------------------------------------
# Defect fixes — language / normalize_loudness
# ---------------------------------------------------------------------------


def test_language_is_not_sent_as_top_level_field(provider_module):
    body = provider_module._build_body(
        "hi", voice=None, fmt="mp3", speed=None, cfg={}, extra={"language": "en"},
    )
    assert "language" not in body


def test_language_in_config_is_ignored(provider_module):
    body = provider_module._build_body(
        "hi", voice=None, fmt="mp3", speed=None,
        cfg={"language": "zh"}, extra={},
    )
    assert "language" not in body


def test_normalize_loudness_attached_to_prosody(provider_module):
    body = provider_module._build_body(
        "hi", voice=None, fmt="mp3", speed=None,
        cfg={"normalize_loudness": True}, extra={},
    )
    assert body["prosody"]["normalize_loudness"] is True
    assert "normalize_loudness" not in body  # NOT top-level


def test_normalize_loudness_not_in_top_level_when_false(provider_module):
    body = provider_module._build_body(
        "hi", voice=None, fmt="mp3", speed=None,
        cfg={"normalize_loudness": False}, extra={},
    )
    assert "normalize_loudness" not in body
    assert "prosody" not in body


# ---------------------------------------------------------------------------
# HTTPS enforcement
# ---------------------------------------------------------------------------


def test_https_enforced_by_default(provider_module):
    with pytest.raises(ValueError, match="not HTTPS"):
        provider_module._https_enforced(
            "http://api.fish.audio/v1/tts", allow_insecure_local=False,
        )


def test_localhost_http_allowed_with_opt_in(provider_module):
    provider_module._https_enforced(
        "http://localhost:8080/v1/tts", allow_insecure_local=True,
    )
    provider_module._https_enforced(
        "http://127.0.0.1:8080/v1/tts", allow_insecure_local=True,
    )
    provider_module._https_enforced(
        "http://[::1]:8080/v1/tts", allow_insecure_local=True,
    )


def test_localhost_http_rejected_without_opt_in(provider_module):
    with pytest.raises(ValueError, match="not HTTPS"):
        provider_module._https_enforced(
            "http://localhost:8080/v1/tts", allow_insecure_local=False,
        )


def test_non_local_http_rejected_even_with_opt_in(provider_module):
    with pytest.raises(ValueError, match="not HTTPS"):
        provider_module._https_enforced(
            "http://attacker.example/v1/tts", allow_insecure_local=True,
        )


def test_synthesize_rejects_http_endpoint(tmp_path, provider_module):
    provider = provider_module.FishAudioTTSProvider()
    cfg = {"fishaudio": {"api_base": "http://api.fish.audio"}}
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value=cfg), \
         patch("urllib.request.urlopen") as urlopen:
        with pytest.raises(ValueError, match="not HTTPS"):
            provider.synthesize("hi", str(tmp_path / "out.mp3"))
    urlopen.assert_not_called()


# ---------------------------------------------------------------------------
# Sanitization — deny-by-default allowlist
# ---------------------------------------------------------------------------


def test_sanitize_drops_unknown_keys(provider_module):
    cleaned = provider_module._sanitize_extra(
        {"temperature": 0.5, "random_key": "x", "unknown_field": "y"},
    )
    assert cleaned == {"temperature": 0.5}


def test_security_keys_never_pass_through(provider_module):
    malicious = {
        "authorization": "Bearer stolen-key",
        "api_base": "https://evil.example.com",
        "headers": {"X-Injected": "1"},
        "model": "attacker-model",
        "model_id": "x",
        "endpoint": "https://evil",
        "audio_path": "/etc/passwd",
        "clone": {"audio_path": "/etc/passwd"},
        "api_key": "stolen",
    }
    assert provider_module._sanitize_extra(malicious) == {}


def test_all_allowed_keys_pass(provider_module):
    extra = {k: 1 for k in provider_module.ALLOWED_EXTRA_KEYS}
    assert provider_module._sanitize_extra(extra) == extra


def test_security_extras_cannot_override_endpoint(tmp_path, provider_module):
    provider = provider_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen", return_value=FakeResponse(b"audio")) as urlopen:
        provider.synthesize(
            "hi",
            str(tmp_path / "out.mp3"),
            api_base="https://evil.example.com",
            endpoint="https://evil.example.com",
            headers={"X-Injected": "1"},
            model="attacker-model",
            api_key="stolen",
            authorization="Bearer stolen",
            audio_path="/etc/passwd",
        )
    request = urlopen.call_args[0][0]
    assert request.full_url == "https://api.fish.audio/v1/tts"
    assert request.headers["Authorization"] == "Bearer fish-secret"
    assert request.headers["Model"] == "s2.1-pro-free"


def test_security_extras_cannot_override_authorization_via_headers(provider_module):
    provider = provider_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value={}), \
         patch("urllib.request.urlopen", return_value=FakeResponse(b"audio")) as urlopen:
        provider.synthesize("hi", "/tmp/x.mp3", headers={"Authorization": "Bearer stolen"})
    request = urlopen.call_args[0][0]
    assert request.headers["Authorization"] == "Bearer fish-secret"


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


def test_resolve_known_preset(provider_module):
    cfg = {"presets": {"radio": {"model": "s2.1-pro", "temperature": 0.9}}}
    assert provider_module._resolve_preset("radio", cfg) == {"model": "s2.1-pro", "temperature": 0.9}


def test_resolve_unknown_preset_returns_empty(provider_module):
    assert provider_module._resolve_preset("nope", {"presets": {"radio": {}}}) == {}


def test_effective_config_merges_preset_over_base(provider_module):
    cfg = {"model": "s1", "temperature": 0.5, "presets": {"radio": {"temperature": 0.9}}}
    merged = provider_module._effective_config(cfg, "radio")
    assert merged["model"] == "s1"
    assert merged["temperature"] == 0.9


def test_explicit_call_args_win_over_preset(tmp_path, provider_module):
    """An explicit ``model=`` kwarg is a stronger signal than a preset's default model."""
    provider = provider_module.FishAudioTTSProvider()
    cfg = {"fishaudio": {"presets": {"jarvis": {"model": "s2.1-pro", "temperature": 0.9}}}}
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"), \
         patch("tools.tts_tool._load_tts_config", return_value=cfg), \
         patch("urllib.request.urlopen", return_value=FakeResponse(b"audio")) as urlopen:
        provider.synthesize(
            "hi", str(tmp_path / "out.mp3"), preset="jarvis", model="s1",
        )
    request = urlopen.call_args[0][0]
    assert request.headers["Model"] == "s1"


def test_preset_is_allowed_through_sanitize(provider_module):
    assert provider_module._sanitize_extra({"preset": "jarvis"}) == {"preset": "jarvis"}


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_redact_strips_api_key(provider_module, monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "super-secret-key")
    redacted = provider_module._redact("error: super-secret-key invalid")
    assert "super-secret-key" not in redacted
    assert "<redacted-api-key>" in redacted


def test_redact_strips_configured_voice(provider_module):
    redacted = provider_module._redact(
        "bad voice voice-xyz", configured_voice="voice-xyz",
    )
    assert "voice-xyz" not in redacted
    assert "<redacted-voice-id>" in redacted


def test_redact_strips_per_call_voice(provider_module):
    redacted = provider_module._redact(
        "bad voice per-call-voice", per_call_voice="per-call-voice",
    )
    assert "per-call-voice" not in redacted


def test_redact_with_no_secrets_is_identity(provider_module):
    assert provider_module._redact("ordinary message") == "ordinary message"


# ---------------------------------------------------------------------------
# Configuration accessor helpers
# ---------------------------------------------------------------------------


def test_config_value_first_alias_wins(provider_module):
    cfg = {"voice_id": "b", "reference_id": "a"}
    assert provider_module._config_value(cfg, "reference_id", "voice", "voice_id") == "a"


def test_config_value_default_when_absent(provider_module):
    assert provider_module._config_value({}, "reference_id", default="fallback") == "fallback"


def test_resolve_endpoint_appends_v1_tts(provider_module):
    assert provider_module._resolve_endpoint({"api_base": "https://x.example"}) == \
        "https://x.example/v1/tts"


def test_resolve_endpoint_idempotent(provider_module):
    assert provider_module._resolve_endpoint({"api_base": "https://x.example/v1/tts"}) == \
        "https://x.example/v1/tts"


def test_resolve_endpoint_strips_trailing_slash(provider_module):
    assert provider_module._resolve_endpoint({"api_base": "https://x.example/"}) == \
        "https://x.example/v1/tts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_ensure_extension_no_change(provider_module):
    assert str(provider_module._ensure_extension("/tmp/x.mp3", "mp3")) == "/tmp/x.mp3"


def test_ensure_extension_corrects_mismatch(provider_module):
    assert str(provider_module._ensure_extension("/tmp/x.wav", "mp3")) == "/tmp/x.mp3"


def test_api_key_aliases(provider_module, monkeypatch):
    """Primary ``FISH_AUDIO_API_KEY`` wins; ``FISH_API_KEY`` is the fallback."""
    # No key set.
    monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
    monkeypatch.delenv("FISHAUDIO_API_KEY", raising=False)
    monkeypatch.delenv("FISH_API_KEY", raising=False)
    with patch("hermes_cli.config.get_env_value", return_value=None):
        assert provider_module._api_key() == ""
    # Primary name wins.
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "primary")
    monkeypatch.setenv("FISH_API_KEY", "fallback")
    with patch("hermes_cli.config.get_env_value",
               side_effect=lambda k: {"FISH_AUDIO_API_KEY": "primary"}.get(k)):
        assert provider_module._api_key() == "primary"
    # Fallback only.
    monkeypatch.delenv("FISH_AUDIO_API_KEY", raising=False)
    with patch("hermes_cli.config.get_env_value",
               side_effect=lambda k: "fallback" if k == "FISH_API_KEY" else None):
        assert provider_module._api_key() == "fallback"