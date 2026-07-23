# Changelog

## 0.2.0 - 2026-07-23

- Mark Hermes v0.19 / v2026.7.20 as the supported TTS API baseline.
- Add a pip entry point (`hermes_agent.plugins`) so standalone installs are discoverable by Hermes PluginManager, while preserving copied-directory plugin loading.
- Add compatibility tests for plain-module imports, entry-point package registration, and pyproject metadata.
- Redact configured Fish reference/voice IDs from bounded HTTP error details alongside API credentials.

## 0.1.0 - 2026-07-23

- Initial Hermes-native Fish Audio TTS provider using `PluginContext.register_tts_provider()`.
