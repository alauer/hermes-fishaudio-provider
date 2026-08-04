# Changelog

## 0.2.1 - 2026-08-05

- Verify plugin `0.2.1` against Hermes v0.20.0 / `v2026.8.3` native registration, dispatch, voice-compatible conversion, and real MP3 synthesis contracts.
- Add a focused Hermes v0.20 regression test for Fish Audio plugin discovery, dispatch, and the voice-compatible flag.

## 0.2.0 - 2026-07-31

- Mark Hermes v0.19 / v2026.7.20 as the supported TTS API baseline.
- Verify native plugin registration and real daemon dispatch against Hermes v0.19.1 / v2026.7.30.
- Add a pip entry point (`hermes_agent.plugins`) so standalone installs are discoverable by Hermes PluginManager, while preserving copied-directory plugin loading.
- Add compatibility tests for plain-module imports, entry-point package registration, and pyproject metadata.
- Redact configured Fish reference/voice IDs from bounded HTTP error details alongside API credentials.

## 0.1.0 - 2026-07-23

- Initial Hermes-native Fish Audio TTS provider using `PluginContext.register_tts_provider()`.
