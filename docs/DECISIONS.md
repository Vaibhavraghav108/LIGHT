# LIGHT — Architecture Decision Records (ADRs)

> **Context**: This document captures the rationale, trade-offs, and consequences of critical technical and architectural decisions in the **LIGHT** repository.

---

# ADR-001 — Deterministic-First Hybrid Brain Architecture

## Status
Accepted

## Decision
Route high-frequency, structured voice commands through deterministic regex and grammatical parsers (`brain/decision.py`) as the primary execution path, reserving the local Large Language Model (Qwen3 1.7B) exclusively for complex, multi-clause natural language search and browsing tasks.

## Reason
1. **Latency**: Deterministic parsing completes in **<1ms**, compared to 300ms–2000ms for local LLM token generation. For common navigation (`"open youtube"`, `"scroll down"`, `"press enter"`), sub-millisecond execution is essential for an ambient voice experience.
2. **Reliability & Determinism**: Deterministic parsing eliminates hallucinations, token drift, and non-deterministic formatting anomalies.
3. **Resource Efficiency**: Avoids continuous CPU/GPU load from running an LLM on every spoken utterance.

## Consequences
- **Positive**: Near-instantaneous response times for 90%+ of common voice commands; 100% predictable action outputs.
- **Negative**: Grammars and regex patterns must be maintained for new deterministic command forms.

## Related Components
- [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py), [`brain/laya.py`](file:///c:/Projects/LIGHT/brain/laya.py), [`brain/llm.py`](file:///c:/Projects/LIGHT/brain/llm.py)

---

# ADR-002 — Local Qwen3 1.7B via Ollama for Complex Planning

## Status
Accepted

## Decision
Standardize the natural language planning model on local **Qwen3 1.7B** served via Ollama (`http://127.0.0.1:11434`), explicitly avoiding remote cloud LLMs (OpenAI, Anthropic) for core planning.

## Reason
1. **Privacy**: User voice commands and personal browsing goals are processed entirely on the user's workstation.
2. **Offline Resilience**: The system remains functional without an internet connection or active subscription API keys.
3. **Hardware Fit**: Qwen3 1.7B delivers high instruction-following fidelity for JSON action generation while fitting comfortably within low VRAM or standard CPU limits.

## Consequences
- **Positive**: No API costs, no rate limits, zero data exfiltration.
- **Negative**: Small models can produce thinking tokens (`<think>`, `/no_think`) or syntax quirks that require post-generation normalization (`normalize_command_plan`).

## Related Components
- [`brain/llm.py`](file:///c:/Projects/LIGHT/brain/llm.py), [`config.py`](file:///c:/Projects/LIGHT/config.py)

---

# ADR-003 — Decoupled Producer-Consumer Command Queue

## Status
Accepted

## Decision
Decouple speech-to-text audio ingestion from action execution using a thread-safe, prioritized producer-consumer queue (`core/queue_manager.py`).

## Reason
1. **Audio Latency & Dropped Speech**: When action execution was synchronous with the voice listener, slow browser navigations or multi-second page loads blocked the listener thread, causing speech lag or dropped utterances.
2. **Preemption**: A queue enables immediate out-of-band preemption for emergency `"Stop"` commands without waiting for prior commands to finish executing.

## Consequences
- **Positive**: Voice listener never drops transcriptions; emergency stop commands are detected in <5ms; dependent commands can be pruned on failure.
- **Negative**: Requires thread-safe state synchronization and intermediate planning state clones (`LightState.clone_for_planning()`).

## Related Components
- [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py), [`core/queue_manager.py`](file:///c:/Projects/LIGHT/core/queue_manager.py), [`core/state.py`](file:///c:/Projects/LIGHT/core/state.py)

---

# ADR-004 — Dual-Engine Browser Automation (Playwright Primary, Browser Use Subordinate)

## Status
Accepted

## Decision
Retain Playwright Chromium as LIGHT's primary deterministic browser automation engine, while integrating Browser Use as an isolated, subordinate agent invoked exclusively for open-ended exploratory research goals (`AGENT_TASK`).

## Reason
1. **Playwright Strengths**: Playwright is fast, lightweight, and deterministic for direct DOM actions (`click_element`, `search`, `scroll`, `copy_text_range`).
2. **Browser Use Strengths**: Browser Use excels at autonomous multi-step discovery and summarization across unknown DOMs.
3. **Separation of Concerns**: Replacing Playwright with Browser Use for everyday browsing would introduce unacceptable latency and unreliability for common commands.

## Consequences
- **Positive**: Best of both worlds: instant deterministic control for known tasks; autonomous capabilities for research.
- **Negative**: Requires careful session isolation to prevent the two browser controllers from colliding.

## Related Components
- [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py), [`browser/agent.py`](file:///c:/Projects/LIGHT/browser/agent.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py)

---

# ADR-005 — Strict Three-State Browser Ownership Model

## Status
Accepted

## Decision
Enforce a formal ownership lifecycle (`BrowserOwnership.NONE`, `LIGHT`, `AGENT`) tracked in `LightState` and managed by `Executor`.

## Reason
1. **Session Corruption**: If Playwright attempts to navigate or click elements while Browser Use is actively controlling a page, both controllers will crash or trigger race conditions.
2. **Concurrency Clarity**: Normal desktop commands (`OPEN_APP`, `HOTKEY`, `TYPE`, `MEDIA_*`) can proceed safely while `AGENT` ownership is active, but deterministic browser commands must be blocked or wait.

## Consequences
- **Positive**: Eliminates dual-controller race conditions; ensures clean handover and return of browser sessions; allows desktop multitasking while research agents run.
- **Negative**: Subsystems must check and update ownership flags during state transitions.

## Related Components
- [`core/state.py`](file:///c:/Projects/LIGHT/core/state.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py)

---

# ADR-006 — Highest-Priority Emergency STOP Preemption (<5ms)

## Status
Accepted

## Decision
Assign highest priority to emergency cancellation phrases (`"Stop"`, `"Cancel"`, `"Quit"`, `"Exit"`), bypassing normal queue scheduling and immediately setting a global `cancel_event`.

## Reason
1. **User Safety**: In a physical automation system controlling mouse and keyboard, the user must always have instantaneous veto power.
2. **Interruptibility**: Long-running actions (e.g. `WAIT 10`, autonomous agent exploration) must abort immediately upon voice command.

## Consequences
- **Positive**: Hard preemption latency under 5ms; stops runaway agent loops or incorrect automated actions instantly.
- **Negative**: All blocking or long-running operations must monitor and accept `cancel_event`.

## Related Components
- [`core/queue_manager.py`](file:///c:/Projects/LIGHT/core/queue_manager.py), [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py)

---

# ADR-007 — Multi-Feature Search Candidate Ranking Over Blind Result Selection

## Status
Accepted

## Decision
Replace blind "click result #1" fallbacks with a multi-feature candidate scoring algorithm that evaluates visible links in the viewport based on search context, domain match, repository slug patterns, and semantic authority.

## Reason
1. **Wrong Result Failures**: Blindly clicking result #1 for a query like `"LangGraph"` often landed on irrelevant results (e.g. high school math graph paper).
2. **Confidence Threshold**: Named target requests (`"official repository"`, `"official docs"`) must require a minimum confidence score (score $\ge 20$) and fail safely if no matching link is visible.

## Consequences
- **Positive**: Consistently selects official repositories and primary project documentation over ads and unrelated matches.
- **Negative**: Requires maintaining and tuning candidate ranking heuristics.

## Related Components
- [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py)

---

# ADR-008 — Semantic Post-Click Destination Verification

## Status
Accepted

## Decision
Require explicit post-click destination verification (`verify_destination`) after clicking named search targets, validating landing page URL, domain, title, and body content against target query semantics.

## Reason
1. **Physical Click $\neq$ Task Success**: A physical mouse click on an element can trigger navigation to an error page, an ad, or an unintended repository.
2. **Truthful Status Reporting**: The system must fail loudly and raise `RuntimeError` on mismatch, rather than reporting `[EXECUTOR] OK` when on the wrong page.

## Consequences
- **Positive**: Eliminates false positive execution reports; enables automated retry on alternative candidate links.
- **Negative**: Adds a brief post-click inspection window (~50–200ms) after page navigation commits.

## Related Components
- [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py)

---

# ADR-009 — Foreground and Focus-Aware Desktop Typing

## Status
Accepted

## Decision
Enforce active foreground window and process verification (`computer/screen.py`) before dispatching OS keystrokes for `TYPE` commands.

## Reason
1. **Accidental Keystrokes**: If a target application loses focus or is minimized, blind keystrokes can inadvertently type into terminal sessions, IDEs, or background chat windows.
2. **Integrity**: Verifies that the window receiving input matches the intended application or is an active foreground target.

## Consequences
- **Positive**: Prevents corrupted input and catastrophic typing errors in background programs.
- **Negative**: Requires Windows Win32 API calls (`GetForegroundWindow`, `GetWindowTextW`) before keystroke generation.

## Related Components
- [`computer/screen.py`](file:///c:/Projects/LIGHT/computer/screen.py), [`computer/keyboard.py`](file:///c:/Projects/LIGHT/computer/keyboard.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py)

---

# ADR-010 — Managed Background Worker for Autonomous Agent Tasks (`LIGHT-AgentWorker`)

## Status
Accepted

## Decision
Execute long-running Browser Use autonomous agent tasks (`Action.AGENT_TASK`) in a dedicated managed background daemon thread (`LIGHT-AgentWorker`) managed by `core/executor.py`, returning immediately to the `LightLoop` consumer loop. Enforce single-active-worker semantics by rejecting duplicate concurrent agent requests (`ActionExecutionResult.REJECTED`).

## Reason
1. **Consumer Thread Blocking**: Previously, `Executor.execute()` synchronously invoked `self.browser_agent.run_task(...)`. For open-ended web research tasks taking 2–7 minutes, this blocked the single consumer thread of `LightLoop`, preventing any normal commands (`"Open YouTube"`, `"Open Google"`, `"Close Notepad"`) from executing until the research task completed.
2. **Preserving Ambient Low Latency**: LIGHT's core value proposition is instantaneous, hands-free computer control. Background research must not degrade desktop responsiveness.
3. **Session Safety & Duplicate Prevention**: Running multiple concurrent Browser Use sessions would cause resource contention, CPU exhaustion, and WebDriver conflicts. Single-active-worker rejection ensures system stability while maintaining responsiveness.

## Consequences
- **Positive**: Normal desktop and browser commands execute immediately without queuing delays (`queue_wait` <1ms); the user can multitask during long research tasks; emergency STOP and loop teardown safely join the worker thread within bounded timeouts (<300ms on STOP, 500ms on shutdown).
- **Negative**: Requires thread-safe lifecycle tracking (`_agent_lock`, `_agent_thread`, `state._lock`) and bounded thread join management in `Executor` and `LightLoop`.

## Related Components
- [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py), [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py), [`browser/agent.py`](file:///c:/Projects/LIGHT/browser/agent.py), [`core/state.py`](file:///c:/Projects/LIGHT/core/state.py)

---

# ADR-011 — Cross-Platform Operating System Abstraction (`PlatformController`)

## Status
Accepted

## Decision
Introduce an abstract `PlatformController` interface (`computer/platform_base.py`) and factory (`computer/platform_factory.py`) with OS-specific implementations (`WindowsPlatformController`, `MacOSPlatformController`). High-level desktop controllers (`AppController`, `ScreenController`, `KeyboardController`, `MouseController`) and entry points (`main.py`) delegate OS-specific operations (app launching, process scanning/killing, window management, hotkey modifier mapping, screen scaling) to the active platform controller.

## Reason
1. **Multi-Platform Support**: LIGHT must support macOS alongside Windows without duplicating high-level logic or branching on `sys.platform` throughout the codebase.
2. **Preserving Existing Windows Contract**: Win32 APIs, DPI awareness, and PowerShell CIM process management remain 100% intact for Windows without regression.
3. **Clean Encapsulation**: OS primitives (such as macOS `osascript` AppleScript execution and `open -a`, versus Windows Win32 `ctypes` and `taskkill`) are isolated within platform classes.

## Consequences
- **Positive**: Enables full desktop automation on macOS; standardizes window management and modifier mappings; maintains 100% backward compatibility for all existing Windows unit and smoke tests.
- **Negative**: Adds a layer of indirection for OS calls.

## Related Components
- [`computer/platform_base.py`](file:///c:/Projects/LIGHT/computer/platform_base.py), [`computer/platform_windows.py`](file:///c:/Projects/LIGHT/computer/platform_windows.py), [`computer/platform_macos.py`](file:///c:/Projects/LIGHT/computer/platform_macos.py), [`computer/platform_factory.py`](file:///c:/Projects/LIGHT/computer/platform_factory.py), [`computer/apps.py`](file:///c:/Projects/LIGHT/computer/apps.py), [`computer/screen.py`](file:///c:/Projects/LIGHT/computer/screen.py), [`computer/keyboard.py`](file:///c:/Projects/LIGHT/computer/keyboard.py), [`computer/mouse.py`](file:///c:/Projects/LIGHT/computer/mouse.py), [`main.py`](file:///c:/Projects/LIGHT/main.py)

---

# ADR-012 — Extensible Speech Ingestion (`VoiceInputProvider`)

## Status
Accepted

## Decision
Abstract speech ingestion behind the `VoiceInputProvider` interface (`voice/base.py`). Wrap Handy SQLite ingestion into `HandyVoiceProvider` (with `Handy` as a backward-compatible subclass). Provide `UnavailableVoiceProvider` and a dynamic factory (`voice/factory.py`) that checks for database availability and gracefully operates without crashing when no provider is active.

## Reason
1. **Decoupling from External Third-Party Utilities**: LIGHT core should consume transcription events without being hardcoded to the external Handy desktop application.
2. **macOS Compatibility & Graceful Degradation**: Handy availability on macOS is unverified / third-party dependent. When missing on macOS (or unconfigured hosts), LIGHT must report an informative diagnostic status and keep voice listening idle instead of raising `FileNotFoundError` or crashing.
3. **Future Extensibility**: Prepares the architecture for pluggable direct microphone input (e.g. local in-process Whisper) in future milestones.

## Consequences
- **Positive**: Zero crashes on hosts lacking Handy; enables test mocks without temporary SQLite tables; backward-compatible with all existing tests.
- **Negative**: When no provider is installed, voice commands cannot be ingested until a provider is configured.

## Related Components
- [`voice/base.py`](file:///c:/Projects/LIGHT/voice/base.py), [`voice/handy_provider.py`](file:///c:/Projects/LIGHT/voice/handy_provider.py), [`voice/unavailable_provider.py`](file:///c:/Projects/LIGHT/voice/unavailable_provider.py), [`voice/factory.py`](file:///c:/Projects/LIGHT/voice/factory.py), [`voice/handy.py`](file:///c:/Projects/LIGHT/voice/handy.py), [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py)
