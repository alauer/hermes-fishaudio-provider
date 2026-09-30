# hermes-fishaudio-provider

[![CI](https://github.com/alauer/hermes-fishaudio-provider/actions/workflows/ci.yml/badge.svg)](https://github.com/alauer/hermes-fishaudio-provider/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Hermes Agent plugin](https://img.shields.io/badge/Hermes%20Agent-plugin-6f42c1)](https://github.com/NousResearch/hermes-agent)
[![No core patches](https://img.shields.io/badge/core%20files-not%20patched-brightgreen)](SECURITY.md)

A [Hermes Agent](https://github.com/NousResearch/hermes-agent)-native
[Fish Audio](https://fish.audio) text-to-speech provider, implemented
entirely through Hermes's public `TTSProvider` plugin API
(`agent/tts_provider.py`). No Hermes core files are patched or
monkey-patched.

This repository began as a fork of
[`xiaoyaner-home/hermes-fishaudio-tts`](https://github.com/xiaoyaner-home/hermes-fishaudio-tts)
and selectively incorporates features adapted from
[`Ryvexam/hermes-fishaudio-plugin`](https://github.com/Ryvexam/hermes-fishaudio-plugin).
See [`NOTICE.md`](NOTICE.md) for full attribution and what came from where.
Neither upstream author endorses this fork.

## Features

| Capability | Description |
|---|---|
| TTS provider | Registers `fishaudio` via `PluginContext.register_tts_provider()`. |
| Voice cloning | Fish Audio `reference_id` (accepted under `voice`, `reference_id`, or `voice_id` in config). |
| Models | `s2.1-pro`, `s2.1-pro-free`, `s2-pro`, `s1` — the four Fish documents for `/v1/tts`. Unknown values fall back to `s2.1-pro-free` so a typo cannot target a deprecated variant. |
| Formats | MP3, WAV, Opus, **PCM**. Validated against Fish's own format set rather than Hermes core's `resolve_output_format()`, which doesn't know about `pcm` and would silently downgrade it to mp3. |
| Controls | `temperature`, `top_p`, `sample_rate`, `mp3_bitrate`, `opus_bitrate`, `latency`, `speed` / `volume` / `normalize_loudness` (via prosody), `chunk_length`, `normalize`. |
| Streaming | `stream()` yields Fish response bytes incrementally. |
| **Voice aliases** | `tts.fishaudio.voices.<alias>` → `reference_id`. Friendly names work anywhere a voice is accepted. |
| **Presets** | `tts.fishaudio.presets.<name>` bundles of voice / model / prosody. Selected via `preset=` (config default, call-time kwarg, or tool-call `**extra`). Explicit call-time args still win over a preset. |
| **Bounded retry** | Transient network failures and 5xx (except 501) retry with exponential backoff (`tts.fishaudio.max_retries`, default 2). 4xx and 501 do not retry. |
| **HTTPS enforcement** | Non-HTTPS endpoints are rejected unless `tts.fishaudio.allow_insecure_local: true` and the host is `localhost` / `127.0.0.1` / `[::1]`. |
| **Error redaction** | API key, configured voice, and per-call voice are stripped from every error message before it surfaces. |
| Zero runtime deps | stdlib `urllib` only — no `requests`. |

## Streaming limitation

Hermes's standard `text_to_speech` path completes a file before platform
delivery even though `FishAudioTTSProvider.stream()` yields Fish response
bytes incrementally. True chunk-to-platform voice-channel playback requires
a generic streaming consumer in Hermes core; this plugin does not patch the
gateway to simulate it.

## Install

```bash
hermes plugins install alauer/hermes-fishaudio-provider
hermes plugins enable fishaudio-provider
```

Add your key to the active Hermes profile's `.env`:

```env
FISH_AUDIO_API_KEY=your_key_here
```

(Get one at https://fish.audio/app/api-keys. `FISHAUDIO_API_KEY` and
`FISH_API_KEY` are accepted as aliases for migration.)

Then configure it in `~/.hermes/config.yaml`:

```yaml
tts:
  provider: fishaudio
  fishaudio:
    model: s2.1-pro        # s1 | s2-pro | s2.1-pro | s2.1-pro-free
    voice: ""              # raw Fish reference_id, or a name from `voices:`
    temperature: 0.7
    top_p: 0.7
    mp3_bitrate: 128       # 64 | 128 | 192
    latency: normal        # low | balanced | normal
    # api_base: https://api.fish.audio    # override only for a self-hosted proxy
    # timeout: 120
    # max_retries: 2
    # allow_insecure_local: false          # set true ONLY for a local proxy

    # Friendly names for reference_ids.
    voices:
      jarvis: "<fish-audio-reference-id>"
      martin: "<fish-audio-reference-id>"

    # Named bundles — one per agent personality, for example.
    presets:
      jarvis:
        voice: jarvis
        model: s2.1-pro
        temperature: 0.6
      martin:
        voice: martin
        model: s1
        temperature: 0.5
        latency: low
```

Or select it interactively via `hermes tools` → Text-to-Speech → Fish Audio.

### Example: a tool call picking a voice alias

Once `voices` / `presets` are configured, an agent can request its
personality's voice without touching config:

```
text_to_speech(text="...", preset="jarvis")
```

## Security model

| Concern | Handling |
|---|---|
| API key | Only `FISH_AUDIO_API_KEY` (env, plus two aliases) is ever used for auth. A tool call cannot supply or override it. |
| Tool-call override | `**extra` from a tool call is **allow-listed** (`temperature`, `top_p`, `sample_rate`, `mp3_bitrate`, `opus_bitrate`, `latency`, `chunk_length`, `normalize`, `volume`, `preset` — nothing else passes through, deny-by-default). `authorization`, `api_base`, `headers`, and the `model` header can never be set from a tool call, only from env/config. |
| Preset selection is safe | `preset` only *selects* a named config object the operator already defined — a tool call cannot invent or modify a preset. |
| HTTPS | Non-HTTPS endpoints are rejected unless explicitly opted in via `allow_insecure_local` and the host is local. |
| Error reporting | API error messages are redacted before being raised — the API key, configured `reference_id`, and per-call `reference_id` are stripped so they cannot leak into agent-visible tool output or logs. |
| Private voice data | Do not commit private `reference_id`s or generated private audio samples. The `.gitignore` already excludes common audio formats and `.env`. |

## Configuration reference

| Key | Default | Notes |
|---|---:|---|
| `model` | `s2.1-pro-free` | One of `s1`, `s2-pro`, `s2.1-pro`, `s2.1-pro-free`. Unknown values fall back to the default. |
| `voice` / `reference_id` / `voice_id` | — | Fish voice/reference ID, or a name from `voices:`. |
| `format` | `mp3` | `mp3`, `wav`, `pcm`, or `opus`. |
| `temperature` | — | Sampling temperature. |
| `top_p` | — | Nucleus sampling. |
| `sample_rate` | — | Output sample rate in Hz. |
| `mp3_bitrate` | `128` | `64` / `128` / `192`. |
| `opus_bitrate` | — | Optional Opus bitrate. |
| `speed` | — | Prosody speed multiplier (0.5–2.0). |
| `volume` | — | Prosody volume (-20 to 20). |
| `normalize_loudness` | — | Boolean, attached to `prosody` (s2-pro / s2.1-pro family only). |
| `latency` | — | `low`, `balanced`, or `normal`. |
| `chunk_length` | — | Characters per generation chunk. |
| `normalize` | — | Whether to normalize/clean input text. |
| `timeout` | `120` | HTTP timeout in seconds. |
| `max_retries` | `2` | Bounded retry on 5xx / network failures. 4xx is never retried. |
| `api_base` | `https://api.fish.audio` | Custom Fish-compatible endpoint. HTTPS required unless `allow_insecure_local` is set. |
| `allow_insecure_local` | `false` | Opt-in only. Lets you point at a local proxy without HTTPS. |
| `voices.<alias>` | — | Map friendly name to `reference_id`. |
| `presets.<name>` | — | Bundles of voice / model / prosody. |

## Compatibility matrix

| Plugin version | Hermes baseline | Status |
|---|---|---|
| `0.3.0` | Hermes v0.20+ / `v2026.8.3+` TTS API | Supported; native registration, dispatch, voice-compatible conversion, retry, voice aliases, presets, and security tests verified. |
| `0.2.x` | Hermes v0.19 / v0.20 | Maintenance baseline; see upstream [`xiaoyaner-home/hermes-fishaudio-tts`](https://github.com/xiaoyaner-home/hermes-fishaudio-tts). |

## Development

Clone Hermes and this repository, then run the test suite with the Hermes
checkout on `PYTHONPATH`:

```bash
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-fishaudio-provider
PYTHONPATH=/path/to/hermes-agent /path/to/hermes-agent/.venv/bin/python -m pytest --import-mode=importlib --rootdir=tests tests
```

A real API smoke test is intentionally not run in public CI because it
requires a credential and incurs an external request. Maintainers run it
before releases.

For local Hermes v0.20 compatibility verification, run both the plugin
suite and the host TTS registration / registry / dispatch tests against
the same Hermes checkout. Use an isolated temporary `HERMES_HOME` for
install or synthesis smoke tests; do not change the live `tts.provider`
during release validation.

## Security

- Never commit `FISH_AUDIO_API_KEY` or generated private voice samples.
- The plugin blocks tool-call extras from overriding authorization headers,
  the API endpoint, the model header, or any local file path.
- API response errors are bounded and redact the API key, configured
  `reference_id`, and per-call `reference_id` before surfacing.

Please report vulnerabilities privately through GitHub's security advisory
interface.

## License

MIT — see [LICENSE](LICENSE). Copyright notices from both upstream projects
are preserved there. See [NOTICE.md](NOTICE.md) for attribution details.
Neither upstream author endorses this fork.