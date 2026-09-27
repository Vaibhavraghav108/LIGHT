# LIGHT — LLM-Free Voice-Controlled Windows & Browser Automation Assistant

**LIGHT** is a local, LLM-free voice-controlled automation assistant for Windows. It reads speech-to-text transcriptions from the **Handy** SQLite database, parses commands deterministically via [`brain/decision.py`](file:///c:/Projects/LIGHT/brain/decision.py) (with [`Laya`](file:///c:/Projects/LIGHT/brain/laya.py) intent classification as a strict prefix-guarded fallback), and executes actions across Windows desktop utilities (`Notepad`, `Calculator`, `Brave`, `Chrome`), physical mouse/keyboard controls, and a Playwright-controlled browser (`Brave` with automatic fallback to Playwright-managed `Chromium` and `Chrome`).

```text
[Handy SQLite DB] ──► [DecisionEngine + Laya Fallback] ──► [Executor]
                                                              ├──► [BrowserController (Brave -> Playwright Chromium -> Chrome)]
                                                              └──► [Computer Controllers (AppController / MouseController / KeyboardController / ScreenController)]
```

---

## Feature Support Matrix

| Category | Feature / Capability | Example Voice Commands | Status |
| :--- | :--- | :--- | :--- |
| **Voice Loop** | Continuous SQLite polling (`voice/handy.py`), duplicate debouncing (`core/loop.py`), locked/malformed DB recovery | *(Automatic background loop)* | Verified |
| **Websites** | Open 8 canonical website shortcuts (`youtube`, `google`, `github`, `linkedin`, `gmail`, `chatgpt`, `reddit`, `wikipedia`) or any domain/URL (`https://` auto-normalized) | `"Open YouTube"`, `"Go to github.com"`, `"Open wikipedia"` | Verified |
| **Context Search** | Context-aware search on YouTube (when active site is YouTube or explicitly specified) and Google fallback | `"Search for Coldplay"`, `"Search YouTube for Python"`, `"Find machine learning"` | Verified |
| **DOM Clicking** | Semantic DOM element detection via `BrowserController.click_element()` (skips hidden duplicates, scrolls into view, clicks visible control) | `"Click Subscribe"`, `"Click Subscriptions"`, `"Click Ask about files"`, `"Click search bar"` | Verified |
| **Result Selection** | Click Nth visible search result or video link (`1st` through `5th` or numeric) via `BrowserController.click_result()` | `"Click the first result"`, `"Select second video"`, `"Click result 3"` | Verified |
| **Precision Mouse (DOM)** | DPI-aware viewport-to-physical screen mapping (`convert_viewport_to_screen`) + closed-loop OS `mousemove` self-calibration (`move_mouse_to_element`) | `"Move mouse to the search bar"`, `"Move mouse onto the Subscribe button"`, `"Move mouse to the first video"` | Verified |
| **Precision Mouse (Relative/Screen)** | Exact pixel offsets, semantic nudges (`a little`, `slightly`, `a lot`, `far`), screen anchors, click via `MouseController` | `"Move mouse 100 pixels right"`, `"Move mouse slightly up"`, `"Move mouse to center"`, `"Click"` | Verified |
| **Range Copy & Paste** | Inclusive text range copy (`copy_text_range`) with original casing, clipboard verification (`pyperclip`), and DOM highlight cleanup (`clear_highlights`) | `"Copy from I know this one will hurt till demolish"`, `"Paste"` | Verified |
| **Page Reading & Navigation** | Read page/window title (`get_title` / `get_active_window_title`), visible page text (`get_visible_text`), scroll, back, forward, refresh | `"Read title"`, `"Read page"`, `"Scroll down"`, `"Go back"`, `"Go forward"`, `"Refresh page"` | Verified |
| **Keyboard & Typing** | Direct DOM input typing (`type_in_browser`) when browser is active, or OS keyboard typing + key presses (`KeyboardController`) | `"Type Coldplay"`, `"Press enter"`, `"Press escape"` | Verified |
| **Windows Apps** | Launch and close supported Windows apps (`Notepad`, `Calculator`); `Open Brave`/`Open Chrome` starts LIGHT's one Playwright-controlled browser session, which all browser commands reuse. Closing either voice-browser command closes only that session. | `"Open Notepad"`, `"Close Notepad"`, `"Open Calculator"`, `"Open Brave"`, `"Close Brave"` | Verified |
| **Safety & Rejection** | Rejects incomplete/malformed commands (`ValueError`) and prevents casual speech from triggering actions or `STOP` | `"Open"` (rejected), `"Search"` (rejected), `"How are you"` (ignored) | Verified |

---

## Windows Setup & Installation

### Prerequisites
1. **Windows 10 / 11** (64-bit) with High-DPI scaling supported via `SetProcessDpiAwareness`.
2. **Python 3.10+** (verified on Python 3.12).
3. **Browser Runtime**:
   - **Brave Browser** (checked first via `BRAVE_EXECUTABLE_PATH` or standard `Program Files` / `%LOCALAPPDATA%` paths), **or**
   - **Playwright-managed Chromium** (automatic fallback when Brave is missing or inaccessible, stored in `.playwright-browsers` or `%LOCALAPPDATA%\ms-playwright`), **or**
   - **Google Chrome** (`CHROME_EXECUTABLE_PATH` or standard Windows Chrome paths).
4. **Handy STT Desktop App** (for live microphone dictation) writing transcriptions to `%APPDATA%\com.pais.handy\history.db`.

### 1. Create Virtual Environment & Install Dependencies
From PowerShell inside `c:\Projects\LIGHT`:

```powershell
python -m venv lightenv
.\lightenv\Scripts\pip.exe install --upgrade pip
.\lightenv\Scripts\pip.exe install -r requirements.txt
```

### 2. Install Playwright Chromium Fallback
To ensure `BrowserController` has a working Chromium binary even if Brave is not installed or is blocked by permissions:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH="c:\Projects\LIGHT\.playwright-browsers"
.\lightenv\Scripts\playwright.exe install chromium
```

### 3. Run LIGHT
```powershell
.\lightenv\Scripts\python.exe main.py
```
Say **"Stop"**, **"Stop light"**, **"Exit"**, **"Exit light"**, **"Quit"**, or **"Quit light"** (or press `Ctrl+C`) to cleanly close the browser session and exit.

---

## Running Tests

See [`TESTING.md`](file:///c:/Projects/LIGHT/TESTING.md) for the complete test breakdown.

### Static Compilation Check
```powershell
.\lightenv\Scripts\python.exe -m compileall -q main.py config.py voice brain computer browser core utils tests
```

### Default Automated Test Suite (35 Unit Tests + 5 Local Playwright Browser Integration Tests)
Runs **44 discovered tests**: **40 execute and pass** (`35` unit tests + `5` real headless Playwright browser tests against a local HTTP server) and **4 opt-in Windows smoke tests skip by default**:

```powershell
.\lightenv\Scripts\python.exe -m unittest discover -s tests -v
```

### Opt-In Windows Host Smoke Tests (4 Tests)
Verifies live Windows browser path discovery, system clipboard round-trip (`pyperclip`), `ScreenController` screen/mouse/window observation, and non-destructive `Handy` SQLite read access:

```powershell
$env:LIGHT_RUN_WINDOWS_SMOKE="1"; .\lightenv\Scripts\python.exe -m unittest tests/test_windows_smoke.py -v
```

---

## Configuration & Environment Variables

All canonical dictionaries (`WEBSITES`, `KNOWN_APPS`, `STOP_COMMANDS`) and runtime settings live in [`config.py`](file:///c:/Projects/LIGHT/config.py):

- `HANDY_DB_PATH`: Path to Handy's `history.db` (default: `%APPDATA%\com.pais.handy\history.db`).
- `LAYA_MODEL`: Model identifier for `Laya` fallback (default: `convaiinnovations/laya`).
- `POLL_INTERVAL`: Voice loop polling interval in seconds (default: `0.25`).
- `DUPLICATE_COOLDOWN_SECONDS`: Cooldown window in seconds to debounce consecutive identical utterances unless repeatable actions (`SCROLL`, `PRESS_KEY`, `CLICK`, `MOVE_MOUSE`, `GO_BACK`, `GO_FORWARD`, `REFRESH`, `PASTE`, `WAIT`) are triggered (default: `1.0`).
- `BROWSER_TIMEOUT_MS`: Browser operation timeout in milliseconds (default: `5000`).
- `HIGHLIGHT_DURATION_MS`: Highlight duration for matched elements in milliseconds (default: `3000`).
- `BROWSER_TYPE_GUARD_MS`: Short browser-input protection window after a `Type ...` command (default: `1200`). It prevents Handy's delayed auto-typing from appending a duplicate value in the controlled browser.
- `BRAVE_EXECUTABLE_PATH` / `CHROME_EXECUTABLE_PATH`: Optional custom executable path overrides.
- `PLAYWRIGHT_BROWSERS_PATH`: Path to Playwright browser binaries (automatically defaults to `c:\Projects\LIGHT\.playwright-browsers` when present).
- `LIGHT_FORCE_KILL_BROWSERS`: Set to `1` to opt in to `taskkill /IM brave.exe /F` (or `chrome.exe`) when closing browsers via `AppController.close()`. By default (`0`/unset), LIGHT closes only browser processes it started.
- `LIGHT_LOG_LEVEL`: Logging verbosity (`DEBUG`, `INFO`, `WARN`, `ERROR`; default: `INFO`).
- `LIGHT_RUN_WINDOWS_SMOKE`: Set to `1` to run the 4 opt-in host Windows smoke tests in `tests/test_windows_smoke.py`.

---

## Permissions & Known External Limitations

1. **Handy SQLite Database Availability**:
   - In production (`python main.py`), the external **Handy** STT application must be installed and running so transcriptions are written to `%APPDATA%\com.pais.handy\history.db`.
   - Disable Handy's **auto-type / type into focused app** option in Handy itself. LIGHT only needs Handy to save transcriptions in its database. That setting is required for duplicate-free typing in desktop applications such as Notepad; LIGHT cannot safely erase text injected by another application into an arbitrary document.
2. **Browser Process Safety (`Close Brave` / `Close Chrome`)**:
   - By default, `AppController.close("Brave")` and `AppController.close("Chrome")` terminate only `subprocess.Popen` instances launched by LIGHT (and `Executor` closes LIGHT's active Playwright browser session) without running `taskkill /F`, protecting any personal browser windows open on the desktop.
3. **Elevated (Administrator) Windows Processes**:
   - Windows UIPI prevents a non-elevated Python process from sending simulated `PyAutoGUI` mouse/keyboard events to windows running as Administrator.
