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
        """Return details (hwnd, title, class_name, pid, process_name) of the foreground window."""
        info = {
            "hwnd": 0,
            "title": "",
            "class_name": "",
            "pid": 0,
            "process_name": "",
        }
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                info["hwnd"] = hwnd
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    info["title"] = buf.value.strip()

                class_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buf, 256)
                info["class_name"] = class_buf.value.strip()

                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                info["pid"] = pid.value
                if pid.value > 0:
                    try:
                        import psutil
                        info["process_name"] = psutil.Process(pid.value).name().lower()
                    except Exception:
                        pass
        except Exception as err:
            log_debug(f"Could not inspect foreground window: {err}")
        return info

    def is_browser_foreground(self, browser_controller=None) -> bool:
        """Return True if the current foreground window belongs to the browser."""
        info = self.get_foreground_window_info()
        proc = info.get("process_name", "")
        title = info.get("title", "").lower()
        class_name = info.get("class_name", "").lower()

        if proc in {"chrome.exe", "brave.exe", "msedge.exe", "chromium.exe"}:
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
        import time
        import ctypes

        user32 = ctypes.windll.user32
        target = app_name.lower().strip()
        canonical_map = {
            "notepad": ["notepad", "notepad.exe"],
            "calculator": ["calculator", "calc", "calc.exe", "calculatorapp.exe"],
            "chrome": ["chrome", "google chrome", "chrome.exe"],
            "brave": ["brave", "brave browser", "brave.exe"],
        }
        aliases = canonical_map.get(target, [target])

        deadline = time.time() + timeout
        while time.time() < deadline:
            # 1. Check current foreground first
            fg = self.get_foreground_window_info()
            fg_title = fg.get("title", "").lower()
            fg_proc = fg.get("process_name", "")
            if any(a in fg_title or a == fg_proc for a in aliases):
                return True

            # 2. Search open windows
            found_hwnd = None
            if gw is not None:
                try:
                    for win in gw.getAllWindows():
                        w_title = (win.title or "").strip().lower()
                        if any(a in w_title for a in aliases):
                            found_hwnd = getattr(win, "_hWnd", None)
                            if found_hwnd:
                                break
                except Exception:
                    pass

            if found_hwnd:
                try:
                    # Restore if minimized (SW_RESTORE = 9)
                    user32.ShowWindow(found_hwnd, 9)
                    user32.SetForegroundWindow(found_hwnd)
                except Exception:
                    pass
                time.sleep(0.08)
                fg = self.get_foreground_window_info()
                if fg.get("hwnd") == found_hwnd or any(a in fg.get("title", "").lower() for a in aliases):
                    return True

            time.sleep(0.1)

        return False

    def switch_to_window(self, target: str) -> bool:
        """Find and bring a window matching target to the foreground."""
        return self.wait_for_window_and_focus(target, timeout=2.0)

    def minimize_foreground_window(self) -> bool:
        """Minimize the currently active foreground window."""
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            # SW_MINIMIZE = 6
            ctypes.windll.user32.ShowWindow(hwnd, 6)
            return True
        return False

    def maximize_foreground_window(self) -> bool:
        """Maximize the currently active foreground window."""
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            # SW_MAXIMIZE = 3
            ctypes.windll.user32.ShowWindow(hwnd, 3)
            return True
        return False

    def restore_foreground_window(self) -> bool:
        """Restore the currently active foreground window."""
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            # SW_RESTORE = 9
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            return True
        return False

    def show_desktop(self) -> bool:
        """Show the Windows desktop (Win+D)."""
        pyautogui.hotkey("win", "d")
        return True

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
