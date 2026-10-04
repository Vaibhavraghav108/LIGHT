# AGENTS.md — LIGHT Engineering Contract

This is the binding contributor and AI-agent contract for LIGHT. Read it before
changing the repository. Code and tests are the behavioral authority; the
documentation map is [docs/README.md](docs/README.md).

## Product and architecture contract

LIGHT is a local-first, low-latency desktop and browser automation assistant
for Windows and macOS. Preserve this pipeline:

```text
VoiceInputProvider -> LIGHT-VoiceListener -> CommandQueue -> Laya/brain
                   -> Executor -> desktop / Playwright / Browser Use
                   -> verification -> LightState
```

The responsibilities are deliberately separate:

- deterministic parsing handles common commands without an LLM;
- Laya is the guarded final intent-classification fallback;
- a selected `AIProvider` plans complex structured commands; local
  Ollama/Qwen3 remains the default;
- Playwright owns deterministic browser actions;
- Browser Use handles open-ended autonomous web goals in an isolated session;
- `PlatformController` contains operating-system primitives;
- `VoiceInputProvider` contains provider-specific transcription ingestion.

## Non-negotiable invariants

1. Preserve existing behavior and prefer the smallest safe change.
2. Do not rewrite working subsystems for style.
3. Keep deterministic commands deterministic and free of network/LLM calls.
4. Keep `_listener_worker` separate from command execution.
5. STOP/CANCEL must set cancellation directly at ingestion and retain priority.
   The measured sub-5ms contract begins at `ingest_text()`, not at speech.
6. Long-running code must observe cancellation. Do not claim every third-party
   call is instantly cancellable.
7. Keep `AGENT_TASK` on the managed `LIGHT-AgentWorker`; it must not block the
   normal consumer loop.
8. Keep Browser Use and Playwright sessions isolated. Preserve truthful
   `BrowserOwnership` until the agent worker actually exits.
9. Never equate dispatch with success. Preserve focus, click, clipboard, and
   destination verification.
10. Named browser targets must be ranked and may not silently fall back to the
    first result.
11. LLM output is untrusted. Validate actions, applications, URLs, targets, and
    STOP intent before execution. Never add an arbitrary shell action.
12. Normal application close may affect only LIGHT-tracked processes. A broad
    force close requires explicit API opt-in and must never be normal routing.
13. Desktop OS operations belong behind `PlatformController`.
14. Voice-provider behavior belongs behind `VoiceInputProvider`.
    AI transport/model behavior belongs behind `AIProvider`; provider selection
    must never bypass action validation or introduce silent model fallback.
15. Keep local-first defaults: no mandatory cloud API, telemetry, analytics, or
    tracking. Web automation still communicates with sites the user requests.
16. Do not delete, skip, weaken, or rewrite tests merely to make CI green.
17. Add deterministic regression coverage for each bug fix.
18. Preserve the Windows/macOS CI matrix and platform markers.
19. Never commit `.env`, secrets, runtime logs, browser profiles, caches, or
    machine-specific paths.
20. Never force-push, amend published history, or destructively reset user work.
21. Report exactly what was run. Separate mocked tests, local-browser tests,
    CI results, opt-in host smoke tests, and physical-device validation.

## Before editing

1. Run `git status --short --branch`, identify HEAD/origin, and stop if the
   worktree contains changes you do not own.
2. Read this contract and the relevant canonical documents:
   [ARCHITECTURE](docs/ARCHITECTURE.md), [SAFETY](docs/SAFETY.md),
   [DECISIONS](docs/DECISIONS.md), [TESTING](docs/TESTING.md), and
   [TROUBLESHOOTING](docs/TROUBLESHOOTING.md).
3. Inspect relevant source, tests, history, and configuration. Unusual code may
   encode a prior race, safety constraint, platform behavior, or CI fix.
4. Establish the relevant test baseline before modification.
5. Create a focused branch; do not work directly on `main`.
6. Plan the smallest behavior-preserving change and its regression test.

## Verification after editing

Run targeted tests first, then the complete checks appropriate to the change:

```powershell
.\lightenv\Scripts\python.exe -m unittest discover -s tests -v
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py providers voice brain computer browser core utils tests
git diff --check
git status --short --branch
```

Changes to `core/loop.py`, `core/queue_manager.py`, `core/executor.py`, or
`browser/browser.py` require synchronous and asynchronous path coverage plus
cancellation/shutdown tests. OS changes require both platform unit coverage and
the existing CI matrix. Real microphone, GUI, clipboard, and permissions checks
remain opt-in host smoke tests.

Update documentation by ownership: behavior in `FEATURES`, architecture in
`ARCHITECTURE`/`DECISIONS`, safety boundaries in `SAFETY`, test evidence in
`TESTING`, fixed defects in `TROUBLESHOOTING`, release history in `CHANGELOG`,
and future work in `ROADMAP`.

## Current `v0.5.0` caveats

- macOS has unit and CI coverage, but physical Mac hardware/permission/voice
  validation is not recorded.
- Some Playwright calls and third-party Browser Use internals cannot guarantee
  immediate cancellation; joins are bounded and a dependency may outlive them.
- Mixed-DPI multi-monitor coordinates are not physically validated.
- The optional agent install currently has a `click` metadata conflict between
  `browser-use==0.13.10` and the installed Laya dependency chain.

See [docs/TESTING.md](docs/TESTING.md) for the dated release baseline and
[docs/SAFETY.md](docs/SAFETY.md) for precise guarantee boundaries.
