import os
from pathlib import Path


def _load_env_file():
    """Load simple KEY=VALUE pairs from .env if it exists."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()

# Speech-to-Text (Handy SQLite Database)
DEFAULT_HANDY_DB = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "com.pais.handy"
    / "history.db"
)
HANDY_DB_PATH = Path(os.environ.get("HANDY_DB_PATH", str(DEFAULT_HANDY_DB)))

# Laya Model
LAYA_MODEL = os.environ.get("LAYA_MODEL", "convaiinnovations/laya")

# Loop & timing settings
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "0.25"))
DUPLICATE_COOLDOWN_SECONDS = float(os.environ.get("DUPLICATE_COOLDOWN_SECONDS", "1.0"))
DEFAULT_WAIT_SECONDS = 2.0
BROWSER_TIMEOUT_MS = int(os.environ.get("BROWSER_TIMEOUT_MS", "5000"))
HIGHLIGHT_DURATION_MS = int(os.environ.get("HIGHLIGHT_DURATION_MS", "3000"))
# Briefly protects a browser input after LIGHT handles a TYPE command. This
# prevents Handy's delayed auto-typing event from appending the same text.
BROWSER_TYPE_GUARD_MS = int(os.environ.get("BROWSER_TYPE_GUARD_MS", "1200"))
CDP_DEBUG_PORT = int(os.environ.get("LIGHT_CDP_PORT", "9222"))
CDP_ENDPOINT_URL = f"http://127.0.0.1:{CDP_DEBUG_PORT}"

# Explicit stop phrases (never trust model prediction alone for STOP)
STOP_COMMANDS = {
    "stop",
    "stop light",
    "exit",
    "exit light",
    "quit",
    "quit light",
}

# Canonical website shortcuts used by decision engine and state tracker
WEBSITES = {
    "youtube": "https://youtube.com",
    "google": "https://google.com",
    "github": "https://github.com",
    "linkedin": "https://linkedin.com",
    "gmail": "https://gmail.com",
    "chatgpt": "https://chatgpt.com",
    "reddit": "https://reddit.com",
    "wikipedia": "https://wikipedia.org",
}

# Canonical Windows applications supported by AppController
KNOWN_APPS = {
    "brave": "Brave",
    "brave browser": "Brave",
    "chrome": "Chrome",
    "google chrome": "Chrome",
    "notepad": "Notepad",
    "calculator": "Calculator",
    "calc": "Calculator",
}


def get_brave_candidate_paths() -> list[Path]:
    """Return standard Windows installation paths for Brave Browser."""
    custom = os.environ.get("BRAVE_EXECUTABLE_PATH")
    paths = [Path(custom)] if custom else []
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_key, "")
        if base:
            paths.append(
                Path(base) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"
            )
    return paths


def get_chrome_candidate_paths() -> list[Path]:
    """Return standard Windows installation paths for Google Chrome."""
    custom = os.environ.get("CHROME_EXECUTABLE_PATH")
    paths = [Path(custom)] if custom else []
    for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env_key, "")
        if base:
            paths.append(
                Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            )
    return paths


WORKSPACE_PLAYWRIGHT_DIR = Path(__file__).resolve().parent / ".playwright-browsers"
if WORKSPACE_PLAYWRIGHT_DIR.exists() and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(WORKSPACE_PLAYWRIGHT_DIR)


def get_workspace_chromium_candidate_paths() -> list[Path]:
    """Return any Playwright-managed Chromium binaries stored inside the workspace."""
    candidates: list[Path] = []
    if WORKSPACE_PLAYWRIGHT_DIR.exists():
        candidates.extend(sorted(WORKSPACE_PLAYWRIGHT_DIR.glob("chromium-*/chrome-win64/chrome.exe")))
        candidates.extend(
            sorted(
                WORKSPACE_PLAYWRIGHT_DIR.glob(
                    "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"
                )
            )
        )
    return candidates
