# LIGHT Product Specification

This document defines the intended product behavior for release `v0.5.0`.
Implementation evidence belongs in [FEATURES.md](FEATURES.md), technical design
in [ARCHITECTURE.md](ARCHITECTURE.md), and safety boundaries in
[SAFETY.md](SAFETY.md).

## Product statement

LIGHT is a local-first, continuously listening desktop and browser automation
assistant for Windows and macOS. It optimizes common actions for low latency,
uses an explicitly selected AI model only when useful, verifies high-risk physical and
browser actions, and keeps interruption authority with the user.

Target users include people who need hands-free navigation, developers and
researchers moving quickly between applications and websites, and users who
benefit from accessibility-oriented computer control. LIGHT is not a general
shell agent, a cloud service, or a replacement for OS permissions and user
judgment.

## Functional requirements

### Voice ingestion

- Consume ordered transcription events through `VoiceInputProvider` without
  coupling the core loop to one STT implementation.
- Select local Handy or a custom transcript-feed API independently from the AI
  provider and model.
- Poll continuously on a listener thread while actions execute elsewhere.
- Suppress rapid duplicate non-repeatable transcripts while preserving intended
  repeatable commands.
- Remain operational with voice ingestion idle when no provider is available.
- Never write to the Handy SQLite database.

Handy or a user-controlled service supplies STT/VAD outside LIGHT. Direct
microphone capture, VAD, and Whisper are not implemented in this release.

### Decision engine

- Route common commands through deterministic parsing without model calls.
- Support compound commands and contextual continuations without prematurely
  mutating live state.
- Use the explicitly selected AI provider/model only for command-like requests
  that need structured planning. Local Ollama/Qwen3 remains the default.
- Support local Ollama and LM Studio plus opt-in OpenAI, Claude, Gemini, and
  custom OpenAI-compatible services without changing the action vocabulary.
- Never auto-select an installed provider, silently substitute a model, or
  persist credential values in repository configuration.
- Normalize and validate every model-generated action before execution.
- Use Laya only as a guarded final classifier fallback.
- Ignore casual or malformed speech rather than inventing an action.

### Desktop control

- Provide known-application launch/close, foreground-aware typing, hotkeys,
  window controls, media controls, and mouse movement.
- Isolate Windows and macOS primitives behind `PlatformController`.
- Restrict normal close behavior to processes LIGHT has tracked.
- Fail when the foreground target cannot be verified for typing.

### Deterministic browser control

- Own a Playwright Chromium session for direct navigation and DOM actions.
- Recover from a closed page/context where supported.
- Locate only visible elements and map browser coordinates to screen clicks.
- Rank named search targets; never treat an arbitrary first result as an
  official target.
- Verify named-result navigation from the pre-click URL and destination
  semantics before reporting success.
- Verify clipboard writes used by copy actions.

### Autonomous web tasks

- Reserve `AGENT_TASK` for open-ended research and multi-step web goals.
- Run at most one agent task on `LIGHT-AgentWorker` without blocking ordinary
  commands.
- Use an isolated Browser Use session and the explicitly selected AI provider.
- Expose cancellation and bounded cleanup while acknowledging that third-party
  internals may not terminate instantly.

### Interruption and state

- Recognize explicit STOP/CANCEL phrases before normal planning.
- Set the shared cancellation event and prioritize STOP once transcription
  reaches `ingest_text()`.
- Cancel queued normal work and plan-scoped dependents appropriately.
- Clear stale browser context on STOP and keep browser ownership truthful.
- Maintain thread-safe live state and isolated planning clones.

## Non-functional requirements

| Area | Requirement | Evidence boundary |
| --- | --- | --- |
| Deterministic latency | Common parsing should remain sub-millisecond on normal developer hardware | Unit/performance tests; not a universal hardware guarantee |
| Voice polling | Default poll interval is 150ms | Configuration/source inspection |
| STOP signaling | Cancellation event should be set within 5ms after `ingest_text()` receives explicit STOP | Unit timing; excludes STT and provider polling |
| Privacy | No mandatory cloud LLM, audio upload, telemetry, or analytics | Source/config inspection; requested web traffic remains external |
| Reliability | Fail loudly when required verification fails | Unit and local-browser tests |
| Portability | Shared logic runs in Windows/macOS CI; OS calls stay behind the platform interface | CI and mocked platform tests; physical Mac validation is separate |
| Maintainability | Minimal dependencies, explicit boundaries, regression tests, current docs | Repository review |

## Release acceptance and limits

`v0.5.0` is accepted when the Windows/macOS CI matrix passes the default 155
test discovery suite and documentation distinguishes CI from physical-host
evidence. Current limitations are:

- Handy and end-to-end voice control are not physically verified on macOS;
- Accessibility, Screen Recording, Retina, and mixed-DPI multi-monitor behavior
  are not validated on a physical Mac in repository evidence;
- application launch targets are an allowlist rather than system-wide discovery;
- named-result ranking considers the loaded page, not an autonomous multi-page
  retry/scroll strategy;
- some Playwright and Browser Use operations are cooperatively, not instantly,
  cancellable;
- the optional Browser Use/Laya environment has a known `click` dependency
  metadata conflict.

Planned work is non-binding until implemented and verified; see
[ROADMAP.md](ROADMAP.md).
