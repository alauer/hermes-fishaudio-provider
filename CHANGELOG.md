# Changelog

## 0.3.0 - 2026-09-29

- Palace-maintained integration. One canonical ``fishaudio`` provider
  loaded through Hermes' public ``PluginContext.register_tts_provider()``.
- Drop the dual-``__init__.py`` packaging arrangement (root
  ``__init__.py`` plus ``hermes_fishaudio_tts/__init__.py``) and consolidate
  on the root-level ``__init__.py`` + ``provider.py`` layout. The pip
  entry point now resolves to ``provider:register`` and the directory-copy
  plugin path keeps working unchanged.
- Add the deny-by-default allowlist for caller ``**extra`` — only
  ``temperature``, ``top_p``, ``sample_rate``, ``mp3_bitrate``,
  ``opus_bitrate``, ``latency``, ``chunk_length``, ``normalize``, ``volume``,
  and ``preset`` pass through. ``authorization``, ``api_base``, ``headers``,
  the ``model`` header, ``audio_path``, ``clone``, and ``api_key`` cannot
  reach the outgoing request from a tool call.
- Add named voice aliases (``tts.fishaudio.voices.<alias>``) and named
  presets (``tts.fishaudio.presets.<name>``); explicit call-time args
  still win over a preset's defaults.
- Add bounded retry on transient network failures and ``5xx`` (default
  ``max_retries: 2``); ``4xx`` and ``501`` are not retried. Backoff is
  exponential with a cap and is injected through ``provider._sleep`` so
  tests can stub it without real sleeps.
- Add complete error redaction: the API key, the configured
  ``reference_id``, and the per-call ``reference_id`` are stripped from
  every error message before it surfaces.
- Enforce HTTPS for non-local endpoints. Local overrides require an
  explicit ``tts.fishaudio.allow_insecure_local: true`` opt-in.
- Drop the previously-shipped top-level ``language`` field (Fish's
  ``/v1/tts`` does not document or honor it — it is an STT-only field).
- Move ``normalize_loudness`` from a top-level body field to ``prosody``
  (where Fish documents it for ``s2-pro`` and the s2.1-pro family).
- Expand the verified Fish model catalogue to ``s2.1-pro``,
  ``s2.1-pro-free``, ``s2-pro``, ``s1``; unknown values fall back to the
  default so a typo cannot accidentally target a deprecated variant.
- Rename project metadata (``pyproject.toml``, ``plugin.yaml``,
  ``README.md`` badges, ``LICENSE`` copyright holders) to
  ``alauer/hermes-fishaudio-provider``. The runtime provider name
  remains ``fishaudio``.

## 0.2.1 - 2026-08-05

- Verify plugin ``0.2.1`` against Hermes v0.20.0 / ``v2026.8.3`` native
  registration, dispatch, voice-compatible conversion, and real MP3
  synthesis contracts.
- Add a focused Hermes v0.20 regression test for Fish Audio plugin
  discovery, dispatch, and the voice-compatible flag.

## 0.2.0 - 2026-07-31

- Mark Hermes v0.19 / v2026.7.20 as the supported TTS API baseline.
- Verify native plugin registration and real daemon dispatch against
  Hermes v0.19.1 / v2026.7.30.
- Add a pip entry point (``hermes_agent.plugins``) so standalone installs
  are discoverable by Hermes PluginManager, while preserving
  copied-directory plugin loading.
- Add compatibility tests for plain-module imports, entry-point package
  registration, and pyproject metadata.
- Redact configured Fish reference/voice IDs from bounded HTTP error
  details alongside API credentials.

## 0.1.0 - 2026-07-23

- Initial Hermes-native Fish Audio TTS provider using
  ``PluginContext.register_tts_provider()``.