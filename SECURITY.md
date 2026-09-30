# Security Policy

Please report vulnerabilities through GitHub's private vulnerability
reporting rather than a public issue. Do not include API keys, private
voice identifiers, generated private audio, or full provider responses in
reports.

## Security model

- **API key** — only `FISH_AUDIO_API_KEY` (env, with two aliases
  `FISHAUDIO_API_KEY` and `FISH_API_KEY`) is ever used for auth. A
  `text_to_speech` tool call cannot supply or override it.
- **Tool-call override** — `**extra` from a tool call is **allow-listed**
  (`temperature`, `top_p`, `sample_rate`, `mp3_bitrate`, `opus_bitrate`,
  `latency`, `chunk_length`, `normalize`, `volume`, `preset` — nothing
  else passes through, deny-by-default). `authorization`, `api_base`,
  `headers`, the `model` header, and `audio_path` / `clone` cannot be
  set from a tool call, only from env/config.
- **HTTPS enforcement** — non-HTTPS endpoints are rejected unless
  `tts.fishaudio.allow_insecure_local: true` is set and the host is
  `localhost` / `127.0.0.1` / `[::1]`.
- **Error reporting** — API error messages are redacted before being
  raised: the API key, configured `reference_id`, and per-call
  `reference_id` are stripped so they cannot leak into agent-visible
  tool output or logs.
- **Preset selection is safe** — `preset` only *selects* a named config
  object the operator already defined; a tool call cannot invent or
  modify a preset.
- **Private voice data** — don't commit private `reference_id`s, clone
  samples, or generated private audio samples. The `.gitignore`
  already excludes common audio formats and `.env`.