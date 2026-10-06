# LIGHT Roadmap

This roadmap separates released work from current risks and future ideas. A
checked item means source plus automated evidence exists; it does not imply
physical validation on every supported host.

## Released in `v0.5.0`

- [x] deterministic-first command routing with guarded Laya and optional local
  Qwen planning;
- [x] background transcript listener and STOP-priority producer/consumer queue;
- [x] plan-scoped dependent cancellation and thread-safe planning state;
- [x] deterministic Playwright browser with candidate ranking, physical click
  handling, clipboard read-back, and named-destination verification;
- [x] Browser Use isolation and one non-blocking `LIGHT-AgentWorker`;
- [x] atomic agent admission and ownership preservation;
- [x] Windows/macOS `PlatformController` and `VoiceInputProvider` boundaries;
- [x] tracked-process-only normal app close;
- [x] local/private Browser Use defaults;
- [x] 155-test Windows/macOS CI baseline and opt-in host smoke suites;
- [x] consolidated engineering documentation and source-of-truth map.

## Current hardening priorities

Phase 0/1 is merged by PR #8 at `6350e38`:
bounded non-blocking planning, ordered admission, cancellation generations,
task identity/results, truthful worker ownership, and bounded timing evidence.
Phase 2 is implemented on `codex/typed-capability-foundation`, pending review:
eight opt-in typed capabilities backed by existing commands, a pure registry,
strict admission/dispatch validation, and existing action-specific verification.
No new automation backend, structured read result, dependency scheduler, or
context/entity system is included. See [ARCHITECTURE.md](ARCHITECTURE.md).

Next, separately review Phase 2 and obtain authorization for Phase 3: one bounded
semantic compiler call into the validated capability boundary, initially only
single-step supported plans, with out-of-band confirmation and deterministic
rejection tests. Do not auto-start compiler/context/vision/agent work.

1. **Resolve optional dependency metadata conflict** — select a compatible
   Browser Use/Laya/Hugging Face set and validate agent behavior before changing
   pins.
2. **Broaden cancellation coverage** — identify blocking Playwright/OS calls
   that can accept timeouts or cancellation without harming deterministic
   latency.
3. **Physical macOS validation** — exercise permissions, Handy/unavailable
   voice, clipboard, window focus, Retina coordinates, application lifecycle,
   STOP, and cleanup on actual hardware; record environment and outcomes.
4. **Mixed-DPI multi-monitor validation** — define coordinate spaces and test
   heterogeneous display scale factors on both operating systems.
5. **Clipboard integration reliability** — distinguish unavailable/locked host
   clipboards from product regressions without weakening verification.
6. **Live provider compatibility matrix** — validate opted-in Ollama, LM
   Studio, OpenAI, Claude, Gemini, and custom endpoints without adding secrets
   or live-account requirements to default CI.

## Near-term improvements

- [ ] retry an alternative ranked candidate after a verified named destination
  fails;
- [ ] scan below the initial viewport safely before declaring no named target;
- [ ] add deterministic multi-tab selection and state coordination;
- [ ] expand known-app discovery without introducing arbitrary shell execution;
- [ ] add a small local status surface for listening/executing/agent/cancelled;
- [ ] improve completed-agent result delivery beyond log/state inspection;
- [ ] add hermetic dependency resolution and `pip check` to an explicit CI
  policy once the conflict is resolved.
- [ ] integrate OS credential vaults while retaining environment-variable
  support for headless/CI operation;
- [ ] add a graphical provider/model settings surface over the validated CLI;

## Exploratory, not committed

- [ ] direct in-process local Whisper/VAD provider;
- [ ] local vision grounding for non-DOM desktop controls;
- [ ] optional local text-to-speech feedback;
- [ ] offline documentation indexing.

## Explicit non-goals

- mandatory cloud models, telemetry, analytics, or user tracking;
- arbitrary LLM-generated shell commands;
- weakening STOP, focus, process, click, clipboard, or destination checks for
  convenience;
- replacing the deterministic parser with an LLM-first architecture;
- claiming Linux support from the current fallback code;
- treating mocked or hosted-runner tests as physical-hardware certification.
