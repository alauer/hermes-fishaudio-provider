# Design note — Palace-owned Fish Audio provider

Governing contract: [issue #1](https://github.com/alauer/hermes-fishaudio-provider/issues/1)
Working branch: `feat/palace-integration`
Base upstream: `xiaoyaner-home/hermes-fishaudio-tts` @ `042ec252c95165e62c52718575d9e40fd115f56a`
Feature donor: `Ryvexam/hermes-fishaudio-plugin` @ `dc45f8a3305a39a1d36b686d7bd66ecdfa25a450`
Public provider name (runtime, unchanged): `fishaudio`
Public project identity: `hermes-fishaudio-provider`

## Purpose of this document

Issue #1 is a long prose contract. This note flattens it into twelve numbered
checklist items — the IMPLEMENTATION CONTRACT clauses — so that every
requirement has exactly one owner, one implementation approach, and one named
acceptance test. Nothing in issue #1 is allowed to live only in prose: the
coverage map at the end proves each of the issue's own numbered sub-lists maps
onto one of the twelve clauses.

Read the checklist as the authority on *what must be true*, `provider.py` as the
authority on *how it is true today*, and the conflict register as the authority
on *where Fish's real behaviour disagrees with inherited code*.

Legend for status: **done** = implemented and covered by a passing named test;
**partial** = implemented, test coverage thinner than the clause deserves;
**open** = not yet satisfied.

---

## Architecture in one page

One Python module, one registration, no core edits.

```
hermes plugin load
        │
        ├─ pip entry point  hermes_fishaudio_provider → provider:register
        └─ directory copy   <plugin>/__init__.py      → re-exports provider.register
                    │
                    ▼
            register(ctx) → ctx.register_tts_provider(FishAudioTTSProvider())
                    │
                    ▼
      Hermes tts_registry ──► tools.tts_tool._dispatch_to_plugin_provider
                    │
                    ▼
        FishAudioTTSProvider.synthesize / .stream
                    │
        ┌───────────┴───────────────────────────────┐
        │ pure, no I/O                              │ I/O
        │  _sanitize_extra    (deny-by-default)     │  _http_post
        │  _effective_config  (preset merge)        │   ├─ bounded retry
        │  _resolve_voice_alias                     │   ├─ _backoff_seconds
        │  _build_body        (/v1/tts JSON)        │   └─ _sleep (stubbable)
        │  _resolve_endpoint  (config/env only)     │  urllib.request
        │  _resolve_model_header                    │
        │  _https_enforced                          │
        │  _redact                                  │
        └───────────────────────────────────────────┘
```

Two deliberate shapes carry most of the design weight:

1. **The pure/impure split.** Everything that decides *what* gets sent is a pure
   function taking config and kwargs and returning a dict. Everything that
   *sends* it lives in `_http_post` / `stream`. This is what makes the security
   and precedence tests cheap and the retry tests sleepless.
2. **Config and env are privileged; caller `**extra` is not.** The endpoint, the
   API key, the headers, and the model header are resolved only from operator
   config or environment. A tool call — which in practice may be steered by
   model output or injected text — can influence only the allow-listed
   synthesis parameters. This is the one boundary where "deny by default" is
   non-negotiable.

---

## Checklist — contract clauses 1 through 12

### 1. Feature branch from `origin/main`, base SHA recorded and verified

- **Requirement.** All work on a branch cut from the target repo's current
  `origin/main`; the base SHA is recorded before any edit and verified after.
- **Approach.** `feat/palace-integration` off `main`. Record the base SHA in the
  PR body and in the completion handoff, not only in shell history.
- **Acceptance test.** Not a pytest gate — a validation gate:
  `git merge-base --is-ancestor <base_sha> HEAD` plus
  `git ls-remote origin feat/palace-integration` matching local `HEAD`.
- **Status.** done — base `042ec252c95165e62c52718575d9e40fd115f56a`, verified
  against the remote after push.
- **Open question.** `main` has since moved (CI registration commit
  `196396f`). Rebase or leave the PR on the original base? Default: leave it;
  the base SHA is the audited one the issue pins, and a rebase would move the
  PR head and invalidate the already-green exact-head CI run.

### 2. One native provider named `fishaudio`, registered only via `PluginContext.register_tts_provider()`

- **Requirement.** Exactly one registered provider, exactly one registration
  path, no second provider under an alias, no patching of Hermes core.
- **Approach.** `register(ctx)` lives on `provider.py` and does nothing but
  `ctx.register_tts_provider(FishAudioTTSProvider())`. The repo-root
  `__init__.py` re-exports that same symbol so the directory-copy install path
  and the pip entry-point path converge on one function. `name` property returns
  the literal `"fishaudio"` regardless of package/project renaming.
- **Acceptance test.** `test_provider_metadata`,
  `test_register_uses_native_provider_hook`,
  `test_root_register_uses_native_provider_hook`.
- **Status.** done.
- **Open question.** None.

### 3. No Hermes-core edits, no runtime monkey-patching

- **Requirement.** The diff touches only this repository; nothing rebinds a
  Hermes attribute at import or call time.
- **Approach.** Import only the documented surface
  (`agent.tts_provider.TTSProvider`, `resolve_output_format`,
  `DEFAULT_OUTPUT_FORMAT`). Config reads (`tools.tts_tool._load_tts_config`,
  `hermes_cli.config.get_env_value`) are lazy, inside function bodies, wrapped
  in `try/except` returning an empty dict — read-only, and tolerant of a Hermes
  version that renames them.
- **Acceptance test.** Validation gate, not pytest: `git diff --name-only <base>
  HEAD` contains only paths in this repo, and `git status` in the Hermes
  checkout is clean.
- **Status.** done.
- **Open question.** Both lazy imports reach private Hermes symbols
  (`_load_tts_config`). That is not monkey-patching, but it is a private-API
  dependency. Worth a follow-up: ask upstream Hermes for a public config
  accessor, and meanwhile keep the `except Exception: return {}` fallback so a
  rename degrades to defaults instead of breaking synthesis.

### 4. Preserve and expand the real current-Hermes PluginManager → registry → dispatcher integration test

- **Requirement.** A test that exercises the real plugin discovery and dispatch
  path against the local Hermes checkout, not a mock of it.
- **Approach.** `tests/test_hermes_integration.py` drives the actual
  `PluginManager`, then the real `tts_registry`, then
  `tools.tts_tool._dispatch_to_plugin_provider`, with only the HTTP transport
  faked. A second test loads the plugin under its canonical directory name so
  the directory-copy path is covered by the same harness.
- **Acceptance test.** `test_plugin_manager_dispatch_and_voice_contract`,
  `test_plugin_loads_under_canonical_directory_name`.
- **Status.** done.
- **Open question.** The test binds to the Hermes checkout present on the
  machine. Which Hermes version is authoritative for CI — the pinned tag in
  `.github/workflows/ci.yml`, or current `HEAD`? Today CI pins a tag while local
  runs used a newer `HEAD`; both passed, but the discrepancy should be a
  deliberate matrix entry rather than an accident.

### 5. Integrate allowlist, aliases, presets, bounded retry, verified model catalogue, security tests, complete redaction

This is the densest clause; it carries six sub-requirements from the issue's
"Integrate from the donor" list. Each is broken out.

**5a. Deny-by-default extras allowlist.**
`ALLOWED_EXTRA_KEYS` is a `frozenset` of ten synthesis parameters;
`_sanitize_extra` is a dict comprehension keeping only members of that set, so
an unknown key cannot reach the body even by accident. `FORBIDDEN_EXTRA_KEYS`
exists as documentation and as a test fixture, not as the enforcement mechanism
— enforcement is the allowlist, and that ordering matters: a denylist that is
missing an entry fails open, an allowlist that is missing an entry fails closed.
Tests: `test_sanitize_drops_unknown_keys`, `test_all_allowed_keys_pass`,
`test_security_keys_never_pass_through`.

**5b. Named voice aliases.** `tts.fishaudio.voices` maps readable names to Fish
reference IDs; `_resolve_voice_alias` returns the mapped value or, for a
non-alias, the input unchanged — so a raw reference ID keeps working and the
feature is purely additive. Tests: `test_voice_alias_resolves_to_reference_id`,
`test_unknown_voice_name_passes_through`, `test_default_voice_reads_any_alias`,
`test_synthesize_resolves_alias_via_tool_call`.

**5c. Named presets.** `tts.fishaudio.presets.<name>` is a config bundle merged
over the base section by `_effective_config`. Precedence, lowest to highest:
defaults < `tts.fishaudio` < preset < explicit call arguments. `preset` is
allow-listed in `**extra` because selecting an operator-defined object is safe;
*defining* one from a call is not possible. Tests:
`test_resolve_known_preset`, `test_resolve_unknown_preset_returns_empty`,
`test_effective_config_merges_preset_over_base`,
`test_explicit_call_args_win_over_preset`, `test_preset_is_allowed_through_sanitize`.

**5d. Bounded retry.** Retry transient `URLError` and `5xx`; never retry `4xx`
(including `429`) and never retry `501`. Bound is `max_retries + 1` attempts,
default 3 total, with `_backoff_seconds` capped at 8s. `_sleep` is a module-level
indirection so tests stub it and the suite performs no real sleep. Tests:
`test_5xx_then_success_retries`, `test_5xx_exhausts_retries_and_redacts`,
`test_501_is_not_retried`, `test_http_429_is_redacted_and_not_retried`,
`test_connection_reset_retries_and_succeeds`.

**5e. Verified model catalogue, honestly described.** `SUPPORTED_MODELS` is a
closed `frozenset` (`s2.1-pro`, `s2.1-pro-free`, `s2-pro`, `s1`); an unrecognised
model falls back to `DEFAULT_MODEL` with a debug log rather than being sent
verbatim. `speech-1.x` is deliberately excluded and documented as an
OpenAI-compat-layer model, not a raw `/v1/tts` model — see conflict C4. Tests:
`test_unknown_model_falls_back_to_default`, `test_model_arg_overrides_config`.

**5f. Complete redaction.** `_redact` strips the API key, the configured
reference ID, and the per-call reference ID from every error string, on both the
`synthesize` and `stream` paths and on both the fail-fast and
retries-exhausted branches. Tests: `test_redact_strips_api_key`,
`test_redact_strips_configured_voice`, `test_redact_strips_per_call_voice`,
`test_redact_with_no_secrets_is_identity`, plus redaction assertions inside the
4xx/429/5xx tests.

- **Status.** done for 5a–5f.
- **Open questions.** (i) The model catalogue is a frozen set in code; adding a
  model is a code change plus a test change. Should it be operator-extensible
  via config? Default answer: no — a closed set is the point, and an operator
  who needs a new model should get a release, not a config escape hatch.
  (ii) `_redact` does substring replacement; a one- or two-character reference
  ID would corrupt unrelated error text. Low risk with real Fish IDs, but a
  minimum-length guard is cheap insurance.

### 6. Remove or correctly map the ignored `normalize_loudness` and `language` fields

- **Requirement.** Stop advertising settings Fish ignores; either drop them or
  map them to where Fish actually reads them.
- **Approach.** `language` is dropped entirely from the request body — it is a
  Fish STT-side field and was never honoured by `/v1/tts`; a `language` key in
  config is ignored rather than forwarded. `normalize_loudness` is *remapped*,
  not dropped: it moves from a top-level field into `prosody`, attached only
  when `True` (Fish's documented default is `False`, so emitting
  `prosody: {normalize_loudness: false}` would be noise).
- **Acceptance test.** `test_language_is_not_sent_as_top_level_field`,
  `test_language_in_config_is_ignored`,
  `test_normalize_loudness_attached_to_prosody`,
  `test_normalize_loudness_not_in_top_level_when_false`.
- **Status.** done, pending the documentation verification in C1/C2 below.
- **Open question.** `prosody.normalize_loudness` is documented for `s2-pro` and
  the `s2.1-pro` family. We attach it unconditionally and let Fish ignore it for
  other models. Alternative: refuse the setting for models that do not support
  it, so the operator learns their config is inert. That is stricter and
  arguably more honest, but it couples the request builder to per-model
  capability tables we have not verified. Flagged, not decided.

### 7. Enforce HTTPS for non-local endpoints, and test the policy

- **Requirement.** HTTPS required; if local `http` development endpoints are
  supported at all, they require an explicit opt-in and documentation.
- **Approach.** `_https_enforced` allows `https` unconditionally; allows `http`
  only when the host is exactly `localhost`, `127.0.0.1`, or `::1` **and**
  `tts.fishaudio.allow_insecure_local` is true; raises `ValueError` otherwise.
  The check runs in both `synthesize` and `stream`, before the API key is read,
  so a misconfigured endpoint fails on policy rather than on auth.
- **Acceptance test.** `test_https_enforced_by_default`,
  `test_localhost_http_allowed_with_opt_in`,
  `test_localhost_http_rejected_without_opt_in`,
  `test_non_local_http_rejected_even_with_opt_in`,
  `test_synthesize_rejects_http_endpoint`.
- **Status.** done.
- **Open question.** Host matching is exact-string. `http://localhost.evil.tld`
  is correctly rejected, but a loopback alias in `/etc/hosts` or an IPv6-mapped
  form (`::ffff:127.0.0.1`) is also rejected. Acceptable, and preferable to
  resolving hostnames inside a policy check — but worth stating in the README so
  no one files it as a bug.

### 8. Consolidate packaging to one canonical implementation, retaining both load paths

- **Requirement.** Kill the dual-`__init__.py` arrangement without breaking
  either the source-checkout/pip path or the Hermes directory-copy path.
- **Approach.** `provider.py` is the single implementation. Root `__init__.py`
  re-exports `register` for directory-copy installs. The legacy
  `hermes_fishaudio_tts/` subpackage is deleted, and a test asserts it stays
  deleted. Both entry points (`fishaudio-provider`, the legacy
  `fishaudio-tts`) resolve to the same `provider:register` symbol, so an
  existing install keeps working after the rename.
- **Acceptance test.** `test_no_dual_init_packaging`,
  `test_root_init_imports_without_package_context`,
  `test_provider_module_is_also_loadable_directly`,
  `test_pyproject_declares_hermes_plugin_entrypoints`,
  `test_pyproject_module_target_is_loadable`,
  `test_plugin_loads_under_canonical_directory_name`.
- **Status.** done.
- **Open question.** How long does the legacy `fishaudio-tts` entry point stay?
  Proposal: keep it through the next minor release, note the deprecation in
  `CHANGELOG.md`, remove it in the release after.

### 9. No caching, no persistent daily budget in this pass

- **Requirement.** Explicitly deferred by the issue — both introduce state and
  concurrency semantics that need their own decision and test plan.
- **Approach.** Absence, enforced by review rather than by a test. No module
  keeps synthesis state between calls; the provider holds no mutable instance
  attributes.
- **Acceptance test.** Review gate: grep the diff for cache/budget/persistence
  primitives (`sqlite`, `shelve`, `pickle`, `lru_cache`, a state file path) and
  confirm none appear on a synthesis path.
- **Status.** done (by construction).
- **Open question.** Should the deferral be recorded as a follow-up issue so it
  is tracked rather than merely absent? Recommended: yes, one issue covering
  both, with the concurrency question stated up front.

### 10. Keep credentials, real reference IDs, generated audio, and `.env` out of Git

- **Requirement.** Nothing secret and nothing generated is tracked.
- **Approach.** `.gitignore` covers `.env` and audio extensions; the example
  config carries placeholders only; tests use obviously-fake IDs; `_redact`
  keeps secrets out of logs and error text, which is the leak path people
  forget.
- **Acceptance test.** Validation gate: scan tracked *and* untracked files for
  `.env` and for `mp3/wav/pcm/opus/flac/ogg/m4a/aac/aiff`, plus a grep for
  credential-shaped strings across `*.py,*.yaml,*.yml,*.md,*.toml,*.json`.
- **Status.** done — scan returned empty.
- **Open question.** None. Re-run the scan before every push; it is cheap and
  the failure mode is permanent.

### 11. Preserve MIT obligations; attribute both upstreams and their pinned commits; imply no endorsement

- **Requirement.** Upstream license and copyright retained, both source projects
  named with pinned commits, fork history explained, no implied endorsement.
- **Approach.** `LICENSE` retains the upstream MIT text and copyright line.
  `NOTICE.md` names both projects with their pinned SHAs and states which
  component came from which. `provider.py`'s module docstring carries the same
  provenance so a reader of the code alone still sees it. The README repeats the
  attribution and includes the explicit sentence that neither upstream author
  endorses this fork.
- **Acceptance test.** Review gate plus the metadata assertions in
  `test_pyproject_metadata_renamed_to_alauer_slug`. Verify manually that
  `LICENSE`, `NOTICE.md`, README, and the module docstring all name both
  pinned SHAs.
- **Status.** done.
- **Open question.** Should attribution be per-function (a provenance comment on
  each adapted helper) rather than per-module? Per-module plus `NOTICE.md`
  satisfies MIT; per-function is a courtesy. Proposal: keep the current scheme
  and note provenance inline only where a reader would otherwise guess wrong.

### 12. Rename project metadata, docs, badges, and URLs; keep the runtime name `fishaudio`

- **Requirement.** Everything identifying the project becomes
  `alauer/hermes-fishaudio-provider`; the provider's runtime name stays
  `fishaudio` so existing configs and voice bubbles keep working.
- **Approach.** `pyproject.toml` name/URLs, README badges and install
  instructions, `CHANGELOG.md`, `SECURITY.md`, `plugin.yaml`, and `examples/`
  all renamed. The `name` property in `provider.py` is untouched and covered by
  a test, which is what keeps the rename from becoming a breaking change.
- **Acceptance test.** `test_pyproject_metadata_renamed_to_alauer_slug`,
  `test_provider_metadata` (asserts runtime `name == "fishaudio"`).
- **Status.** done.
- **Open question.** None.

---

## Conflict register — issue #1 versus upstream and Fish reality

Each entry: the conflict, the decision taken, how to verify it against
authoritative sources, and what happens if verification contradicts us.

**Verification sources, in order of authority.** (1) The official Fish Audio
Python SDK source — the request models are the tightest available statement of
what `/v1/tts` accepts. (2) The official Fish Audio HTTP API documentation.
(3) A single live probe against a throwaway key, run by a human, never from the
test suite. Tests must never call the real API, so a live probe is a manual
verification step recorded in a comment, not a gate.

**C1 — `language` was sent as a top-level `/v1/tts` field.**
Inherited from upstream; we drop it. Verify: search the SDK's TTS request model
for a `language` field, and the HTTP docs' `/v1/tts` body schema. Expected
result: absent from TTS, present on the STT side. If verification shows Fish
*does* accept it on `/v1/tts`, the fix is small and additive — restore it as an
allow-listed, validated field and add a body test.

**C2 — `normalize_loudness` was sent top-level; Fish reads it inside `prosody`.**
We remap rather than remove, because the setting is real, just misplaced.
Verify: the SDK's prosody model, and the per-model support note for `s2-pro` and
the `s2.1-pro` family. If prosody does not carry it either, delete the setting
and its config key outright — advertising an inert knob is the defect the clause
exists to kill.

**C3 — `pcm` is a valid Fish format but not a Hermes core format.**
Hermes' `resolve_output_format` does not know `pcm` and would silently downgrade
it to `mp3`. We validate against our own `SUPPORTED_OUTPUT_FORMATS` instead, and
map `ogg` → `opus` because a caller asking for `ogg` means the Opus container in
practice. Verify: the SDK's format enum. Note this is a divergence from core
behaviour, documented rather than hidden — the alternative (silently returning
mp3 bytes to a caller who asked for PCM) is worse.

**C4 — the donor's model catalogue includes models the raw endpoint does not serve.**
`speech-1.5`/`speech-1.6` live behind Fish's OpenAI-compatibility layer, not
`/v1/tts`. We exclude them and document why. Verify: the SDK's accepted model
values for the raw endpoint versus the compat layer, and whether any listed
model is account-tier-gated. Account-dependent models must be labelled as such
in the README rather than quietly listed as supported.

**C5 — `mp3_bitrate` accepted arbitrary integers.**
Fish documents an enum (64/128/192) and the SDK enforces it; an out-of-enum
value is dropped or rejected server-side. We validate locally and drop invalid
values so the failure is visible in a unit test instead of in production audio.
Verify: the SDK enum. Same treatment for `latency` (`low`/`balanced`/`normal`).

**C6 — retry semantics for `429`.**
Issue #1 requires retrying `429`; the implementation currently does not, and
fails fast with a redacted message instead. This is the one live disagreement
between the contract and the code. The reasoning for failing fast: without a
`Retry-After` honouring implementation, retrying a rate limit mostly converts
one clear error into three slower ones. The reasoning for the contract: a
transient burst limit genuinely does clear. **Resolution path:** implement
`429` retry gated on a `Retry-After` header, bounded by `max_retries` and by a
ceiling on the honoured delay, falling back to the existing fail-fast when the
header is absent. Verify the header's presence against the API docs. Until that
lands, the divergence must be stated in the PR body and the README, not left
for a reviewer to discover — and the acceptance criterion in issue #1 is not
fully met.

**C7 — streaming.**
The provider reads the upstream response incrementally, but Hermes'
`text_to_speech` path completes a file before delivery. This is not a defect to
fix here; clause 6 of the issue's defect list asks only that it be documented.
Verify by reading the current `tools/tts_tool.py` delivery path, and restate the
finding in the PR body, README, and `SECURITY.md`.

### Block-and-request-guidance path

If a clause turns out to be impossible or self-contradictory, do not weaken it
silently. The escalation is:

1. Reproduce the impossibility as a minimal failing test or a single command
   with its real output.
2. Record on the card, in this order: the clause number and its exact text, the
   authoritative source that contradicts it (SDK line, doc URL, or command
   output), the two or three options with their costs, and a recommendation.
3. Call `kanban_block(kind="needs_input", reason=...)` naming the clause number.
   Do not substitute a plausible weaker requirement and continue.
4. If the blocker is infrastructure rather than contract — CI not provisioned, a
   missing token, an API the harness cannot reach — say so explicitly and
   separate it from implementation status, so a reviewer is not left guessing
   whether the artifact or the plumbing failed.

C6 is the live candidate for this path if the `Retry-After` approach proves
unworkable.

---

## PR body outline

The pull request against `alauer/hermes-fishaudio-provider:main` uses exactly
these sections, in this order.

**Summary.** What this PR does in three or four sentences: one maintained
`fishaudio` provider, base spine preserved, named donor features integrated,
three inherited defects corrected. Branch, base SHA, head SHA, commit list.

**Architecture.** The pure/impure split and why it exists; the two load paths
converging on one `register`; the privilege boundary between operator config and
caller `**extra`; the decisions taken at each conflict in the register above,
each with its verification source.

**Feature provenance.** Two labelled lists. From `xiaoyaner-home/hermes-fishaudio-tts`
@ `042ec25`: native registration, `/v1/tts` urllib transport with bearer auth and
the model header, `reference_id` voice cloning, file and incremental synthesis,
`voice_compatible`. From `Ryvexam/hermes-fishaudio-plugin` @ `dc45f8a`:
deny-by-default extras allowlist, voice aliases, presets, bounded retry, model
catalogue, security tests, error redaction. State plainly what was adapted
rather than copied, and that neither upstream author endorses this fork.

**Test and validation commands.** Every gate as a runnable command with its real
output: full pytest run against the local Hermes checkout; `py_compile`;
isolated venv packaging/install probe with the resolved entry points;
credential and audio artifact scan; `git diff --check`; changed-file scope proof;
remote branch SHA verification; the exact-head CI run URL and conclusion. No
gate is claimed without its output.

**Security behaviour.** The allowlist as the enforcement mechanism and the
denylist as documentation; the specific keys a caller can never influence
(`api_key`, `authorization`, `headers`, `api_base`, `base_url`, `endpoint`,
`model`, `model_id`, `audio_path`, `clone`); redaction coverage across all error
paths; the HTTPS policy and the narrow local opt-in; the API key as an
environment secret that is never written to config or logs.

**Limitations.** Deferred by the issue: response caching, persistent daily
budget. Deferred by choice: zero-shot cloning from a local audio file, any
added runtime dependency. Known divergence: the `429` retry question (C6),
stated as a divergence and not as a feature. Local-opt-in host matching is
exact-string. The model catalogue is closed and requires a release to extend.

**Hermes `text_to_speech` delivery statement.** Verbatim intent: the provider
can read the Fish response incrementally via `stream()`, but Hermes' normal
`text_to_speech` path completes the audio file before platform delivery. This
provider does not change that. Nothing here should be read as live gateway
streaming.

**Closing.** `Closes #1` only when every acceptance criterion is met, C6
included. If C6 remains a divergence, reference the issue without the closing
keyword and say why in one sentence.

---

## Coverage map — every issue #1 clause maps to a contract clause

| Issue #1 clause | Contract clause | Where |
|---|---|---|
| Preserve 1 — native registration | 2 | §2 |
| Preserve 2 — real PluginManager/registry/dispatcher test | 4 | §4 |
| Preserve 3 — `/v1/tts`, bearer auth, model header | 2, 5 | §Architecture, `_request` |
| Preserve 4 — cloning via pre-uploaded `reference_id` | 5b | §5b |
| Preserve 5 — file synthesis + incremental read | 2, C7 | §2, C7 |
| Preserve 6 — `voice_compatible = True` | 2 | §2 |
| Preserve 7 — zero Hermes-core modifications | 3 | §3 |
| Integrate 1 — extras allowlist | 5a | §5a |
| Integrate 2 — voice aliases | 5b | §5b |
| Integrate 3 — presets | 5c | §5c |
| Integrate 4 — explicit retry policy | 5d, C6 | §5d, C6 |
| Integrate 5 — verified model catalogue, honest labelling | 5e, C4 | §5e, C4 |
| Integrate 6 — security override tests | 5a | §5a |
| Integrate 7 — redaction of key + both reference IDs | 5f | §5f |
| Defect 1 — `normalize_loudness` | 6, C2 | §6, C2 |
| Defect 2 — `language` | 6, C1 | §6, C1 |
| Defect 3 — HTTPS policy with documented local opt-in | 7 | §7 |
| Defect 4 — consolidate dual-`__init__.py` | 8 | §8 |
| Defect 5 — `warm()`/`release()` contract compatibility | 4 | §4, inherited no-ops covered by the integration test |
| Defect 6 — document file-complete delivery | C7 | C7, PR body |
| Deferred — no caching, no daily budget | 9 | §9 |
| Deferred — do not touch the active gateway | 9 | §9, process constraint |
| Deferred — no secrets/audio/`.env` in Git | 10 | §10 |
| Architecture constraints — public API, one provider, no patching, `tts.fishaudio` config, env-only key, stdlib preference, deterministic builders, bounded testable retry | 2, 3, 5c, 5d, 9 | §Architecture and the named clauses |
| Attribution 1–4 — MIT, NOTICE, fork history, no endorsement | 11 | §11 |
| Attribution 5 — rename metadata, keep runtime name | 12 | §12 |
| Required tests — all thirteen bullets | 2, 4, 5a–5f, 6, 7, 8 | named tests in each clause |
| Documentation requirements | 11, 12, C7 | README, §11, §12, C7 |
| Validation gates 1–10 | 1, 3, 8, 10 | the gate lists in those clauses and the PR body |
| Acceptance criteria 1–10 | all | the status line of each clause |

No clause is unmapped. Where a clause's status is anything other than **done**,
the reason is stated in that clause and, for C6, escalated in the conflict
register.
