# LIGHT — Comprehensive Testing Guide

> **Test Suite Baseline**: Running the automated test discovery command discovers **119 tests**: **115 execute and pass**, **0 fail**, **0 errors**, and **4 opt-in host smoke tests skip by default (`OK (skipped=4)`)**.

---

## 1. Test Architecture Overview

LIGHT employs a multi-tiered test suite to guarantee safety, deterministic accuracy, low-latency execution, and non-regression across all desktop and browser subsystems:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   LIGHT MULTI-TIER TEST SUITE (119 TESTS)              │
├────────────────────────────────┬───────────────────────────────────────┤
│ Tier 1: Deterministic Unit     │ 42 Tests across voice, intent parsing,│
│ (Isolated Mocks, <1ms parsing) │ desktop apps, screen, and browser.    │
├────────────────────────────────┼───────────────────────────────────────┤
│ Tier 2: Real Local Browser     │ 5 Headless Playwright integration     │
│ (ThreadingHTTPServer + DOM)    │ tests against local HTML fixtures.    │
├────────────────────────────────┼───────────────────────────────────────┤
│ Tier 3: Queue, LLM Planning,   │ 68 Tests covering queue, Qwen planner,│
│ Reliability & Advanced Features│ Browser Use, ranking, and verification│
├────────────────────────────────┼───────────────────────────────────────┤
│ Tier 4: Opt-In Windows Smoke   │ 4 Host environment checks skipped     │
│ (LIGHT_RUN_WINDOWS_SMOKE=1)    │ by default during automated runs.     │
└────────────────────────────────┴───────────────────────────────────────┘
```

---

## 2. Test Execution Commands

### 2.1 Full Automated Discovery Suite (Default CI & Local Baseline)
Executes all 115 unit and local browser integration tests across the repository:

```powershell
.\lightenv\Scripts\python.exe -m unittest discover -s tests -v
```

**Expected Baseline Output**:
```text
Ran 119 tests in ~24s
OK (skipped=4)
```

### 2.2 Static Syntax & Compilation Check
Verifies that all Python modules compile cleanly without syntax errors:

```powershell
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py voice brain computer browser core utils tests
```

### 2.3 Individual Subsystem Test Runs

| Subsystem | Target Test File | Test Command | Tests |
| :--- | :--- | :--- | :---: |
| **Voice & Handy Loop** | `tests/test_voice.py` | `python -m unittest tests/test_voice.py -v` | 6 |
| **Laya & Intent Parsing** | `tests/test_laya.py` | `python -m unittest tests/test_laya.py -v` | 16 |
| **Desktop & Computer** | `tests/test_computer.py` | `python -m unittest tests/test_computer.py -v` | 12 |
| **Browser Unit** | `tests/test_browser.py` | `python -m unittest tests/test_browser.py -v` | 8 |
| **Local Browser Integration**| `tests/test_integration_local_browser.py` | `python -m unittest tests/test_integration_local_browser.py -v`| 5 |
| **V2 Queue & LLM Planning** | `tests/test_queue_and_llm.py` | `python -m unittest tests/test_queue_and_llm.py -v` | 24 |
| **Reliability & Ownership** | `tests/test_new_features.py` | `python -m unittest tests/test_new_features.py -v` | 44 |
| **Opt-In Windows Smoke** | `tests/test_windows_smoke.py` | `$env:LIGHT_RUN_WINDOWS_SMOKE="1"; python -m unittest tests/test_windows_smoke.py -v` | 4 |

---

## 3. Detailed Test Suite Inventory

### Tier 1: Deterministic Unit Tests (42 Tests)
- **`tests/test_voice.py` (6 tests)**:
  - Missing Handy database handling (`FileNotFoundError`).
  - Empty `transcription_history` handling (`None` return).
  - Latest transcription retrieval with monotonic ID ordering.
  - Malformed database schema recovery (`RuntimeError`).
  - Voice loop debouncing and SQLite locked-database error recovery.
  - Single-instance process cleanup (`ensure_single_instance`).
- **`tests/test_laya.py` (16 tests)**:
  - Deterministic command mapping across all `Action` enum variants.
  - Context-aware search destination routing (YouTube vs Google).
  - Direct copy commands (`"copy text <phrase>"`) and delimiter boundary slicing (`|||`).
  - Mouse movement variants and ambiguous phrase protection.
  - Rejection of malformed/incomplete commands (`"Open"`, `"Search"`, `"Copy from"`).
  - Safety rejection of casual speech (`"How are you"`, `"I am hungry"`) and single unrelated words (`"Cricket"`).
- **`tests/test_computer.py` (12 tests)**:
  - App launch/close for `Notepad` and `Calculator`.
  - Protected browser termination ensuring only LIGHT-tracked PIDs are terminated.
  - Controlled browser session management and state updates.
  - Mouse relative movements, boundary clamping, and anchor point homing.
  - Keyboard focus typing, key presses, and system hotkey dispatch.
  - Unknown application error handling.
- **`tests/test_browser.py` (8 tests)**:
  - URL normalization and standard website shortcut expansion.
  - Navigation controls (`go_back`, `go_forward`, `refresh`, `scroll`).
  - High-DPI viewport-to-screen coordinate math.
  - Browser start fallback chain from inaccessible Brave to Playwright Chromium.
  - Google reCAPTCHA `/sorry/` detection and automatic DuckDuckGo fallback.
  - End-to-end mocked context loop execution.

### Tier 2: Real Local-Browser Playwright Integration Tests (5 Tests)
- **`tests/test_integration_local_browser.py` (5 tests)**:
  - Spins up a real `ThreadingHTTPServer` on `127.0.0.1` serving local HTML test fixtures (`index.html`, `page2.html`).
  - Launches headless Playwright Chromium via `BrowserController(headless=True)`.
  - **Test 1**: Page title and visible text reading against live DOM.
  - **Test 2**: Search bar element location and text typing.
  - **Test 3**: Visible element detection skipping hidden duplicates (`display: none`).
  - **Test 4**: Result selection by index and window scroll tracking.
  - **Test 5**: Inclusive text range copying, casing preservation, and DOM highlight cleanup (`clear_highlights`).

### Tier 3: Queue, LLM Planning & Feature Reliability (68 Tests)
- **`tests/test_queue_and_llm.py` (24 tests)**:
  - Producer-consumer command queue prioritizing `CommandPriority.STOP`.
  - Immediate STOP preemption interrupting active `WAIT` actions.
  - Background voice ingestion decoupled from synchronous command execution.
  - Rapid stress sequences preserving exact queue order and zero dropped transcriptions.
  - Fast-path verification confirming zero LLM calls for 22 deterministic commands.
  - Local Qwen3 1.7B planning, prompt construction, and plan normalization.
  - Google reCAPTCHA fallback, closed-context browser recovery, and skip button verification.
  - Pruning downstream dependent commands on prerequisite failure.
- **`tests/test_new_features.py` (44 tests)**:
  - Foreground-aware typing and active window verification (`computer/screen.py`).
  - Windows window controls (minimize, maximize, restore, switch) and media keys.
  - Autonomous browser agent initialization with local Ollama (`qwen3:1.7b`).
  - Event-loop-safe async agent execution (`execute_task`) without `asyncio.run()` collisions.
  - Immediate agent task cancellation upon voice STOP.
  - GitHub search integration (`search_github`) and result container selectors.
  - Target candidate scoring and ranking prioritizing official repos over math papers.
  - Semantic post-click destination verification (`verify_destination`).
  - Browser ownership lifecycle transitions (`NONE` $\to$ `LIGHT` $\to$ `AGENT` $\to$ `NONE`).
  - Concurrent execution of desktop commands while an autonomous agent runs.

### Tier 4: Opt-In Windows Host Smoke Tests (4 Tests)
- **`tests/test_windows_smoke.py` (4 tests, skipped by default)**:
  - Enabled exclusively when `$env:LIGHT_RUN_WINDOWS_SMOKE="1"`.
  - Verifies local Brave/Chrome executable discovery.
  - Verifies system clipboard write/read round-trip via `pyperclip`.
  - Verifies live screen dimensions, cursor tracking, and active window titles.
  - Verifies non-destructive read access to the host's actual Handy `history.db`.

---

## 4. Critical Verification Workflows

The test suite validates three mission-critical end-to-end workflows:

### Critical Workflow 1: Compound GitHub Search & Official Repository Navigation
- **Spoken Text**: `"Open GitHub, search for LangGraph and open the official repository."`
- **Expected Flow**:
  1. `parse_multi_command` deterministically yields 3 actions:
     - `OPEN_URL("https://github.com")`
     - `SEARCH("github:LangGraph")`
     - `CLICK_RESULT("official repository")`
  2. `Executor` opens GitHub, recognizes active site `github`, and executes repository search without injecting Google URLs.
  3. `LightState` preserves `current_site = "github"` and `last_search_query = "LangGraph"`.
  4. `locate_element_in_viewport` ranks candidate links on page:
     - Scores `langchain-ai/langgraph` link (+120 domain, +80 slug, +50 official = 250).
     - Rejects unrelated or social links.
  5. Clicks official repository link and triggers `verify_destination()`.
  6. Verifies landing URL contains `github.com` and `langgraph`; confirms page title matches repository; reports `[EXECUTOR] OK`.
  7. If user utters a continuation like `"Official repository"`, context-aware parsing routes it directly to `CLICK_RESULT("official repository")` without re-searching Google or converting to an invalid `OPEN_URL`.

### Critical Workflow 2: Concurrent Desktop Commands & STOP During Agent Task
- **Scenario**: Autonomous agent task running in background while user issues desktop commands.
- **Expected Flow**:
  1. `AGENT_TASK` starts; browser ownership transitions to `BrowserOwnership.AGENT`.
  2. Browser Use launches its own isolated browser session.
  3. User says `"Open Notepad"` or `"Hotkey ctrl+c"`.
  4. Desktop controllers execute immediately without blocking on or waiting for the autonomous agent.
  5. User says `"Stop"`.
  6. Listener detects STOP in <5ms, sets `cancel_event`, and calls `executor.browser_agent.cancel()`.
  7. Agent halts immediately, state resets cleanly, and browser ownership returns to `BrowserOwnership.NONE`.

### Critical Workflow 3: Wrong Browser Result Rejection & Verification Failure
- **Scenario**: Search results return irrelevant or malicious links, or page navigates to a mismatched target.
- **Expected Flow**:
  1. User requests `"Click official repository"`.
  2. If visible links in viewport do not meet the minimum confidence score (score < 20), `BrowserController` fails safely with `RuntimeError` rather than blindly clicking result #1.
  3. If a click occurs but the destination page lands on an unrelated site (e.g. `mathworld.com/graph-paper` for a LangGraph search), `verify_destination()` detects domain and content mismatch.
  4. `BrowserController` raises `RuntimeError("Semantic verification failed")`.
  5. `Executor` logs failure and refuses to return `[EXECUTOR] OK`.
