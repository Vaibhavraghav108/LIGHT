from pathlib import Path
import pyautogui

from computer.platform_factory import get_platform_controller
from utils.logger import log_debug

try:
    import pygetwindow as gw
except ImportError:
    gw = None


class ScreenController:

    def __init__(self, platform=None):
        self.platform = platform if platform is not None else get_platform_controller()

    def get_active_window_title(self) -> str | None:
        """Return the title of the currently active window."""
        info = self.get_foreground_window_info()
        if info.get("title"):
            return info["title"]
        if gw is None:
            return None
        try:
            window = gw.getActiveWindow()
            if window and window.title:
                return window.title.strip()
        except Exception as err:
            log_debug(f"Could not read active window title: {err}")
        return None

    def get_foreground_window_info(self) -> dict:
        """Return details (hwnd/id, title, class_name, pid, process_name) of the foreground window."""
        return self.platform.get_foreground_window_info()

    def is_browser_foreground(self, browser_controller=None) -> bool:
        """Return True if the current foreground window belongs to the browser."""
        info = self.get_foreground_window_info()
        proc = info.get("process_name", "")
        title = info.get("title", "").lower()
        class_name = info.get("class_name", "").lower()

        if proc in {"chrome.exe", "brave.exe", "msedge.exe", "chromium.exe", "google chrome", "brave browser", "brave", "chrome"}:
            return True
        if "chrome" in class_name or "brave" in class_name:
            return True

        if browser_controller is not None and browser_controller.is_active():
            b_title = (browser_controller.get_title() or "").strip().lower()
            if b_title and b_title in title:
                return True

        return False

    def wait_for_window_and_focus(self, app_name: str, timeout: float = 3.0) -> bool:
        """Wait for a window matching app_name to exist and bring it to the foreground."""
        return self.platform.wait_for_window_and_focus(app_name, timeout=timeout)

    def switch_to_window(self, target: str) -> bool:
        """Find and bring a window matching target to the foreground."""
        return self.wait_for_window_and_focus(target, timeout=2.0)

    def minimize_foreground_window(self) -> bool:
        """Minimize the currently active foreground window."""
        return self.platform.minimize_foreground_window()

    def maximize_foreground_window(self) -> bool:
        """Maximize the currently active foreground window."""
        return self.platform.maximize_foreground_window()

    def restore_foreground_window(self) -> bool:
        """Restore the currently active foreground window."""
        return self.platform.restore_foreground_window()

    def show_desktop(self) -> bool:
        """Show the desktop / minimize all windows."""
        return self.platform.show_desktop()

    def get_screen_size(self) -> tuple[int, int]:
        """Return (width, height) of the primary screen."""
        size = pyautogui.size()
        return int(size[0]), int(size[1])

    def get_mouse_position(self) -> tuple[int, int]:
        """Return current (x, y) coordinates of the mouse."""
        pos = pyautogui.position()
        return int(pos[0]), int(pos[1])

    def take_screenshot(self, path: str | None = None):
        """Capture a screenshot and optionally save it to a file."""
        image = pyautogui.screenshot()
        if path:
            output = Path(path)
            output.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(output))
        return image
