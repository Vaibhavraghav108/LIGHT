# LIGHT — Voice-Controlled Windows & Browser Automation Assistant

[![LIGHT CI](https://github.com/Vaibhavraghav108/LIGHT/actions/workflows/tests.yml/badge.svg)](https://github.com/Vaibhavraghav108/LIGHT/actions/workflows/tests.yml)
[![Tests: 123 Passed](https://img.shields.io/badge/Tests-123%20passed-brightgreen.svg)](docs/TESTING.md)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue.svg)](docs/PRODUCT_SPEC.md)
[![Architecture: Local--First](https://img.shields.io/badge/Architecture-Local--First-orange.svg)](docs/ARCHITECTURE.md)

**LIGHT** is a local-first, low-latency, voice-controlled Windows and browser automation assistant. It listens continuously to speech-to-text transcriptions from the local **Handy** desktop engine, parses commands through a multi-tier hybrid brain (deterministic fast path in <1ms, local Qwen3 1.7B planning via Ollama, and strict prefix-guarded Laya classification), and executes verified actions across Windows desktop applications, physical mouse/keyboard controls, deterministic Playwright browser automation, and an isolated Browser Use autonomous agent.

```text
[Handy SQLite DB] ──► [Thread-Safe CommandQueue] ──► [Hybrid Brain (<1ms Fast Path + Qwen3 1.7B)]
                                                              │
                    ┌─────────────────────────────────────────┴────────────────────────────┐
                    ▼                                                                      ▼
     [Computer Controllers]                                                      [Browser Controllers]
  ├── Desktop Apps (Notepad, Calc)                                             ├── Playwright Chromium (LIGHT)
  ├── Screen & Focus Observation                                               │   └── Result Ranking & Verification
  └── Keyboard, Mouse & Media Keys                                             └── Browser Use Agent (AGENT)
```

---

## Key Capabilities

- **Ambient Continuous Listening**: Dedicated non-blocking listener thread (`core/loop.py`) continuously ingests speech from Handy SQLite `history.db` at 150ms intervals with monotonic ID ordering and duplicate debouncing.
- **Sub-Millisecond Deterministic Fast Path**: Instantaneous regex and grammatical parsing (<1ms) for common actions (`"open youtube"`, `"scroll down"`, `"press enter"`, `"mute"`).
- **Local Small Language Model (Qwen3 1.7B via Ollama)**: Plans complex natural language search and browsing workflows offline without cloud API fees or external latency.
- **Autonomous Web Research Agent (Browser Use)**: Isolated agent mode for open-ended multi-step exploration and synthesis (`"research 3 Python frameworks and compare them"`).
- **Strict Browser Ownership Model**: Formally transitions between `NONE`, `LIGHT`, and `AGENT` ownership, preventing controller collisions while allowing concurrent desktop commands during web tasks.
- **Target Candidate Ranking**: Multi-feature link scoring (+120 domain, +80 slug, +50 target) prioritizing official repositories and primary project documentation over ads and irrelevant links.
- **Semantic Destination Verification**: Validates landing URLs, domains, and title semantics post-navigation, refusing to report false success.
- **Immediate STOP Preemption (<5ms)**: Instantaneous cancellation of in-flight wait loops, active browser agents, and queued actions when the user says `"Stop"`, `"Cancel"`, or `"Quit"`.
- **Focus-Aware Desktop Typing**: Verifies foreground window and application identity before keystrokes are typed, preventing accidental input leakage.

---

## Documentation Suite

Comprehensive system documentation is organized under [`docs/`](docs/):

| Document | Purpose |
| :--- | :--- |
| **[`AGENTS.md`](AGENTS.md)** | **Primary AI developer contract**, operational invariants, modification workflows, and forbidden behaviors. |
| **[`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md)** | Functional and non-functional product requirements, user experience, and core boundaries. |
| **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)** | Complete technical architecture, component dependencies, ownership lifecycles, and data flows. |
| **[`docs/FEATURES.md`](docs/FEATURES.md)** | Subsystem feature matrix, verified commands, source files, and test mapping. |
| **[`docs/CHANGELOG.md`](docs/CHANGELOG.md)** | Human-readable milestone evolution history reconstructed from Git commits. |
| **[`docs/DECISIONS.md`](docs/DECISIONS.md)** | Architecture Decision Records (ADRs) detailing the rationale behind critical engineering decisions. |
| **[`docs/ROADMAP.md`](docs/ROADMAP.md)** | Completed milestones, current hardening priorities, and planned future improvements. |
| **[`docs/TESTING.md`](docs/TESTING.md)** | Multi-tier test suite architecture, execution commands, and critical end-to-end verification workflows. |
| **[`docs/SAFETY.md`](docs/SAFETY.md)** | Operational safety invariants, interruption protocols, and verification rules. |
| **[`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)** | Catalog of historical bugs, root causes, permanent fixes, and regression tests. |

---

## Windows Setup & Installation

### Prerequisites
1. **Windows 10 / 11** (64-bit) with High-DPI display awareness.
2. **Python 3.10+** (verified on Python 3.12).
3. **Handy Desktop App**: For continuous local voice dictation writing to `%APPDATA%\com.pais.handy\history.db`.
4. **Ollama**: Running locally with `qwen3:1.7b` for complex natural language planning and autonomous agent tasks:
   ```powershell
   ollama run qwen3:1.7b
   ```

### 1. Environment Setup & Dependencies
From PowerShell in the project root:

```powershell
python -m venv lightenv
.\lightenv\Scripts\pip.exe install --upgrade pip
.\lightenv\Scripts\pip.exe install -r requirements.txt
.\lightenv\Scripts\pip.exe install browser-use==0.13.10 ollama==0.6.1
```

### 2. Install Playwright Chromium Browser
```powershell
$env:PLAYWRIGHT_BROWSERS_PATH="c:\Projects\LIGHT\.playwright-browsers"
.\lightenv\Scripts\playwright.exe install chromium
```

### 3. Run LIGHT
```powershell
.\lightenv\Scripts\python.exe main.py
```
Say **"Stop"**, **"Stop light"**, **"Exit"**, or **"Quit"** (or press `Ctrl+C`) to cleanly exit.

---

## Running Tests

See [`docs/TESTING.md`](docs/TESTING.md) for full testing documentation.

### Full Discovery Test Suite (127 Tests)
```powershell
.\lightenv\Scripts\python.exe -m unittest discover -s tests -v
```
**Baseline Result**: `Ran 127 tests in ~27s` $\to$ `OK (skipped=4)` (123 executed and passed; 4 opt-in Windows host smoke checks skipped by default).

### Static Compilation Syntax Check
```powershell
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py voice brain computer browser core utils tests
```

### Opt-In Windows Host Smoke Tests
```powershell
$env:LIGHT_RUN_WINDOWS_SMOKE="1"; .\lightenv\Scripts\python.exe -m unittest tests/test_windows_smoke.py -v
```

---

## Repository Structure

```text
LIGHT/
├── AGENTS.md                    # Core operating contract for AI coding assistants
├── README.md                    # Developer-facing project overview
├── config.py                    # Central configuration and environment settings
├── main.py                      # Single-instance application entry point
├── requirements.txt             # Primary Python dependencies
│
├── brain/                       # Hybrid Decision Engine
│   ├── commands.py              # Action enum, Command dataclasses
│   ├── decision.py              # Deterministic multi-step & single-step parsers
│   ├── decisions.py             # Backward-compatible re-exports
│   ├── laya.py                  # Multi-tier orchestrator & Laya classifier
│   └── llm.py                   # Local Qwen3 1.7B planner via Ollama
│
├── browser/                     # Browser Automation
│   ├── agent.py                 # Subordinate Browser Use autonomous agent
│   └── browser.py               # Deterministic Playwright Chromium controller
│
├── computer/                    # Windows Desktop Subsystem
│   ├── apps.py                  # Application lifecycle (Notepad, Calc, etc.)
│   ├── keyboard.py              # Keystrokes, typing, hotkeys
│   ├── mouse.py                 # Precision cursor homing & physical clicking
│   └── screen.py                # Window focus observation & window controls
│
├── core/                        # Concurrency & Execution Core
│   ├── executor.py              # Action dispatcher, ownership routing & background agent worker
│   ├── loop.py                  # Dedicated background listener & consumer loop
│   ├── queue_manager.py         # Thread-safe CommandQueue with STOP preemption
│   └── state.py                 # LightState & BrowserOwnership lifecycle
│
├── docs/                        # Complete Engineering Memory System
│   ├── ARCHITECTURE.md          # Technical architecture & component specs
│   ├── CHANGELOG.md             # Categorized milestone evolution history
│   ├── DECISIONS.md             # Architecture Decision Records (ADRs)
│   ├── FEATURES.md              # Complete subsystem feature inventory
│   ├── PRODUCT_SPEC.md          # Requirements, UX, and operational boundaries
│   ├── ROADMAP.md               # Milestones, active hardening & future plans
│   ├── SAFETY.md                # Safety invariants, preemption, verification
│   ├── TESTING.md               # Test suite guide & critical workflows
│   └── TROUBLESHOOTING.md       # Historical defects, root causes & fixes
│
├── logs/                        # Runtime execution logs (tracked via .gitkeep)
│   └── .gitkeep
│
├── tests/                       # Multi-Tier Automated Test Suite
│   ├── test_browser.py          # Browser navigation & reCAPTCHA tests
│   ├── test_computer.py         # Desktop app, keyboard, and mouse tests
│   ├── test_integration_local_browser.py # Real headless Playwright DOM tests
│   ├── test_laya.py             # Deterministic parser & safety guards
│   ├── test_new_features.py     # Reliability, ranking, verification, agent
│   ├── test_queue_and_llm.py    # Producer-consumer queue & Qwen planner
│   ├── test_voice.py            # SQLite reader & voice debouncing tests
│   └── test_windows_smoke.py    # Opt-in host Windows smoke tests
│
├── utils/                       # Shared Utilities
│   └── logger.py                # Standardized prefix logger ([LIGHT], [PERF], etc.)
│
└── voice/                       # Speech Ingestion
    ├── handy.py                 # SQLite reader for Handy history.db
    └── handy_voice.py           # Compatibility alias
```
