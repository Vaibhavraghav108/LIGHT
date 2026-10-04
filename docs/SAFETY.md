# LIGHT Safety and Operational Boundaries

LIGHT controls a user's mouse, keyboard, processes, and browser. These rules are
product invariants, but guarantees apply only at the stated measurement and
verification boundaries.

## Mandatory invariants

| Rule | Enforcement | Honest boundary |
| --- | --- | --- |
| Explicit STOP is highest priority | detected before planning; cancellation event set; pending queue cleared; STOP inserted first | <5ms target begins at `ingest_text()`, not spoken audio |
| Listener stays independent | `LIGHT-VoiceListener` only reads/debounces/enqueues | provider/database polling still has default 150ms cadence |
| Dependent failure is plan-scoped | failed search/open prunes matching utterance dependents | plan identity is currently the raw utterance text |
| Agent work does not block normal commands | one `LIGHT-AgentWorker` returns control immediately | agent and deterministic browser can consume resources concurrently |
| Browser sessions are isolated | Browser Use and Playwright never share a context | `BrowserOwnership` is a state signal, not a lock |
| No blind named-result fallback | ranked visible candidates require confidence | explicit numeric result requests intentionally select an ordinal |
| Dispatch is not success | focus, click state, clipboard, and named destination checks | verification is action-specific and cannot prove every UI side effect |
| Normal close is scoped | only LIGHT-tracked processes are terminated | explicit `force=True` can be broad and must not be normal routing |
| OS/provider details stay behind interfaces | `PlatformController`; `VoiceInputProvider` | generic subprocess execution may run commands returned by the platform |
| LLM output is untrusted | structured JSON, action allowlist, app/URL/STOP validation | permitted text/click targets still need executor/browser checks |
| Local-first defaults remain | local STT database/model; Browser Use telemetry/cloud sync off by default | web tasks necessarily send requests/content to requested sites |
| Tests may not be weakened | regressions require tests and CI matrix preservation | mocked/CI tests are not physical-host certification |

## STOP and cancellation

```text
spoken STOP -> STT/VAD -> provider publication -> listener poll
                                                   |
                                                   v
                                           ingest_text("Stop")
                                                   |
                         immediate cancel_event.set + queue preemption
                                                   |
                         cooperative interruption / STOP execution / cleanup
```

The measurable fast path is the second line: explicit phrase detection and
event signaling after ingestion. End-to-end voice latency includes external STT
and up to a polling interval. Active work responds according to its design:

- `WAIT` waits directly on the cancellation event;
- named-destination navigation polls the event every 10ms;
- Browser Use has a 10ms async poller and calls `agent.stop()`/task cancel;
- STOP joins the worker for up to 200ms before continuing cleanup;
- some Playwright, OS, and third-party calls do not inspect the event while
  blocked and therefore cannot promise immediate interruption.

Do not document “all automation aborts within 5ms.” The enforced contract is
fast cancellation signaling, queue preemption, and cooperative cleanup.

## Browser and webpage safety

Browser page text is untrusted. Deterministic commands do not turn page content
into new desktop actions. Qwen planning is based on the user's request and
validated against a fixed action vocabulary; Browser Use may observe webpage
content inside its isolated session, but it has no LIGHT shell action.

Named targets such as “official repository” are scored using visible link text,
href/domain, query tokens, and semantic hints. A candidate below the threshold
is rejected. After clicking, the controller requires an active browser, a URL
different from the pre-click URL, and semantic URL/title/body evidence. These
are relevance checks, not malware, authenticity, or reputation guarantees.

Arbitrary URLs accepted by the deterministic parser are navigable when they
pass URL normalization. LIGHT does not currently implement a domain allowlist,
blocklist, Safe Browsing check, or confirmation prompt. Users should treat
unknown URLs and webpage-driven autonomous goals as potentially hostile.

## LLM safety boundary

The Ollama planner cannot emit actions outside `Action`; there is no shell,
filesystem, package-install, credential, or arbitrary-process action. STOP is
accepted only when the raw user text is explicit. Known applications are
allowlisted and URL-like targets are validated.

This validation does not make model output inherently trusted. Actions such as
typing user-provided text, clicking named elements, or visiting a valid URL can
still have consequences. Focus checks, browser verification, scoped process
rules, and user STOP authority remain required.

## Desktop and process safety

- Typing checks the foreground target immediately before dispatch, but a focus
  race remains possible after the check.
- Normal app close terminates tracked `Popen` instances. On macOS, a graceful
  AppleScript quit is allowed only after a tracked `open -a` launch because the
  launcher process exits early.
- Broad `taskkill /IM`, `pkill -f`, or equivalent commands require explicit
  `force=True`. The executor's normal close path does not opt in.
- Single-instance startup may terminate stale `main.py` process trees using
  platform commands while protecting the current process and parent shim.
- Physical cursor/click verification checks coordinates and selected UI state;
  it cannot guarantee the absence of OS overlays or last-moment focus changes.

## Privacy and data handling

- Handy audio processing and database publication occur in the external Handy
  application; LIGHT reads transcript text only.
- Qwen/Laya inference is local by default. Ollama's endpoint is configurable,
  so a non-local override changes that privacy boundary.
- Browser Use configuration is repository-local by default, with optional
  telemetry and cloud sync disabled unless the environment overrides them.
- Runtime logs can contain spoken commands, URLs, errors, and timings. They are
  ignored by Git and must not be committed without review/redaction.
- `.env`, browser profiles, and caches are ignored because they may contain
  secrets or session data.
- Websites receive normal browser traffic and any information a requested task
  submits. LIGHT does not provide a privacy sandbox for the public web.

## Platform and validation limits

Windows/macOS CI exercises shared code and a real local Playwright page.
Platform unit tests mock many OS calls. The repository does not record physical
macOS validation of microphone/Handy, Accessibility, Screen Recording, Retina,
or mixed-DPI monitors. Host smoke tests are opt-in and non-destructive.

Any change that expands URL trust, process scope, LLM actions, OS subprocesses,
or unverified clicks requires explicit safety review and regression coverage.
