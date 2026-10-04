# LIGHT Feature Status (`v0.5.0`)

Status reflects source plus available evidence, not aspiration. Definitions are
in [README.md](README.md). “CI” means the automated Windows/macOS matrix; it is
not physical-device certification.

## Voice and core

| Feature | Status | Evidence | Limits |
| --- | --- | --- | --- |
| `VoiceInputProvider` and factory | Implemented | `voice/`; `test_voice_provider.py` | one production provider plus unavailable fallback |
| Handy SQLite ingestion | Partial | read-only provider tests; Windows smoke exists | requires external Handy; physical macOS path unverified |
| ordered transcript polling | Implemented | `test_voice.py`; queue tests | polling, not push; default 150ms |
| duplicate suppression | Implemented | voice/queue tests | one-second policy with repeatable-action exceptions |
| unavailable-provider idle mode | Implemented | provider tests | no commands arrive until a provider exists |
| direct microphone/VAD/Whisper | Not implemented | no source | Handy performs STT/VAD externally |
| priority queue and plan-scoped pruning | Implemented | `test_queue_and_llm.py` | consumer still executes ordinary commands sequentially |
| ingestion-time STOP priority | Implemented | queue/new-feature timing tests | sub-5ms boundary excludes STT/polling; running calls vary |
| thread-safe contextual state | Implemented | state/ownership tests | observation can become stale between checks |

## Brain and planning

| Feature | Status | Evidence | Limits |
| --- | --- | --- | --- |
| deterministic single/compound parsing | Implemented | parser and queue tests | grammar/vocabulary based |
| contextual continuations | Implemented | `test_new_features.py` | relies on recorded site/search context |
| casual/malformed speech rejection | Implemented | Laya/queue tests | heuristic and guarded classifier behavior |
| local Qwen3 1.7B planning | Partial | mocked transport/normalization tests | live Ollama/model quality not part of default suite |
| LLM action validation | Implemented | malformed/action tests | text targets still require downstream checks |
| deterministic offline fallback | Implemented | queue/LLM tests | covers selected complex-search forms |
| guarded Laya fallback | Implemented | `test_laya.py` | model dependency is loaded at normal startup |

## Desktop and platform

| Feature | Status | Evidence | Limits |
| --- | --- | --- | --- |
| `PlatformController` boundary | Implemented | platform unit tests and source inspection | Linux is unsupported |
| Windows desktop control | Partial | unit tests, CI, opt-in smoke suite | not every physical action runs in default CI |
| macOS desktop control | Partial | mocked unit tests and macOS CI | physical permissions/hardware/voice unverified |
| known-app launch and tracked close | Implemented | `test_computer.py` | fixed app allowlist; external instances are not normal close targets |
| foreground-aware typing | Partial | mocked focus/routing tests | focus can change after verification |
| hotkeys and clipboard modifier mapping | Implemented | Windows/macOS unit tests | host clipboard availability is environment-sensitive |
| window/media controls | Partial | parser/routing/platform tests | real application behavior varies by host |
| precision mouse and screen anchors | Partial | mocked/unit tests, host smoke available | mixed-DPI multi-monitor not validated |
| arbitrary installed-app discovery | Not implemented | no source | planned |

## Deterministic browser

| Feature | Status | Evidence | Limits |
| --- | --- | --- | --- |
| Playwright Chromium lifecycle/recovery | Implemented | unit plus local real-browser tests | executable/profile/host policies can prevent launch |
| URL shortcuts and contextual search | Implemented | browser/parser tests | website DOM changes can break selectors |
| Google challenge detection with DuckDuckGo fallback | Implemented | browser unit test | fallback is not a CAPTCHA bypass guarantee |
| visible DOM element location | Implemented | local-browser tests | loaded page/viewport only |
| numeric result selection | Implemented | local-browser tests | explicit ordinal may still choose an undesired result |
| named-target ranking | Implemented | ranking tests | heuristic; no below-fold alternative retry yet |
| changed-URL and semantic destination verification | Implemented | verification regressions | heuristic content checks; not a trust/reputation service |
| physical click post-state checks | Partial | unit/local-page tests | generic web controls cannot all expose definitive state |
| copy range and clipboard read-back | Partial | unit/local-browser test | depends on an accessible system clipboard |
| multi-tab coordination | Not implemented | no source | planned |

## Autonomous agent

| Feature | Status | Evidence | Limits |
| --- | --- | --- | --- |
| Browser Use with local Ollama | Experimental | initialization/adapter tests | optional dependencies; live agent not in default CI |
| intent routing to `AGENT_TASK` | Implemented | parser tests | heuristic trigger phrases |
| isolated Browser Use session | Implemented | ownership tests/source | two browsers may operate concurrently by design |
| one atomic agent admission | Implemented | concurrency regression | one task at a time |
| non-blocking `LIGHT-AgentWorker` | Implemented | sync/async consumer tests | daemon may outlive bounded join if dependency hangs |
| cooperative STOP/cancellation | Partial | mocked async/worker tests | Browser Use internals may not stop immediately |
| agent result notification UI | Not implemented | logs/state only | no dedicated completion surface |

## Reliability, privacy, and delivery

| Feature | Status | Evidence | Limits |
| --- | --- | --- | --- |
| process-safe normal app close | Implemented | app regression tests | explicit `force=True` remains a broad operation |
| local Browser Use config/privacy defaults | Implemented | config regression | explicit user environment overrides are respected |
| single-instance cleanup | Partial | mocked tests, Windows smoke | stale/permission-constrained processes may resist termination |
| Windows/macOS CI matrix | Implemented | GitHub Actions | no Linux job; host smoke disabled by default |
| runtime performance logging | Implemented | queue request metrics | logs are ignored and not telemetry |
| cloud LLM/analytics requirement | Not implemented | source/config | requested websites and package installs use network |

## Planned, not current behavior

Direct Whisper/VAD, dynamic application discovery, multi-monitor DPI
normalization, multi-tab coordination, below-fold candidate retry, local visual
grounding, system-tray status, and TTS are roadmap items. They must not be
described as released features.
