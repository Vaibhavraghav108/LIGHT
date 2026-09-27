from dataclasses import dataclass
from brain.commands import Command, Action
from config import WEBSITES


@dataclass
class LightState:
    """Short-term state and observation tracking for LIGHT."""
    current_app: str | None = None
    current_browser: str | None = None
    browser_open: bool = False
    current_url: str | None = None
    current_title: str | None = None
    current_site: str | None = None
    current_task: str | None = None
    previous_command: str | None = None
    last_action: str | None = None
    last_search_query: str | None = None
    last_status: str | None = None
    last_error: str | None = None

    def infer_site_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        url_lower = url.lower()
        for site in WEBSITES:
            if site in url_lower:
                return site
        return None

    def record_command(self, raw_text: str | None, command: Command):
        """Update state based on a successfully executed command."""
        if raw_text:
            self.previous_command = raw_text
        self.last_action = command.action.value
        self.last_status = "STOP" if command.action == Action.STOP else "OK"
        self.last_error = None

        if command.action == Action.OPEN_APP and command.target:
            app = command.target.lower().strip()
            self.current_app = app
            self.current_task = f"using {app}"
            if "brave" in app or "chrome" in app:
                self.current_browser = app

        elif command.action == Action.CLOSE_APP and command.target:
            app = command.target.lower().strip()
            if self.current_app == app:
                self.current_app = None
            if self.current_browser and app in self.current_browser:
                self.current_browser = None
                self.browser_open = False
                self.current_url = None
                self.current_site = None

        elif command.action == Action.OPEN_URL and command.target:
            self.current_app = "brave"
            self.current_browser = "brave"
            self.browser_open = True
            self.current_url = command.target
            site = self.infer_site_from_url(command.target)
            self.current_site = site
            self.current_task = f"browsing {site or command.target}"

        elif command.action == Action.SEARCH and command.target:
            self.current_app = "brave"
            self.current_browser = "brave"
            self.browser_open = True
            if command.target.lower().startswith("youtube:"):
                self.current_site = "youtube"
                self.last_search_query = command.target[8:].strip()
            elif command.target.lower().startswith("google:"):
                self.current_site = "google"
                self.last_search_query = command.target[7:].strip()
            else:
                if not self.current_site:
                    self.current_site = "google"
                self.last_search_query = command.target
            self.current_task = f"searching {self.current_site} for {self.last_search_query}"

        elif command.action in {
            Action.CLICK_RESULT,
            Action.CLICK_ELEMENT,
            Action.FIND_ELEMENT,
            Action.GO_BACK,
            Action.GO_FORWARD,
            Action.REFRESH,
            Action.COPY_TEXT,
            Action.READ_TEXT,
        }:
            self.current_app = "brave"
            self.current_browser = "brave"
            self.browser_open = True

        elif command.action == Action.STOP:
            self.browser_open = False
            self.current_browser = None

    def record_failure(self, raw_text: str | None, status: str, error_message: str):
        """Record an ignored or failed command without losing browser/app context."""
        if raw_text:
            self.previous_command = raw_text
        self.last_status = status
        self.last_error = error_message

    def sync_observation(self, browser=None, screen=None):
        """Refresh state from active browser DOM or screen window when available."""
        if browser is not None and browser.is_active():
            self.browser_open = True
            self.current_browser = "brave"
            url = browser.get_current_url()
            if url:
                self.current_url = url
                inferred = self.infer_site_from_url(url)
                if inferred:
                    self.current_site = inferred
            title = browser.get_title()
            if title:
                self.current_title = title
        # An inactive BrowserController can mean that LIGHT is intentionally
        # using native-browser mode. Do not erase that state merely because a
        # Playwright session is absent.

        if screen is not None:
            active_win = screen.get_active_window_title()
            if active_win and not self.current_title:
                self.current_title = active_win
