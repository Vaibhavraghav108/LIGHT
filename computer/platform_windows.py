"""
computer/platform_windows.py
Windows-specific implementation of the PlatformController.
Encapsulates Win32 APIs, ctypes, PowerShell CIM queries, and Windows system utilities.
"""

import os
from pathlib import Path
import time
import pyautogui

from computer.platform_base import PlatformController
from utils.logger import log_debug

try:
    import pygetwindow as gw
except ImportError:
    gw = None


class WindowsPlatformController(PlatformController):
    """Windows operating system controller."""

    @property
    def platform_name(self) -> str:
        return "windows"

    def get_app_launch_command(self, app_key: str, custom_executable: str | None = None) -> list[str]:
        if app_key in ("brave", "chrome"):
            if not custom_executable:
                raise ValueError(f"Custom executable path required to launch {app_key} on Windows.")
            return [custom_executable]
        if app_key == "notepad":
            return ["notepad.exe"]
        if app_key == "calculator":
            return ["calc.exe"]
        raise ValueError(f"Unknown application key: {app_key}")

    def get_app_close_commands(self, app_key: str, force: bool = False) -> list[list[str]]:
        if app_key == "brave":
            return [["taskkill", "/IM", "brave.exe", "/F"]] if force else []
        if app_key == "chrome":
            return [["taskkill", "/IM", "chrome.exe", "/F"]] if force else []
        if app_key == "notepad":
            return [["taskkill", "/IM", "notepad.exe", "/F"]] if force else []
        if app_key == "calculator":
            return [
                ["taskkill", "/IM", "CalculatorApp.exe", "/F"],
                ["taskkill", "/IM", "calc.exe", "/F"],
            ] if force else []
        return []

    def get_browser_candidate_paths(self, browser_name: str) -> list[Path]:
        lowered = browser_name.lower().strip()
        paths: list[Path] = []
        if lowered == "brave":
            custom = os.environ.get("BRAVE_EXECUTABLE_PATH")
            if custom:
                paths.append(Path(custom))
            for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                base = os.environ.get(env_key, "")
                if base:
                    paths.append(
                        Path(base) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"
                    )
        elif lowered == "chrome":
            custom = os.environ.get("CHROME_EXECUTABLE_PATH")
            if custom:
                paths.append(Path(custom))
            for env_key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                base = os.environ.get(env_key, "")
                if base:
                    paths.append(
                        Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
                    )
        return paths

    def get_default_handy_db_path(self) -> Path:
        return (
            Path.home()
            / "AppData"
            / "Roaming"
            / "com.pais.handy"
            / "history.db"
        )

    def set_dpi_awareness(self) -> None:
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    def get_screen_scale_factor(self) -> float:
        return 1.0

    def get_foreground_window_info(self) -> dict:
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

    def wait_for_window_and_focus(self, app_name: str, timeout: float = 3.0) -> bool:
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

            # 2. Search open windows via pygetwindow
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

    def minimize_foreground_window(self) -> bool:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            # SW_MINIMIZE = 6
            ctypes.windll.user32.ShowWindow(hwnd, 6)
            return True
        return False

    def maximize_foreground_window(self) -> bool:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            # SW_MAXIMIZE = 3
            ctypes.windll.user32.ShowWindow(hwnd, 3)
            return True
        return False

    def restore_foreground_window(self) -> bool:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if hwnd:
            # SW_RESTORE = 9
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            return True
        return False

    def show_desktop(self) -> bool:
        pyautogui.hotkey("win", "d")
        return True

    def map_hotkey(self, *keys: str) -> list[str]:
        return list(keys)

    def get_process_scan_command(self, script_name: str) -> list[str]:
        ps_cmd = (
            f'Get-CimInstance Win32_Process -Filter "Name LIKE \'python%\'" '
            f'| Where-Object {{ $_.CommandLine -match \'(^|[\\\\/"\\s]){script_name}(\\s|"|$)\' }} '
            '| ForEach-Object { "$($_.ProcessId):$($_.ParentProcessId)" }'
        )
        return ["powershell", "-NoProfile", "-Command", ps_cmd]

    def parse_process_scan_output(self, output: str) -> list[tuple[int, int]]:
        rows: list[tuple[int, int]] = []
        for line in (output or "").splitlines():
            line = line.strip()
            if ":" in line:
                p_str, pp_str = line.split(":", 1)
                if p_str.isdigit() and pp_str.isdigit():
                    rows.append((int(p_str), int(pp_str)))
            elif line.isdigit():
                rows.append((int(line), 0))
        return rows

    def get_kill_pid_tree_command(self, pid: int) -> list[str]:
        return ["taskkill", "/PID", str(pid), "/T", "/F"]

    def get_cursor_position_fallback(self, last_known_pos: tuple[int, int]) -> tuple[int, int]:
        try:
            import ctypes
            pt = (ctypes.c_long * 2)()
            ok = ctypes.windll.user32.GetCursorPos(pt)
            if ok == 0 and last_known_pos != (0, 0):
                return last_known_pos
        except Exception:
            pass
        return last_known_pos
