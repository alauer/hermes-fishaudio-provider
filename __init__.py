"""Hermes Fish Audio TTS plugin."""
from .provider import FishAudioTTSProvider

__all__ = ["FishAudioTTSProvider", "register"]


def register(ctx) -> None:
    """Register Fish Audio through Hermes' public TTS provider API."""
    ctx.register_tts_provider(FishAudioTTSProvider())
