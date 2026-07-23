"""Hermes Fish Audio TTS plugin."""

try:
    from .provider import FishAudioTTSProvider
except ImportError:  # pragma: no cover - plain-module import fallback
    from provider import FishAudioTTSProvider

__all__ = ["FishAudioTTSProvider", "register"]


def register(ctx) -> None:
    """Register Fish Audio through Hermes' public TTS provider API."""
    ctx.register_tts_provider(FishAudioTTSProvider())
