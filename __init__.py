"""Hermes Fish Audio TTS plugin.

A Hermes Agent-native TTS provider for Fish Audio
(https://fish.audio), implemented entirely through Hermes's public
``TTSProvider`` plugin API (``agent.tts_provider``). The plugin
registers a single provider named ``fishaudio`` via
``PluginContext.register_tts_provider()``; no Hermes core files are
patched or monkey-patched.

API reference: https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech
  POST https://api.fish.audio/v1/tts
  Headers: Authorization: Bearer *** model: <s1|s2-pro|s2.1-pro|s2.1-pro-free>
  Body (JSON): {text, reference_id, format, temperature, top_p, prosody,
                sample_rate, mp3_bitrate, opus_bitrate, latency, references, ...}
  Formats: mp3, wav, pcm, opus — validated against this plugin's own set,
  not Hermes core's ``resolve_output_format()`` (which doesn't know about
  ``pcm`` and would silently downgrade it to mp3).
  Response: chunked binary audio stream in the requested format.

Feature provenance
------------------
The native Hermes integration spine, the ``/v1/tts`` urllib transport,
the plugin-name resolution, and the packaging metadata are adapted
from ``xiaoyaner-home/hermes-fishaudio-tts`` at pinned commit
``042ec252c95165e62c52718575d9e40fd115f56a``. The deny-by-default
allowlist for caller ``**extra``, voice aliases, presets, bounded retry
policy, broader verified model catalogue, the security regression
tests, and the complete error redaction are adapted from
``Ryvexam/hermes-fishaudio-plugin`` at pinned commit
``dc45f8a3305a39a1d36b686d7bd66ecdfa25a450``. See ``NOTICE.md`` for
full attribution. Neither upstream author endorses this fork.

Security model
--------------
- The credential lives only in ``FISH_AUDIO_API_KEY`` (env, with two
  accepted aliases). It is never accepted from a tool call.
- ``**extra`` (forwarded from the ``text_to_speech`` tool call —
  agent- or user-influenced input) is explicitly allow-listed in
  :func:`provider._sanitize_extra`. It can never set/override the
  Authorization header, the API base URL, the ``model`` header, or
  any local file path — those come only from env/config, never from a
  tool call, so a prompt-injected ``extra`` argument cannot redirect
  requests to an attacker-controlled endpoint, smuggle a different
  key, or override the chosen voice/model.
- HTTPS is enforced for non-local API endpoints. Local overrides
  (e.g. ``http://localhost``, ``http://127.0.0.1``) require an
  explicit ``tts.fishaudio.allow_insecure_local: true`` opt-in.
- Error messages are passed through :func:`provider._redact` before
  being raised, stripping the API key, the configured reference ID,
  and the per-call reference ID so they cannot leak into agent-visible
  tool output or logs.

Streaming caveat
----------------
Hermes's standard ``text_to_speech`` path still completes a file
before platform delivery even though :meth:`FishAudioTTSProvider.stream`
yields Fish Audio response bytes incrementally. True chunk-to-platform
voice-channel playback requires a generic streaming consumer in Hermes
core; this plugin does not patch the gateway to simulate it.
"""

from provider import FishAudioTTSProvider, register

__all__ = ["FishAudioTTSProvider", "register"]