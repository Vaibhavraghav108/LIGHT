import time
from urllib.parse import quote_plus

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

    def _native_browser_selected(self) -> bool:
        """
        Return True if commands should use the Native Browser Fallback (Ctrl+F highlight homing
        + keyboard focus-click) because a native Brave/Chrome window is active without a CDP session.
        Automatically attaches over CDP first if port 9222 is reachable.
        """
        if self.browser.is_active():
            return False
        if (self.state.current_browser or "").lower() not in {
            "brave",
            "brave browser",
            "chrome",
            "google chrome",
        }:
            return False
        if isinstance(self.browser, BrowserController) and self.browser.try_connect_cdp():
            return False
        return True

    def _ensure_native_browser(self):
        """Open the user's normal Brave window (with CDP port enabled) when no browser mode exists yet."""
        if self.browser.is_active():
            return
        if isinstance(self.browser, BrowserController) and self.browser.try_connect_cdp():
            self.state.current_browser = "brave"
            self.state.current_app = "brave"
            self.state.browser_open = True
            return
        if (self.state.current_browser or "").lower() not in {
            "brave",
            "brave browser",
            "chrome",
            "google chrome",
        }:
            self.apps.open_browser_window("Brave")
            self.state.current_browser = "brave"
            self.state.current_app = "brave"
            self.state.browser_open = True
            if isinstance(self.browser, BrowserController):
                time.sleep(0.35)
                self.browser.try_connect_cdp()

    def _navigate_native_browser(self, url: str):
        """Navigate the focused normal browser window without Playwright."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self.keyboard.hotkey("ctrl", "l")
        self.keyboard.type_text(url)
        self.keyboard.press("enter")

    def _find_highlight_on_screen(self) -> tuple[int, int] | None:
        """Locate Chromium's Ctrl+F orange/yellow match highlight on the physical screen."""
        try:
            img = self.screen.take_screenshot()
            if img is None or not hasattr(img, "size"):
                return None
            width, height = img.size
            rgb_img = img.convert("RGB")
            pixels = rgb_img.load()

            # Skip the top 115px (browser tabs, address bar, and Ctrl+F find box itself)
            start_y = min(115, height // 6)
            orange_xs: list[int] = []
            orange_ys: list[int] = []
            yellow_xs: list[int] = []
            yellow_ys: list[int] = []

            for y in range(start_y, height - 10, 2):
                for x in range(10, width - 10, 2):
                    r, g, b = pixels[x, y]
                    # Chromium active find match highlight (#FF9632 / RGB(255, 150, 50))
                    if r >= 220 and 115 <= g <= 185 and b <= 90:
                        orange_xs.append(x)
                        orange_ys.append(y)
                    # Chromium inactive find match highlight (#FFFF00 / RGB(255, 255, 0))
                    elif r >= 230 and g >= 215 and b <= 60:
                        yellow_xs.append(x)
                        yellow_ys.append(y)

            if len(orange_xs) >= 3:
                return int(sum(orange_xs) / len(orange_xs)), int(sum(orange_ys) / len(orange_ys))
            if len(yellow_xs) >= 3:
                return int(sum(yellow_xs) / len(yellow_xs)), int(sum(yellow_ys) / len(yellow_ys))
        except Exception:
            return None
        return None

    def _native_browser_find_element(
        self,
        target: str,
        close_find_bar: bool = True,
    ) -> tuple[int, int] | None:
        """Use Chromium's Ctrl+F in-page search to scroll to, highlight, and focus a target element."""
        import pyperclip

        parsed = self.browser.parse_element_target(target)
        query = (parsed.get("query") or target or "").strip()
        query_lower = query.lower()
        if query_lower in BrowserController.ELEMENT_ALIASES:
            query = BrowserController.ELEMENT_ALIASES[query_lower][0]

        if not query:
            return None

        old_clip = None
        try:
            old_clip = pyperclip.paste()
        except Exception:
            pass

        try:
            self.keyboard.hotkey("ctrl", "f")
            time.sleep(0.08)
            try:
                pyperclip.copy(query)
                self.keyboard.hotkey("ctrl", "v")
            except Exception:
                self.keyboard.type_text(query)
            time.sleep(0.22)

            coords = self._find_highlight_on_screen()

            if close_find_bar:
                # In Brave/Chrome, Escape closes the Find bar and transfers DOM focus
                # directly onto the link/button containing the active match.
                self.keyboard.press("escape")
                time.sleep(0.06)

            return coords
        finally:
            if old_clip is not None:
                try:
                    pyperclip.copy(old_clip)
                except Exception:
                    pass

    def _native_browser_click_result(self, index: int = 1):
        """Click the Nth visible result or video in native Brave mode without launching Playwright."""
        if index < 1:
            index = 1
        sw, sh = self.mouse.get_screen_size()
        # Position on the Nth result card in the main content feed
        target_x = int(sw * 0.42)
        target_y = int(min(sh - 80, 260 + (index - 1) * 180))
        self.mouse.move(target_x, target_y, duration=0.2)
        self.mouse.click(target_x, target_y)

    def _native_browser_click_element(self, target: str):
        """Locate and click a target element in native Brave mode without spawning Playwright."""
        parsed = self.browser.parse_element_target(target)
        kind = parsed.get("kind")
        index = int(parsed.get("index", 1))
        sw, sh = self.mouse.get_screen_size()

        if kind == "search_bar":
            # '/' focuses the search input on YouTube and many web apps
            self.keyboard.press("/")
            return

        if kind == "nth_short":
            coords = self._native_browser_find_element("Shorts", close_find_bar=True)
            if coords is not None:
                hx, hy = coords
                card_x = min(sw - 40, hx + (index - 1) * 230 + 70)
                card_y = min(sh - 40, hy + 190)
            else:
                card_x = int(sw * min(0.85, 0.35 + (index - 1) * 0.18))
                card_y = int(sh * 0.55)
            self.mouse.move(card_x, card_y, duration=0.2)
            self.mouse.click(card_x, card_y)
            return

        if kind == "nth_result":
            self._native_browser_click_result(index)
            return

        coords = self._native_browser_find_element(target, close_find_bar=True)
        if coords is not None:
            cx, cy = coords
            self.mouse.move(cx, cy, duration=0.2)
            self.mouse.click(cx, cy)
        else:
            # Pressing Enter activates the link/button focused by Ctrl+F -> Escape in Brave/Chrome
            self.keyboard.press("enter")

    def execute(self, command: Command, raw_text: str | None = None) -> str:
        action = command.action
        target = command.target

        # ==========================================
        # APPLICATIONS
        # ==========================================

        if action == Action.OPEN_APP:
            # Browser commands must use the Playwright-controlled session.
            # Launching Brave with AppController here created a separate normal
            # browser window, while later SEARCH/OPEN_URL commands created a
            # second Playwright window. Starting the controller directly keeps
            # the entire voice workflow in one browser session.
            if target and target.lower().strip() in {"brave", "brave browser", "chrome", "google chrome"}:
                self.apps.open_browser_window(target)
                log_executor("Opened a normal browser window using your existing profile.")
            else:
                self.apps.open(target)

        elif action == Action.CLOSE_APP:
            if target and any(b in target.lower() for b in ("brave", "chrome")):
                # Do not call AppController.close for browsers: this session is
                # owned by BrowserController, and normal user browser windows
                # must remain untouched.
                self.browser.close()
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
            elif self._native_browser_selected():
                coords = self._native_browser_find_element(target, close_find_bar=True)
                if coords is not None:
                    self.mouse.move(coords[0], coords[1], duration=0.25)
            else:
                self.browser.move_mouse_to_element(target, self.mouse)

        # ==========================================
        # BROWSER NAVIGATION & INTERACTION
        # ==========================================

        elif action == Action.OPEN_URL:
            if self.browser.is_active():
                self.browser.open_url(target)
            else:
                self._ensure_native_browser()
                self._navigate_native_browser(target)

        elif action == Action.GO_BACK:
            if self.browser.is_active():
                self.browser.go_back()
            elif self._native_browser_selected():
                self.keyboard.hotkey("alt", "left")
            else:
                raise ValueError("Open Brave first to navigate in native browser mode.")

        elif action == Action.GO_FORWARD:
            if self.browser.is_active():
                self.browser.go_forward()
            elif self._native_browser_selected():
                self.keyboard.hotkey("alt", "right")
            else:
                raise ValueError("Open Brave first to navigate in native browser mode.")

        elif action == Action.REFRESH:
            if self.browser.is_active():
                self.browser.refresh()
            elif self._native_browser_selected():
                self.keyboard.hotkey("ctrl", "r")
            else:
                raise ValueError("Open Brave first to refresh in native browser mode.")

        elif action == Action.SEARCH:
            if not target:
                raise ValueError("No search query provided.")

            if self.browser.is_active():
                if target.lower().startswith("youtube:"):
                    self.browser.search(target[8:].strip(), engine="youtube")
                elif target.lower().startswith("google:"):
                    self.browser.search(target[7:].strip(), engine="google")
                elif self.state.current_site == "youtube":
                    self.browser.search(target, engine="youtube")
                else:
                    self.browser.search(target)
            else:
                self._ensure_native_browser()
                if target.lower().startswith("youtube:"):
                    url = f"https://www.youtube.com/results?search_query={quote_plus(target[8:].strip())}"
                elif target.lower().startswith("google:"):
                    url = f"https://www.google.com/search?q={quote_plus(target[7:].strip())}"
                elif self.state.current_site == "youtube":
                    url = f"https://www.youtube.com/results?search_query={quote_plus(target)}"
                else:
                    url = f"https://www.google.com/search?q={quote_plus(target)}"
                self._navigate_native_browser(url)

        elif action == Action.CLICK_RESULT:
            index = int(target) if target and str(target).isdigit() else 1
            if self._native_browser_selected():
                self._native_browser_click_result(index)
            else:
                self.browser.click_result(index)

        elif action == Action.CLICK_ELEMENT:
            if self._native_browser_selected():
                self._native_browser_click_element(target)
            else:
                try:
                    self.browser.click_element(target, mouse_controller=self.mouse)
                except TypeError:
                    self.browser.click_element(target)

        elif action == Action.FIND_ELEMENT:
            if self._native_browser_selected():
                coords = self._native_browser_find_element(target, close_find_bar=False)
                if coords is not None:
                    self.mouse.move(coords[0], coords[1], duration=0.2)
            else:
                self.browser.find_element(target)

        elif action == Action.READ_TITLE:
            if self.browser.is_active():
                title = self.browser.get_title()
            else:
                title = self.screen.get_active_window_title() or "Unknown Window"
                log_executor(f"Active window title: {title}")

        elif action == Action.READ_TEXT:
            if self._native_browser_selected():
                raise ValueError("'Read page text' needs DOM automation and is unavailable in native Brave mode.")
            self.browser.get_visible_text()

        elif action == Action.COPY_TEXT:
            if self._native_browser_selected():
                if target:
                    raise ValueError("'Copy from ... till ...' needs DOM automation and is unavailable in native Brave mode.")
                import pyautogui
                pyautogui.hotkey("ctrl", "c")
            elif self.browser.is_active():
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
