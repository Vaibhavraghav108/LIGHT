# LIGHT — Changelog & Milestone History

> **Traceability**: All milestones recorded below correspond to verified Git commit history and changes in the LIGHT repository.

---

## [Unreleased] — Engineering Memory & CI Foundation
*Current Branch: `feature/project-engineering-system`*

### Added
- Standardized engineering memory suite under [`docs/`](file:///c:/Projects/LIGHT/docs/) including `PRODUCT_SPEC.md`, `ARCHITECTURE.md`, `FEATURES.md`, `CHANGELOG.md`, `DECISIONS.md`, `ROADMAP.md`, `TESTING.md`, `SAFETY.md`, and `TROUBLESHOOTING.md`.
- AI Agent Contract [`AGENTS.md`](file:///c:/Projects/LIGHT/AGENTS.md) in repository root detailing operational invariants, modification workflows, and prohibited behaviors.
- Windows GitHub Actions continuous integration workflow [`.github/workflows/tests.yml`](file:///c:/Projects/LIGHT/.github/workflows/tests.yml) executing the full 119-test discovery suite.
- Tracked logs directory via [`logs/.gitkeep`](file:///c:/Projects/LIGHT/logs/.gitkeep) with `.gitignore` exclusion rules for runtime logs.

### Reliability
- Updated `.gitignore` to prevent runtime log files and temporary artifacts from polluting the Git repository.

---

## [Commit f03e9cd] — 2026-10-04
*Commit: `f03e9cd` — "Add desktop window/media controls, Browser Use Ollama agent, browser ownership model, candidate ranking, and workflow reliability"*

### Added
- **Browser Ownership Model**: Introduced `BrowserOwnership` enum (`NONE`, `LIGHT`, `AGENT`) in [`core/state.py`](file:///c:/Projects/LIGHT/core/state.py) and enforced clean ownership handoffs between Playwright and Browser Use in [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py).
- **Target Candidate Ranking**: Implemented multi-feature candidate scoring in [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) prioritizing domain match (+120), exact repository slugs (+80), and official keywords (+50) over irrelevant search results.
- **Semantic Destination Verification**: Added `verify_destination()` in [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) to validate landing page URL, domain, title, and text content against target queries before reporting success.
- **Desktop Window & Media Controls**: Added window management (`MINIMIZE_WINDOW`, `MAXIMIZE_WINDOW`, `RESTORE_WINDOW`, `SWITCH_WINDOW`) in [`computer/screen.py`](file:///c:/Projects/LIGHT/computer/screen.py) and media actions (`MEDIA_PLAY_PAUSE`, `MEDIA_MUTE`, `VOLUME_UP`, `VOLUME_DOWN`, `MEDIA_FORWARD`, `MEDIA_BACKWARD`).
- **Foreground Window Observation**: Added `get_foreground_window_info()` and `verify_foreground_app()` in [`computer/screen.py`](file:///c:/Projects/LIGHT/computer/screen.py) to ensure typing only occurs in verified foreground processes.
- **Browser Use Ollama Agent**: Implemented [`browser/agent.py`](file:///c:/Projects/LIGHT/browser/agent.py) supporting autonomous multi-step goals via local Ollama (`qwen3:1.7b`) with native event loop async execution (`execute_task`) and immediate `STOP` preemption.
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
- Added 44 integration tests in [`tests/test_new_features.py`](file:///c:/Projects/LIGHT/tests/test_new_features.py), bringing the discovered test suite to **119 tests (115 passed, 4 skipped)**.

---

## [Commit 8868089] — 2026-09-28
*Commit: `8868089` — "Implement LIGHT V2 producer-consumer queue, Qwen3 1.7B planning, browser readiness recovery, and verified physical click pipeline"*

### Added
- **Producer-Consumer Command Queue**: Implemented [`core/queue_manager.py`](file:///c:/Projects/LIGHT/core/queue_manager.py) with prioritized queuing (`CommandPriority.STOP` vs `NORMAL`) and monotonic timestamp tracking.
- **Non-Blocking Background Listener**: Separated voice ingestion onto a dedicated background thread (`_listener_worker` in `core/loop.py`) polling Handy every 150ms.
- **Local Qwen3 1.7B Planner**: Implemented [`brain/llm.py`](file:///c:/Projects/LIGHT/brain/llm.py) with Ollama API integration, plan normalization, and complex multi-clause action planning.
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
- Added 31 unit and integration tests in [`tests/test_queue_and_llm.py`](file:///c:/Projects/LIGHT/tests/test_queue_and_llm.py).

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
