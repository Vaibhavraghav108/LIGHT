# LIGHT Architecture

This is the canonical runtime architecture. The `v0.5.0` release baseline is
commit `8524bde`; provider/model selection is merged at `777c7d9`, and Phase 0/1
planning safety is merged by PR #8 at `6350e38`. The Phase 2 working branch adds
an opt-in typed capability boundary without replacing the executor, providers,
or action vocabulary.

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
        |                              before admission locks / inference
        |                                           |
        +-------------------------------------------v
                         pure deterministic route OR FIFO planning reservation
                                                   |
                       LIGHT-PlanningWorker: existing Laya/decision orchestration
                       selected AI provider -> existing fallback -> guarded Laya
                                                   |
                           validated List[Command] + cancellation generation gate
                                                   |
                           CommandQueue (STOP first, normal FIFO; resolve in place)
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
| `LIGHT-VoiceListener` | `core/loop.py` | polls the provider every `POLL_INTERVAL` (default 150ms), debounces, admits without inference | daemon; event-woken polling waits; shared bounded loop-close join budget |
| `LIGHT-PlanningWorker` | `core/loop.py` | single interpretation lane; at most 64 pending reservations plus one in flight | generation invalidation rejects late results; blocking provider/classifier calls remain cooperative/timeout-bound |
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
planning. STOP signals cancellation before admission locks, increments the queue
generation, clears pending work, and is inserted at the front. Normal requests
remain FIFO: an unknown interpretation reserves its queue position before
inference and later expands into validated commands at that same position.
Later commands wait behind that reservation and are interpreted against ordered
planning context. No admission/queue lock spans inference or browser execution.
A failed `OPEN_URL` or `SEARCH` prunes dependents by task identity; the text-based
compatibility path remains for direct queue callers without task records.

Admission, planner publication, dequeue-to-dispatch, and executor entry reject
cancelled work. STOP does not forcibly terminate synchronous HTTP/classifier
calls; their late results cannot enter the executable queue. A stopped loop
cannot be restarted. `process_text()` still waits for execution; callers needing
responsive ingestion use `ingest_text()` rather than that synchronous wrapper.

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

`Executor` owns controllers and performs action routing. Browser operations
with existing verification checks run those checks before recording state;
other commands can succeed without independent goal verification.
`WAIT` and `AGENT_TASK` skip synchronous observation to avoid unnecessary
AppleScript/process latency. STOP cancels the agent, attempts a bounded join,
closes the deterministic browser, and records state cleanup. Timed-out joins
retain `agent_running` and `BrowserOwnership.AGENT` until worker cleanup exits.

`LightState` protects mutations with an `RLock`, stores current app/browser,
URL/site/title, recent command history, search context, pending goal, mouse
position, and agent status, and creates `clone_for_planning()` snapshots so a
plan cannot mutate live state before execution.

`TaskRecord` is separate from observed and speculative state. Task status is
`accepted`, `running`, `verified`, `succeeded`, `failed`, `ambiguous`, or
`cancelled`. `succeeded` means executor/agent-reported success without independent
verification; `verified` means the existing action-specific verification path
completed, not universal proof of the user's goal. Agent dispatch remains
`running` until the worker reports its result. Phase 0/1 introduced no capability
catalog; Phase 2's opt-in catalog is described below. Neither phase introduces
a context memory system or clarification UI.

## Phase 2: typed capabilities (working branch)

`core/capabilities.py` contains immutable `Capability`, `Argument`, and
`CapabilityPlan` contracts plus a small definition registry. Definitions own
purpose, schema, backend support, risk, confirmation, execution mode,
preconditions, cancellation/timeout expectations, verification, and state-effect
descriptions. Risk and verification are authoritative definition metadata, not
fields an untrusted producer can override. Plans own copied read-only arguments,
task identity/generation, backend, mode, source, and caller confirmation.

| Capability | Existing action/backend | Scope |
| --- | --- | --- |
| `browser.open_site` | `OPEN_URL` / Playwright | explicit HTTP(S) URL without embedded credentials |
| `browser.search` | `SEARCH` / Playwright | explicit Google (default), YouTube, or GitHub query |
| `browser.scroll` | `SCROLL` / Playwright | active controlled browser only; never desktop fallback |
| `browser.activate` | `CLICK_ELEMENT` / Playwright | confirmed named page element; not an ordinal, OS window, or browser tab |
| `browser.read` | not registered | existing reads log content, but Executor returns status rather than structured content |
| `desktop.open_app` | `OPEN_APP` / platform | canonical `notepad` (TextEdit on macOS) or `calculator`; no arbitrary launch |
| `desktop.switch_window` | `SWITCH_WINDOW` / platform | existing window-name matching/focus behavior |
| `keyboard.type` | `TYPE` / foreground keyboard | confirmed existing DOM/OS focus-aware routing, including its fallback |
| `keyboard.press` | `PRESS_KEY` / foreground keyboard | confirmed single-key subset; no chords or shell action |

Registration/lookup/validation are pure CPU/in-memory operations: no backend
imports, model calls, screenshots, execution, process probes, or network I/O.
Availability means a definition/backend is registered, not that a live host,
browser, application, or permission is ready. Registration is initialization-time
only; there is no plugin/discovery framework or runtime replacement of definitions.

`CapabilityAdapter.lower()` validates and produces an existing `Command`.
`LightLoop.ingest_capability()` is a trusted internal/testing entry point that
issues task IDs/generations and enqueues that command in the existing queue.
Consumers revalidate the attached plan/command/generation before calling the
unchanged execution routes, on the same owning thread. Browser preconditions are
checked at dispatch, not by registry lookup. A narrow Executor scroll guard also
rejects a browser closing between the precondition and the action's routing check.

```python
request = loop.ingest_capability("browser.open_site", {"url": "https://example.com"})
loop.execute_next_queued()  # existing sync consumer; async consumer also supported
```

Unknown capabilities/arguments, missing/empty/wrongly typed arguments, invalid
URLs/choices, unsupported backends/modes/sources, mismatched or stale identities,
terminal/cancelled tasks, and absent required confirmation fail closed. Phase 2
plans are single-step: `dependencies` is reserved and must be an empty tuple.
Typed admission rejects unresolved semantic interpretations rather than waiting
or letting an older planning snapshot overwrite typed predictions. Existing
voice commands remain on their existing fast/planning paths, without registry
validation or a changed model/agent selection.

Verification is inherited, not upgraded: browser readiness/click checks do not
prove an arbitrary user goal. Desktop foreground checks retain the existing
`succeeded` status without browser-verification timestamps. Scroll/keyboard actions
have no independent postcondition and must not report `verified`. Timeouts and
interruption remain backend-specific; no universal execution deadline is added.

There is no semantic compiler, dependency scheduler, entity/context resolver,
structured read-result API, vision/accessibility backend, or agent capability yet.

## Browser sessions and ownership

`BrowserOwnership` is a state signal with values `NONE`, `LIGHT`, and `AGENT`:

- `LIGHT`: the deterministic Playwright session is the relevant owner;
- `AGENT`: an isolated Browser Use worker is active; deterministic commands may
  still use their separate Playwright session, but may not erase this signal;
- `NONE`: no relevant session is active after cleanup; not a timed-out join.

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
  configuration file. AI activation requires a non-empty discovered model list,
  the exact configured model, and any explicitly named credential environment
  variable. A failed or unverified candidate remains inactive.

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
them. Legacy Ollama runtime, model, and endpoint defaults apply only when the
legacy/default local Ollama selection is active; an explicit non-Ollama
provider must supply its own model and endpoint where required.

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

## Measurement boundary

`LightLoop.task_status()` exposes the latest 256 transcript-free task snapshots;
queue diagnostic history is bounded to 512 requests. `Laya.metrics`,
`QwenPlanner.metrics`, and `BrowserController.metrics` expose counters and the
latest 256 timing samples. These are in-memory debug/test surfaces, not telemetry
or a UI. They retain no prompts, URLs, provider responses, or credential values.

Task timestamps use `perf_counter()`. Publication timing is optional and requires
the same process's monotonic clock; current Handy/custom adapters do not provide
it. First-visible-effect timing remains unavailable without backend observation
evidence; dispatch is recorded separately and never substituted for visibility.
Multi-step task execution/verification timestamps describe the most recent step;
per-command queue history retains individual execution timings. STOP signal timing
is interpreted on the STOP task; active tasks use their cancellation timestamp
to measure planner/agent termination. Shutdown reports surviving workers via
`shutdown_status` instead of equating a bounded join with termination. Executor
cleanup exceptions or an explicit failed/incomplete cleanup result set
`executor_cleanup_failed`; `close()` returns false in that case. Browser close
itself is still a synchronous third-party operation, not a guaranteed bounded
resource-cleanup deadline.
