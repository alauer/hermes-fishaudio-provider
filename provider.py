"""Fish Audio TTS provider for Hermes Agent.

This module only uses Hermes' public TTSProvider extension surface. It does not
patch or replace any Hermes function.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from agent.tts_provider import DEFAULT_OUTPUT_FORMAT, TTSProvider, resolve_output_format

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.fish.audio"
DEFAULT_MODEL = "s2.1-pro-free"
DEFAULT_FORMAT = "mp3"
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_MP3_BITRATE = 128
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_CHUNK_SIZE = 8192
SUPPORTED_OUTPUT_FORMATS = frozenset({"mp3", "wav", "pcm", "opus"})


class FishAudioTTSProvider(TTSProvider):
    """Fish Audio implementation of Hermes' native TTSProvider contract."""

    @property
    def name(self) -> str:
        return "fishaudio"

    @property
    def display_name(self) -> str:
        return "Fish Audio"

    @property
    def voice_compatible(self) -> bool:
        return True

    def is_available(self) -> bool:
        return bool(self._api_key())

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {"id": "s2.1-pro-free", "display": "S2.1 Pro Free", "languages": ["multilingual"], "max_text_length": 5000},
            {"id": "s2.1-pro", "display": "S2.1 Pro", "languages": ["multilingual"], "max_text_length": 5000},
            {"id": "s2-pro", "display": "S2 Pro", "languages": ["multilingual"], "max_text_length": 5000},
        ]

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def default_voice(self) -> Optional[str]:
        voice = self._config_value("reference_id", "voice", "voice_id")
        return str(voice).strip() if voice else None

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Fish Audio",
            "badge": "cloud",
            "tag": "Voice cloning and multilingual synthesis via Fish Audio",
            "env_vars": [{
                "key": "FISH_AUDIO_API_KEY",
                "prompt": "Fish Audio API key",
                "url": "https://fish.audio/app/api-keys",
            }],
        }

    def synthesize(
        self,
        text: str,
        output_path: str,
        *,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        speed: Optional[float] = None,
        format: str = DEFAULT_OUTPUT_FORMAT,
        **extra: Any,
    ) -> str:
        fmt = self._resolve_format(format, output_path)
        out = self._output_path(output_path, fmt)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = self._payload(text, voice=voice, speed=speed, format=fmt, extra=dict(extra))
        request = self._request(payload, model=model)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout()) as response:
                audio = response.read()
        except urllib.error.HTTPError as exc:
            detail = self._redact_sensitive(exc.read().decode("utf-8", errors="replace")[:500])
            raise RuntimeError(f"Fish Audio TTS HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Fish Audio TTS connection failed: {exc.reason}") from exc
        if not audio:
            raise RuntimeError("Fish Audio returned an empty audio response")
        out.write_bytes(audio)
        return str(out)

    def stream(
        self,
        text: str,
        *,
        voice: Optional[str] = None,
        model: Optional[str] = None,
        format: str = DEFAULT_FORMAT,
        **extra: Any,
    ) -> Iterator[bytes]:
        fmt = self._resolve_format(format, None)
        speed = extra.pop("speed", None)
        chunk_size = self._positive_int(extra.pop("chunk_size", self._config_value("chunk_size", default=DEFAULT_CHUNK_SIZE)), DEFAULT_CHUNK_SIZE)
        payload = self._payload(text, voice=voice, speed=speed, format=fmt, extra=dict(extra))
        request = self._request(payload, model=model)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout()) as response:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        except urllib.error.HTTPError as exc:
            detail = self._redact_sensitive(exc.read().decode("utf-8", errors="replace")[:500])
            raise RuntimeError(f"Fish Audio TTS HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Fish Audio TTS connection failed: {exc.reason}") from exc

    def _api_key(self) -> Optional[str]:
        try:
            from hermes_cli.config import get_env_value
            value = get_env_value("FISH_AUDIO_API_KEY") or get_env_value("FISH_API_KEY")
        except Exception:
            value = os.getenv("FISH_AUDIO_API_KEY") or os.getenv("FISH_API_KEY")
        return str(value).strip() if value else None

    def _tts_config(self) -> Dict[str, Any]:
        try:
            from tools.tts_tool import _load_tts_config
            cfg = _load_tts_config()
        except Exception:
            return {}
        return cfg if isinstance(cfg, dict) else {}

    def _provider_config(self) -> Dict[str, Any]:
        cfg = self._tts_config()
        section = cfg.get("fishaudio")
        if isinstance(section, dict):
            return section
        providers = cfg.get("providers")
        if isinstance(providers, dict) and isinstance(providers.get("fishaudio"), dict):
            return providers["fishaudio"]
        return {}

    def _config_value(self, *names: str, default: Any = None) -> Any:
        provider_cfg = self._provider_config()
        for name in names:
            if provider_cfg.get(name) is not None:
                return provider_cfg[name]
        return default

    def _endpoint(self) -> str:
        raw = str(self._config_value("api_base", "base_url", "endpoint", default=DEFAULT_API_BASE)).rstrip("/")
        if raw.endswith("/v1/tts"):
            return raw
        if raw.endswith("/v1"):
            return f"{raw}/tts"
        return f"{raw}/v1/tts"

    def _request(self, payload: Dict[str, Any], *, model: Optional[str]) -> urllib.request.Request:
        api_key = self._api_key()
        if not api_key:
            raise ValueError("FISH_AUDIO_API_KEY is not set")
        model_id = str(model or self._config_value("model", "model_id", default=DEFAULT_MODEL) or DEFAULT_MODEL).strip()
        return urllib.request.Request(
            self._endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "model": model_id},
            method="POST",
        )

    def _payload(self, text: str, *, voice: Optional[str], speed: Optional[float], format: str, extra: Dict[str, Any]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"text": text, "format": format}
        reference_id = voice or self._config_value("reference_id", "voice", "voice_id")
        if reference_id:
            payload["reference_id"] = str(reference_id).strip()
        fields = {
            "temperature": 0.7,
            "top_p": 0.7,
            "chunk_length": None,
            "normalize": None,
            "sample_rate": DEFAULT_SAMPLE_RATE,
            "mp3_bitrate": DEFAULT_MP3_BITRATE,
            "opus_bitrate": None,
            "latency": None,
            "language": None,
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
        prosody: Dict[str, Any] = {}
        if resolved_speed is not None:
            prosody["speed"] = float(resolved_speed)
        if volume is not None:
            prosody["volume"] = volume
        if normalize_loudness is not None:
            prosody["normalize_loudness"] = bool(normalize_loudness)
        if prosody:
            payload["prosody"] = prosody
        # Forward only explicit, non-transport extras for API evolution.
        blocked = {"api_key", "authorization", "headers", "api_base", "base_url", "endpoint", "model"}
        payload.update({key: value for key, value in extra.items() if key not in blocked and value is not None})
        return payload

    def _timeout(self) -> float:
        raw = self._config_value("timeout", "timeout_seconds", default=DEFAULT_TIMEOUT_SECONDS)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_SECONDS
        return value if value > 0 else DEFAULT_TIMEOUT_SECONDS

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

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _resolve_format(requested: Optional[str], output_path: Optional[str]) -> str:
        if output_path:
            suffix = Path(output_path).suffix.lower().lstrip(".")
            if suffix in SUPPORTED_OUTPUT_FORMATS:
                return suffix
        fmt = resolve_output_format(requested) if requested else DEFAULT_FORMAT
        if fmt == "ogg":
            return "opus"
        return fmt if fmt in SUPPORTED_OUTPUT_FORMATS else DEFAULT_FORMAT

    @staticmethod
    def _output_path(output_path: str, format: str) -> Path:
        out = Path(output_path).expanduser().resolve()
        suffix = out.suffix.lower().lstrip(".")
        if suffix not in SUPPORTED_OUTPUT_FORMATS:
            out = out.with_suffix(f".{format}")
        return out
