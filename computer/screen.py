from pathlib import Path
import pyautogui

from utils.logger import log_debug

try:
    import pygetwindow as gw
except ImportError:
    gw = None


class ScreenController:

    def get_active_window_title(self) -> str | None:
        """Return the title of the currently active Windows window."""
        if gw is None:
            return None
        try:
            window = gw.getActiveWindow()
            if window and window.title:
                return window.title.strip()
        except Exception as err:
            log_debug(f"Could not read active window title: {err}")
        return None

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
