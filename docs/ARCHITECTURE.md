# LIGHT — System Architecture Specification

> **Source of Truth**: This document details the technical architecture, runtime data flows, concurrency models, and component boundaries of **LIGHT**. All descriptions correspond directly to the active implementation in the repository.

---

## 1. High-Level Architecture Diagram

```text
                  PHYSICAL ENVIRONMENT
                           │ (Spoken Audio)
                           ▼
                 Handy Desktop Application
       (Continuous Local Speech-to-Text & VAD)
                           │
                           ▼
           SQLite Database (%APPDATA%\...\history.db)
                           │
═══════════════════════════╪════════════════════════════════════════════
                           │ LIGHT RUNTIME PROCESS
                           ▼
                     voice/handy.py
            (Handy SQLite Reader & Poller)
                           │
                           ▼
                      core/loop.py
       (Dedicated Background Listener Thread: 150ms)
                           │
                           ▼
                  core/queue_manager.py
    (Producer-Consumer Queue with Immediate STOP Preemption)
                           │
                           ▼
                      brain/laya.py
            (Hybrid Multi-Tier Intent Parser)
  ┌────────────────────────┼────────────────────────┐
  ▼                        ▼                        ▼
Deterministic Fast Path  Local Qwen3 1.7B LLM    Strict Laya Fallback
(brain/decision.py)      (brain/llm.py @ Ollama) (laya library)
(<1ms regex/grammars)    (complex goal planning) (prefix-guarded choice)
  └────────────────────────┬────────────────────────┘
                           │ Canonical Plan (List[Command])
                           ▼
                    core/executor.py
              (Central Action Dispatcher)
  ┌────────────────────────┼────────────────────────┐
  ▼                        ▼                        ▼
computer/                browser/browser.py       browser/agent.py
- apps.py (lifecycle)    - Playwright Chromium    - Browser Use
- screen.py (focus/win)  - DOM candidate ranking  - Autonomous goals
- keyboard.py (typing)   - Semantic verification  - Subordinate worker
- mouse.py (precision)   [Ownership: LIGHT]       [Ownership: AGENT]
  └────────────────────────┬────────────────────────┘
                           ▼
               Observation & Verification
       (Foreground check, DOM bounds, URL/Title semantics)
```

---

## 2. Pipeline Execution Layers

### Layer 1: Speech Ingestion & Polling (`voice/`)
- **Component**: [`voice/handy.py`](file:///c:/Projects/LIGHT/voice/handy.py)
- **Role**: Reads transcription records produced by the local Handy speech-to-text service from SQLite (`history.db`).
- **Data Flow**:
  - `Handy.get_transcriptions_since(last_id)` retrieves all new transcriptions since the last processed ID in monotonic order.
  - Opens the database in read-only URI mode (`file:{path}?mode=ro`) with a strict 1.5s timeout to prevent locking conflicts with the external Handy process.
- **Key Invariants**:
  - Never writes to or locks the Handy database.
  - Recovers gracefully from locked database errors (`sqlite3.OperationalError: database is locked`) without crashing the voice loop.

### Layer 2: Concurrency & Command Queue (`core/`)
- **Components**: [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py), [`core/queue_manager.py`](file:///c:/Projects/LIGHT/core/queue_manager.py)
- **Role**: Decouples audio ingestion from action execution via a thread-safe producer-consumer model.
- **Data Flow**:
  - **Producer**: Dedicated background thread `_listener_worker` continuously polls `Handy` every 150ms (`POLL_INTERVAL`), debounces duplicate utterances via `_normalize_for_dedup()`, and ingests spoken text via `LightLoop.ingest_text()`.
  - **High-Priority Preemption**: `is_explicit_stop_or_cancel()` checks for `"Stop"`, `"Cancel"`, `"Exit"`, or `"Quit"` immediately at ingestion time. If detected, `command_queue.cancel_event.set()` is invoked immediately (<5ms preemption) and a high-priority `STOP` request is queued.
  - **Consumer**: The main loop drains `CommandRequest` items sequentially via `execute_next_queued()` (or `execute_next_queued_async()`).
  - **Failure Propagation**: If a command fails, `cancel_dependent_after_failure()` automatically purges any subsequent dependent actions in the same compound sequence (e.g. failing `SEARCH` skips subsequent `CLICK_RESULT`).

### Layer 3: Decision Engine & Brain (`brain/`)
- **Components**: [`brain/laya.py`](file:///c:/Projects/LIGHT/brain/laya.py), [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py), [`brain/llm.py`](file:///c:/Projects/LIGHT/brain/llm.py)
- **Role**: Translates natural language utterances into an ordered list of typed `Command` objects (`Action`, `target`).
- **Multi-Tier Resolution Order**:
  1. **Multi-Step Deterministic Parser** (`parse_multi_command`): Splits clauses on conjunctions (`"and"`, `","`, `"then"`) and parses sequential commands (<1ms).
  2. **Single-Step Deterministic Parser** (`parse_deterministic_command`): Regex and vocabulary matching for direct actions, keyboard shortcuts, media controls, and navigation (<1ms).
  3. **Local Qwen3 1.7B LLM Planner** (`QwenPlanner` via Ollama): Invoked for complex, multi-clause natural language search and browsing requests. Output is normalized and strictly validated via `normalize_command_plan()`.
  4. **Complex Search Fallback** (`parse_complex_fallback`): Rule-based parser handling complex natural search syntax when Ollama is offline or disabled.
  5. **Laya Intent Classifier** (`Laya.agent.predict`): Machine-learning fallback for ambiguous single-phrase utterances, guarded by strict prefix validation (e.g. casual speech is rejected; single unrelated words are blocked).

### Layer 4: State & Ownership Management (`core/state.py`)
- **Component**: [`core/state.py`](file:///c:/Projects/LIGHT/core/state.py)
- **Role**: Tracks active desktop and browser context across multi-utterance interactions.
- **State Attributes**:
  - `current_app`: Name of active Windows application (`"notepad"`, `"calculator"`, `"browser"`).
  - `current_site`: Canonical active website shortcut (`"youtube"`, `"google"`, `"github"`).
  - `current_url`: Full active URL in the browser.
  - `last_search_query`: Query text from the most recent search action.
  - `browser_ownership`: Active browser session owner (`BrowserOwnership.NONE`, `LIGHT`, or `AGENT`).
  - `recent_history`: Sliding window of recently executed commands.
- **Planning Isolation**:
  - `LightState.clone_for_planning()` creates an isolated state clone used during multi-command parsing to track projected intermediate state changes without mutating the live state before execution.

### Layer 5: Execution Engine (`core/executor.py`)
- **Component**: [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py)
- **Role**: Dispatches parsed commands to appropriate subsystem controllers.
- **Subsystem Routing**:
  - **Desktop Applications** (`computer/apps.py`): Launch, focus, and close desktop programs.
  - **Window & Focus** (`computer/screen.py`): Inspect active foreground windows and process names.
  - **Keyboard & Typing** (`computer/keyboard.py`): Focus-aware typing and system hotkeys.
  - **Mouse Controls** (`computer/mouse.py`): Relative nudges, DPI-aware coordinates, physical clicks.
  - **Deterministic Browser** (`browser/browser.py`): Playwright-controlled Chromium session.
  - **Autonomous Web Agent** (`browser/agent.py`): Subordinate Browser Use task runner.

---

## 3. Browser Ownership Model

To prevent session corruption and event collisions between deterministic Playwright automation and autonomous Browser Use execution, LIGHT enforces a strict three-state ownership model:

```text
                  ┌──────────────────┐
                  │       NONE       │
                  │ (Browser Closed) │
                  └─────────┬────────┘
                            │
               ┌────────────┴────────────┐
               ▼                         ▼
      Playwright Action          AGENT_TASK Started
               │                         │
               ▼                         ▼
     ┌──────────────────┐       ┌──────────────────┐
     │      LIGHT       │       │      AGENT       │
     │ Playwright Active│       │ Browser Use Runs │
     └─────────┬────────┘       └─────────┬────────┘
               │                         │
               │  [Handed to Agent]      │
               ├────────────────────────►│
               │                         │
               │  [Returned to LIGHT]    │
               │◄────────────────────────┤
               │                         │
               └────────────┬────────────┘
                            │
                      STOP / Close
                            │
                            ▼
                  ┌──────────────────┐
                  │       NONE       │
                  └──────────────────┘
```

### Ownership Rules
1. **`BrowserOwnership.LIGHT`**:
   - Active when LIGHT executes deterministic browser actions (`OPEN_URL`, `SEARCH`, `CLICK_RESULT`, `CLICK_ELEMENT`, `SCROLL`).
   - Browser operations run via the primary `BrowserController` instance.
2. **`BrowserOwnership.AGENT`**:
   - Active exclusively during `AGENT_TASK` execution.
   - Browser Use creates and manages its own isolated browser session.
   - The primary Playwright session is locked to prevent command interleaving.
3. **Desktop Concurrency**:
   - While `BrowserOwnership.AGENT` is active, normal desktop commands (`OPEN_APP`, `HOTKEY`, `TYPE`, `MEDIA_*`) continue to execute unimpeded. The user can switch to Notepad or adjust volume while an agent browses in the background.
4. **Emergency STOP Reset**:
   - If `"Stop"` or `"Cancel"` is uttered while `AGENT` ownership is active, `executor.browser_agent.cancel()` aborts the agent and ownership resets immediately to `BrowserOwnership.NONE`.

---

## 4. Search Ranking & Semantic Verification Pipeline

```text
User Request: "click official repository" (Context: LangGraph)
                          │
                          ▼
            browser/browser.py::locate_element_in_viewport
  ┌────────────────────────────────────────────────────────┐
  │ 1. Collect all visible anchor and clickable elements   │
  │ 2. Compute Candidate Feature Score:                    │
  │    + Domain match (e.g. github.com)            : +120  │
  │    + Exact repo slug match (langchain-ai/...)  : +80   │
  │    + Target semantic match (repository/docs)   : +50   │
  │    + Query tokens in text or href              : +30   │
  │    - Unrelated / social link penalty           : -100  │
  │ 3. Score Threshold Validation (Min Score >= 20)        │
  └───────────────────────┬────────────────────────────────┘
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
   Score < 20                        Score >= 20
         │                                 │
         ▼                                 ▼
  Fail Safely                       Dispatch Physical Click
(Never blindly click #1)                   │
                                           ▼
                            browser/browser.py::verify_destination
                          ┌────────────────────────────────────────┐
                          │ 1. Wait for navigation commit/idle     │
                          │ 2. Verify destination URL and domain   │
                          │ 3. Check page title and visible text   │
                          │ 4. Require query tokens in destination │
                          └──────────────────┬─────────────────────┘
                                             │
                            ┌────────────────┴────────────────┐
                            ▼                                 ▼
                     Verification Match               Mismatch Detected
                            │                                 │
                            ▼                                 ▼
                     Report [EXECUTOR] OK              Raise RuntimeError
                                                    (Refuse false success)
```

---

## 5. Component Breakdown & Boundaries

| Component | File Path | Inbound Dependencies | Outbound Dependencies | Key Invariants | AI Agent Cautions |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Handy Reader** | [`voice/handy.py`](file:///c:/Projects/LIGHT/voice/handy.py) | `core/loop.py` | `sqlite3`, `config.py` | Read-only SQLite mode; monotonic ID ordering. | Do not write to `history.db` or alter table schemas. |
| **Command Queue** | [`core/queue_manager.py`](file:///c:/Projects/LIGHT/core/queue_manager.py) | `core/loop.py` | `threading`, `time` | STOP preemption <5ms; priority ordering; thread-safe. | Never remove `cancel_event` or bypass queue locks. |
| **Voice Loop** | [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py) | `main.py` | `voice/handy.py`, `core/queue_manager.py`, `core/executor.py` | Listener thread decoupled from consumer execution. | Never execute blocking actions inside `_listener_worker`. |
| **Decision Engine** | [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py) | `brain/laya.py` | `brain/commands.py`, `config.py` | Multi-step fast path <1ms; strictly typed `Command` output. | Do not add network calls or slow operations to deterministic parsing. |
| **LLM Planner** | [`brain/llm.py`](file:///c:/Projects/LIGHT/brain/llm.py) | `brain/laya.py` | `urllib`, `config.py` | Local Ollama only; timeout-guarded; plan normalized. | Never add cloud API keys; sanitize `/no_think` tokens. |
| **Browser Controller**| [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `core/executor.py` | `playwright`, `config.py` | Single active session; DPI screen conversion; semantic verification. | Never fall back to blind result #1 clicking on named targets. |
| **Browser Agent** | [`browser/agent.py`](file:///c:/Projects/LIGHT/browser/agent.py) | `core/executor.py` | `browser_use`, `ollama` | Async-safe (`execute_task`); immediate STOP preemption. | Do not call `asyncio.run()` within an existing event loop. |
| **App Controller** | [`computer/apps.py`](file:///c:/Projects/LIGHT/computer/apps.py) | `core/executor.py` | `subprocess`, `psutil` | Clean process tracking; no destructive `taskkill` on shared browsers. | Protect system processes and launcher PID trees. |
| **Screen Controller**| [`computer/screen.py`](file:///c:/Projects/LIGHT/computer/screen.py) | `core/executor.py` | `pygetwindow`, `ctypes` | High-DPI awareness; foreground window verification. | Always verify foreground before typing text. |
| **State Tracker** | [`core/state.py`](file:///c:/Projects/LIGHT/core/state.py) | All subsystems | `brain/commands.py` | Thread-safe locks; explicit ownership transitions. | Use `clone_for_planning()` during multi-command planning. |
