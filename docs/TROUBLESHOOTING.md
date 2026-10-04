# LIGHT — Troubleshooting & Historical Defect Catalog

This catalog preserves diagnosed defects, their causes, fixes, and regression
evidence. All listed issues are **Resolved in `v0.5.0`** unless a limitation is
called out. Historical logs and symptoms explain the fix; they are not current
failure reports or universal performance guarantees.

## Current status index

| Issues | Status at `v0.5.0` | Remaining boundary |
| --- | --- | --- |
| 1, 3, 4 | Resolved | parser/model behavior remains input-dependent |
| 2, 7, 10, 16 | Resolved | external websites and browser policy can still change |
| 5, 18, 20 | Resolved | OS focus/clipboard/process permissions remain environment-sensitive |
| 6, 11, 17 | Resolved | agent cancellation is cooperative; bounded joins may time out |
| 8, 9, 12 | Resolved | stale processes/SQLite/provider availability can still fail loudly |
| 13, 14 | Resolved in CI | not physical macOS hardware validation |
| 15, 19 | Resolved | raw-text plan identity and explicit env overrides remain documented constraints |

For installation conflicts, including the current optional `click` metadata
conflict, see [TESTING.md](TESTING.md). For operational guarantees, use
[SAFETY.md](SAFETY.md), not historical wording here.

---

## Issue 1 — `asyncio.run() cannot be called from a running event loop`

### Problem
Browser Use agent execution crashed with an unhandled exception when invoked from an active asynchronous loop.

### Symptoms
```text
RuntimeError: asyncio.run() cannot be called from a running event loop
```
The agent task failed immediately, aborting the command queue without returning a result.

### Root Cause
`browser/agent.py` previously called `asyncio.run(self.execute_task(...))` synchronously. In modern versions of LIGHT where `LightLoop.process_text_async` or external asynchronous frameworks run an active asyncio event loop in the main thread, nested calls to `asyncio.run()` are explicitly forbidden by Python's asyncio specification.

### Fix
1. Refactored `AutonomousBrowserAgent` to expose a native coroutine method: `async def execute_task(...)`.
2. Created `run_task_async(...)` for calling directly with `await` within active loops.
3. Updated the synchronous wrapper `run_task(...)` to detect a running event loop and delegate execution to a dedicated worker with an isolated loop rather than nesting `asyncio.run()`.
4. Made `core/loop.py` support native async execution via `execute_next_queued_async()`.

### Relevant Files
- [`browser/agent.py`](../browser/agent.py), [`core/loop.py`](../core/loop.py), [`core/executor.py`](../core/executor.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeatures::test_19_issue1_async_browser_agent_in_running_event_loop`
- `tests/test_new_features.py::TestNewFeatures::test_35_run_task_safe_inside_running_loop`

---

## Issue 2 — Blind Result Clicking & High School Math Paper Misdirection

### Problem
Searching for `"LangGraph"` and requesting `"open official repository"` resulted in clicking an irrelevant link entitled *"Graph Paper for High School Math"*.

### Symptoms
```text
[COMMAND] Action: click_result | Target: official repository
[BROWSER] Clicking result #1...
[BROWSER] target=result 1 viewport=(400,300) screen=(400,300) click_completed
[EXECUTOR] OK
Landed on: https://mathworld.com/graph-paper ("Graph Paper for High School Math")
```

### Root Cause
`BrowserController.locate_element_in_viewport` defaulted to clicking the first search result element (`nth_result(1)`) whenever the named target was not an exact CSS string match. In organic search results, the word *"Graph"* matched a high school math paper at position #1, causing the system to blindly click it without considering repository semantics.

### Fix
1. Implemented multi-feature candidate scoring in `browser/browser.py` for named targets:
   - +120 points for authoritative domain match (`github.com`).
   - +80 points for exact repository slug match (`langchain-ai/langgraph`).
   - +50 points for target semantic match (`repository`, `docs`, `website`).
   - -100 points penalty for social links, sharing buttons, or ad domains.
2. Enforced a minimum score threshold ($\ge 20$). If no candidate meets the threshold, the controller raises `RuntimeError` rather than blindly clicking result #1.
3. Added post-click semantic verification (`verify_destination`).

### Relevant Files
- [`browser/browser.py`](../browser/browser.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeatures::test_39_named_result_ranking_selects_repository_over_irrelevant`
- `tests/test_new_features.py::TestNewFeatures::test_40_wrong_result_detection`

---

## Issue 3 — Unwanted Google Search URL Injection in GitHub Search Flows

### Problem
Saying `"Open GitHub, search for LangGraph and open the official repository"` opened GitHub, but then unexpectedly navigated to `https://google.com` before executing the search.

### Symptoms
```text
[COMMAND] Action: open_url | Target: https://github.com
[COMMAND] Action: open_url | Target: https://google.com   <-- UNWANTED INJECTION
[COMMAND] Action: search   | Target: LangGraph
```

### Root Cause
In [`brain/decision.py`](../brain/decision.py), `normalize_command_plan()` inspected intermediate commands in a multi-step plan. Any search action that did not explicitly target `"youtube"` defaulted `required_site = "google"`. Because GitHub was active (`active_site == "github"`), the mismatch (`active_site != "google"`) caused the normalizer to inject `OPEN_URL https://google.com`.

### Fix
Updated `normalize_command_plan()` to recognize `github` as a canonical active search engine:
```python
if active_site == "github" or target.lower().startswith("github:"):
    required_site = "github"
    canonical_target = target if target.startswith("github:") else f"github:{target}"
```
This preserves GitHub as the active context and formats the search target as `github:<query>` without injecting Google.

### Relevant Files
- [`brain/decision.py`](../brain/decision.py), [`browser/browser.py`](../browser/browser.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeatures::test_37_open_github_search_langgraph_open_official_repo`

---

## Issue 4 — `"Click on First Element"` Literal String Fallback

### Problem
Voice utterance `"Click on First Element"` was interpreted as searching the DOM for an element with text `"First Element"`, which did not exist on the page.

### Symptoms
```text
[COMMAND] Action: click_element | Target: First Element
[BROWSER] Clicking element: 'First Element'
[ERROR] Could not find a visible element matching 'First Element'.
```

### Root Cause
The deterministic regex in `parse_deterministic_command()` matched `"click element <target>"` literally before checking for ordinal numbers. If the user said `"first element"`, `"element"` was captured as the noun and `"First Element"` was extracted as the target string.

### Fix
Added pre-normalization regex in `parse_deterministic_command()`:
- If a search context exists (`state.last_search_query` or `state.current_site`), phrases like `"click [the] first/1st element"` are mapped to `CLICK_RESULT(1)`.
- If on a generic webpage, it maps to `CLICK_ELEMENT("element 1")`.
- It is never dispatched as `CLICK_ELEMENT("First Element")`.

### Relevant Files
- [`brain/decision.py`](../brain/decision.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeatures::test_26_issue4_click_first_element_safe_handling`

---

## Issue 5 — Typing Keystrokes into Background or Inactive Windows

### Problem
Issuing a voice command `"Type Hello"` typed characters into whatever window happened to be active (e.g. an open terminal or IDE), even if the intended app was minimized or in the background.

### Symptoms
Keystrokes leaked into background processes, corrupting code in editor windows.

### Root Cause
`KeyboardController.type_text()` relied solely on `pyautogui.write()`, which blindly dispatches synthetic keyboard events to the OS active window without checking what process owns that window.

### Fix
1. Implemented `ScreenController.get_foreground_window_info()` using Win32 API calls (`GetForegroundWindow`, `GetWindowTextW`, `GetWindowThreadProcessId`).
2. Added `verify_foreground_app()` in `computer/screen.py` to confirm window ownership.
3. Added focus-checking guards in `Executor` before `TYPE` actions execute.

### Relevant Files
- [`computer/screen.py`](../computer/screen.py), [`core/executor.py`](../core/executor.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeatures::test_02_type_routes_to_desktop_when_browser_not_foreground`
- `tests/test_new_features.py::TestNewFeatures::test_03_type_routes_to_browser_when_browser_is_foreground`

---

## Issue 6 — Browser Ownership Collisions between Playwright and Browser Use

### Problem
Issuing deterministic browser commands while Browser Use was running corrupted the browser session or caused Playwright to crash with target closed errors.

### Symptoms
```text
playwright._impl._errors.TargetClosedError: Target page, context or browser has been closed
```

### Root Cause
Playwright and Browser Use both attempted to manipulate Chromium simultaneously without coordination or mutual exclusion.

### Fix
Implemented the `BrowserOwnership` state machine (`NONE`, `LIGHT`, `AGENT`):
- When Browser Use starts: `[BROWSER] Session handed to Browser Use` (`BrowserOwnership.AGENT`).
- Browser Use creates its own independent session.
- Browser Use never receives LIGHT's Playwright context. Deterministic commands may continue in LIGHT's independent session while `AGENT` remains the authoritative ownership state.
- Desktop commands (`OPEN_APP`, `HOTKEY`, `TYPE`, `MEDIA_*`) remain fully responsive.
- When Browser Use finishes: `[BROWSER] Session returned to LIGHT` (`BrowserOwnership.LIGHT`).

### Relevant Files
- [`core/state.py`](../core/state.py), [`core/executor.py`](../core/executor.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeatures::test_42_browser_ownership_transitions`
- `tests/test_new_features.py::TestNewFeatures::test_43_normal_desktop_command_while_agent_task_running`

---

## Issue 7 — Google reCAPTCHA `/sorry/` Challenge Blocking Search

### Problem
Automated Google searches occasionally triggered Google bot detection, redirecting to `https://www.google.com/sorry/index?continue=...` and stalling the automation loop.

### Symptoms
```text
[WARN] Google triggered an 'I'm not a robot' (/sorry/) challenge.
```

### Root Cause
Rapid headless navigation without automation masking flags triggered Google IP rate limiting and bot heuristics.

### Fix
1. Configured Playwright with stealth launch arguments (`--disable-blink-features=AutomationControlled`).
2. Added automatic `/sorry/` URL detection in `BrowserController.search()`.
3. When detected, the controller logs a warning and automatically switches the query to DuckDuckGo, preserving workflow continuity without blocking the user.

### Relevant Files
- [`browser/browser.py`](../browser/browser.py)

### Regression Test
- `tests/test_browser.py::TestBrowserAndContextFlow::test_search_google_falls_back_to_duckduckgo_when_google_shows_captcha`

---

## Issue 8 — Stale Process Accumulation on Windows

### Problem
If `main.py` crashed or was terminated abruptly, background `python.exe` processes or zombie Playwright Chromium instances remained running, locking port 9222 and the Handy database.

### Symptoms
```text
OSError: [WinError 10048] Only one usage of each socket address is normally permitted
```

### Root Cause
Windows does not automatically kill child process trees when a parent process terminates abnormally without explicit job object binding.

### Fix
Implemented `ensure_single_instance()` in [`main.py`](../main.py):
1. Reads previous PID from `.light.pid`.
2. Queries Windows `Win32_Process` via PowerShell for any other `python.exe` running `main.py`.
3. Terminates stale instances using `taskkill /PID <pid> /T /F` while carefully protecting the current process and its parent launcher shim.
4. Registers an `atexit` hook to clean up `.light.pid`.

### Relevant Files
- [`main.py`](../main.py)

### Regression Test
- `tests/test_windows_smoke.py::TestWindowsSmoke`

---

## Issue 9 — SQLite `database is locked` During Rapid Speech

### Problem
When the user dictated continuously, Handy wrote new rows to `history.db` at the exact instant LIGHT polled it, throwing a lock error.

### Symptoms
```text
[ERROR] Database read error: Database locked (sqlite3.OperationalError: database is locked)
```

### Root Cause
SQLite databases in default mode acquire exclusive locks during transactions. Attempting to open the file in default mode caused contention.

### Fix
1. In `voice/handy.py`, opened the SQLite connection using URI mode with read-only flag:
   `sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=self.timeout)`.
2. Kept the last successful transcription ID unchanged when a read fails; the listener logs the error, waits for the configured poll interval, and retries on the next iteration.

### Relevant Files
- [`voice/handy.py`](../voice/handy.py), [`core/loop.py`](../core/loop.py)

### Regression Test
- `tests/test_voice.py::TestHandyVoiceAndLoop::test_loop_duplicate_handling_and_error_recovery`

---

## Issue 10 — Brave Browser `[WinError 5] Access is denied`

### Problem
On systems where Brave was installed in user `%LOCALAPPDATA%`, launching Brave directly via Playwright threw an OS permission error.

### Symptoms
```text
PermissionError: [WinError 5] Access is denied: 'C:\Users\<user>\AppData\Local\...\brave.exe'
```

### Root Cause
Windows security sandboxing and file locks prevented Playwright from executing the Brave binary directly with debugging pipes.

### Fix
Implemented a robust multi-browser fallback chain in `BrowserController.start()`:
1. Try configured Brave path.
2. If `PermissionError` or `FileNotFoundError` occurs, log a warning and fall back to Playwright-managed Chromium (`.playwright-browsers` or `%LOCALAPPDATA%\ms-playwright`).
3. If Chromium is unavailable, fall back to Google Chrome.

### Relevant Files
- [`browser/browser.py`](../browser/browser.py), [`config.py`](../config.py)

### Regression Test
- `tests/test_browser.py::TestBrowserAndContextFlow::test_start_falls_back_to_playwright_chromium_on_winerror_5`

---

## Issue 11 — Normal Commands Blocked Behind Long-Running Autonomous Agent Tasks (`queue_wait` ~260s)

### Problem
When the user initiated an open-ended autonomous research task (`Action.AGENT_TASK`), all subsequent voice commands (`"Open YouTube"`, `"Open Google"`, `"Close Notepad"`) were queued behind the agent task and blocked until the agent fully finished minutes later.

### Symptoms
```text
[AGENT_TASK] execution ≈ 443215 ms
[VOICE] Open YouTube
[PERF] ... queue_wait=263354 ms
[VOICE] Open Google
[PERF] ... queue_wait=255313 ms
```
The voice listener continued hearing and enqueueing spoken utterances, but the consumer loop was completely blocked inside synchronous execution of the agent task.

### Root Cause
In [`core/executor.py`](../core/executor.py), `Executor.execute()` handled `Action.AGENT_TASK` by synchronously calling `self.browser_agent.run_task(task_instruction=target, cancel_event=cancel_event)`. Because Browser Use with local Ollama (`qwen3:1.7b`) takes multiple minutes to browse, synthesize, and complete tasks, the single `LightLoop` consumer thread was held hostage for the entire duration of the research run.

### Fix
1. **Managed Background Worker (`LIGHT-AgentWorker`)**: Offloaded `browser_agent.run_task()` to a dedicated managed daemon thread (`LIGHT-AgentWorker`) inside `Executor.execute()`.
2. **Immediate Consumer Return**: `Executor.execute()` sets `state.agent_running = True`, transitions `BrowserOwnership.AGENT`, starts the background worker thread, and returns `"OK"` immediately to the caller, allowing `LightLoop` to continue dequeuing and executing normal commands.
3. **Duplicate Agent Protection**: If a second `AGENT_TASK` is received while a worker is already running, `Executor.execute()` logs a message and returns `"REJECTED"`, preventing duplicate sessions and CPU starvation.
4. **Lifecycle & Preemption Management**: Added `join_agent()` and `close()` in `Executor` plus bounded join attempts (200ms in the STOP path and 500ms by default during close). A dependency that ignores cancellation may outlive the join window.
5. **State Restoration**: When `_agent_worker` terminates, it updates `state.agent_running = False` and safely restores `BrowserOwnership` to `LIGHT` (if primary browser is open) or `NONE`.

### Relevant Files
- [`core/executor.py`](../core/executor.py), [`core/loop.py`](../core/loop.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeatures::test_45_agent_task_dispatch_is_non_blocking`
- `tests/test_new_features.py::TestNewFeatures::test_46_normal_command_while_agent_runs`
- `tests/test_new_features.py::TestNewFeatures::test_47_multiple_normal_commands_execute_in_queue_order_during_agent_task`
- `tests/test_new_features.py::TestNewFeatures::test_48_stop_preemption_cancels_background_agent_within_bounded_time`
- `tests/test_new_features.py::TestNewFeatures::test_49_duplicate_agent_task_rejected_while_active`
- `tests/test_new_features.py::TestNewFeatures::test_50_agent_completion_restores_state_safely`
- `tests/test_new_features.py::TestNewFeatures::test_51_agent_failure_restores_state_safely`
- `tests/test_new_features.py::TestNewFeatures::test_52_shutdown_cancels_active_agent_with_bounded_cleanup`

---

## Issue 12 — Missing Voice Provider on Non-Windows Hosts (macOS)

### Problem
Starting LIGHT on macOS or a machine without Handy installed caused an immediate `FileNotFoundError` during `Handy.__init__()` when trying to open `%APPDATA%\com.pais.handy\history.db`.

### Symptoms
```text
FileNotFoundError: Handy database not found:
/Users/.../Library/Application Support/com.pais.handy/history.db
```

### Root Cause
`main.py` directly instantiated `Handy()`, which strictly asserted that the SQLite database file existed on disk. On macOS hosts where Handy was uninstalled or unverified, this crashed the process on launch.

### Fix
1. Abstracted speech ingestion into `VoiceInputProvider` (`voice/base.py`).
2. Implemented `voice/factory.py:get_voice_provider()`:
   - If the Handy database exists at the platform-appropriate location, instantiates `HandyVoiceProvider`.
   - If the database is missing, returns an `UnavailableVoiceProvider` with an informative status message instead of crashing.
3. Updated `LightLoop` to inspect `voice_provider.is_available()`, logging a clear diagnostic warning and keeping the voice listener idle without throwing errors.

### Relevant Files
- [`voice/base.py`](../voice/base.py), [`voice/factory.py`](../voice/factory.py), [`voice/unavailable_provider.py`](../voice/unavailable_provider.py), [`core/loop.py`](../core/loop.py), [`main.py`](../main.py)

### Regression Test
- `tests/test_voice_provider.py::TestVoiceProviders::test_factory_returns_unavailable_when_db_missing_without_crashing`
- `tests/test_voice_provider.py::TestVoiceProviders::test_unavailable_provider_behavior`


---

## Issue 13 — macOS CI Test Discovery Failures (PyObjC & Platform Assertions)

### Problem
When executing automated test discovery on `macos-latest` GitHub Actions runners, test discovery failed due to missing PyAutoGUI macOS frameworks and Windows-specific mock assertions.

### Symptoms
```text
AssertionError: You must first install pyobjc-core and pyobjc
AssertionError: expected call not found. Expected: hotkey('ctrl', 'r') Actual: hotkey('command', 'r')
AssertionError: expected call not found. Expected: Popen(['notepad.exe']) Actual: Popen(['open', '-a', 'TextEdit'])
```

### Root Cause
1. PyAutoGUI's macOS backend (`_pyautogui_osx.py`) imports `Quartz` and `AppKit`. Without `pyobjc-core`, `pyobjc-framework-Quartz`, and `pyobjc-framework-Cocoa`, PyAutoGUI aborts during import on native macOS.
2. Unit tests in `tests/test_computer.py` and `tests/test_new_features.py` had hardcoded Windows command strings (`notepad.exe`, `taskkill /IM ...`, `ctrl+c`), causing them to fail when running against native `MacOSPlatformController`.
3. In `tests/test_voice.py`, process scan simulation only emitted Windows PowerShell output format rather than POSIX `ps` output.

### Fix
1. In `requirements.txt`, added `pyobjc-core`, `pyobjc-framework-Quartz`, and `pyobjc-framework-Cocoa` guarded with `sys_platform == 'darwin'`.
2. Updated `tests/test_computer.py`, `tests/test_new_features.py`, and `tests/test_voice.py` to assert platform-appropriate commands (`open -a TextEdit`, `pkill -f TextEdit`, `command+c`, `ps` output) conditionally based on `sys.platform`.
3. Configured `strategy.fail-fast: false` in `.github/workflows/tests.yml` so that matrix runners execute to completion independently.

### Relevant Files
- [`requirements.txt`](../requirements.txt), [`tests/test_computer.py`](../tests/test_computer.py), [`tests/test_new_features.py`](../tests/test_new_features.py), [`tests/test_voice.py`](../tests/test_voice.py), [`.github/workflows/tests.yml`](../.github/workflows/tests.yml)

### Regression Test
- `tests/test_computer.py::TestComputerControl::test_open_notepad_and_calculator`
- `tests/test_computer.py::TestComputerControl::test_close_apps`
- `tests/test_computer.py::TestComputerControl::test_keyboard_hotkey`
- `tests/test_new_features.py::TestNewFeatures::test_05_hotkey_execution`
- `tests/test_voice.py::TestHandyVoiceAndLoop::test_ensure_single_instance_kills_stale_pids_and_writes_current_pid`

---

## Issue 14 — Post-Action Observation Sync Overhead on Interruptible Actions (WAIT / AGENT_TASK)

### Problem
On macOS CI runners, three timing tests (`test_12_stop_preemption_interrupts_wait_under_5ms`, `test_45_agent_task_dispatch_is_non_blocking`, and `test_03_stop_and_cancel_priority_preempts_wait_and_queued_commands`) failed timing assertions with latencies of 139ms–207ms against thresholds of 50ms–80ms.

### Symptoms
```text
AssertionError: 207.41 not less than 50.0 (test_12_stop_preemption_interrupts_wait_under_5ms)
AssertionError: 188.74 not less than 50.0 (test_45_agent_task_dispatch_is_non_blocking)
AssertionError: 139.32 not less than 80.0 : Expected STOP to interrupt 10s WAIT within 80ms (test_03_stop_and_cancel_priority_preempts_wait_and_queued_commands)
```

### Root Cause
In `core/executor.py`, after executing `Action.WAIT` and `Action.AGENT_TASK`, execution fell through to `self.state.sync_observation(browser=self.browser, screen=self.screen)`:
1. `WAIT` does not alter active windows, URLs, or mouse position, making post-action observation synchronization redundant.
2. `AGENT_TASK` runs asynchronously on `LIGHT-AgentWorker` and transfers browser ownership to `BrowserOwnership.AGENT`, making synchronous browser inspection on dispatch redundant.
3. On macOS, `screen.get_foreground_window_info()` executes AppleScript via `osascript`, taking 50ms–150ms per process invocation. Running this synchronously inside `WAIT` wakeups and `AGENT_TASK` dispatch severely inflated latency and broke STOP preemption contracts.

### Fix
In [`core/executor.py`](../core/executor.py), updated `Action.AGENT_TASK` and `Action.WAIT` to record the command in `self.state` and return `"OK"` immediately, bypassing redundant post-action observation sync and AppleScript subprocess execution.

### Relevant Files
- [`core/executor.py`](../core/executor.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeatures::test_12_stop_preemption_interrupts_wait_under_5ms`
- `tests/test_new_features.py::TestNewFeatures::test_45_agent_task_dispatch_is_non_blocking`
- `tests/test_queue_and_llm.py::TestProducerConsumerQueueAndLLM::test_03_stop_and_cancel_priority_preempts_wait_and_queued_commands`

---

## Issue 15 — Failed Plan Cancelled Another Utterance's Queued Click

### Problem
When a compound `SEARCH` failed, dependent-action pruning could cancel the first queued `CLICK_RESULT` even when that click belonged to a different utterance.

### Root Cause
`CommandQueue.cancel_dependent_after_failure()` used `(same_plan or cancelled == 0)`. The second term deliberately selected one dependent action even when `CommandRequest.text` did not match the failed plan.

### Fix
Dependent actions are now cancelled only when their plan text matches `failed_text`; passing no plan text retains the explicit all-plan behavior.

### Regression Test
- `tests/test_queue_and_llm.py::TestProducerConsumerQueueAndLLM::test_25_failed_plan_only_cancels_its_own_dependent_commands`

---

## Issue 16 — Named Result Click Could Verify the Unchanged Search Page

### Problem
A named click such as `"official repository"` could fail to navigate yet still pass semantic verification because the unchanged GitHub search URL and page text contained the expected tokens.

### Root Cause
`verify_destination()` waited for a URL change but did not require one. It also returned silently if the browser became inactive, and its wait did not observe STOP cancellation.

### Fix
Verification now rejects inactive browsers and unchanged pre-click URLs. The bounded navigation wait accepts the queue `cancel_event` and exits immediately on STOP.

### Regression Tests
- `tests/test_new_features.py::TestNewFeatures::test_41b_semantic_verification_rejects_inactive_and_unchanged_pages`
- `tests/test_new_features.py::TestNewFeatures::test_41c_semantic_verification_wait_is_stop_cancellable`

---

## Issue 17 — Agent Admission and Ownership State Races

### Problem
Concurrent `AGENT_TASK` calls could both pass duplicate detection before either published its worker. Separately, a deterministic browser action during agent execution overwrote `BrowserOwnership.AGENT` with `LIGHT` even though the agent remained active.

### Root Cause
Duplicate detection and worker assignment occurred in separate `_agent_lock` critical sections. `LightState.record_command()` unconditionally assigned LIGHT ownership for browser actions.

### Fix
Agent admission, state publication, worker publication, and thread start now occur in one critical section. Browser state recording preserves `AGENT` ownership until the isolated worker exits.

### Regression Tests
- `tests/test_new_features.py::TestNewFeatures::test_43b_deterministic_browser_command_preserves_active_agent_ownership`
- `tests/test_new_features.py::TestNewFeatures::test_49b_agent_admission_uses_one_atomic_critical_section`

---

## Issue 18 — Normal Desktop Close Used Image-Wide Force Kill

### Problem
Closing Notepad/TextEdit or Calculator without a LIGHT-tracked launch fell through to `taskkill /F /IM ...` or `pkill -f ...`, risking unrelated user documents and processes.

### Root Cause
`AppController.close()` always requested force-close commands for standard utilities after checking its tracked `Popen` list.

### Fix
Normal close now terminates only LIGHT-tracked processes. macOS may issue a graceful AppleScript quit after a tracked `open -a` launch because that launcher exits immediately. Image-wide termination is available only through explicit `force=True`.

### Regression Tests
- `tests/test_computer.py::TestComputerControl::test_close_apps`
- `tests/test_computer.py::TestComputerControl::test_close_notepad_only_terminates_light_tracked_process`

---

## Issue 19 — Browser Use Global Config Write and Optional Network Defaults

### Problem
The lazy Browser Use import attempted to write under the user's global configuration directory and defaulted optional telemetry/cloud sync on. Restricted or hermetic environments failed during import, and the behavior conflicted with LIGHT's local-first default.

### Root Cause
LIGHT did not initialize Browser Use's configuration environment before importing the optional dependency.

### Fix
`config.py` selects the ignored repository-local `.light_browseruse/` directory and defaults `ANONYMIZED_TELEMETRY=false` and `BROWSER_USE_CLOUD_SYNC=false`. `AutonomousBrowserAgent` reasserts those defaults immediately before the lazy import while respecting explicit user overrides.

### Regression Test
- `tests/test_new_features.py::TestNewFeatures::test_53_browser_agent_defaults_are_local_and_private`

---

## Issue 20 — False Clipboard Success and Stale STOP Browser State

### Problem
Browser copy actions ignored clipboard read-back failure and reported success. STOP closed the browser but returned before `LightState.record_command()`, leaving stale URL/site/browser context that could influence subsequent planning.

### Root Cause
The boolean result of `_write_and_verify_clipboard()` was discarded, and STOP had a special early return that bypassed normal state recording.

### Fix
Browser copy paths raise on failed clipboard verification. Desktop copy/paste routes through `KeyboardController` for platform modifier mapping. STOP records its command after shutdown and clears browser URL, title, site, app, and ownership state.

### Regression Tests
- `tests/test_browser.py::TestBrowserAndContextFlow::test_copy_selected_text_requires_verified_clipboard_write`
- `tests/test_computer.py::TestComputerControl::test_executor_routes_clipboard_shortcuts_through_platform_keyboard`
- `tests/test_new_features.py::TestNewFeatures::test_44b_stop_clears_stale_browser_state`

---

## Issue 21 — AI Provider and Model Hardcoded to Ollama/Qwen

### Problem
The planner accepted provider/model constructor strings but always called the
Ollama `/api/chat` protocol. The autonomous browser agent separately hardcoded
`ChatOllama`. Changing configuration therefore did not produce a real provider
switch, and planning and agent tasks could disagree.

### Root Cause
Transport, provider selection, model selection, and planner action validation
were combined inside `QwenPlanner`, while Browser Use constructed its own LLM
independently.

### Fix
Typed provider/model configuration and an explicit AI adapter registry now own
transport and model discovery. The backward-compatible planner delegates to the
selected adapter, and Browser Use reuses that same selection. Every adapter
returns through the existing action validation. Configuration activation is
explicit; an unavailable provider never causes silent provider/model fallback.

The audit also confirmed that `VoiceInputProvider` starts at completed
transcript events. Handy remains the supported local runtime, and custom STT is
a documented transcript feed. Direct Whisper was not fabricated without an
audio capture/VAD contract.

### Regression Tests
- `tests/test_provider_architecture.py`
- `tests/test_queue_and_llm.py::TestProducerConsumerQueueAndLLM::test_04_phase9_all_22_fast_path_commands_have_zero_llm_calls`
- `tests/test_new_features.py::TestNewFeatures::test_16_agent_task_initialization_logs_and_ollama`

---

## Issue 22 — Inaccessible Handy Path Crashed Provider Discovery

### Problem
An existing but inaccessible Handy database path could raise `PermissionError`
during `Path.exists()`, crashing startup/status before LIGHT could enter its
documented unavailable-provider mode.

### Root Cause
The existence check occurred immediately before the factory's guarded Handy
constructor block.

### Fix
The factory now handles `OSError` around the path probe, logs the access
diagnostic, and returns `UnavailableVoiceProvider`. It does not try a different
STT provider.

### Regression Test
- `tests/test_voice_provider.py::TestVoiceProviders::test_factory_returns_unavailable_when_handy_path_is_inaccessible`
