import time

from brain.commands import Action, Command
from browser.browser import BrowserController
from computer.apps import AppController
from computer.keyboard import KeyboardController
from computer.mouse import MouseController
from computer.screen import ScreenController
from config import DEFAULT_WAIT_SECONDS
from core.state import LightState
from utils.logger import log_executor


class Executor:

    def __init__(self, state: LightState | None = None):
        self.apps = AppController()
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.browser = BrowserController()
        self.screen = ScreenController()
        self.state = state if state is not None else LightState()

    def execute(self, command: Command, raw_text: str | None = None) -> str:
        action = command.action
        target = command.target

        # ==========================================
        # APPLICATIONS
        # ==========================================

        if action == Action.OPEN_APP:
            if target and target.lower().strip() in {
                "brave",
                "brave browser",
                "chrome",
                "google chrome",
            }:
                self.browser.start()
                self.state.current_browser = "chrome"
                self.state.current_app = "chrome"
                self.state.browser_open = True
                log_executor("Started Playwright Chromium/Chrome browser session.")
            else:
                self.apps.open(target)

        elif action == Action.CLOSE_APP:
            if target and any(b in target.lower() for b in ("brave", "chrome")):
                self.browser.close()
                self.state.browser_open = False
                self.state.current_browser = None
            else:
                self.apps.close(target)

        # ==========================================
        # KEYBOARD
        # ==========================================

        elif action == Action.TYPE:
            if self.browser.is_active() and self.browser.type_in_browser(target):
                pass
            else:
                self.keyboard.type_text(target)

        elif action == Action.PRESS_KEY:
            self.keyboard.press(target)

        # ==========================================
        # MOUSE & SCROLL
        # ==========================================

        elif action == Action.CLICK:
            self.mouse.click()

        elif action == Action.SCROLL:
            if self.browser.is_active():
                self.browser.scroll(target)
            else:
                self.mouse.scroll(target)

        elif action == Action.MOVE_MOUSE:
            if not target:
                raise ValueError("No mouse movement target specified.")

            if self.mouse.can_handle_directly(target):
                self.mouse.move_by_command(target)
            else:
                self.browser.move_mouse_to_element(target, self.mouse)

        # ==========================================
        # PLAYWRIGHT CHROMIUM / CHROME AUTOMATION
        # ==========================================

        elif action == Action.OPEN_URL:
            self.browser.open_url(target)

        elif action == Action.GO_BACK:
            self.browser.go_back()

        elif action == Action.GO_FORWARD:
            self.browser.go_forward()

        elif action == Action.REFRESH:
            self.browser.refresh()

        elif action == Action.SEARCH:
            if not target:
                raise ValueError("No search query provided.")

            if target.lower().startswith("youtube:"):
                query = target[8:].strip()
                self.browser.search(query, engine="youtube")
            elif target.lower().startswith("google:"):
                query = target[7:].strip()
                self.browser.search(query, engine="google")
            elif self.state.current_site == "youtube":
                self.browser.search(target, engine="youtube")
            else:
                self.browser.search(target)

        elif action == Action.CLICK_RESULT:
            index = int(target) if target and str(target).isdigit() else 1
            try:
                self.browser.click_result(index, mouse_controller=self.mouse)
            except TypeError:
                self.browser.click_result(index)

        elif action == Action.CLICK_ELEMENT:
            try:
                self.browser.click_element(target, mouse_controller=self.mouse)
            except TypeError:
                self.browser.click_element(target)

        elif action == Action.FIND_ELEMENT:
            self.browser.find_element(target)

        elif action == Action.READ_TITLE:
            if self.browser.is_active():
                self.browser.get_title()
            else:
                title = self.screen.get_active_window_title() or "Unknown Window"
                log_executor(f"Active window title: {title}")

        elif action == Action.READ_TEXT:
            self.browser.get_visible_text()

        elif action == Action.COPY_TEXT:
            if self.browser.is_active() or target:
                self.browser.copy_text_range(target)
            else:
                import pyautogui
                pyautogui.hotkey("ctrl", "c")

        elif action == Action.PASTE:
            import pyautogui
            pyautogui.hotkey("ctrl", "v")

        # ==========================================
        # WAIT
        # ==========================================

        elif action == Action.WAIT:
            seconds = float(target) if target else DEFAULT_WAIT_SECONDS
            log_executor(f"Waiting {seconds} seconds...")
            time.sleep(seconds)

        # ==========================================
        # STOP
        # ==========================================

        elif action == Action.STOP:
            self.browser.close()
            return "STOP"

        else:
            raise ValueError(f"Unsupported action: {action}")

        # Update short-term context and observation state
        self.state.record_command(raw_text, command)
        self.state.sync_observation(browser=self.browser, screen=self.screen)

        return "OK"
