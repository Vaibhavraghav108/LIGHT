# LIGHT — Troubleshooting & Historical Defect Catalog

> **Knowledge Base**: This document catalogues real technical challenges, edge-case regressions, and historical defects encountered during the development of **LIGHT**, detailing the exact symptoms, root causes, permanent fixes, and corresponding regression tests.

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
3. Updated the synchronous wrapper `run_task(...)` to inspect `asyncio.get_event_loop()`: if an event loop is already running, it delegates execution to a dedicated background worker thread with its own isolated event loop (`_run_in_new_loop`) rather than using forbidden `nest_asyncio`.
4. Made `core/loop.py` support native async execution via `execute_next_queued_async()`.

### Relevant Files
- [`browser/agent.py`](file:///c:/Projects/LIGHT/browser/agent.py), [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_19_issue1_async_browser_agent_in_running_event_loop`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_35_run_task_safe_inside_running_loop`

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
- [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_39_named_result_ranking_selects_repository_over_irrelevant`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_40_wrong_result_detection`

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
In [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py), `normalize_command_plan()` inspected intermediate commands in a multi-step plan. Any search action that did not explicitly target `"youtube"` defaulted `required_site = "google"`. Because GitHub was active (`active_site == "github"`), the mismatch (`active_site != "google"`) caused the normalizer to inject `OPEN_URL https://google.com`.

### Fix
Updated `normalize_command_plan()` to recognize `github` as a canonical active search engine:
```python
if active_site == "github" or target.lower().startswith("github:"):
    required_site = "github"
    canonical_target = target if target.startswith("github:") else f"github:{target}"
```
This preserves GitHub as the active context and formats the search target as `github:<query>` without injecting Google.

### Relevant Files
- [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py), [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_37_open_github_search_langgraph_open_official_repo`

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
- [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_20_click_first_element_voice_variations`

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
- [`computer/screen.py`](file:///c:/Projects/LIGHT/computer/screen.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_01_foreground_window_detection`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_02_focus_aware_typing_success`

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
- Playwright actions are blocked while `AGENT` ownership is active.
- Desktop commands (`OPEN_APP`, `HOTKEY`, `TYPE`, `MEDIA_*`) remain fully responsive.
- When Browser Use finishes: `[BROWSER] Session returned to LIGHT` (`BrowserOwnership.LIGHT`).

### Relevant Files
- [`core/state.py`](file:///c:/Projects/LIGHT/core/state.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_42_browser_ownership_transitions`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_43_normal_desktop_command_while_agent_task_running`

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
- [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py)

### Regression Test
- `tests/test_browser.py::TestBrowserAndContextFlow::test_google_recaptcha_fallback_to_duckduckgo`

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
Implemented `ensure_single_instance()` in [`main.py`](file:///c:/Projects/LIGHT/main.py):
1. Reads previous PID from `.light.pid`.
2. Queries Windows `Win32_Process` via PowerShell for any other `python.exe` running `main.py`.
3. Terminates stale instances using `taskkill /PID <pid> /T /F` while carefully protecting the current process and its parent launcher shim.
4. Registers an `atexit` hook to clean up `.light.pid`.

### Relevant Files
- [`main.py`](file:///c:/Projects/LIGHT/main.py)

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
2. Wrapped DB read operations in a retry loop with exponential backoff in `core/loop.py`.

### Relevant Files
- [`voice/handy.py`](file:///c:/Projects/LIGHT/voice/handy.py), [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py)

### Regression Test
- `tests/test_voice.py::TestHandyVoiceAndLoop::test_loop_duplicate_handling_and_error_recovery`

---

## Issue 10 — Brave Browser `[WinError 5] Access is denied`

### Problem
On systems where Brave was installed in user `%LOCALAPPDATA%`, launching Brave directly via Playwright threw an OS permission error.

### Symptoms
```text
PermissionError: [WinError 5] Access is denied: 'C:\Users\...\Application\brave.exe'
```

### Root Cause
Windows security sandboxing and file locks prevented Playwright from executing the Brave binary directly with debugging pipes.

### Fix
Implemented a robust multi-browser fallback chain in `BrowserController.start()`:
1. Try configured Brave path.
2. If `PermissionError` or `FileNotFoundError` occurs, log a warning and fall back to Playwright-managed Chromium (`.playwright-browsers` or `%LOCALAPPDATA%\ms-playwright`).
3. If Chromium is unavailable, fall back to Google Chrome.

### Relevant Files
- [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py), [`config.py`](file:///c:/Projects/LIGHT/config.py)

### Regression Test
- `tests/test_browser.py::TestBrowserAndContextFlow::test_start_fallback_to_chromium_when_brave_inaccessible`

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
In [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py), `Executor.execute()` handled `Action.AGENT_TASK` by synchronously calling `self.browser_agent.run_task(task_instruction=target, cancel_event=cancel_event)`. Because Browser Use with local Ollama (`qwen3:1.7b`) takes multiple minutes to browse, synthesize, and complete tasks, the single `LightLoop` consumer thread was held hostage for the entire duration of the research run.

### Fix
1. **Managed Background Worker (`LIGHT-AgentWorker`)**: Offloaded `browser_agent.run_task()` to a dedicated managed daemon thread (`LIGHT-AgentWorker`) inside `Executor.execute()`.
2. **Immediate Consumer Return**: `Executor.execute()` sets `state.agent_running = True`, transitions `BrowserOwnership.AGENT`, starts the background worker thread, and returns `"OK"` immediately to the caller, allowing `LightLoop` to continue dequeuing and executing normal commands.
3. **Duplicate Agent Protection**: If a second `AGENT_TASK` is received while a worker is already running, `Executor.execute()` logs a message and returns `"REJECTED"`, preventing duplicate sessions and CPU starvation.
4. **Lifecycle & Preemption Management**: Added `join_agent()` and `close()` in `Executor` to set `cancel_event` and safely join the worker within bounded timeouts (<300ms on STOP, 500ms on loop exit).
5. **State Restoration**: When `_agent_worker` terminates, it updates `state.agent_running = False` and safely restores `BrowserOwnership` to `LIGHT` (if primary browser is open) or `NONE`.

### Relevant Files
- [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py), [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py)

### Regression Test
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_45_agent_task_runs_in_background_without_blocking_executor`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_46_normal_commands_execute_immediately_while_agent_runs`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_47_duplicate_agent_task_is_rejected_while_one_is_running`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_48_stop_preempts_background_agent_worker`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_49_loop_shutdown_joins_agent_worker`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_50_agent_worker_failure_resets_state`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_51_async_loop_executes_normal_command_while_agent_runs`
- `tests/test_new_features.py::TestNewFeaturesIntegration::test_52_interleaved_desktop_and_browser_commands_during_agent_task`
