# Notice — Attributions and Provenance

This repository began as a fork of
[`xiaoyaner-home/hermes-fishaudio-tts`](https://github.com/xiaoyaner-home/hermes-fishaudio-tts)
at pinned commit `042ec252c95165e62c52718575d9e40fd115f56a`, and selectively
incorporates features adapted from
[`Ryvexam/hermes-fishaudio-plugin`](https://github.com/Ryvexam/hermes-fishaudio-plugin)
at pinned commit `dc45f8a3305a39a1d36b686d7bd66ecdfa25a450`.

It is now maintained under the `alauer/hermes-fishaudio-provider` slug for the
Hermes Agent (https://github.com/NousResearch/hermes-agent). Neither upstream
author endorses this fork; nothing here is affiliated with Fish Audio beyond
its published HTTP API.

## What came from xiaoyaner (kept as the native Hermes integration spine)

- Native registration through `PluginContext.register_tts_provider()`.
- Fish Audio `/v1/tts` HTTP transport using stdlib `urllib` (no runtime
  dependency on `requests`).
- Voice cloning through a pre-uploaded Fish `reference_id`.
- `synthesize()` (file-based) and `stream()` (incremental response reading).
- `voice_compatible = True`.
- Plugin-package layout that satisfies both `hermes plugins install <ref>` and
  the directory-copy plugin path.
- Zero Hermes-core modifications; tests against the real
  `hermes_cli.plugins.PluginManager` → `agent.tts_registry` →
  `tools.tts_tool_plugins._dispatch_to_plugin_provider` pipeline.

## What was adapted from Ryvexam (selectively integrated)

- Deny-by-default allowlist for provider-specific `**extra` parameters
  (`provider.ALLOWED_EXTRA_KEYS`).
- Named voice aliases (`tts.fishaudio.voices.<alias>`) that map friendly names
  to Fish reference IDs.
- Named presets (`tts.fishaudio.presets.<name>`) bundling model / voice /
  format / speed / temperature / top-p / prosody controls.
- Bounded retry policy: transient connection failures and 5xx (except 501)
  retry with exponential backoff; 4xx and 501 do not retry.
- Broader verified Fish model catalogue (`s2.1-pro`, `s2.1-pro-free`,
  `s2-pro`, `s1`) with `max_text_length` per entry.
- Full redaction of the API key, the configured `reference_id`, and the
  per-call `reference_id` on every error path.
- Security regression tests proving caller extras cannot override
  authorization, endpoint, headers, API key, or model transport semantics.

## What was intentionally NOT carried over from Ryvexam

- The `requests` dependency. The Palace build uses stdlib `urllib` to stay
  zero-dependency, as the original xiaoyaner spine did.
- Zero-shot cloning from a local audio sample (`tts.fishaudio.clone.*`).
  Deferred to a later change: it adds operator-managed local file paths and
  an audio-byte base64 payload that the Palace scope intentionally excludes.
- Local response cache (`tts.fishaudio.cache.*`) and daily character budget
  (`tts.fishaudio.daily_char_budget`). The issue explicitly defers these —
  they introduce state and concurrency semantics that require a separate
  decision and test plan.
- `list_voices()`'s live call to Fish's `/model` endpoint. The operator-configured
  voice aliases are sufficient for the v0.3.0 surface; live model listing
  requires a separate authorization-and-throttling review.

## Defects corrected during integration

- The previously-shipped `normalize_loudness` was advertised as a top-level
  config field. Fish documents it inside the `prosody` object for `s2-pro`
  and the s2.1-pro family only; it now lives in `prosody.normalize_loudness`
  and is sent only when configured.
- The previously-shipped `language` field was sent as a top-level request
  field. Fish's `/v1/tts` does not document or honor it (it is an STT-only
  field). It is no longer sent.
- HTTPS is now enforced for non-local endpoints; local overrides require an
  explicit `tts.fishaudio.allow_insecure_local: true` opt-in.
- The dual-`__init__.py` packaging arrangement (root `__init__.py` plus
  `hermes_fishaudio_tts/__init__.py`) is collapsed into one canonical
  `__init__.py` at the repo root. Both the directory-copy install path and
  the `hermes_agent.plugins` entry-point path are tested.
- `warm()` and `release()` keep the upstream no-op default from
  `agent.tts_provider.TTSProvider`, matching the current-Hermes provider
  contract.

## License

This project is MIT-licensed; the upstream projects are MIT-licensed. See
[`LICENSE`](LICENSE). Original copyright notices from both source projects
are preserved there.