# LIGHT Architecture

This is the canonical runtime architecture. The `v0.5.0` release baseline is
commit `8524bde`; the provider/model milestone described below is implemented
on its feature branch and retains that runtime pipeline.

## Runtime map

```text
selected STT transcript source (Handy or custom feed)
        |
        v
VoiceInputProvider -- read-only transcripts --> LIGHT-VoiceListener thread
        |                                           |
        | unavailable provider: idle                v
        |                                      LightLoop.ingest_text
        |                                           |
        |                              explicit STOP sets cancel_event
        |                                           |
        +-------------------------------------------v
                                      CommandQueue (STOP first, normal FIFO)
                                                   |
                                                   v
                                      Laya / decision orchestration
                          +------------------------+--------------------+
                          |                        |                    |
                  deterministic parser      selected AI provider  guarded Laya
                          +------------------------+--------------------+
                                                   |
                                        validated List[Command]
                                                   |
                                                   v
                                      LightLoop consumer / Executor
                          +------------------------+--------------------+
                          |                        |                    |
                  desktop controllers       BrowserController    LIGHT-AgentWorker
                  via PlatformController     Playwright session    Browser Use session
                          |                        |                    |
                          +------------------------+--------------------+
                                                   |
                                      verification + LightState
```

## Threads, loops, and sessions

| Runtime unit | Owner | Work | Shutdown/cancellation |
| --- | --- | --- | --- |
| Main thread | `main.py` / `LightLoop.run()` | sequential queue consumption and ordinary execution | loop STOP/finally closes executor and browser |
| `LIGHT-VoiceListener` | `core/loop.py` | polls the provider every `POLL_INTERVAL` (default 150ms), debounces, ingests | daemon thread; loop stop flag; joined up to 1s |
| `LIGHT-AgentWorker` | `core/executor.py` | one synchronous Browser Use task with its own asyncio loop | agent `stop()`, shared event, task cancellation; bounded joins (200ms STOP, configurable close) |
| Browser Use asyncio loop | `browser/agent.py` | isolated autonomous agent and 10ms cancellation poller | task cancel plus `Browser.close()` in `finally` |
| Playwright session | `browser/browser.py` | deterministic Chromium context/page | `BrowserController.close()` |

The agent worker is a daemon thread. Bounded join protects command latency, but
if a dependency ignores cancellation the thread can outlive the join window.
That is a known limitation, not a guarantee of immediate process termination.

## Voice and queue flow

`get_voice_provider()` constructs exactly the selected `VoiceInputProvider`.
The default local runtime is `HandyVoiceProvider`; a missing Handy database
produces `UnavailableVoiceProvider`. `CustomAPITranscriptProvider` polls a
user-owned transcript-feed API. A failed custom API is not silently replaced by
Handy. Handy queries are read-only and ordered by monotonically increasing IDs.
Provider read errors are handled by the listener without moving the last
successful ID.

The custom transcript-feed contract is:

- `GET {base_url}/v1/transcriptions/latest` returns either an empty object,
  `{"id": 7, "text": "..."}`, or
  `{"transcription": {"id": 7, "text": "..."}}`;
- `GET {base_url}/v1/transcriptions?after_id=7` returns
  `{"transcriptions": [{"id": 8, "text": "..."}]}`;
- IDs are integer, monotonic event IDs; returned batches are sorted before
  ingestion;
- an optional bearer credential is resolved from the configured environment
  variable name.

This is a transcript-event boundary, not an audio API. LIGHT still does not own
microphone capture, VAD, chunking, or direct Whisper inference.

`LightLoop.ingest_text()` performs explicit STOP detection before brain
planning. STOP sets `CommandQueue.cancel_event`, clears queued normal work, and
is inserted at the front. Normal requests remain FIFO. A failed `OPEN_URL` or
`SEARCH` prunes only dependent requests carrying the same utterance text; it
does not cancel another plan's work.

The sub-5ms measurement begins when `ingest_text()` receives a transcript. It
does not cover speech recognition, Handy publication, or the polling interval.

## Decision order and trust boundaries

`Laya.understand_many()` resolves input in this order:

1. deterministic multi-command parser;
2. deterministic single-command parser;
3. optional selected AI provider/model planner;
4. deterministic complex-search fallback;
5. guarded Laya classification.

The backward-compatible `QwenPlanner` orchestration class delegates transport
to an `AIProvider`. Registered choices are local Ollama, local LM Studio,
OpenAI, Claude, Gemini, and a custom OpenAI-compatible endpoint. Ollama remains
the default. Every provider returns content to the same JSON cleanup and action
validation path; changing provider cannot expand the action vocabulary.
Applications are allowlisted, URLs are normalized/validated, STOP requires an
explicit user phrase, and no shell action exists. This reduces—but does not
eliminate—the risk of harmful text targets or browser content. Executor and
browser safety checks remain authoritative.

## Executor and state

`Executor` owns controllers and performs action routing. Most commands verify
their result and then call `LightState.record_command()` plus observation sync.
`WAIT` and `AGENT_TASK` skip synchronous observation to avoid unnecessary
AppleScript/process latency. STOP cancels the agent, attempts a bounded join,
closes the deterministic browser, and records state cleanup.

`LightState` protects mutations with an `RLock`, stores current app/browser,
URL/site/title, recent command history, search context, pending goal, mouse
position, and agent status, and creates `clone_for_planning()` snapshots so a
plan cannot mutate live state before execution.

## Browser sessions and ownership

`BrowserOwnership` is a state signal with values `NONE`, `LIGHT`, and `AGENT`:

- `LIGHT`: the deterministic Playwright session is the relevant owner;
- `AGENT`: an isolated Browser Use worker is active; deterministic commands may
  still use their separate Playwright session, but may not erase this signal;
- `NONE`: no relevant session is active or STOP has cleared state.

The enum is not a mutex and does not serialize the two independent browsers.
Atomic agent admission under `_agent_lock` prevents two agent workers. The
Playwright controller has its own page/context lifecycle and recovery.

Named result handling collects visible anchors, scores query/domain/semantic
signals, physically clicks the selected point, requires a changed active URL,
and verifies URL/title/body semantics. Numeric “first result” requests are
explicit ordinal actions and do not use the named-target confidence promise.

## Platform boundary

High-level desktop controllers depend on `PlatformController`. Windows uses
Win32/ctypes, PowerShell, and `taskkill`; macOS uses AppleScript, `open`, POSIX
process commands, and modifier/scale mappings. `main.py` performs generic
subprocess execution using commands supplied by the platform controller for
single-instance enforcement.

Linux is not supported. The factory's fallback is compatibility behavior, not
a Linux platform implementation.

## Provider and model architecture

`providers/configuration.py` owns typed `STTConfig`, `AIConfig`, and
`ProviderSettings`. Provider, runtime, and model are distinct fields. The
explicit registries do not inspect installed applications and do not auto-pick
a provider. The default user file is `.light/providers.json`, ignored by Git;
`LIGHT_PROVIDER_CONFIG` can redirect it.

`python -m providers` provides four operational surfaces:

- `show` displays selected STT/AI provider, runtime, model, endpoint, and the
  credential environment-variable name without reading its value;
- `status` contacts the selected endpoints and reports availability;
- `models` discovers models from Ollama `/api/tags` or provider model APIs;
- `set-ai` / `set-stt` validate the candidate before atomically replacing the
  configuration file. A failed candidate remains inactive.

AI planning uses standard-library HTTP, so switching providers does not add a
mandatory SDK. Browser Use is already optional and supplies lazy native
wrappers for Ollama, OpenAI-compatible services, OpenAI, Anthropic, and Google.
At startup `main.py` builds one selected AI provider and injects it into both
the planner and autonomous agent so one run cannot observe two configurations.
There is no automatic fallback to another provider/model.

Credentials are resolved from environment variables and are never persisted as
values. Provider exceptions are converted to messages that omit request URLs,
headers, response bodies, and third-party SDK details. OS keychain integration
is not implemented in this milestone.

## Configuration and external dependencies

- Handy is an external local STT/VAD application and SQLite producer.
- Ollama and LM Studio are optional local AI runtimes. Ollama/Qwen3 is the
  default; neither is mandatory when AI planning is disabled or another
  provider is explicitly selected.
- OpenAI, Claude, Gemini, and custom APIs are opt-in and change LIGHT's privacy
  boundary by sending prompts—and for Browser Use, observed web context—to the
  configured service.
- Playwright Chromium is required for deterministic browser automation.
- Browser Use is optional and lazily imported.
- Laya is loaded for the final classifier path.
- PyAutoGUI/Pyperclip drive physical input and clipboard behavior.

Provider selection is read from `.light/providers.json`, with legacy `LLM_*`
and `HANDY_DB_PATH` environment defaults retained for compatibility. General
configuration is read from environment variables and optional untracked
`.env`. Browser Use configuration defaults to `.light_browseruse/`, with its
optional telemetry and cloud sync disabled unless a user explicitly overrides
them.

## Architectural limits

- cancellation coverage is not uniform across every blocking Playwright or OS
  operation;
- browser state is a best-effort observation and can become stale between an OS
  focus change and dispatch;
- coordinate conversion has single-display/high-DPI coverage, not heterogeneous
  mixed-DPI multi-monitor evidence;
- Browser Use output is reported asynchronously through logs/state fields, not
  a dedicated user notification channel;
- provider polling is filesystem/database based; there is no direct audio
  pipeline in LIGHT.
