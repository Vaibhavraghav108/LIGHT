# LIGHT — Voice-Controlled Desktop & Browser Automation Assistant

[![LIGHT CI](https://github.com/Vaibhavraghav108/LIGHT/actions/workflows/tests.yml/badge.svg)](https://github.com/Vaibhavraghav108/LIGHT/actions/workflows/tests.yml)
[![Tests: 147 Passed](https://img.shields.io/badge/Tests-147%20passed-brightgreen.svg)](docs/TESTING.md)
[![Platform: Windows & macOS](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-blue.svg)](docs/PRODUCT_SPEC.md)
[![Architecture: Local--First](https://img.shields.io/badge/Architecture-Local--First-orange.svg)](docs/ARCHITECTURE.md)

**LIGHT** is a local-first, low-latency, voice-controlled desktop and browser automation assistant supporting **Windows** and **macOS**. It ingests speech-to-text transcriptions through an extensible `VoiceInputProvider` architecture (Handy SQLite on Windows/macOS with graceful fallback), parses commands through a multi-tier hybrid brain (deterministic fast path in <1ms, local Qwen3 1.7B planning via Ollama, and strict prefix-guarded Laya classification), and executes verified actions across operating system applications, physical mouse/keyboard controls, deterministic Playwright browser automation, and an isolated Browser Use autonomous agent.

```text
[VoiceInputProvider] ──► [Thread-Safe CommandQueue] ──► [Hybrid Brain (<1ms Fast Path + Qwen3 1.7B)]
 (Handy / Fallback)                                                    │
                      ┌────────────────────────────────────────────────┴────────────────────────────┐
                      ▼                                                                             ▼
          [PlatformController]                                                            [Browser Controllers]
   ├── Windows: Win32, ctypes, PowerShell                                      ├── Playwright Chromium (LIGHT)
   └── macOS: AppleScript, open, POSIX                                         │   └── Result Ranking & Verification
                                                                               └── Browser Use Agent (AGENT)
```

---

## Platform Support Matrix

| Subsystem | Windows (10/11) | macOS (Sonoma/Sequoia) | Status Notes |
| :--- | :--- | :--- | :--- |
| **Hybrid Brain & LLM Planner** | **SUPPORTED** | **SUPPORTED** | Pure Python parsing + local Ollama HTTP REST API. |
| **Playwright Browser Automation** | **SUPPORTED** | **SUPPORTED** | Chromium runs identically on Windows and macOS. |
| **Autonomous Agent (Browser Use)** | **SUPPORTED** | **SUPPORTED** | Isolated session on `LIGHT-AgentWorker` background thread. |
| **Desktop Application Lifecycle** | **SUPPORTED** | **SUPPORTED** | Windows `.exe` / `taskkill` vs macOS `open -a` / AppleScript. |
| **Screen & Window Observation** | **SUPPORTED** | **SUPPORTED** | Win32 DPI & APIs vs macOS AppleScript & Quartz. |
| **Mouse & Keyboard Control** | **SUPPORTED** | **SUPPORTED** | PyAutoGUI with platform modifier mapping (`ctrl` $\to$ `cmd`). |
| **Voice Input Provider** | **SUPPORTED** | **PARTIALLY SUPPORTED** | Native Handy SQLite on Windows. On macOS, Handy is third-party dependent; if missing, reports unavailable provider without crashing. |

---

## Setup & Installation

### Windows Prerequisites
1. **Windows 10 / 11** (64-bit).
2. **Python 3.10+** (verified on Python 3.12).
3. **Handy Desktop App**: For continuous local voice dictation writing to `%APPDATA%\com.pais.handy\history.db`.
4. **Ollama**: Running locally with `qwen3:1.7b`:
   ```powershell
   ollama run qwen3:1.7b
   ```

### macOS Prerequisites
1. **macOS 13+** (Ventura, Sonoma, or Sequoia on Apple Silicon or Intel).
2. **Python 3.10+** (verified on Python 3.12).
3. **Permissions**: Grant your terminal / IDE permissions under *System Settings > Privacy & Security*:
   - **Accessibility**: Required for synthetic keyboard shortcuts and cursor movement.
   - **Screen Recording**: Required for screen capture and element observation.
4. **Ollama**: Running locally with `qwen3:1.7b`:
   ```bash
   ollama run qwen3:1.7b
   ```
5. **Voice Input**: If Handy desktop is installed, LIGHT reads from `~/Library/Application Support/com.pais.handy/history.db`. If Handy is not present, LIGHT gracefully operates with voice listening idle.
6. **macOS PyObjC Frameworks**: `requirements.txt` specifies `pyobjc-core`, `pyobjc-framework-Quartz`, and `pyobjc-framework-Cocoa` using `sys_platform == 'darwin'` markers for PyAutoGUI automation.

### 1. Environment Setup & Dependencies
From PowerShell in the project root:

```powershell
python -m venv lightenv
.\lightenv\Scripts\pip.exe install --upgrade pip
.\lightenv\Scripts\pip.exe install -r requirements.txt
.\lightenv\Scripts\pip.exe install browser-use==0.13.10 ollama==0.6.1
```

LIGHT defaults Browser Use to a repository-local `.light_browseruse/` configuration directory and disables its optional anonymized telemetry and cloud sync. Explicit environment overrides remain available for developers who intentionally opt in.

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

### Full Discovery Test Suite (155 Tests)
```powershell
.\lightenv\Scripts\python.exe -m unittest discover -s tests -v
```
**Baseline Result**: `Ran 155 tests in ~28s` $\to$ `OK (skipped=8)` (147 executed and passed; 8 opt-in host smoke checks skipped by default).

### Static Compilation Syntax Check
```powershell
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py voice brain computer browser core utils tests
```

### Opt-In Windows Host Smoke Tests
```powershell
$env:LIGHT_RUN_WINDOWS_SMOKE="1"; .\lightenv\Scripts\python.exe -m unittest tests/test_windows_smoke.py -v
```

### Opt-In macOS Host Smoke Tests
```bash
LIGHT_RUN_MACOS_SMOKE=1 python -m unittest tests/test_macos_smoke.py -v
```

---

## Repository Structure

```text
LIGHT/
├── AGENTS.md                    # Core operating contract for AI coding assistants
├── README.md                    # Developer-facing project overview
├── config.py                    # Central configuration and cross-platform paths
├── main.py                      # Single-instance application entry point
├── requirements.txt             # Primary Python dependencies with platform markers
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
├── computer/                    # Desktop & Hardware Subsystem
│   ├── apps.py                  # Application lifecycle (Notepad/TextEdit, Calc, etc.)
│   ├── keyboard.py              # Keystrokes, typing, hotkey mappings
│   ├── mouse.py                 # Precision cursor homing & physical clicking
│   ├── screen.py                # Window focus observation & window controls
│   ├── platform_base.py         # Abstract PlatformController base class
│   ├── platform_windows.py      # Windows Win32, ctypes, and PowerShell implementation
│   ├── platform_macos.py        # macOS AppleScript, open, and POSIX implementation
│   └── platform_factory.py      # OS detection and platform controller factory
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
│   ├── test_macos_smoke.py      # Opt-in host macOS smoke tests
│   ├── test_new_features.py     # Reliability, ranking, verification, agent
│   ├── test_platform_macos.py   # Unit tests for macOS platform controller
│   ├── test_queue_and_llm.py    # Producer-consumer queue & Qwen planner
│   ├── test_voice.py            # SQLite reader & voice debouncing tests
│   ├── test_voice_provider.py   # VoiceInputProvider abstraction tests
│   └── test_windows_smoke.py    # Opt-in host Windows smoke tests
│
├── utils/                       # Shared Utilities
│   └── logger.py                # Standardized prefix logger ([LIGHT], [PERF], etc.)
│
└── voice/                       # Speech Ingestion & Providers
    ├── base.py                  # Abstract VoiceInputProvider interface
    ├── handy_provider.py        # SQLite reader for Handy history.db
    ├── unavailable_provider.py  # Graceful fallback when no voice provider is configured
    ├── factory.py               # Voice provider factory with platform awareness
    ├── handy.py                 # Backward-compatible wrapper for Handy
    └── handy_voice.py           # Compatibility alias
```
