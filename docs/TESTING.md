# LIGHT Testing Guide

## Phase 2 typed-capability working-branch baseline — 2026-10-06

Branch `codex/typed-capability-foundation` starts from merged PR #8 main
`6350e38`. Before changes: **225 discovered, 217 passed, 8 opt-in host smoke
skips, 0 failures/errors**, 31.193s locally on Windows.
After Phase 2: **279 discovered, 271 passed, 8 opt-in host smoke skips,
0 failures, 0 errors**, 26.402s on the same Windows host. Targeted capability
tests passed **53/53**; twenty repetitions passed **1,060 test executions**
with no failures/errors and no surviving LIGHT workers. The final full suite
includes **six real localhost/headless-Chromium tests**. Compileall and
`git diff --check` passed.

`test_capabilities.py` adds **53 tests** covering registration, duplicate/unknown
rejection, strict arguments/backends/identity/generation, URL safety, confirmation,
immutability, action lowering, existing browser/desktop/keyboard routing,
admission/dispatch cancellation, sync/async paths, STOP under an admission lock,
backlog cancellation beyond snapshot retention, stale predictions, verification,
and shutdown. One additional localhost integration test exercises typed open,
DOM typing, and scroll through the real queue/Executor/Chromium path. Existing
assertions and skips are preserved.

Hosted Windows/macOS CI has not run on these uncommitted Phase 2 changes.
The workflow/matrix, provider/model configuration, dependency pins, and platform
implementations are unchanged. Physical voice/Mac checks remain opt-in limitations.

Controlled pure-CPU measurements on this Windows host (5,000 samples each):

| Operation | P50 / P95 / P99 |
| --- | --- |
| Registry lookup | 0.2 / 0.2 / 0.3 microseconds |
| Plan validation | 8.6 / 8.9 / 13.9 microseconds |
| Lowering including validation | 9.1 / 9.4 / 15.7 microseconds |

Matched ordinary `press tab` voice ingestion, 1,000 samples per implementation,
logging disabled and execution outside the timing interval: main **42.3 / 52.1 /
73.4 microseconds**, Phase 2 **42.2 / 50.7 / 64.0 microseconds** (P50/P95/P99).
Main loop/queue were loaded in-memory from Git without modifying the checkout.
This shows no meaningful deterministic-ingestion regression, not a claimed speedup
or hardware SLA. Registry measurements include no backend/network/model work.

## Planning-safety milestone baseline — 2026-10-06

Branch `codex/planning-safety-foundation` starts from clean merged main
`777c7d9`. Before changes: **192 discovered, 184 passed, 8 opt-in skips,
0 failures/errors**, 29.385s on Windows. After Phase 0/1: **225 discovered,
217 passed, 8 opt-in skips, 0 failures/errors**, 26.370s. This includes the
five real localhost/headless-Chromium integration tests; it is not a physical
voice or Mac certification. These historical local measurements preceded the
Phase 0/1 commit and PR #8 merge; they are not Phase 2 CI evidence.

The new `test_planning_foundation.py` contains **33 tests** covering bounded
planning, spoken STOP while inference is blocked, stale publication, FIFO and
concurrent ingestion, task identity/results, sync/async cancellation (including
repeated async cancellation), verification recovery, metrics, and truthful
worker shutdown/ownership and cleanup failures. Twenty repeated runs executed
**660 tests with no failures/errors and no surviving LIGHT workers**.
Existing test 52 retains its shutdown latency/cancel checks
and now asserts ownership until its cancellation-ignoring fixture actually exits.
No tests were deleted, skipped, or loosened to hide a failure.

Additional targeted results: provider/platform/voice **57/57 passed**;
queue/new-feature **83/83 passed**. Full compileall and `git diff --check`
passed. `pip check` still fails for the pre-existing click metadata conflict
described below; dependencies were not changed.

Commands used for the final checks:

```powershell
.\lightenv\Scripts\python.exe -m unittest tests.test_planning_foundation -q
.\lightenv\Scripts\python.exe -m unittest tests.test_queue_and_llm tests.test_new_features -q
.\lightenv\Scripts\python.exe -m unittest tests.test_provider_architecture tests.test_platform_macos tests.test_voice tests.test_voice_provider -q
.\lightenv\Scripts\python.exe -m unittest discover -s tests -v
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py providers voice brain computer browser core utils tests
.\lightenv\Scripts\python.exe -m pip check
git diff --check
git status --short --branch
```

### Controlled latency evidence

Measurements use `perf_counter()` on the development Windows host, not hosted CI.
P95/P99 are empirical sorted-sample percentiles, not production SLAs.

| Measurement | Samples | P50 / P95 / P99 or observed result |
| --- | ---: | --- |
| Baseline deterministic ingestion, main loop/queue from `777c7d9` | 500 | 0.042 / 0.062 / 0.093ms |
| Foundation deterministic ingestion, same parser/fixture, logging disabled for both | 500 | 0.050 / 0.084 / 0.101ms |
| Simulated 200ms inference: old ingestion vs new submission | one each | 200.524ms blocked vs 0.728ms submission; worker inference still 200.329ms |
| Queue wait, mocked executor | 200 | 0.009 / 0.013 / 0.029ms |
| Execution, mocked executor | 200 | 0.029 / 0.040 / 0.058ms |
| STOP ingestion to cancellation signal | 200 | 0.0049 / 0.0109 / 0.0152ms |
| STOP to planner return, event-controlled fixture immediately released after STOP | 100 | 0.043 / 0.064 / 0.073ms |
| Existing browser verification, mocked browser | 100 | 0.023 / 0.037 / 0.053ms |
| Fresh real headless Chromium startup | 5 | median 670ms; range 659–703ms |
| Selected local `qwen2.5:3b`, resident model, actual validated planner requests | 3 | 4943 / 5097 / 5404ms individual calls; all returned valid plans |
| Selected local `qwen2.5:3b`, not resident before request | 1 | existing 8s provider timeout, no valid plan; cold completion latency not obtained |

The matched deterministic measurement shows about **0.008ms median overhead**
for identity/status/timing, not a deterministic speedup. The improvement is
removal of inference from ingestion. The old loop/queue were evaluated in-memory
from `git show`, without checking out or modifying main. The live local-model
probe executed no desktop/browser actions and did not change model selection.
After the cold timeout, the planner's existing cooldown suppressed two further
requests; those near-zero returns are **not warm inference measurements**.
The separate resident-model run used a fresh planner with the same selection.
Three warm calls and five browser starts are too few for credible tail estimates.

Read timings through `LightLoop.task_status()` and `.metrics.snapshot()` on
Laya, the planner, or browser controller. Counters include success/failure and
semantic abstention; false-positive Laya STOP rejection has explicit coverage.
Publication-to-ingestion and first-visible-effect remain **unavailable** unless
the source/backend provides evidence. Handy/custom adapters currently do not
provide a same-process monotonic publication timestamp, and no physical display
effect was measured. Do not reinterpret dispatch or a socket timeout as either
visibility or worker termination. Task execution timings cover the latest step;
per-command queue history preserves individual step timings.

## Dated `v0.5.0` baseline

The tagged release (`8524bde`, 2026-10-04) discovers **155 tests**. GitHub
Actions run `python -m unittest discover -s tests -v` on Python 3.12 for both
`windows-latest` and `macos-latest`; the main-branch run after merge passed both
jobs with **147 passing and 8 skipped** in each matrix environment.

The eight skips are four Windows and four macOS opt-in host smoke tests. A green
default suite therefore does not mean physical voice, clipboard, display,
permission, or application behavior was exercised.

During the 2026-10-04 documentation audit, the first Windows run discovered 155
tests but reported **146 passing, 8 skipped, 1 error** because the real local
browser copy-range test could not open the host clipboard. An immediate targeted
rerun of that test passed, identifying a transient host clipboard condition
rather than a deterministic source failure. The result was not hidden or
converted into a skip; source and tests were not changed by this documentation
milestone. After the targeted pass, the final full rerun completed in 26.050s
with **147 passing and 8 skipped**.

The merged provider/model milestone added 36 deterministic provider regression
tests plus one Handy-path regression. Its final local Windows full-suite baseline
was **192 discovered, 184 passing, 8 skipped, 0 failures, and 0 errors** with
both the persisted non-default
`qwen2.5:3b` selection and a clean/default `qwen3:1.7b` selection. These tests
mock provider HTTP/SDK boundaries; they do not make live OpenAI, Claude, Gemini,
LM Studio, Ollama, Handy, or custom-service claims.

## Test layers

| Layer | Files | Count | What it proves | What it does not prove |
| --- | --- | ---: | --- | --- |
| Unit/parser/platform mocks | `test_laya`, `test_voice*`, `test_computer`, `test_browser`, `test_platform_macos` | 60 | parsing, routing, validation, provider behavior, platform commands | real OS permissions/hardware/GUI results |
| Local real-browser integration | `test_integration_local_browser` | 6 | headless Chromium against localhost DOM; typed capability path; copy path reaches real clipboard | public websites, real display coordinates, clipboard availability everywhere |
| Queue/LLM/reliability | `test_queue_and_llm`, `test_new_features` | 83 | concurrency, cancellation, normalization, ownership, agent lifecycle with mocks/local pages | live Ollama or a full Browser Use research run |
| Provider/model architecture | `test_provider_architecture` | 36 | configuration, provider-aware defaults, strict activation validation, protocol shapes, credentials, redaction, no-fallback, planner/agent reuse | live external accounts, model quality, direct audio STT |
| Planning-safety foundation (merged PR #8) | `test_planning_foundation` | 33 | ordered planning, cancellation generations, bounded metrics, status, truthful ownership/shutdown | physical speech/display timing, guaranteed interruption of third-party calls |
| Typed capabilities (Phase 2 working branch) | `test_capabilities` | 53 | pure contracts, validation/lowering, existing mocked execution, cancellation/status/shutdown | live providers, new structured results, physical GUI behavior |
| Opt-in host smoke | `test_windows_smoke`, `test_macos_smoke` | 8 | selected browser, clipboard, display, and provider observations on the current host | destructive actions or full end-to-end voice workflow |

Per-file counts: voice 6, voice provider 6, Laya 16, computer 14,
macOS platform 9, browser 9, local browser 6, queue/LLM 25, new features 58,
provider architecture 36, planning foundation 33, capabilities 53,
Windows smoke 4, macOS smoke 4.

## Stable commands

Windows PowerShell:

```powershell
.\lightenv\Scripts\python.exe -m unittest discover -s tests -v
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py providers voice brain computer browser core utils tests
.\lightenv\Scripts\python.exe -m pip check
git diff --check
```

macOS:

```bash
./lightenv/bin/python -m unittest discover -s tests -v
./lightenv/bin/python -m compileall -q main.py config.py providers voice brain computer browser core utils tests
./lightenv/bin/python -m pip check
git diff --check
```

Target one module with, for example:

```powershell
.\lightenv\Scripts\python.exe -m unittest tests.test_queue_and_llm -v
```

Use importable dotted module names for the most portable command form.

## Opt-in host smoke tests

These checks interact with the current host but remain non-destructive:

```powershell
$env:LIGHT_RUN_WINDOWS_SMOKE="1"
.\lightenv\Scripts\python.exe -m unittest tests.test_windows_smoke -v
```

```bash
LIGHT_RUN_MACOS_SMOKE=1 ./lightenv/bin/python -m unittest tests.test_macos_smoke -v
```

Run the matching suite only on its OS. Record the machine type, permissions,
voice-provider availability, and exact output. Never infer physical Mac success
from `macos-latest` CI.

## Critical regression areas

- explicit STOP signaling, queue priority, queue clearing, and interruptible
  wait behavior;
- listener independence under a slow executor and rapid ordered transcripts;
- failed-plan pruning without cross-utterance cancellation;
- deterministic fast paths making zero AI-provider/model calls;
- malformed, unavailable, and control-token LLM output;
- provider/model independence, explicit registry selection, candidate
  validation, model discovery, credential indirection, error redaction, and no
  implicit provider fallback;
- Browser Use admission races, duplicate rejection, result state, shutdown, and
  ownership preservation during deterministic browser work;
- inactive/unchanged/mismatched named destinations and cancellable verification;
- clipboard read-back failures and platform modifier routing;
- tracked-process-only normal close and explicit-force separation;
- unavailable voice provider, locked/malformed SQLite, and duplicate speech;
- Windows/macOS platform command mapping without shared-module OS leakage.

## Timing tests

Timing assertions test bounded behavior, not universal hardware performance.
Virtualized runners have scheduler jitter, and historical macOS CI failures led
to removal of unnecessary observation subprocesses and CI-tolerant end-to-end
thresholds. Keep the semantic requirement separate from the threshold:

- direct STOP event signaling targets under 5ms after ingestion;
- a running `WAIT` may wake on OS scheduling later than the signal;
- agent dispatch must return promptly without waiting for research;
- bounded joins protect shutdown latency but do not prove a third-party thread
  has terminated.

## CI behavior

`.github/workflows/tests.yml` installs core dependencies plus pinned optional
agent packages, installs Playwright Chromium, compiles the tree, and runs full
discovery. Its matrix is `windows-latest` and `macos-latest`, with fail-fast
disabled. Pull requests to `main` always run; push filters cover `main`,
`feature/*`, `fix/*`, and `refactor/*`. A `docs/*` push alone does not run, but a
pull request to `main` does.

The install currently emits/resolves into a known metadata inconsistency:
`browser-use==0.13.10` pins `click==8.3.3`, while installed
`huggingface-hub` requires `click>=8.4.2,<9`. `pip check` therefore fails even
though tests and CI pass. Track this separately; do not weaken tests or conceal
the conflict.

## Result reporting standard

For every change report:

1. exact commit/branch and OS;
2. exact commands;
3. discovered, passed, failed, errored, and skipped counts;
4. whether Playwright, clipboard, GUI, microphone, Ollama, and Browser Use were
   real, mocked, skipped, or unavailable;
5. CI links and separate Windows/macOS conclusions;
6. known dependency or environment warnings.

“Tests pass” is insufficient when any layer was skipped or blocked.
