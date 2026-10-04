"""
computer/platform_macos.py
macOS-specific implementation of the PlatformController.
Encapsulates AppleScript (osascript), open command, POSIX process management,
and macOS modifier key mappings without requiring heavy external binary dependencies.
"""

import os
from pathlib import Path
import re
import subprocess
import time

from computer.platform_base import PlatformController
from utils.logger import log_debug


class MacOSPlatformController(PlatformController):
    """macOS operating system controller."""

    @property
    def platform_name(self) -> str:
        return "macos"

    def get_app_launch_command(self, app_key: str, custom_executable: str | None = None) -> list[str]:
        if custom_executable:
            return [custom_executable]

        if app_key == "brave":
            return ["open", "-a", "Brave Browser"]
        if app_key == "chrome":
            return ["open", "-a", "Google Chrome"]
        if app_key == "notepad":
            return ["open", "-a", "TextEdit"]
        if app_key == "calculator":
            return ["open", "-a", "Calculator"]
        raise ValueError(f"Unknown application key: {app_key}")

    def get_app_close_commands(self, app_key: str, force: bool = False) -> list[list[str]]:
        if app_key == "brave":
            if force:
                return [["pkill", "-f", "Brave Browser"]]
            return [["osascript", "-e", 'tell application "Brave Browser" to quit']]
        if app_key == "chrome":
            if force:
                return [["pkill", "-f", "Google Chrome"]]
            return [["osascript", "-e", 'tell application "Google Chrome" to quit']]
        if app_key == "notepad":
            if force:
                return [["pkill", "-f", "TextEdit"]]
            return [["osascript", "-e", 'tell application "TextEdit" to quit']]
        if app_key == "calculator":
            if force:
                return [["pkill", "-f", "Calculator"]]
            return [["osascript", "-e", 'tell application "Calculator" to quit']]
        return []

    def get_browser_candidate_paths(self, browser_name: str) -> list[Path]:
        lowered = browser_name.lower().strip()
        paths: list[Path] = []
        if lowered == "brave":
            custom = os.environ.get("BRAVE_EXECUTABLE_PATH")
            if custom:
                paths.append(Path(custom))
            paths.extend([
                Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
                Path.home() / "Applications" / "Brave Browser.app" / "Contents" / "MacOS" / "Brave Browser",
            ])
        elif lowered == "chrome":
            custom = os.environ.get("CHROME_EXECUTABLE_PATH")
            if custom:
                paths.append(Path(custom))
            paths.extend([
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path.home() / "Applications" / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome",
            ])
        return paths

    def get_default_handy_db_path(self) -> Path:
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "com.pais.handy"
            / "history.db"
        )

    def set_dpi_awareness(self) -> None:
        # macOS compositor handles high-DPI (Retina) scaling automatically
        pass

    def get_screen_scale_factor(self) -> float:
        # Query display info via system_profiler or default to 2.0 on macOS Retina
        try:
            res = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if "Retina" in res.stdout:
                return 2.0
        except Exception:
            pass
        return 1.0

    def get_foreground_window_info(self) -> dict:
        info = {
            "hwnd": 0,
            "title": "",
            "class_name": "",
            "pid": 0,
            "process_name": "",
        }
        script = (
            'tell application "System Events"\n'
            '    try\n'
            '        set frontApp to first application process whose frontmost is true\n'
            '        set appName to name of frontApp\n'
            '        set winTitle to ""\n'
            '        try\n'
            '            set winTitle to name of window 1 of frontApp\n'
            '        end try\n'
            '        return appName & "|||" & winTitle\n'
            '    on error\n'
            '        return ""\n'
            '    end try\n'
            'end tell'
        )
        try:
            res = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2,
            )
            out = res.stdout.strip()
            if "|||" in out:
                app_name, win_title = out.split("|||", 1)
                info["process_name"] = app_name.strip().lower()
                info["title"] = win_title.strip()
        except Exception as err:
            log_debug(f"Could not inspect macOS foreground window: {err}")
        return info

    def wait_for_window_and_focus(self, app_name: str, timeout: float = 3.0) -> bool:
        target = app_name.lower().strip()
        app_names = {
            "notepad": "TextEdit",
            "calculator": "Calculator",
            "chrome": "Google Chrome",
            "google chrome": "Google Chrome",
            "brave": "Brave Browser",
            "brave browser": "Brave Browser",
        }
        mac_name = app_names.get(target, app_name)
        script = f'tell application "{mac_name}" to activate'

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
            except Exception:
                pass

            fg = self.get_foreground_window_info()
            fg_proc = fg.get("process_name", "")
            if mac_name.lower() in fg_proc or target in fg_proc:
                return True
            time.sleep(0.1)

        return False

    def minimize_foreground_window(self) -> bool:
        script = (
            'tell application "System Events"\n'
            '    try\n'
            '        set frontApp to first application process whose frontmost is true\n'
            '        set value of attribute "AXMinimized" of window 1 of frontApp to true\n'
            '        return "OK"\n'
            '    on error\n'
            '        return "ERROR"\n'
            '    end try\n'
            'end tell'
        )
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
            return "OK" in res.stdout
        except Exception:
            return False

    def maximize_foreground_window(self) -> bool:
        script = (
            'tell application "System Events"\n'
            '    try\n'
            '        set frontApp to first application process whose frontmost is true\n'
            '        set zoomed of window 1 of frontApp to true\n'
            '        return "OK"\n'
            '    on error\n'
            '        return "ERROR"\n'
            '    end try\n'
            'end tell'
        )
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
            return "OK" in res.stdout
        except Exception:
            return False

    def restore_foreground_window(self) -> bool:
        script = (
            'tell application "System Events"\n'
            '    try\n'
            '        set frontApp to first application process whose frontmost is true\n'
            '        set value of attribute "AXMinimized" of window 1 of frontApp to false\n'
            '        return "OK"\n'
            '    on error\n'
            '        return "ERROR"\n'
            '    end try\n'
            'end tell'
        )
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
            return "OK" in res.stdout
        except Exception:
            return False

    def show_desktop(self) -> bool:
        # F11 (key code 103) triggers macOS Show Desktop
        script = (
            'tell application "System Events"\n'
            '    try\n'
            '        key code 103\n'
            '        return "OK"\n'
            '    on error\n'
            '        return "ERROR"\n'
            '    end try\n'
            'end tell'
        )
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
            return "OK" in res.stdout
        except Exception:
            return False

    def map_hotkey(self, *keys: str) -> list[str]:
        mapped = []
        for key in keys:
            k = key.lower().strip()
            if k in ("ctrl", "control", "win", "windows", "super"):
                mapped.append("command")
            else:
                mapped.append(key)
        return mapped

    def get_process_scan_command(self, script_name: str) -> list[str]:
        return ["ps", "-eo", "pid,ppid,command"]

    def parse_process_scan_output(self, output: str) -> list[tuple[int, int]]:
        rows: list[tuple[int, int]] = []
        for line in (output or "").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 2)
            if len(parts) >= 3:
                pid_str, ppid_str, cmd = parts[0], parts[1], parts[2]
                if pid_str.isdigit() and ppid_str.isdigit():
                    if "python" in cmd.lower() and "main.py" in cmd:
                        rows.append((int(pid_str), int(ppid_str)))
        return rows

    def get_kill_pid_tree_command(self, pid: int) -> list[str]:
        return ["kill", "-9", str(pid)]

    def get_cursor_position_fallback(self, last_known_pos: tuple[int, int]) -> tuple[int, int]:
        return last_known_pos
