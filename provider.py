"""Fish Audio TTS provider for Hermes Agent.

This module only uses Hermes' public :class:`agent.tts_provider.TTSProvider`
extension surface. It does not patch, replace, or monkey-patch any Hermes
function.

Feature provenance
------------------
The urllib-based ``/v1/tts`` transport, file-and-stream synthesis, and
public-provider surface are adapted from ``xiaoyaner-home/hermes-fishaudio-tts``
at pinned commit ``042ec252c95165e62c52718575d9e40fd115f56a``. The
deny-by-default allowlist for caller ``**extra``, voice aliases, presets,
bounded retry policy, broader verified model catalogue, the security
regression tests, and the complete error redaction are adapted from
``Ryvexam/hermes-fishaudio-plugin`` at pinned commit
``dc45f8a3305a39a1d36b686d7bd66ecdfa25a450``. See ``NOTICE.md`` for full
attribution.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

from agent.tts_provider import DEFAULT_OUTPUT_FORMAT, TTSProvider, resolve_output_format

logger = logging.getLogger(__name__)

# --- Default constants -----------------------------------------------------

DEFAULT_API_BASE = "https://api.fish.audio"
DEFAULT_MODEL = "s2.1-pro-free"
DEFAULT_FORMAT = "mp3"
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_MP3_BITRATE = 128
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_CHUNK_SIZE = 8192
DEFAULT_MAX_RETRIES = 2

# Fish Audio v1/tts output formats. ``pcm`` is Fish-specific; Hermes core's
# :func:`agent.tts_provider.resolve_output_format` does not include it and would
# silently downgrade it to ``mp3`` — we therefore validate against our own set.
SUPPORTED_OUTPUT_FORMATS: FrozenSet[str] = frozenset({"mp3", "wav", "pcm", "opus"})

# Models Fish Audio documents for the raw ``/v1/tts`` endpoint. Anything
# outside this set (or outside ``HTTP_RECOGNIZED_MODEL_HEADER``) falls back to
# ``DEFAULT_MODEL`` so a typo in config cannot accidentally target a deprecated
# or unsupported variant. ``speech-1.x`` exists behind Fish's OpenAI-compat
# layer, not on the raw ``/v1/tts`` endpoint — see ``HTTP_RECOGNIZED_MODEL_HEADER``.
SUPPORTED_MODELS: FrozenSet[str] = frozenset({
    "s2.1-pro",
    "s2.1-pro-free",
    "s2-pro",
    "s1",
})
HTTP_RECOGNIZED_MODEL_HEADER: FrozenSet[str] = SUPPORTED_MODELS

# Fish's documented top-level ``mp3_bitrate`` enum. The Python SDK enforces the
# same set; sending 96 here will be silently dropped or rejected by the API.
VALID_MP3_BITRATE: FrozenSet[int] = frozenset({64, 128, 192})
VALID_LATENCY: FrozenSet[str] = frozenset({"low", "balanced", "normal"})

# Maximum request body length Fish Audio accepts on ``/v1/tts`` (matches the
# ``_MAX_TEXT_LENGTH`` documented in the Fish SDK; rejected locally before any
# network call so a bad input gets an immediate, specific error regardless of
# auth state).
MAX_TEXT_LENGTH = 5000

# Allowed request-body fields a tool-call ``**extra`` may influence. Deny by
# default: anything outside this set is dropped before the body is built. This
# is the single most important security boundary in this provider — see the
# module docstring's "Security model" section and the security tests under
# ``tests/test_provider.py::test_security_extras_cannot_override_*``.
ALLOWED_EXTRA_KEYS: FrozenSet[str] = frozenset({
    "temperature", "top_p", "sample_rate", "mp3_bitrate", "opus_bitrate",
    "latency", "chunk_length", "normalize", "volume", "preset",
})

# Fields a tool-call ``**extra`` MUST NEVER influence. Most are transport
# fields (``authorization``, ``api_base``, ``headers``, ``model``); the rest
# are configuration that would let a prompt injection read arbitrary local
# files or change operator-written policy. The provider is responsible for
# enforcing that none of these leak into the outgoing request, headers, or
# URL — see the security tests.
FORBIDDEN_EXTRA_KEYS: FrozenSet[str] = frozenset({
    "api_key", "authorization", "headers", "api_base", "base_url", "endpoint",
    "model", "model_id", "audio_path", "clone",
})


# --- Configuration accessors ----------------------------------------------


def _api_key() -> str:
    """Read ``FISH_AUDIO_API_KEY`` (env). Never raises; returns empty str.

    The primary name is ``FISH_AUDIO_API_KEY``. ``FISHAUDIO_API_KEY`` (no
    underscore) and ``FISH_API_KEY`` (shortened) are accepted as aliases for
    anyone migrating from a different Fish Audio plugin/config. The primary
    name wins when more than one is set.
    """
    try:
        from hermes_cli.config import get_env_value
        for var in ("FISH_AUDIO_API_KEY", "FISHAUDIO_API_KEY", "FISH_API_KEY"):
            value = get_env_value(var)
            if value and str(value).strip():
                return str(value).strip()
    except Exception:
        pass
    for var in ("FISH_AUDIO_API_KEY", "FISHAUDIO_API_KEY", "FISH_API_KEY"):
        value = os.getenv(var)
        if value and value.strip():
            return value.strip()
    return ""


def _tts_config() -> Dict[str, Any]:
    """Return the ``tts`` section of the active Hermes config ({} on any failure).

    Imports :func:`tools.tts_tool._load_tts_config` lazily inside the function
    body so a test can patch ``tools.tts_tool._load_tts_config`` at any time
    and have the patch take effect on the next call.
    """
    try:
        from tools.tts_tool import _load_tts_config
        cfg = _load_tts_config()
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _provider_config() -> Dict[str, Any]:
    """Return ``tts.fishaudio`` from the active config ({} on any failure).

    Accepts both the flat ``tts.fishaudio`` shape and the namespaced
    ``tts.providers.fishaudio`` shape so older configs keep working.
    """
    cfg = _tts_config()
    section = cfg.get("fishaudio")
    if isinstance(section, dict):
        return section
    providers = cfg.get("providers")
    if isinstance(providers, dict) and isinstance(providers.get("fishaudio"), dict):
        return providers["fishaudio"]
    return {}


def _config_value(cfg: Dict[str, Any], *names: str, default: Any = None) -> Any:
    """First non-None value among several accepted key aliases in *cfg*."""
    for name in names:
        if cfg.get(name) is not None:
            return cfg[name]
    return default


# --- Voice aliases & presets ------------------------------------------------


def _resolve_voice_alias(name: Optional[str], cfg: Dict[str, Any]) -> Optional[str]:
    """Resolve a friendly ``tts.fishaudio.voices`` name to a raw ``reference_id``.

    Falls through to returning *name* unchanged when it isn't a known alias —
    so a raw Fish Audio reference_id keeps working exactly as before; this is
    purely additive.
    """
    if not name:
        return name
    voices = cfg.get("voices")
    if isinstance(voices, dict) and name in voices:
        return voices[name]
    return name


def _resolve_preset(name: Optional[str], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return the named ``tts.fishaudio.presets`` bundle, or {} if unset/unknown."""
    if not name:
        return {}
    presets = cfg.get("presets")
    if isinstance(presets, dict) and isinstance(presets.get(name), dict):
        return presets[name]
    logger.debug("Fish Audio: preset %r not found in tts.fishaudio.presets", name)
    return {}


def _effective_config(cfg: Dict[str, Any], preset_name: Optional[str]) -> Dict[str, Any]:
    """Merge a selected preset over the base ``tts.fishaudio`` config.

    Precedence (lowest to highest): base config < preset. The caller's own
    ``**extra``/``voice``/``model`` kwargs are layered on top of this by
    :func:`_build_body` and :meth:`_resolve_model_header`, which already prefer
    an explicit call-time value over config.
    """
    preset = _resolve_preset(preset_name, cfg)
    if not preset:
        return cfg
    merged = dict(cfg)
    merged.update(preset)
    return merged


# --- Sanitization, redaction, output-path safety ----------------------------


def _sanitize_extra(extra: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only the allow-listed, non-security-relevant keys from **extra.

    Deny-by-default. Anything outside ``ALLOWED_EXTRA_KEYS`` (notably
    ``authorization``, ``api_base``, ``headers``, ``model``, ``audio_path``,
    ``clone``) is dropped before it ever reaches the outgoing request — see
    the module docstring's "Security model" section. ``preset`` is safe to
    allow: it only *selects* a named config object the operator already
    defined, it cannot create one.
    """
    if not isinstance(extra, dict):
        return {}
    return {k: v for k, v in extra.items() if k in ALLOWED_EXTRA_KEYS}


def _redact(message: str, *, configured_voice: Optional[str] = None,
            per_call_voice: Optional[str] = None) -> str:
    """Strip the API key and the configured/per-call reference IDs from a string."""
    text = str(message)
    key = _api_key()
    if key:
        text = text.replace(key, "<redacted-api-key>")
    if configured_voice:
        text = text.replace(str(configured_voice), "<redacted-voice-id>")
    if per_call_voice:
        text = text.replace(str(per_call_voice), "<redacted-voice-id>")
    return text


def _ensure_extension(output_path: str, fmt: str) -> Path:
    """Return *output_path* with its suffix corrected to match *fmt*.

    The dispatcher normally already picks a matching extension, but a direct
    caller (or a future dispatcher change) might not — writing mp3 bytes to a
    path ending in ``.wav`` would silently mislabel the file, so this is
    defensive, not cosmetic.
    """
    path = Path(output_path)
    wanted = f".{fmt}"
    if path.suffix.lower() == wanted:
        return path
    return path.with_suffix(wanted)


def _https_enforced(endpoint: str, *, allow_insecure_local: bool) -> None:
    """Raise ``ValueError`` if *endpoint* uses a non-HTTPS, non-local scheme.

    Local overrides (``http://localhost``, ``http://127.0.0.1``, ``http://[::1]``)
    require ``allow_insecure_local=True`` so a misconfigured local proxy can't
    be smuggled in via a permissive default.
    """
    parsed = urlparse(endpoint)
    scheme = (parsed.scheme or "").lower()
    if scheme == "https":
        return
    host = (parsed.hostname or "").lower()
    if scheme == "http" and allow_insecure_local and host in {"localhost", "127.0.0.1", "::1"}:
        return
    raise ValueError(
        f"Fish Audio endpoint {endpoint!r} is not HTTPS; "
        "non-HTTPS endpoints require tts.fishaudio.allow_insecure_local=true "
        "and a localhost/127.0.0.1/[::1] host."
    )


# --- Pure request builders -------------------------------------------------


def _build_body(
    text: str,
    *,
    voice: Optional[str],
    fmt: str,
    speed: Optional[float],
    cfg: Dict[str, Any],
    extra: Dict[str, Any],
    per_call_voice_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct the Fish Audio ``/v1/tts`` JSON body.

    Pure (no I/O). Shared by :meth:`FishAudioTTSProvider.synthesize` and
    :meth:`FishAudioTTSProvider.stream` so the two never drift on validation,
    preset/voice resolution, or body construction.

    The previously-shipped top-level ``language`` field is dropped — it is a
    Fish STT-only field, never honored by ``/v1/tts``. The previously-shipped
    top-level ``normalize_loudness`` is also dropped — Fish documents it
    inside ``prosody`` for ``s2-pro`` and the s2.1-pro family, not at the
    top level. We continue to support ``normalize_loudness`` as a prosody
    sub-field when configured.
    """
    body: Dict[str, Any] = {"text": text, "format": fmt}

    reference_id = per_call_voice_id or voice or _config_value(cfg, "voice", "reference_id", "voice_id")
    reference_id = _resolve_voice_alias(reference_id, cfg)
    if reference_id:
        body["reference_id"] = str(reference_id).strip()

    prosody: Dict[str, Any] = {}
    resolved_speed = speed if speed is not None else cfg.get("speed")
    if resolved_speed is not None:
        try:
            prosody["speed"] = float(resolved_speed)
        except (TypeError, ValueError):
            pass
    if "volume" in extra:
        try:
            prosody["volume"] = float(extra["volume"])
        except (TypeError, ValueError):
            pass
    elif cfg.get("volume") is not None:
        try:
            prosody["volume"] = float(cfg["volume"])
        except (TypeError, ValueError):
            pass
    normalize_loudness = cfg.get("normalize_loudness")
    if isinstance(normalize_loudness, bool) and normalize_loudness:
        # ``normalize_loudness=True`` lives inside ``prosody`` (not top-level)
        # and is supported only on s2-pro and the s2.1-pro family. We attach
        # it unconditionally — Fish ignores it for unsupported models.
        # ``False`` is the documented default and is silently dropped here so
        # we don't ship an empty ``prosody: {normalize_loudness: False}``.
        prosody["normalize_loudness"] = True
    if prosody:
        body["prosody"] = prosody

    for key in ("temperature", "top_p", "sample_rate", "chunk_length"):
        value = extra.get(key, cfg.get(key))
        if value is not None:
            body[key] = value

    mp3_bitrate = extra.get("mp3_bitrate", cfg.get("mp3_bitrate"))
    if mp3_bitrate is not None:
        try:
            mp3_bitrate_int = int(mp3_bitrate)
        except (TypeError, ValueError):
            mp3_bitrate_int = None
        if mp3_bitrate_int in VALID_MP3_BITRATE:
            body["mp3_bitrate"] = mp3_bitrate_int

    opus_bitrate = extra.get("opus_bitrate", cfg.get("opus_bitrate"))
    if opus_bitrate is not None:
        try:
            body["opus_bitrate"] = int(opus_bitrate)
        except (TypeError, ValueError):
            pass

    latency = extra.get("latency", cfg.get("latency"))
    if isinstance(latency, str) and latency in VALID_LATENCY:
        body["latency"] = latency

    normalize = extra.get("normalize", cfg.get("normalize"))
    if normalize is not None:
        body["normalize"] = bool(normalize)

    return body


def _resolve_endpoint(cfg: Dict[str, Any]) -> str:
    """Return the configured ``api_base`` with the ``/v1/tts`` suffix added.

    Deliberately env/config only — never settable via a tool call's
    ``**extra``, so a prompt-injected argument can't redirect requests.
    """
    raw = cfg.get("api_base") or cfg.get("base_url") or DEFAULT_API_BASE
    raw = str(raw).strip().rstrip("/")
    if raw.endswith("/v1/tts"):
        return raw
    if raw.endswith("/v1"):
        return f"{raw}/tts"
    return f"{raw}/v1/tts"


# --- The provider itself ---------------------------------------------------


class FishAudioTTSProvider(TTSProvider):
    """Fish Audio ``/v1/tts`` backend."""

    @property
    def name(self) -> str:
        return "fishaudio"

    @property
    def display_name(self) -> str:
        return "Fish Audio"

    @property
    def voice_compatible(self) -> bool:
        """mp3/wav/opus/pcm output is fine for the gateway's voice-bubble pipeline."""
        return True

    def is_available(self) -> bool:
        return bool(_api_key())

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {"id": "s2.1-pro", "display": "S2.1 Pro (recommended)",
             "languages": ["multilingual"], "max_text_length": MAX_TEXT_LENGTH},
            {"id": "s2.1-pro-free", "display": "S2.1 Pro Free",
             "languages": ["multilingual"], "max_text_length": MAX_TEXT_LENGTH},
            {"id": "s2-pro", "display": "S2 Pro",
             "languages": ["multilingual"], "max_text_length": MAX_TEXT_LENGTH},
            {"id": "s1", "display": "S1",
             "languages": ["multilingual"], "max_text_length": MAX_TEXT_LENGTH},
        ]

    def default_model(self) -> Optional[str]:
        cfg_model = _provider_config().get("model")
        if isinstance(cfg_model, str) and cfg_model.strip() in SUPPORTED_MODELS:
            return cfg_model.strip()
        return DEFAULT_MODEL

    def default_voice(self) -> Optional[str]:
        cfg = _provider_config()
        ref = _config_value(cfg, "voice", "reference_id", "voice_id")
        ref = _resolve_voice_alias(ref, cfg)
        return str(ref).strip() if ref else None

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

    # ---- Pure helpers shared by synthesize / stream -----------------------

    def _resolve_model_header(self, model: Optional[str], cfg: Dict[str, Any]) -> str:
        candidate = model or cfg.get("model") or DEFAULT_MODEL
        candidate = candidate.strip() if isinstance(candidate, str) else DEFAULT_MODEL
        if candidate not in HTTP_RECOGNIZED_MODEL_HEADER:
            logger.debug(
                "Fish Audio: model %r not in recognized set %s; falling back to %s",
                candidate, sorted(HTTP_RECOGNIZED_MODEL_HEADER), DEFAULT_MODEL,
            )
            return DEFAULT_MODEL
        return candidate

    def _resolve_format(self, requested: Optional[str], output_path: Optional[str]) -> str:
        if output_path:
            suffix = Path(output_path).suffix.lower().lstrip(".")
            if suffix in SUPPORTED_OUTPUT_FORMATS:
                return suffix
        if isinstance(requested, str) and requested.strip():
            fmt = resolve_output_format(requested)
            if fmt == "ogg":
                # ``ogg`` is valid for Hermes core but Fish rejects it; the
                # user almost certainly meant opus (the same container family
                # in practice). Map silently so a user already familiar with
                # ``ogg=opus`` semantics keeps working.
                return "opus"
            return fmt if fmt in SUPPORTED_OUTPUT_FORMATS else DEFAULT_FORMAT
        return DEFAULT_FORMAT

    def _payload(
        self,
        text: str,
        *,
        voice: Optional[str],
        speed: Optional[float],
        format: str,
        extra: Dict[str, Any],
        cfg: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], str]:
        """Pure: validate input, build body, return (body, resolved_format).

        *format* is normalized against Fish's own format set (``pcm`` /
        ``opus`` are valid; ``ogg`` maps to ``opus``; unknown values fall
        back to ``mp3``) before being passed to the body builder.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"text is {len(text)} chars, exceeds Fish Audio's {MAX_TEXT_LENGTH}-char limit"
            )
        clean_extra = _sanitize_extra(extra)
        effective = _effective_config(cfg, clean_extra.get("preset"))
        # Resolve format against Fish's supported set; the dispatcher usually
        # passes a clean value, but a direct caller can pass ``ogg`` or ``flac``
        # and we want this to be deterministic + testable.
        fmt = self._resolve_format(format, None)
        body = _build_body(
            text, voice=voice, fmt=fmt, speed=speed, cfg=effective,
            extra=clean_extra,
        )
        return body, fmt

    def _request(
        self,
        body: Dict[str, Any],
        *,
        model: str,
        endpoint: str,
        api_key: str,
        timeout: float,
    ) -> urllib.request.Request:
        """Build the ``urllib.request.Request`` for a single POST."""
        return urllib.request.Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "model": model,
            },
            method="POST",
        )

    def _http_post(
        self,
        endpoint: str,
        *,
        body: Dict[str, Any],
        model_header: str,
        api_key: str,
        timeout: float,
        max_retries: int,
    ) -> bytes:
        """POST with bounded retry and full redaction on failure.

        Retries transient network failures and ``5xx`` (excluding ``501`` —
        a permanent "not implemented" never fixes itself by waiting). Does
        not retry ``4xx`` (a bad request, auth failure, or rate limit will
        not fix itself by retrying — and 429/401 are the most common
        operator-actionable failures). Tests must not perform real sleeps;
        retry backoff is injected via :func:`_sleep` so tests can fast-forward.
        """
        request = self._request(
            body, model=model_header, endpoint=endpoint,
            api_key=api_key, timeout=timeout,
        )
        last_exc: Optional[BaseException] = None
        last_resp_data: Optional[bytes] = None
        last_resp_code: Optional[int] = None
        attempts = max_retries + 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                last_resp_code = exc.code
                last_resp_data = exc.read()
                # Non-retryable: 4xx (client error) — fail fast.
                if exc.code < 500:
                    detail = _redact(
                        last_resp_data.decode("utf-8", errors="replace")[:500],
                        configured_voice=_config_value(
                            _provider_config(), "voice", "reference_id", "voice_id",
                        ),
                        per_call_voice=body.get("reference_id"),
                    )
                    raise RuntimeError(
                        f"Fish Audio TTS HTTP {exc.code}: {detail}"
                    ) from exc
                # 5xx — retryable, except 501 (Not Implemented) which is permanent.
                if exc.code == 501:
                    raise RuntimeError(
                        f"Fish Audio TTS HTTP 501 (not implemented)"
                    ) from exc
                last_exc = exc
            except urllib.error.URLError as exc:
                last_exc = exc
            if attempt < attempts - 1:
                _sleep(_backoff_seconds(attempt))
        # Exhausted retries.
        if isinstance(last_exc, urllib.error.HTTPError):
            detail = _redact(
                (last_resp_data or b"").decode("utf-8", errors="replace")[:500],
                configured_voice=_config_value(
                    _provider_config(), "voice", "reference_id", "voice_id",
                ),
                per_call_voice=body.get("reference_id"),
            )
            code = last_resp_code or 0
            raise RuntimeError(
                f"Fish Audio TTS HTTP {code} after {attempts} attempts: {detail}"
            ) from last_exc
        if isinstance(last_exc, urllib.error.URLError):
            raise RuntimeError(
                f"Fish Audio TTS connection failed after {attempts} attempts: {last_exc.reason}"
            ) from last_exc
        raise RuntimeError("Fish Audio TTS request failed after retries")

    # ---- Public API -------------------------------------------------------

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
        """Synthesize ``text`` to ``output_path`` and return the written path."""
        cfg = _provider_config()
        body, fmt = self._payload(
            text, voice=voice, speed=speed, format=format, extra=extra, cfg=cfg,
        )
        out = _ensure_extension(output_path, fmt)
        out.parent.mkdir(parents=True, exist_ok=True)
        endpoint = _resolve_endpoint(cfg)
        _https_enforced(
            endpoint,
            allow_insecure_local=bool(cfg.get("allow_insecure_local", False)),
        )
        api_key = _api_key()
        if not api_key:
            raise RuntimeError(
                "FISH_AUDIO_API_KEY not set. Add it to the profile's .env, "
                "then restart the gateway."
            )
        model_header = self._resolve_model_header(model, cfg)
        audio = self._http_post(
            endpoint,
            body=body,
            model_header=model_header,
            api_key=api_key,
            timeout=self._timeout(cfg),
            max_retries=self._max_retries(cfg),
        )
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
        format: str = "opus",
        **extra: Any,
    ) -> Iterator[bytes]:
        """Yield Fish Audio response bytes incrementally.

        Note: Hermes' ``text_to_speech`` path currently buffers the whole
        file before platform delivery even though the provider can read
        upstream incrementally. This method is the right entry point for a
        future streaming consumer; today it is most useful for tests and
        for direct callers outside the standard tool path.
        """
        cfg = _provider_config()
        body, fmt = self._payload(
            text, voice=voice, speed=None, format=format, extra=extra, cfg=cfg,
        )
        endpoint = _resolve_endpoint(cfg)
        _https_enforced(
            endpoint,
            allow_insecure_local=bool(cfg.get("allow_insecure_local", False)),
        )
        api_key = _api_key()
        if not api_key:
            raise RuntimeError(
                "FISH_AUDIO_API_KEY not set. Add it to the profile's .env, "
                "then restart the gateway."
            )
        model_header = self._resolve_model_header(model, cfg)
        request = self._request(
            body, model=model_header, endpoint=endpoint,
            api_key=api_key, timeout=self._timeout(cfg),
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout(cfg)) as response:
                while True:
                    chunk = response.read(DEFAULT_CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
        except urllib.error.HTTPError as exc:
            detail = _redact(
                exc.read().decode("utf-8", errors="replace")[:500],
                configured_voice=_config_value(cfg, "voice", "reference_id", "voice_id"),
                per_call_voice=body.get("reference_id"),
            )
            raise RuntimeError(f"Fish Audio TTS HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Fish Audio TTS connection failed: {exc.reason}") from exc

    # ---- Configuration-derived numeric helpers ----------------------------

    def _timeout(self, cfg: Dict[str, Any]) -> float:
        raw = cfg.get("timeout", DEFAULT_TIMEOUT_SECONDS)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_SECONDS
        return value if value > 0 else DEFAULT_TIMEOUT_SECONDS

    def _max_retries(self, cfg: Dict[str, Any]) -> int:
        raw = cfg.get("max_retries", DEFAULT_MAX_RETRIES)
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return DEFAULT_MAX_RETRIES

    # warm()/release() inherit from TTSProvider (no-op). Kept documented here
    # so the integration test in test_hermes_integration.py can rely on the
    # current-Hermes provider contract.


# --- Plugin entry point ----------------------------------------------------


def register(ctx) -> None:
    """Register Fish Audio through Hermes' public TTS provider API.

    Lives on the ``provider`` module so the pip entry point
    ``provider:register`` resolves to a single canonical symbol. The
    repo-root ``__init__.py`` re-exports this for the directory-copy
    plugin path (``hermes plugins install <ref>``), which calls
    ``<plugin>.register(ctx)`` directly.
    """
    ctx.register_tts_provider(FishAudioTTSProvider())


# --- Retry backoff (separated so tests can stub it) ------------------------


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with a sane cap.

    Exposed at module scope (not as a method) so tests can patch
    ``provider._sleep`` to fast-forward without performing real sleeps.
    """
    return float(min(2 ** attempt, 8))


def _sleep(seconds: float) -> None:
    """Indirection over :func:`time.sleep` so tests can stub it."""
    import time
    time.sleep(seconds)