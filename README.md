# LIGHT — Local Voice-Controlled Desktop and Browser Automation

[![LIGHT CI](https://github.com/Vaibhavraghav108/LIGHT/actions/workflows/tests.yml/badge.svg)](https://github.com/Vaibhavraghav108/LIGHT/actions/workflows/tests.yml)
[![Tag: v0.5.0](https://img.shields.io/badge/tag-v0.5.0-blue.svg)](https://github.com/Vaibhavraghav108/LIGHT/tree/v0.5.0)

LIGHT is a local-first assistant that turns continuous speech transcriptions
into desktop and browser actions. Frequent commands take a deterministic path;
complex requests can use a user-selected AI provider/model; open-ended web
goals can use an isolated Browser Use agent. The default remains local Qwen3
1.7B through Ollama. Cloud providers are explicit opt-ins, never requirements.

```text
selected transcript source -> listener -> priority queue -> deterministic brain
                                             |              -> selected AI planner
                                      v
                                  executor -> desktop / Playwright / agent
                                           -> verification -> state
```

## Current branch capabilities

This feature branch builds on the tagged `v0.5.0` baseline and adds the
provider/model milestone; provider selection is not part of the `v0.5.0` tag.

- continuous transcript ingestion from local Handy or an explicit custom
  transcript-feed API, with an unavailable-provider mode;
- deterministic commands, compound plans, guarded Laya fallback, and optional
  provider-neutral planning with Ollama, LM Studio, OpenAI, Claude, Gemini, or
  a custom OpenAI-compatible endpoint;
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
| Parser, queue, state, provider adapters | Automated tests and CI | Automated tests and CI |
| Deterministic browser | CI plus local Playwright integration | CI plus local Playwright integration |
| Desktop platform layer | Unit tests; opt-in host smoke available | Mocked unit tests; opt-in host smoke available |
| Handy voice ingestion | Implemented; requires local Handy database | Path/fallback implemented; Handy and physical voice flow not verified |
| Physical hardware/permissions | Some opt-in Windows smoke evidence | Not recorded for a physical Mac |

CI passing on `macos-latest` is not evidence that Accessibility, Screen
Recording, a microphone, Handy, Retina, or multi-monitor behavior works on a
specific Mac.

## Install

Requirements: Python 3.10+ (CI uses 3.12), a supported Chromium browser, and
optionally Handy for voice and Ollama or LM Studio for local planning/agent
work. Cloud AI providers are optional and require user-supplied credentials.

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

### Provider and model configuration

Provider and model are independent settings. Inspect the active selections
without contacting them:

```powershell
.\lightenv\Scripts\python.exe -m providers show
```

Validate both active providers, or discover models from the active AI endpoint:

```powershell
.\lightenv\Scripts\python.exe -m providers status
.\lightenv\Scripts\python.exe -m providers models
```

Switch the AI model independently of STT. Changes are validated before the
user-owned `.light/providers.json` file is replaced:

```powershell
# Local Ollama
.\lightenv\Scripts\python.exe -m providers set-ai --provider local --runtime ollama --model qwen3:1.7b

# Local LM Studio (OpenAI-compatible server)
.\lightenv\Scripts\python.exe -m providers set-ai --provider local --runtime lm_studio --model your-loaded-model

# OpenAI; set the secret in the environment, never in providers.json
$env:OPENAI_API_KEY="..."
.\lightenv\Scripts\python.exe -m providers set-ai --provider openai --model your-model --credential-env OPENAI_API_KEY
```

AI choices are `local` (runtime `ollama` or `lm_studio`), `gemini`, `openai`,
`claude`, and `custom_api`. For a custom OpenAI-compatible endpoint, pass
`--base-url` and optionally `--credential-env`.

STT choices are `local` and `custom_api`. The supported local runtime is Handy:

```powershell
.\lightenv\Scripts\python.exe -m providers set-stt --provider local --runtime handy --db-path C:\path\to\history.db
```

The custom option is a transcript-event feed, not an audio-upload API; its
contract is documented in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). LIGHT
does not yet own microphone capture, VAD, or direct Whisper inference, so those
capabilities are not claimed.

The provider file is ignored by Git. Credential values are never written to
it: only an environment-variable name such as `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, or `GEMINI_API_KEY` is stored. Current credential storage
uses environment variables; OS keychain integration remains future work.

### Environment overrides

Create an untracked `.env` only when overriding defaults. Supported settings
include `HANDY_DB_PATH`, `LAYA_MODEL`, `LLM_ENABLED`, `LLM_PROVIDER`,
`LLM_MODEL`, `LLM_BASE_URL`, `LLM_TIMEOUT`, `POLL_INTERVAL`,
`DUPLICATE_COOLDOWN_SECONDS`, `BROWSER_TIMEOUT_MS`,
`BROWSER_TYPE_GUARD_MS`, `LIGHT_CDP_PORT`, and
`PLAYWRIGHT_BROWSERS_PATH`. Browser Use defaults to repository-local
`.light_browseruse/` storage with optional telemetry and cloud sync disabled.
The legacy `LLM_*` values remain compatible defaults when no provider file is
present. Explicit `LIGHT_AI_PROVIDER`, `LIGHT_AI_RUNTIME`, `LIGHT_AI_MODEL`,
and `LIGHT_AI_BASE_URL` values do not inherit legacy Ollama-specific defaults.
`LIGHT_PROVIDER_CONFIG` can point to a different provider JSON file.

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
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py providers voice brain computer browser core utils tests
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
