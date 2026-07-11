from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest


class FakeResponse:
    def __init__(self, data: bytes):
        self._stream = io.BytesIO(data)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size: int = -1):
        return self._stream.read(size)


def test_provider_metadata(plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    assert provider.name == "fishaudio"
    assert provider.display_name == "Fish Audio"
    assert provider.voice_compatible is True
    assert provider.default_model() == "s2.1-pro-free"
    assert {m["id"] for m in provider.list_models()} >= {"s2.1-pro-free", "s2.1-pro", "s2-pro"}


def test_register_uses_native_provider_hook(plugin_module):
    registered = []
    class Context:
        def register_tts_provider(self, provider):
            registered.append(provider)
    plugin_module.register(Context())
    assert len(registered) == 1
    assert registered[0].name == "fishaudio"


def test_synthesize_builds_request_and_writes_audio(tmp_path: Path, plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    captured = {}
    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(b"ID3-realistic-test-bytes")
    config = {"fishaudio": {"reference_id": "voice-123", "model": "s2.1-pro", "temperature": 0.6}}
    with patch("hermes_cli.config.get_env_value", side_effect=lambda key: "fish-secret" if key == "FISH_AUDIO_API_KEY" else None),          patch("tools.tts_tool._load_tts_config", return_value=config),          patch("urllib.request.urlopen", side_effect=fake_urlopen):
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


def test_stream_yields_chunks(plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"),          patch("tools.tts_tool._load_tts_config", return_value={}),          patch("urllib.request.urlopen", return_value=FakeResponse(b"abcdefgh")):
        assert list(provider.stream("hello", chunk_size=3)) == [b"abc", b"def", b"gh"]


def test_missing_key_fails_without_network(tmp_path: Path, plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    with patch("hermes_cli.config.get_env_value", return_value=None),          patch("tools.tts_tool._load_tts_config", return_value={}),          patch("urllib.request.urlopen") as urlopen:
        with pytest.raises(ValueError, match="FISH_AUDIO_API_KEY"):
            provider.synthesize("hello", str(tmp_path / "sample.mp3"))
    urlopen.assert_not_called()


def test_http_error_is_redacted(tmp_path: Path, plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    error = urllib.error.HTTPError("https://api.fish.audio/v1/tts", 401, "Unauthorized", {}, io.BytesIO(b"bad key"))
    with patch("hermes_cli.config.get_env_value", return_value="fish-secret"),          patch("tools.tts_tool._load_tts_config", return_value={}),          patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(RuntimeError, match="HTTP 401: bad key") as exc:
            provider.synthesize("hello", str(tmp_path / "sample.mp3"))
    assert "fish-secret" not in str(exc.value)


def test_transport_extras_cannot_override_endpoint_or_auth(plugin_module):
    provider = plugin_module.FishAudioTTSProvider()
    with patch("tools.tts_tool._load_tts_config", return_value={}):
        payload = provider._payload("hello", voice=None, speed=None, format="mp3", extra={
            "endpoint": "https://evil.invalid", "headers": {"x": "y"}, "temperature": 0.5
        })
    assert "endpoint" not in payload
    assert "headers" not in payload
    assert payload["temperature"] == 0.5
