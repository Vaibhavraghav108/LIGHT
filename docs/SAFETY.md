# LIGHT — Safety & Operational Invariants

> **Mandatory Policy**: This document outlines the critical safety invariants, operational constraints, and failure-mode policies enforced across **LIGHT**. No pull request, architectural modification, or AI agent intervention may violate these invariants.

---

## 1. Safety Invariants Matrix

| # | Invariant Rule | Operational Enforcement | Failure Mode if Violated |
| :-: | :--- | :--- | :--- |
| **1** | **STOP/CANCEL Ingestion Preemption (<5ms)** | Once an utterance reaches `ingest_text()`, `is_explicit_stop_or_cancel()` sets the global `cancel_event` and enqueues high-priority `STOP` without waiting for planning. End-to-end voice latency also includes the provider's polling/STT delay. | Runaway automation, delayed aborts, user locked out during bad action. |
| **2** | **No Blind Clicks on Ambiguous Targets** | `locate_element_in_viewport` requires candidate score $\ge 20$. Refuses fallback to result #1 on named targets. | Landing on irrelevant search results, ads, or malicious links. |
| **3** | **Physical Click $\neq$ Task Success** | Dispatched mouse events are treated as unconfirmed until destination commits and is semantically checked. | False reporting of completed tasks when page errors or navigates incorrectly. |
| **4** | **Semantic Destination Verification** | `verify_destination()` inspects landing URL, domain, title, and body tokens against expected query semantics. | Reporting success when stranded on an unrelated domain or error page. |
| **5** | **Strict LLM Output Normalization** | Raw LLM output from Qwen3 1.7B is passed through `normalize_command_plan()`, which validates all action targets against allowlists. | Hallucinated command targets, shell escapes, or arbitrary URL visits. |
| **6** | **Strict Browser Session Isolation** | State tracks `BrowserOwnership` (`NONE`, `LIGHT`, `AGENT`). Browser Use owns an independent session; it never shares LIGHT's primary Playwright context. `AGENT` remains authoritative while its worker is active, even if deterministic commands use the separate LIGHT session. | Dual-driver session collisions, corrupted contexts, crashed browser automation. |
| **7** | **Loud Failures (Zero False Positives)** | When an action or verification fails, it raises an exception and logs `[ERROR]`. Never reports `[EXECUTOR] OK`. | Silent degradation, cascading downstream errors, user deception. |
| **8** | **Pruning Dependent Queued Actions** | `cancel_dependent_after_failure()` automatically cancels downstream dependent actions in a compound batch if a prerequisite fails. | Executing a click or copy after a search failed, corrupting system state. |
| **9** | **Foreground Window Focus Guard** | `computer/screen.py` verifies foreground window before keystrokes are typed via `KeyboardController`. | Keystrokes typed into background terminal, IDE, or personal chat window. |
| **10**| **Test Suite Protection Guarantee** | All 155 discovered tests are permanent product contracts. No test may be deleted, commented out, or bypassed. | Masked regressions, degraded product quality, silent feature loss. |
| **11**| **Non-Blocking Background Listening** | Audio ingestion runs on a dedicated background thread (`_listener_worker`), never blocked by action execution. | Dropped speech, microphone lag, user inability to issue commands. |
| **12**| **Safe Application Process Boundaries** | Normal `AppController.close()` terminates only LIGHT-tracked launches. Image-wide `taskkill /F` or `pkill` requires an explicit `force=True` opt-in and is never used by normal browser close routing. | Accidental closure of personal tabs, documents, or unsaved work. |
| **13**| **Read-Only Database Ingestion** | `HandyVoiceProvider` opens SQLite in read-only URI mode (`file:{path}?mode=ro`) with strict timeouts. | Locking conflicts with external Handy STT process, dropping live audio. |
| **14**| **Background Agent Worker Isolation** | `AGENT_TASK` executes on managed `LIGHT-AgentWorker` thread; duplicates are rejected (`REJECTED`); thread is joined within bounded timeout on STOP or shutdown. | Consumer loop stalled for minutes; duplicate browser sessions and CPU starvation. |
| **15**| **Cross-Platform OS Boundaries** | Platform-specific interactions (AppleScript, Win32, POSIX) are strictly isolated in `PlatformController`. High-level core never invokes OS binaries directly. | Fragile cross-platform regressions, broken builds, security leaks. |
| **16**| **Local Agent Privacy Defaults** | Before Browser Use is imported, LIGHT selects `.light_browseruse/` for its config and defaults anonymized telemetry and cloud sync to disabled. | Local usage metadata or configuration leaking outside LIGHT's intended boundary. |

---

## 2. Emergency Interruption & Preemption Protocol

LIGHT guarantees user sovereignty through an out-of-band preemption architecture:

```text
Spoken: "Stop"
      │
      ▼
Dedicated Voice Listener Thread
      │
      ├────────────────────────────────────────────────────────┐
      ▼ (<1ms after ingestion)                                 ▼ (<2ms after ingestion)
is_explicit_stop_or_cancel() == True              command_queue.cancel_event.set()
      │                                                        │
      ▼                                                        ▼
Enqueue CommandPriority.STOP                      Interrupt Active Workers:
      │                                           ├── Interrupt WAIT loops
      ▼                                           ├── Abort & join LIGHT-AgentWorker
Immediate Consumer Dispatch                       └── Prune pending normal queue
      │
      ▼
Reset BrowserOwnership -> NONE
```

### Preemption Verification Requirements
- Every blocking loop (`time.sleep`, polling loops, browser element waits, agent steps) must periodically inspect `cancel_event.is_set()` or accept `cancel_event` as a parameter.
- The processing time from `ingest_text("Stop")` receiving the transcription to `cancel_event` being set must remain under **5 milliseconds**. With Handy polling at 150ms, end-to-end latency from spoken-word completion can be up to one polling interval plus STT/database publication time; this is a documented measurement boundary, not a claim of sub-5ms audio recognition.

---

## 3. Search Relevance & Verification Policies

### The "Never Blindly Click Result #1" Rule
Historically, when a user asked to `"open official repository"` or `"click official docs"`, legacy systems clicked the first link in the search results container. If the first result was an ad, an unrelated math paper, or a forum discussion, the assistant navigated to the wrong page.

**Enforced Policy**:
1. When target semantics imply a specific entity (e.g. `official`, `repository`, `docs`, `website`), visible anchor elements in the viewport are scored:
   $$\text{Score} = \text{DomainMatch}(+120) + \text{RepoSlugMatch}(+80) + \text{SemanticMatch}(+50) + \text{QueryTokens}(+30) - \text{Penalty}(-100)$$
2. If no candidate achieves $\ge 20$ points, `BrowserController` **must fail with `RuntimeError`**.
3. It is strictly forbidden to fall back to `nth_result(1)` for named search targets.

### Post-Click Destination Verification
Even a high-scoring link may redirect to an authentication barrier, a 404 page, or a deprecation notice.
- After every named result navigation, `verify_destination()` executes:
  - Validates that the URL changed from the pre-click page.
  - Validates that the active URL is not an unexpected third-party domain.
  - Validates that the active page title or header text contains core query tokens.
  - If a mismatch is detected, the executor raises `RuntimeError("Semantic verification failed")`.

---

## 4. Input & Keystroke Safety Guards

### Foreground Process Checking
Before sending synthetic keystrokes via PyAutoGUI:
1. `ScreenController.get_foreground_window_info()` retrieves the active window title and process name across Windows (Win32) and macOS (AppleScript).
2. If the user issued a command targeting a specific application (e.g. `"type in notepad"`), the system confirms that the foreground process matches the expected target.
3. If no target application is specified, the system confirms that a valid, non-system window is active.
4. If the active window is desktop, taskbar, or unverified, typing is aborted with an error log.

---

## 5. Process Lifecycle & System Safety

### Process Kill Scope
- System utilities like `taskkill /F /IM brave.exe` or `taskkill /F /IM chrome.exe` are **strictly forbidden** during normal operation.
- Closing an application via normal `AppController.close()` must only terminate processes explicitly spawned by LIGHT. On macOS, a graceful AppleScript quit is permitted only after LIGHT recorded the corresponding launch because `open -a` returns a short-lived launcher process.
- Image-wide termination is permitted only through an explicit `force=True` API call; ordinary executor routing never opts into it.
- The user's external browser instances, personal tabs, and unsaved documents must never be terminated.

---

## 6. Platform Abstraction & Isolation

### Platform-Isolated Desktop Control
1. Desktop interactions must strictly flow through `PlatformController` (`computer/platform_factory.py`).
2. Win32-specific APIs (`ctypes.windll`, `user32`, `pygetwindow`) and PowerShell commands must remain strictly encapsulated within `WindowsPlatformController`.
3. macOS-specific automation (`osascript`, AppleScript, `open -a`, POSIX signals) must remain strictly encapsulated within `MacOSPlatformController`.
4. Shared core modules (`core/`, `brain/`, `browser/`) must never execute direct platform-specific system calls or hardcode platform binary paths.
5. In environments where speech ingestion is unavailable (e.g. unverified Handy availability on macOS), `UnavailableVoiceProvider` safely idles without crashing or throwing unhandled errors.
