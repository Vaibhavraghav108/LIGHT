# LIGHT — Changelog & Milestone History

> **Traceability**: All milestones recorded below correspond to verified Git commit history and changes in the LIGHT repository.

---

## [Unreleased working branch] — Phase 0/1 planning safety foundation

Implemented on `codex/planning-safety-foundation` from merged main `777c7d9`;
not yet committed/merged or validated by hosted CI.

### Added
- One bounded `LIGHT-PlanningWorker` with FIFO reservations, task identity,
  cancellation generations, and stale-result rejection before dispatch.
- Bounded in-memory transcript-free task/status and inference/startup timing
  evidence. Missing publication/visible-effect measurements remain unavailable.
- 33 event-controlled regressions; 20 repeated runs passed 660 executions with
  no surviving LIGHT workers. Current Windows suite:
  **225 discovered, 217 passed, 8 opt-in host smoke skips,
  0 failures/errors**. Compileall and diff checks pass.

### Fixed
- Semantic inference no longer blocks transcript ingestion of a later STOP.
- Failed dependency isolation now uses task IDs for loop-created plans rather
  than repeated utterance text. Async dequeue cancellation preserves accounting.
- Agent dispatch is not completion; timed-out joins preserve running ownership
  until cleanup exits. Browser Use constructor failures close created browsers.
- Executor cleanup failures/incomplete joins are surfaced in loop shutdown
  status instead of being reported as successful cleanup.
- Cancellation suppresses subsequent browser verification recovery.

### Boundaries
- Deterministic parsing, selected providers/models, executor action vocabulary,
  isolated AgentWorker, Handy, and platform abstraction remain intact.
- Cold local-model inference exceeded the existing 8s timeout; three subsequent
  resident-model requests produced valid plans in 4.94–5.40s. No model/timeout or
  fallback policy was changed. Third-party cancellation and physical host checks
  remain limitations; the existing dependency metadata conflict is unchanged.
- No Phase 2 capability catalog, typed conversational memory, vision, raw-audio
  STT, Excel, GUI, new dependency/provider, or CI redesign is included.

## [Unreleased] — Provider and model architecture

### Added
- Typed, independent STT and AI provider/model configuration with an ignored,
  atomically written `.light/providers.json` user file.
- AI adapters for local Ollama, local LM Studio, OpenAI, Claude, Gemini, and
  custom OpenAI-compatible endpoints, including model discovery and sanitized
  status validation.
- `python -m providers` commands to show, validate, discover, and independently
  activate STT/AI selections without editing source.
- A documented custom transcript-feed `VoiceInputProvider` while preserving
  Handy as the default local runtime.
- Provider architecture, configuration, credential, redaction, no-fallback,
  planner, and Browser Use regression tests (36 provider regression tests plus
  one inaccessible-Handy-path regression). That milestone's full-suite baseline was
  192 discovered, 184 passing, 8 opt-in host smoke tests skipped, 0 failures,
  and 0 errors.

### Changed
- `QwenPlanner` remains backward-compatible but delegates every production
  inference, including Ollama, to the selected `AIProvider` and applies the
  same action validation to every model. Its prompt-only injected transport is
  retained solely for isolated legacy tests.
- Browser Use now uses the selected AI provider/model rather than hardcoding
  `ChatOllama`; local Ollama/Qwen3 remains the default.
- Startup reports active STT and AI provider/runtime/model without printing
  credential values.
- Provider-specific defaults no longer leak Ollama runtime/model/endpoint
  values into explicit cloud or custom selections. Empty model inventories,
  absent configured models, and missing explicitly named credentials now fail
  activation validation.

### Safety and limits
- Cloud AI is opt-in and never a fallback. Credential values are resolved from
  environment variables and provider/SDK errors are redacted.
- Direct microphone capture, VAD, and Whisper remain unimplemented because the
  current voice contract begins at completed transcript events.

### Documentation consolidation

### Documentation
- Added `docs/README.md` as the documentation inventory, evidence glossary, and
  source-of-truth map.
- Reconciled the root README, engineering contract, product specification,
  architecture, feature status, safety boundaries, testing guide, roadmap,
  decisions, and troubleshooting catalog against tag `v0.5.0`.
- Distinguished source implementation, mocked tests, real local-browser tests,
  hosted CI, opt-in host smoke tests, and physical-device validation.
- Corrected release state, stale test identifiers, STOP measurement wording,
  worker-join guarantees, platform support claims, and repository-relative
  links without changing runtime code, tests, dependencies, or CI.

---

## [v0.5.0] — 2026-10-04

*Tag: `v0.5.0` at merge commit `8524bde`; PR #5 merged
`refactor/light-engineering-hardening` into `main`.*

### Added
- **Release-level safety evidence** for ownership, cancellation isolation,
  destination verification, clipboard verification, scoped process shutdown,
  and local Browser Use defaults.
- **Windows/macOS CI matrix** at the final tag: 155 discovered tests, 147
  passing and 8 opt-in host smoke tests skipped in each job.

### Fixed
- **Compound-plan queue isolation**: Failed `OPEN_URL`/`SEARCH` prerequisites now cancel only dependent commands from the same utterance, never a matching action queued by another utterance.
- **Atomic background-agent admission**: Duplicate detection, `agent_running` publication, worker publication, and thread start now occur in one `_agent_lock` critical section.
- **Truthful ownership and STOP state**: Deterministic browser commands no longer overwrite `BrowserOwnership.AGENT` while the isolated agent is active; STOP now clears stale URL, title, site, browser, and browser-app state.
- **Named-click verification**: Semantic destination checks now reject an inactive browser and an unchanged pre-click URL. Their navigation wait accepts the queue cancellation event so STOP can interrupt it.
- **Verified clipboard writes**: Browser copy actions raise when clipboard read-back fails instead of logging a false success.
- **Cross-platform clipboard shortcuts**: Desktop copy/paste now flow through `KeyboardController`, preserving macOS `ctrl` to `command` mapping.
- **Scoped desktop app shutdown**: Normal Notepad/TextEdit and Calculator shutdown no longer falls through to image-wide `taskkill`/`pkill`. Only LIGHT-tracked launches are closed unless a caller explicitly opts into `force=True`.
- **Local Browser Use defaults**: Browser Use configuration is workspace-local by default; anonymized telemetry and cloud sync are disabled before its lazy import.

### Tests
- Added 10 regression tests for queue-plan isolation, atomic agent admission, ownership preservation, STOP cleanup, cancellable/stale destination verification, clipboard verification/routing, scoped app termination, and Browser Use privacy defaults.
- Extended push CI branch coverage to `refactor/*` so hardening branches receive the existing Windows/macOS matrix without weakening either job.
- Current automated discovery baseline: **155 tests: 147 passed, 8 opt-in host smoke tests skipped, 0 failures, 0 errors** on Windows.

## [Pre-release macOS support lineage / PR #4] — 2026-10-04
*Historical branch: `feature/macos-platform-support`; merged into `main` by PR #4
before `v0.5.0`.*

### Added
- **Operating System Abstraction Layer (`PlatformController`)**: Created [`computer/platform_base.py`](../computer/platform_base.py) and [`computer/platform_factory.py`](../computer/platform_factory.py) encapsulating OS-specific primitives behind an abstract base class.
- **Windows Platform Controller (`WindowsPlatformController`)**: Implemented [`computer/platform_windows.py`](../computer/platform_windows.py) preserving Win32 APIs, ctypes High-DPI awareness, and PowerShell CIM process management.
- **macOS Platform Controller (`MacOSPlatformController`)**: Implemented [`computer/platform_macos.py`](../computer/platform_macos.py) supporting application launching via `open -a`, AppleScript window management via `osascript`, POSIX process scanning and termination (`ps`/`kill`), modifier mapping (`ctrl` $\to$ `cmd`), and Retina display scaling.
- **Speech Ingestion Abstraction (`VoiceInputProvider`)**: Created [`voice/base.py`](../voice/base.py), [`voice/handy_provider.py`](../voice/handy_provider.py), [`voice/unavailable_provider.py`](../voice/unavailable_provider.py), and [`voice/factory.py`](../voice/factory.py) to decouple the core loop from Handy SQLite file assumptions.
- **Graceful Voice Provider Fallback**: On hosts where Handy is not installed (such as unconfigured macOS hosts), LIGHT operates with an informative status without crashing.
- **Cross-Platform Path Configuration**: Updated [`config.py`](../config.py) to discover browser candidates (`/Applications/...` vs `%PROGRAMFILES%`) and Handy databases dynamically through the platform controller.
- **CI Matrix**: Updated [`.github/workflows/tests.yml`](../.github/workflows/tests.yml) to matrix test against `windows-latest` and `macos-latest`.

### Tests
- Added [`tests/test_platform_macos.py`](../tests/test_platform_macos.py) (9 unit tests with mocked macOS system calls).
- Added [`tests/test_voice_provider.py`](../tests/test_voice_provider.py) (5 unit tests covering provider behaviors and backward compatibility).
- Added [`tests/test_macos_smoke.py`](../tests/test_macos_smoke.py) (4 opt-in host smoke tests).
- Total automated discovery test suite expanded to **145 tests: 137 passed, 8 skipped, 0 failures, 0 errors**.

### Fixed
- **macOS CI Dependencies & Platform-Aware Assertions**: Added `pyobjc-core`, `pyobjc-framework-Quartz`, and `pyobjc-framework-Cocoa` with `sys_platform == 'darwin'` markers in `requirements.txt` for PyAutoGUI automation on macOS runners. Made unit test assertions in `tests/test_computer.py`, `tests/test_new_features.py`, `tests/test_voice.py`, and `tests/test_voice_provider.py` platform-aware across Windows and macOS. Added `fail-fast: false` to the CI matrix.
- **Latency Optimization for WAIT & AGENT_TASK**: Updated `Action.WAIT` and `Action.AGENT_TASK` in `core/executor.py` to return directly after recording the command, eliminating redundant post-action observation sync and AppleScript subprocess overhead during STOP preemption and background agent task dispatch.
- **Browser Type Guard & CI Runner Stability**: Registered native DOM `input` event listener in `BrowserController.type_in_browser()` to synchronously enforce typing guards, and stabilized consumer queue timing assertions across virtualized CI runners. Both matrix jobs passed at that commit.

---

## [Commit d9ad00c / PR #2] — 2026-10-04
*Commit: `d9ad00c` (Merged via PR #2 `12e5fbc`) — "fix: run agent tasks in background"*

### Added
- **Managed Background Agent Worker (`LIGHT-AgentWorker`)**: Offloaded `Action.AGENT_TASK` execution in [`core/executor.py`](../core/executor.py) to a dedicated managed daemon thread, returning `OK` immediately to the consumer loop instead of blocking the main thread for minutes.
- **Continuous Command Concurrency**: Allowed normal high-frequency commands (`"Open YouTube"`, `"Open Google"`, `"Close Notepad"`) to execute immediately without queuing delays (`queue_wait` reduced from ~260s to <1ms) while an autonomous agent runs in the background.
- **Duplicate Task Protection**: Rejects secondary `AGENT_TASK` invocations by returning `"REJECTED"` when an agent worker is already active.
- **Bounded Worker Preemption & Shutdown**: Implemented `join_agent()` and `close()` in `Executor` with bounded join attempts so STOP and loop shutdown do not wait indefinitely. Third-party code can outlive the bound if it ignores cancellation.
- **Graceful Loop Teardown**: Updated `core/loop.py` to close and join background executor workers in its `finally` block and `close()` handler.

### Tests
- Added 8 comprehensive regression tests (Tests A–H, tests 45–52) in [`tests/test_new_features.py`](../tests/test_new_features.py), bringing the test suite to **127 tests (123 passed, 4 skipped)**.

---

## [Commit 1c8ad89 / PR #1] — 2026-10-04
*Commit: `1c8ad89` (Merged via PR #1 `20a1187`) — "Add engineering memory suite, AI agent contract, safety invariants, and Windows CI"*

### Added
- Standardized engineering memory suite under [`docs/`](../docs/) including `PRODUCT_SPEC.md`, `ARCHITECTURE.md`, `FEATURES.md`, `CHANGELOG.md`, `DECISIONS.md`, `ROADMAP.md`, `TESTING.md`, `SAFETY.md`, and `TROUBLESHOOTING.md`.
- AI Agent Contract [`AGENTS.md`](../AGENTS.md) in repository root detailing operational invariants, modification workflows, and prohibited behaviors.
- Windows GitHub Actions continuous integration workflow [`.github/workflows/tests.yml`](../.github/workflows/tests.yml) executing the full discovery test suite.
- Tracked logs directory via [`logs/.gitkeep`](../logs/.gitkeep) with `.gitignore` exclusion rules for runtime logs.

### Reliability
- Updated `.gitignore` to prevent runtime log files and temporary artifacts from polluting the Git repository.

---

## [Commit f03e9cd] — 2026-10-04
*Commit: `f03e9cd` — "Add desktop window/media controls, Browser Use Ollama agent, browser ownership model, candidate ranking, and workflow reliability"*

### Added
- **Browser Ownership Model**: Introduced `BrowserOwnership` enum (`NONE`, `LIGHT`, `AGENT`) in [`core/state.py`](../core/state.py) and enforced clean ownership handoffs between Playwright and Browser Use in [`core/executor.py`](../core/executor.py).
- **Target Candidate Ranking**: Implemented multi-feature candidate scoring in [`browser/browser.py`](../browser/browser.py) prioritizing domain match (+120), exact repository slugs (+80), and official keywords (+50) over irrelevant search results.
- **Semantic Destination Verification**: Added `verify_destination()` in [`browser/browser.py`](../browser/browser.py) to validate landing page URL, domain, title, and text content against target queries before reporting success.
- **Desktop Window & Media Controls**: Added window management (`MINIMIZE_WINDOW`, `MAXIMIZE_WINDOW`, `RESTORE_WINDOW`, `SWITCH_WINDOW`) in [`computer/screen.py`](../computer/screen.py) and media actions (`MEDIA_PLAY_PAUSE`, `MEDIA_MUTE`, `VOLUME_UP`, `VOLUME_DOWN`, `MEDIA_FORWARD`, `MEDIA_BACKWARD`).
- **Foreground Window Observation**: Added `get_foreground_window_info()` and `verify_foreground_app()` in [`computer/screen.py`](../computer/screen.py) to ensure typing only occurs in verified foreground processes.
- **Browser Use Ollama Agent**: Implemented [`browser/agent.py`](../browser/agent.py) supporting autonomous multi-step goals via local Ollama (`qwen3:1.7b`) with native event loop async execution (`execute_task`) and immediate `STOP` preemption.
- **GitHub Search Automation**: Added GitHub repository search integration (`search_github`) and selector support for GitHub search result lists.

### Changed
- Refactored `CLICK_RESULT` to require semantic verification on named targets, failing with `RuntimeError` instead of falling back to result #1.
- Updated `core/loop.py` to support asynchronous execution (`execute_next_queued_async`, `process_text_async`) compatible with running event loops without using `nest_asyncio`.

### Fixed
- Fixed `RuntimeError: asyncio.run() cannot be called from a running event loop` when invoking Browser Use from within an active asyncio loop.
- Fixed unwanted Google URL injection in `normalize_command_plan()` during GitHub search flows by adding `github` to canonical active search engines.
- Fixed `CLICK_ELEMENT("First Element")` voice parsing bug by mapping `"click on first element"` to `CLICK_RESULT(1)` in search contexts or `CLICK_ELEMENT("element 1")` on generic pages.
- Fixed typing into background/inactive applications by enforcing foreground verification before keystroke dispatch.

### Tests
- Added 44 integration tests in [`tests/test_new_features.py`](../tests/test_new_features.py), bringing the discovered test suite to **119 tests (115 passed, 4 skipped)**.

---

## [Commit 8868089] — 2026-09-28
*Commit: `8868089` — "Implement LIGHT V2 producer-consumer queue, Qwen3 1.7B planning, browser readiness recovery, and verified physical click pipeline"*

### Added
- **Producer-Consumer Command Queue**: Implemented [`core/queue_manager.py`](../core/queue_manager.py) with prioritized queuing (`CommandPriority.STOP` vs `NORMAL`) and monotonic timestamp tracking.
- **Non-Blocking Background Listener**: Separated voice ingestion onto a dedicated background thread (`_listener_worker` in `core/loop.py`) polling Handy every 150ms.
- **Local Qwen3 1.7B Planner**: Implemented [`brain/llm.py`](../brain/llm.py) with Ollama API integration, plan normalization, and complex multi-clause action planning.
- **Dependent Action Pruning**: Added `cancel_dependent_after_failure()` to cancel downstream queued actions when a prerequisite command fails.
- **Physical Mouse Homing & Verification**: Enhanced `MouseController` with closed-loop cursor verification and DOM hover/click coordination.
- **Browser Readiness Recovery**: Automatic session recovery and re-initialization if a browser context or page closes unexpectedly.

### Changed
- Replaced synchronous `LightLoop` polling with decoupled producer-consumer architecture.
- Added planning-state snapshots (`clone_for_planning()`) in `LightState` to prevent premature state mutations during multi-step command planning.

### Fixed
- Fixed high-latency voice lag caused by blocking executions inside the voice listener loop.
- Fixed `<think>` and `/no_think` formatting tokens leaking into command targets from Qwen small model output.
- Fixed dropped transcriptions during rapid speech by transitioning to monotonic SQLite ID tracking (`get_transcriptions_since`).

### Tests
- Added 31 unit and integration tests in [`tests/test_queue_and_llm.py`](../tests/test_queue_and_llm.py).

---

## [Commit 893b0c0] — 2026-09-28
*Commit: `893b0c0` — "Support direct 'copy text <phrase>' and 'copy <phrase>' commands with punctuation-tolerant page extraction"*

### Added
- Supported direct voice copy commands: `"copy text <phrase>"` and `"copy <phrase>"` in `brain/decision.py`.
- Punctuation-tolerant text matching in `BrowserController.copy_text_range()`.

### Tests
- Added unit tests for direct copy phrases in `tests/test_laya.py`.

---

## [Commit 1ec461d] — 2026-09-28
*Commit: `1ec461d` — "Fix Google reCAPTCHA detection with stealth flags, Chrome binary preference, and CAPTCHA fallback"*

### Added
- Automatic detection of Google `/sorry/` reCAPTCHA challenges in `BrowserController.search()`.
- Intelligent automatic fallback redirecting blocked Google queries to DuckDuckGo so workflows proceed uninterrupted.
- Playwright launch stealth flags (`--disable-blink-features=AutomationControlled`).

### Fixed
- Fixed intermittent automated search stalls caused by Google bot detection triggers.

### Tests
- Added reCAPTCHA fallback unit tests in `tests/test_browser.py`.

---

## [Commit 1d55344] — 2026-09-28
*Commit: `1d55344` — "Use Playwright Chromium/Chrome exclusively for all browser automation and physical mouse homing"*

### Changed
- Standardized all browser automation on Playwright-controlled Chromium/Chrome, deprecating unmanaged external browser processes.
- Unified browser lifecycle management under a single persistent `BrowserController` session.

### Fixed
- Fixed orphaned Popen browser processes and inconsistent viewport coordinate translations.

---

## [Commit 2220be5] — 2026-09-27
*Commit: `2220be5` — "Upgrade and harden LIGHT voice-controlled Windows and browser automation assistant"*

### Added
- Core voice loop with Handy SQLite database reader (`voice/handy.py`).
- Deterministic intent parser (`brain/decision.py`) and Laya fallback classifier (`brain/laya.py`).
- Application management (`computer/apps.py`), keyboard typing (`computer/keyboard.py`), and precision mouse controls (`computer/mouse.py`).
- Playwright Chromium browser controller (`browser/browser.py`) with DOM element location, scrolling, and navigation.
- Comprehensive initial test suite (44 discovered tests across unit, local browser integration, and Windows smoke checks).
