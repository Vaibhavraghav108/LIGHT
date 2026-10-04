import threading
from dataclasses import dataclass, field
from enum import Enum
from brain.commands import Command, Action
from config import WEBSITES


class BrowserOwnership(str, Enum):
    NONE = "none"
    LIGHT = "light"
    AGENT = "agent"


@dataclass
class LightState:
    """Thread-safe short-term state and observation tracking for LIGHT."""
    current_app: str | None = None
    current_browser: str | None = None
    browser_open: bool = False
    browser_ownership: str = BrowserOwnership.NONE.value
    current_url: str | None = None
    current_title: str | None = None
    current_site: str | None = None
    current_task: str | None = None
    active_window: str | None = None
    foreground_window: dict | None = None
    media_context: str | None = None
    agent_running: bool = False
    mouse_position: tuple[int, int] | None = None
    previous_command: str | None = None
    last_action: str | None = None
    last_search_query: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    recent_commands: list[dict] = field(default_factory=list)
    pending_incomplete_action: str | None = None
    pending_goal: str | None = None

    def __post_init__(self):
        self._lock = threading.RLock()

    def infer_site_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        url_lower = url.lower()
        for site in WEBSITES:
            if site in url_lower:
                return site
        return None

    def snapshot(self) -> dict:
        """Return a thread-safe read-only dictionary snapshot of current state."""
        with self._lock:
            return {
                "current_app": self.current_app,
                "current_browser": self.current_browser,
                "browser_open": self.browser_open,
                "browser_ownership": self.browser_ownership,
                "current_url": self.current_url,
                "current_title": self.current_title,
                "current_site": self.current_site,
                "current_task": self.current_task,
                "active_window": self.active_window,
                "foreground_window": dict(self.foreground_window) if self.foreground_window else None,
                "media_context": self.media_context,
                "agent_running": self.agent_running,
                "mouse_position": self.mouse_position,
                "previous_command": self.previous_command,
                "last_action": self.last_action,
                "last_search_query": self.last_search_query,
                "last_status": self.last_status,
                "last_error": self.last_error,
                "recent_commands": list(self.recent_commands[-10:]),
                "pending_incomplete_action": self.pending_incomplete_action,
                "pending_goal": self.pending_goal,
            }

    def clone_for_planning(self) -> "LightState":
        """Create a lightweight isolated copy for multi-step command planning."""
        with self._lock:
            return LightState(
                current_app=self.current_app,
                current_browser=self.current_browser,
                browser_open=self.browser_open,
                browser_ownership=self.browser_ownership,
                current_url=self.current_url,
                current_title=self.current_title,
                current_site=self.current_site,
                current_task=self.current_task,
                active_window=self.active_window,
                foreground_window=dict(self.foreground_window) if self.foreground_window else None,
                media_context=self.media_context,
                agent_running=self.agent_running,
                mouse_position=self.mouse_position,
                previous_command=self.previous_command,
                last_action=self.last_action,
                last_search_query=self.last_search_query,
                last_status=self.last_status,
                last_error=self.last_error,
                recent_commands=list(self.recent_commands[-10:]),
                pending_incomplete_action=self.pending_incomplete_action,
                pending_goal=self.pending_goal,
            )

    def record_command(self, raw_text: str | None, command: Command):
        """Update state based on a successfully executed command."""
        with self._lock:
            def mark_light_browser_owner():
                # The autonomous agent uses an isolated browser session, while
                # deterministic browser commands may continue concurrently.
                # Keep AGENT ownership truthful until that worker actually exits.
                self.browser_ownership = (
                    BrowserOwnership.AGENT.value
                    if self.agent_running
                    else BrowserOwnership.LIGHT.value
                )

            if raw_text:
                self.previous_command = raw_text
            self.last_action = command.action.value
            self.last_status = "STOP" if command.action == Action.STOP else "OK"
            self.last_error = None

            self.recent_commands.append(
                {
                    "text": raw_text or "",
                    "action": command.action.value,
                    "target": command.target,
                    "status": self.last_status,
                }
            )
            if len(self.recent_commands) > 25:
                self.recent_commands = self.recent_commands[-25:]

            if command.action == Action.OPEN_APP and command.target:
                app = command.target.lower().strip()
                self.current_app = app
                self.current_task = f"using {app}"
                if "brave" in app or "chrome" in app:
                    self.current_browser = app

            elif command.action == Action.SWITCH_WINDOW and command.target:
                app = command.target.lower().strip()
                self.current_app = app
                self.active_window = command.target
                self.current_task = f"switched to {app}"

            elif command.action == Action.CLOSE_APP and command.target:
                app = command.target.lower().strip()
                if self.current_app == app:
                    self.current_app = None
                if self.current_browser and app in self.current_browser:
                    self.current_browser = None
                    self.browser_open = False
                    self.browser_ownership = BrowserOwnership.NONE.value
                    self.current_url = None
                    self.current_site = None

            elif command.action == Action.OPEN_URL and command.target:
                self.current_app = "brave"
                self.current_browser = "brave"
                self.browser_open = True
                mark_light_browser_owner()
                self.current_url = command.target
                site = self.infer_site_from_url(command.target)
                self.current_site = site
                self.current_task = f"browsing {site or command.target}"

            elif command.action == Action.SEARCH and command.target:
                self.current_app = "brave"
                self.current_browser = "brave"
                self.browser_open = True
                mark_light_browser_owner()
                if command.target.lower().startswith("youtube:"):
                    self.current_site = "youtube"
                    self.last_search_query = command.target[8:].strip()
                elif command.target.lower().startswith("google:"):
                    self.current_site = "google"
                    self.last_search_query = command.target[7:].strip()
                elif command.target.lower().startswith("github:"):
                    self.current_site = "github"
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
                mark_light_browser_owner()

            elif command.action in {
                Action.MEDIA_PLAY_PAUSE,
                Action.MEDIA_FORWARD,
                Action.MEDIA_BACKWARD,
                Action.MEDIA_FULLSCREEN,
                Action.MEDIA_EXIT_FULLSCREEN,
                Action.MEDIA_MUTE,
                Action.MEDIA_VOLUME_UP,
                Action.MEDIA_VOLUME_DOWN,
                Action.MEDIA_NEXT,
                Action.MEDIA_PREVIOUS,
            }:
                self.media_context = "video"

            elif command.action == Action.AGENT_TASK:
                self.current_task = f"agent: {command.target}"
                if not self.agent_running:
                    if self.browser_open:
                        self.browser_ownership = BrowserOwnership.LIGHT.value
                    else:
                        self.browser_ownership = BrowserOwnership.NONE.value
                else:
                    self.browser_ownership = BrowserOwnership.AGENT.value

            elif command.action == Action.STOP:
                self.browser_open = False
                self.current_browser = None
                self.browser_ownership = BrowserOwnership.NONE.value
                self.current_url = None
                self.current_title = None
                self.current_site = None
                if self.current_app in {"brave", "chrome", "browser", "chromium"}:
                    self.current_app = None
                self.agent_running = False
                self.pending_incomplete_action = None
                self.pending_goal = None
            else:
                self.pending_incomplete_action = None

    def set_browser_ownership(self, owner: BrowserOwnership | str):
        """Set active browser session owner (NONE, LIGHT, or AGENT)."""
        with self._lock:
            if isinstance(owner, BrowserOwnership):
                self.browser_ownership = owner.value
            else:
                self.browser_ownership = str(owner).lower()

    def get_browser_ownership(self) -> str:
        """Get active browser session owner."""
        with self._lock:
            return self.browser_ownership

    def record_failure(self, raw_text: str | None, status: str, error_message: str):
        """Record an ignored or failed command without losing browser/app context."""
        with self._lock:
            if raw_text:
                self.previous_command = raw_text
            self.last_status = status
            self.last_error = error_message

    def sync_observation(self, browser=None, screen=None):
        """Refresh state from active browser DOM or screen window when available."""
        url = None
        title = None
        browser_active = False
        if browser is not None and browser.is_active():
            browser_active = True
            url = browser.get_current_url()
            title = browser.get_title()

        active_win = None
        fg_info = None
        mouse_pos = None
        if screen is not None:
            if hasattr(screen, "get_foreground_window_info"):
                try:
                    fg_info = screen.get_foreground_window_info()
                    active_win = fg_info.get("title")
                except Exception:
                    pass
            if not active_win and hasattr(screen, "get_active_window_title"):
                active_win = screen.get_active_window_title()
            if hasattr(screen, "get_mouse_position"):
                try:
                    mouse_pos = screen.get_mouse_position()
                except Exception:
                    mouse_pos = None

        with self._lock:
            if browser_active:
                self.browser_open = True
                if not self.current_browser:
                    self.current_browser = "chromium"
                if url:
                    self.current_url = url
                    inferred = self.infer_site_from_url(url)
                    if inferred:
                        self.current_site = inferred
                if title:
                    self.current_title = title

            if fg_info:
                self.foreground_window = fg_info
                proc = fg_info.get("process_name", "").lower()
                if "notepad" in proc:
                    self.current_app = "notepad"
                elif "calc" in proc:
                    self.current_app = "calculator"
                elif proc in {"chrome.exe", "brave.exe", "msedge.exe"}:
                    self.current_app = "chrome" if "chrome" in proc else "brave"

            if active_win:
                self.active_window = active_win
                if not self.current_title:
                    self.current_title = active_win
            if mouse_pos is not None:
                self.mouse_position = mouse_pos

