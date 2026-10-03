# LIGHT — Feature Inventory & Implementation Status

> **Inventory Status**: All entries marked **`[x]`** are verified against the active codebase and covered by automated tests. Entries marked **`[ ]`** represent planned future enhancements.

---

## 1. Voice & Speech-to-Text Subsystem (`voice/`)

| Feature | Status | Description | Example Spoken Input | Source Files | Test Files |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **Continuous Audio Ingestion** | `[x]` | Reads speech-to-text transcriptions from local Handy SQLite database (`history.db`) in read-only URI mode. | *(Continuous ambient speech)* | [`voice/handy.py`](file:///c:/Projects/LIGHT/voice/handy.py) | `tests/test_voice.py` |
| **Monotonic ID Polling** | `[x]` | Tracks `transcription_history.id` to guarantee zero dropped utterances during fast speech. | *(Automatic background loop)* | [`voice/handy.py`](file:///c:/Projects/LIGHT/voice/handy.py) | `tests/test_voice.py` |
| **Locked Database Resilience** | `[x]` | Gracefully catches `sqlite3.OperationalError: database is locked` and recovers without dropping state. | *(Handy writing during read)* | [`voice/handy.py`](file:///c:/Projects/LIGHT/voice/handy.py) | `tests/test_voice.py` |
| **Utterance Debouncing** | `[x]` | Debounces immediate duplicate transcriptions within cooldown window (1.0s) for non-repeatable actions. | *(Duplicate voice transcription)*| [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py) | `tests/test_voice.py` |
| **Direct Local Whisper Integration** | `[ ]` | Standalone in-process Whisper VAD pipeline without requiring external Handy installation. | *(Planned standalone mode)* | — | — |

---

## 2. Intent Parsing & Decision Engine (`brain/`)

| Feature | Status | Description | Example Spoken Input | Source Files | Test Files |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **Deterministic Fast Path** | `[x]` | Regex and grammatical parsing of 25+ discrete actions in <1ms without LLM overhead. | `"Open YouTube"`, `"Scroll down"` | [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py) | `tests/test_laya.py`, `tests/test_new_features.py` |
| **Multi-Command Parsing** | `[x]` | Splits compound sentences on conjunctions (`and`, `then`, `,`) into sequential `Command` objects. | `"Open GitHub, search for LangGraph and open the official repository."` | [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py) | `tests/test_queue_and_llm.py`, `tests/test_new_features.py` |
| **Contextual Continuations** | `[x]` | Context-aware resolution of follow-up utterances using active site and query state. | `"Official repository"`, `"First result"` | [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py) | `tests/test_new_features.py` |
| **Casual Speech Rejection** | `[x]` | Ignores conversational phrases and unrelated single words without raising spurious errors. | `"How are you?"`, `"Cricket"`, `"That's interesting"` | [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py), [`brain/laya.py`](file:///c:/Projects/LIGHT/brain/laya.py) | `tests/test_laya.py` |
| **Laya Strict Safety Guard** | `[x]` | ML intent classification fallback restricted to strict safety choice sets with prefix validation. | `"Click Subscribe"` | [`brain/laya.py`](file:///c:/Projects/LIGHT/brain/laya.py) | `tests/test_laya.py` |

---

## 3. Local Language Model Planning (`brain/llm.py`)

| Feature | Status | Description | Example Spoken Input | Source Files | Test Files |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **Local Ollama Integration** | `[x]` | Uses local Qwen3 1.7B (`http://127.0.0.1:11434`) for complex, multi-clause natural language search planning. | `"Find a beginner Python tutorial on YouTube and open the most relevant result"` | [`brain/llm.py`](file:///c:/Projects/LIGHT/brain/llm.py) | `tests/test_queue_and_llm.py` |
| **Deterministic Plan Normalization** | `[x]` | Sanitizes LLM outputs, injects missing prerequisite URLs, and validates action sequences. | *(Any planned LLM sequence)* | [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py) | `tests/test_queue_and_llm.py` |
| **No-Think Token Filtering** | `[x]` | Strips `<think>` tags and `/no_think` formatting noise from small model output streams. | *(Model reasoning output)* | [`brain/llm.py`](file:///c:/Projects/LIGHT/brain/llm.py) | `tests/test_queue_and_llm.py` |
| **Offline Fallback Routing** | `[x]` | Seamlessly falls back to deterministic complex rule parsing if Ollama is unreachable. | *(Complex search during offline)* | [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py) | `tests/test_queue_and_llm.py` |

---

## 4. Desktop & Application Automation (`computer/`)

| Feature | Status | Description | Example Spoken Input | Source Files | Test Files |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **Application Launch & Close** | `[x]` | Launches and cleanly closes supported Windows apps (`Notepad`, `Calculator`, `Brave`, `Chrome`). | `"Open Notepad"`, `"Close Notepad"` | [`computer/apps.py`](file:///c:/Projects/LIGHT/computer/apps.py) | `tests/test_computer.py` |
| **Process Tree Protection** | `[x]` | Protects launcher shim PIDs and unrelated user instances during application close. | *(Closing LIGHT browser)* | [`computer/apps.py`](file:///c:/Projects/LIGHT/computer/apps.py) | `tests/test_computer.py` |
| **Foreground Window Verification**| `[x]` | Inspects active foreground window and process title before executing typing actions. | *(Pre-typing verification)* | [`computer/screen.py`](file:///c:/Projects/LIGHT/computer/screen.py) | `tests/test_new_features.py` |
| **Keyboard Typing & Hotkeys** | `[x]` | Types text with focus checks; executes OS key combinations (`ctrl+c`, `alt+tab`). | `"Type Hello World"`, `"Press enter"`, `"Hotkey ctrl+v"` | [`computer/keyboard.py`](file:///c:/Projects/LIGHT/computer/keyboard.py) | `tests/test_computer.py`, `tests/test_new_features.py` |
| **Media Playback Controls** | `[x]` | Controls media playback, volume, mute, and video seek offsets. | `"Pause video"`, `"Play"`, `"Mute"`, `"Volume up"`, `"Go back 10 seconds"` | [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py) | `tests/test_new_features.py` |
| **Window State Management** | `[x]` | Minimizes, maximizes, restores, and switches desktop application windows. | `"Minimize window"`, `"Maximize window"`, `"Switch window"` | [`computer/screen.py`](file:///c:/Projects/LIGHT/computer/screen.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py) | `tests/test_new_features.py` |
| **Precision Mouse Control** | `[x]` | Relative pixel nudges, screen anchor homing, semantic distances, and physical clicking. | `"Move mouse 100 pixels right"`, `"Move mouse slightly up"`, `"Click"` | [`computer/mouse.py`](file:///c:/Projects/LIGHT/computer/mouse.py) | `tests/test_computer.py` |
| **Arbitrary Windows App Launch**| `[ ]` | Dynamic start menu discovery for launching any unindexed installed Windows application. | `"Open Spotify"`, `"Open Slack"` | — | — |

---

## 5. Deterministic Browser Automation (`browser/browser.py`)

| Feature | Status | Description | Example Spoken Input | Source Files | Test Files |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **Playwright Chromium Engine** | `[x]` | Single-session browser automation using Playwright Chromium with persistent context fallback. | `"Open YouTube"`, `"Go to github.com"` | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_browser.py`, `tests/test_integration_local_browser.py` |
| **Context-Aware Search** | `[x]` | Routes search queries to YouTube (on YouTube), GitHub (on GitHub), or Google default. | `"Search for Coldplay"`, `"Search on GitHub for LangGraph"` | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_browser.py`, `tests/test_new_features.py` |
| **Google CAPTCHA Bypass** | `[x]` | Detects Google `/sorry/` reCAPTCHA pages and automatically switches to DuckDuckGo. | `"Search Google for nature evolution"` | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_browser.py` |
| **DOM Element Detection** | `[x]` | Scans visible viewport DOM, skips hidden duplicates, scrolls element into view, and clicks. | `"Click Subscribe"`, `"Click Ask about files"` | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_integration_local_browser.py` |
| **Result Selection by Number** | `[x]` | Clicks Nth search result or video entry (`1st` through `5th`). | `"Click the first result"`, `"Select second video"` | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_integration_local_browser.py` |
| **Target Candidate Ranking** | `[x]` | Multi-feature scoring (+120 domain, +80 slug, +50 target) prioritizing official links over math papers. | `"Click official repository"`, `"Open official docs"` | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_new_features.py` |
| **Semantic Destination Verification**| `[x]` | Inspects destination page URL, title, and visible text to verify match with target query. | *(Post-click verification)* | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_new_features.py` |
| **Inclusive Text Range Copying**| `[x]` | Copies inclusive text between start and end boundaries with casing preservation and highlight cleanup. | `"Copy from I know this one will hurt till demolish"` | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_integration_local_browser.py` |
| **Page Reading & Navigation** | `[x]` | Reads page title, visible text content, scrolls up/down, navigates back/forward/refresh. | `"Read title"`, `"Read page"`, `"Scroll down"`, `"Go back"` | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_browser.py`, `tests/test_integration_local_browser.py` |

---

## 6. Autonomous Web Agent (`browser/agent.py`)

| Feature | Status | Description | Example Spoken Input | Source Files | Test Files |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **Browser Use Ollama Agent** | `[x]` | Autonomous multi-step browsing agent powered by Browser Use and local Qwen3 1.7B via Ollama. | `"Research 3 Python AI agent frameworks and compare them"` | [`browser/agent.py`](file:///c:/Projects/LIGHT/browser/agent.py) | `tests/test_new_features.py` |
| **Autonomous Intent Detection**| `[x]` | Distinguishes open-ended research/summarization goals from single DOM element lookups. | `"Find official GitHub page for Python and tell me its URL"` | [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py) | `tests/test_new_features.py` |
| **Event-Loop-Safe Execution** | `[x]` | Native async task runner (`execute_task`) compatible with LIGHT's active event loop (no `asyncio.run()` crash).| *(Agent execution in async loop)* | [`browser/agent.py`](file:///c:/Projects/LIGHT/browser/agent.py) | `tests/test_new_features.py` |
| **Immediate Agent STOP Abort** | `[x]` | Immediately aborts active Browser Use exploration loop when user utters `"Stop"` or `"Cancel"`. | `"Stop"` *(during research)* | [`browser/agent.py`](file:///c:/Projects/LIGHT/browser/agent.py) | `tests/test_new_features.py` |
| **Browser Ownership Model** | `[x]` | Isolates Browser Use (`AGENT`) from Playwright (`LIGHT`), preventing session collisions. | *(Handover & return logging)* | [`core/state.py`](file:///c:/Projects/LIGHT/core/state.py), [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py) | `tests/test_new_features.py` |
| **Managed Background Worker**| `[x]` | Dispatches `AGENT_TASK` to dedicated `LIGHT-AgentWorker` thread, returning `OK` immediately to keep consumer loop responsive. | *(Agent task background execution)* | [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py) | `tests/test_new_features.py` |
| **Duplicate Agent Protection**| `[x]` | Rejects new `AGENT_TASK` invocations (`REJECTED`) when an agent worker is already actively running. | *(Second agent request)* | [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py) | `tests/test_new_features.py` |
| **Concurrent Command Execution**| `[x]` | Desktop commands (`Open Notepad`, hotkeys) and normal browser actions execute unimpeded while agent runs in background. | `"Open Notepad"`, `"Volume up"` *(during research)* | [`core/executor.py`](file:///c:/Projects/LIGHT/core/executor.py) | `tests/test_new_features.py` |

---

## 7. Safety, Preemption & System Reliability

| Feature | Status | Description | Example Spoken Input | Source Files | Test Files |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **Emergency STOP Preemption** | `[x]` | High-priority preemption detecting STOP in <5ms and setting cancellation flags across all workers. | `"Stop"`, `"Cancel"`, `"Quit"`, `"Exit"` | [`core/loop.py`](file:///c:/Projects/LIGHT/core/loop.py), [`core/queue_manager.py`](file:///c:/Projects/LIGHT/core/queue_manager.py) | `tests/test_queue_and_llm.py`, `tests/test_new_features.py` |
| **Dependent Action Cancellation**| `[x]` | Automatically cancels remaining dependent actions in a compound queue if a prerequisite step fails. | *(Search failure cancels click)*| [`core/queue_manager.py`](file:///c:/Projects/LIGHT/core/queue_manager.py) | `tests/test_queue_and_llm.py` |
| **Single-Instance Enforcement** | `[x]` | Detects and terminates stale background `main.py` processes on Windows startup via PID tracking. | *(Process startup)* | [`main.py`](file:///c:/Projects/LIGHT/main.py) | `tests/test_windows_smoke.py` |
| **High-DPI Coordinate Mapping** | `[x]` | Converts browser viewport CSS coordinates to physical screen pixels with DPI awareness. | *(DOM element click)* | [`browser/browser.py`](file:///c:/Projects/LIGHT/browser/browser.py) | `tests/test_browser.py` |
