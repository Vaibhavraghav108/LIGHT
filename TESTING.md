# LIGHT Testing Guide

LIGHT uses a three-tier testing architecture to verify deterministic unit behavior, real headless browser DOM/CSS/JS interaction via Playwright, and opt-in host Windows smoke checks.

---

## 1. Static Compilation Check

Verify that all Python modules compile cleanly without syntax errors:

```powershell
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py voice brain computer browser core utils tests
```

---

## 2. Test Suite Breakdown & Truthful Totals

Running the full discovery suite (`.\lightenv\Scripts\python.exe -m unittest discover -s tests -v`) discovers **44 tests** across 6 test files:

| Tier | Test File | Class | Tests | Default Behavior |
| :--- | :--- | :--- | :---: | :--- |
| **Tier 1: Unit** | `tests/test_browser.py` | `TestBrowserAndContextFlow` | 7 | Runs & passes (7/7) |
| **Tier 1: Unit** | `tests/test_computer.py` | `TestComputerControl` | 9 | Runs & passes (9/9) |
| **Tier 1: Unit** | `tests/test_laya.py` | `TestLayaAndDecisions` | 14 | Runs & passes (14/14) |
| **Tier 1: Unit** | `tests/test_voice.py` | `TestHandyVoiceAndLoop` | 5 | Runs & passes (5/5) |
| **Tier 2: Local Browser Integration** | `tests/test_integration_local_browser.py` | `TestLocalBrowserIntegration` | 5 | **Runs & passes (5/5)** — never skips; fails loudly if browser launch fails |
| **Tier 3: Opt-In Windows Smoke** | `tests/test_windows_smoke.py` | `TestWindowsSmoke` | 4 | **Skipped by default (4 skipped)** unless `LIGHT_RUN_WINDOWS_SMOKE=1` |
| **Total** | | | **44** | **40 executed & passed, 4 opt-in skipped (`OK (skipped=4)`)** |

---

## 3. Tier 1: Deterministic Unit Tests (35 Tests)

Unit tests use `unittest` and `unittest.mock` to validate parsing, fallback safety, process tracking, and coordinate math without opening external windows or moving the physical cursor:

- `tests/test_voice.py` (5 tests) — `Handy` SQLite reader (`voice/handy.py`) handling missing files, empty `transcription_history`, malformed schemas, and locked DB retries, plus `LightLoop` (`core/loop.py`) duplicate debouncing and error recovery.
- `tests/test_laya.py` (14 tests) — Deterministic preprocessing and parsing (`brain/decision.py`) across all 21 `Action` enum values, context-aware YouTube/Google search routing, `copy_text_range` boundary parsing, incomplete/malformed command rejection (`"Open"`, `"Search"`, `"Copy from"`, `"Open http://"`), and `Laya` fallback safety guards preventing casual speech (`"How are you"`) from triggering `STOP` or `MOVE_MOUSE`.
- `tests/test_computer.py` (9 tests) — `AppController` (`computer/apps.py`) launching/closing supported apps (`Notepad`, `Calculator`, `Brave`, `Chrome`), verifying that closing `Brave`/`Chrome` terminates only LIGHT-tracked `Popen` processes by default without running `taskkill /F` (unless `force=True` or `LIGHT_FORCE_KILL_BROWSERS=1` is passed), `KeyboardController` typing/key presses, `MouseController` relative/absolute movement with screen clamping, and `Executor` routing.
- `tests/test_browser.py` (7 tests) — `BrowserController` URL normalization, navigation methods (`go_back`, `go_forward`, `refresh`), `scroll`, semantic target parsing (`parse_element_target`), DPI-aware `convert_viewport_to_screen` math, `start()` automatic fallback from inaccessible Brave (`PermissionError: [WinError 5] Access is denied`) to Playwright-managed Chromium, and end-to-end mocked loop execution.

### Run Command
```powershell
.\lightenv\Scripts\python.exe -m unittest tests/test_voice.py tests/test_laya.py tests/test_computer.py tests/test_browser.py -v
```

---

## 4. Tier 2: Local-Browser Playwright Integration Tests (5 Tests)

`tests/test_integration_local_browser.py` starts a local `ThreadingHTTPServer` on `127.0.0.1` serving `index.html` and `page2.html` from a workspace-local temporary directory (`tests/.tmp_integration`) and launches a real headless browser via `BrowserController(headless=True)`.

### Browser Fallback Chain
`BrowserController.start()` tries candidates in order:
1. Explicitly passed `executable_path` (if provided)
2. Configured Brave paths from `config.get_brave_candidate_paths()`
3. Playwright-managed Chromium (`executable_path=None`, backed by workspace `.playwright-browsers` or `%LOCALAPPDATA%\ms-playwright`)
4. Workspace-local Chromium binaries (`config.get_workspace_chromium_candidate_paths()`)
5. System Google Chrome paths from `config.get_chrome_candidate_paths()`

If Brave is missing or inaccessible (e.g. `WinError 5: Access is denied`), `BrowserController.start()` logs a warning and automatically launches Playwright-managed Chromium so all 5 local integration tests run and pass. `TestLocalBrowserIntegration.setUpClass` does **not** catch and skip on startup errors—any failure to start a browser fails the test suite loudly.

### The 5 Executed Integration Tests
1. `test_title_and_visible_text_reading` — Verifies `get_title()` and `get_visible_text()` against live DOM content.
2. `test_type_in_search_bar_and_locate_elements` — Verifies `locate_element_in_viewport("the search bar")` and `type_in_browser("Coldplay")`.
3. `test_click_element_skips_hidden_duplicate_and_clicks_visible` — Verifies `click_element()` skips hidden duplicate nodes (`display: none`), clicks the visible button/link, and navigates (`go_back()`, `go_forward()`, `refresh()`).
4. `test_click_nth_result_and_scroll` — Verifies `click_result(1)` and `scroll("down")` / `scroll("up")` against `window.scrollY`.
5. `test_copy_text_range_inclusive_slicing_and_highlight_cleanup` — Verifies `copy_text_range("I know this one will hurt|||demolish")` copies inclusive text preserving original casing to the clipboard (`pyperclip.paste()`), marks `<p id="story-para">` with `data-light-highlighted="true"`, cleans up inline styles via `clear_highlights()`, and raises `ValueError` on missing or ambiguous boundary phrases.

### Run Command
```powershell
.\lightenv\Scripts\python.exe -m unittest tests/test_integration_local_browser.py -v
```

---

## 5. Tier 3: Opt-In Windows Host Smoke Tests (4 Tests)

`tests/test_windows_smoke.py` contains 4 non-destructive host environment checks that are **skipped by default** during normal test discovery and enabled only when `LIGHT_RUN_WINDOWS_SMOKE=1` is set:

1. `test_browser_executable_discovery` — Verifies at least one Brave or Chrome executable path exists via `get_brave_candidate_paths()` / `get_chrome_candidate_paths()`.
2. `test_clipboard_roundtrip` — Verifies system clipboard write/read via `pyperclip` and restores prior clipboard content.
3. `test_screen_and_mouse_observation` — Verifies `ScreenController.get_screen_size()`, `ScreenController.get_mouse_position()`, and `ScreenController.get_active_window_title()`.
4. `test_handy_database_read` — Verifies non-destructive read access to `Handy.get_latest_transcription()` if `HANDY_DB_PATH` exists on the machine.

### Run Command
```powershell
$env:LIGHT_RUN_WINDOWS_SMOKE="1"; .\lightenv\Scripts\python.exe -m unittest tests/test_windows_smoke.py -v
```

---

## 6. Default Full Test Suite Command

```powershell
.\lightenv\Scripts\python.exe -m unittest discover -s tests -v
```
Expected result: `Ran 44 tests` -> `OK (skipped=4)` (35 unit tests + 5 local Playwright integration tests executed and passed; 4 opt-in Windows smoke tests skipped).
