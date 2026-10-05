# LIGHT — Local Voice-Controlled Desktop and Browser Automation

[![LIGHT CI](https://github.com/Vaibhavraghav108/LIGHT/actions/workflows/tests.yml/badge.svg)](https://github.com/Vaibhavraghav108/LIGHT/actions/workflows/tests.yml)
[![Tag: v0.5.0](https://img.shields.io/badge/tag-v0.5.0-blue.svg)](https://github.com/Vaibhavraghav108/LIGHT/tree/v0.5.0)

LIGHT is a local-first assistant that turns continuous speech transcriptions
into desktop and browser actions. Frequent commands take a deterministic path;
complex requests can use local Qwen3 1.7B through Ollama; open-ended web goals
can use an isolated Browser Use agent. No cloud LLM or subscription API key is
required.

```text
Handy/local transcript -> listener -> priority queue -> deterministic brain
                                      |              -> local Ollama planner
                                      v
                                  executor -> desktop / Playwright / agent
                                           -> verification -> state
```

## What is in `v0.5.0`

- continuous, read-only Handy SQLite transcript ingestion with an unavailable
  provider fallback;
- deterministic commands, compound plans, guarded Laya fallback, and optional
  local Ollama planning;
- application, keyboard, mouse, window, media, and screen controls through a
  Windows/macOS platform boundary;
- deterministic Playwright navigation, visible-element selection, named-result
  ranking, physical click handling, and destination verification;
- isolated Browser Use research tasks on `LIGHT-AgentWorker`;
- ingestion-time STOP priority, plan-scoped cancellation, browser ownership,
  focus checks, verified clipboard writes, and scoped process shutdown.

Browser automation necessarily connects to requested websites. “Local-first”
means speech ingestion, decision logic, and model inference stay local by
default; it does not mean web requests are offline.

## Platform status

| Area | Windows | macOS |
| --- | --- | --- |
| Parser, queue, state, local Ollama | Automated tests and CI | Automated tests and CI |
| Deterministic browser | CI plus local Playwright integration | CI plus local Playwright integration |
| Desktop platform layer | Unit tests; opt-in host smoke available | Mocked unit tests; opt-in host smoke available |
| Handy voice ingestion | Implemented; requires local Handy database | Path/fallback implemented; Handy and physical voice flow not verified |
| Physical hardware/permissions | Some opt-in Windows smoke evidence | Not recorded for a physical Mac |

CI passing on `macos-latest` is not evidence that Accessibility, Screen
Recording, a microphone, Handy, Retina, or multi-monitor behavior works on a
specific Mac.

## Install

Requirements: Python 3.10+ (CI uses 3.12), a supported Chromium browser, and
optionally Handy for voice and Ollama for local planning/agent work.

Windows PowerShell:

```powershell
python -m venv lightenv
.\lightenv\Scripts\python.exe -m pip install --upgrade pip
.\lightenv\Scripts\python.exe -m pip install -r requirements.txt
.\lightenv\Scripts\python.exe -m pip install browser-use==0.13.10 ollama==0.6.1
.\lightenv\Scripts\python.exe -m playwright install chromium
```

macOS:

```bash
python3 -m venv lightenv
./lightenv/bin/python -m pip install --upgrade pip
./lightenv/bin/python -m pip install -r requirements.txt
./lightenv/bin/python -m pip install browser-use==0.13.10 ollama==0.6.1
./lightenv/bin/python -m playwright install chromium
```

The optional agent installation currently produces a dependency metadata
conflict: `browser-use==0.13.10` requires `click==8.3.3`, while the installed
`huggingface-hub` dependency used by Laya requires `click>=8.4.2,<9`. The tested
CI environment installs successfully, but `pip check` is not clean. Do not
silently resolve this by upgrading packages without compatibility testing.

### Local configuration

Create an untracked `.env` only when overriding defaults. Supported settings
include `HANDY_DB_PATH`, `LAYA_MODEL`, `LLM_ENABLED`, `LLM_PROVIDER`,
`LLM_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT`, `POLL_INTERVAL`,
`DUPLICATE_COOLDOWN_SECONDS`, `BROWSER_TIMEOUT_MS`,
`BROWSER_TYPE_GUARD_MS`, `LIGHT_CDP_PORT`, and
`PLAYWRIGHT_BROWSERS_PATH`. Browser Use defaults to repository-local
`.light_browseruse/` storage with optional telemetry and cloud sync disabled.

Start Ollama when LLM planning or agent work is desired:

```text
ollama run qwen3:1.7b
```

## Run

```powershell
.\lightenv\Scripts\python.exe main.py
```

On macOS use `./lightenv/bin/python main.py` and grant the terminal/IDE the
Accessibility and Screen Recording permissions needed by the actions you use.
If no voice provider is available, LIGHT remains running with voice ingestion
idle instead of crashing.

STOP phrases are checked as soon as a transcript reaches `ingest_text()`.
Cancellation signaling is measured at that boundary; Handy's 150ms polling
interval and STT publication precede it, and some third-party calls are only
cooperatively cancellable.

## Test

```powershell
.\lightenv\Scripts\python.exe -m unittest discover -s tests -v
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py voice brain computer browser core utils tests
```

The tagged `v0.5.0` CI baseline discovers 155 tests: 147 pass and 8 opt-in host
smoke tests skip on both Windows and macOS jobs. Results and local-environment
limitations are documented in [docs/TESTING.md](docs/TESTING.md).

## Documentation

Start with the [documentation map](docs/README.md). The key references are the
[product specification](docs/PRODUCT_SPEC.md),
[architecture](docs/ARCHITECTURE.md), [feature evidence](docs/FEATURES.md),
[safety contract](docs/SAFETY.md), and [engineering contract](AGENTS.md).

Current known limits include physical macOS validation, mixed-DPI
multi-monitor validation, partial cancellation inside third-party calls, the
optional dependency conflict above, fixed app allowlists, and single-page
candidate ranking. See [ROADMAP](docs/ROADMAP.md) for planned work.
