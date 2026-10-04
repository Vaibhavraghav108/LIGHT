# LIGHT Testing Guide

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

The provider/model feature branch adds 22 deterministic provider tests plus one
Handy-path regression. Its local Windows full-suite result is **178 discovered,
170 passing, 8 skipped** in 29.018s. These tests mock provider HTTP/SDK
boundaries; they do not make live OpenAI, Claude, Gemini, LM Studio, Ollama,
Handy, or custom-service claims.

## Test layers

| Layer | Files | Count | What it proves | What it does not prove |
| --- | --- | ---: | --- | --- |
| Unit/parser/platform mocks | `test_laya`, `test_voice*`, `test_computer`, `test_browser`, `test_platform_macos` | 60 | parsing, routing, validation, provider behavior, platform commands | real OS permissions/hardware/GUI results |
| Local real-browser integration | `test_integration_local_browser` | 5 | headless Chromium against localhost DOM; copy path reaches real clipboard | public websites, real display coordinates, clipboard availability everywhere |
| Queue/LLM/reliability | `test_queue_and_llm`, `test_new_features` | 83 | concurrency, cancellation, normalization, ownership, agent lifecycle with mocks/local pages | live Ollama or a full Browser Use research run |
| Provider/model architecture | `test_provider_architecture` | 22 | configuration, registry, protocol shapes, credentials, redaction, no-fallback, planner/agent reuse | live external accounts, model quality, direct audio STT |
| Opt-in host smoke | `test_windows_smoke`, `test_macos_smoke` | 8 | selected browser, clipboard, display, and provider observations on the current host | destructive actions or full end-to-end voice workflow |

Per-file counts: voice 6, voice provider 6, Laya 16, computer 14,
macOS platform 9, browser 9, local browser 5, queue/LLM 25, new features 58,
provider architecture 22, Windows smoke 4, macOS smoke 4.

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
- deterministic fast paths making zero Qwen calls;
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
