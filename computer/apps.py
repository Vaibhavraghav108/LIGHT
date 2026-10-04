import os
import subprocess
from computer.platform_factory import get_platform_controller
from config import get_brave_candidate_paths, get_chrome_candidate_paths
from utils.logger import log_debug, log_warning


class AppController:

    def __init__(self, platform=None):
        self.platform = platform if platform is not None else get_platform_controller()
        self._launched_processes: dict[str, list[subprocess.Popen]] = {
            "brave": [],
            "chrome": [],
            "notepad": [],
            "calculator": [],
        }

    @staticmethod
    def _canonical_app_key(app_name: str) -> str:
        lowered = app_name.lower().strip()
        if lowered in ("brave", "brave browser"):
            return "brave"
        if lowered in ("chrome", "google chrome"):
            return "chrome"
        if lowered == "notepad":
            return "notepad"
        if lowered in ("calculator", "calc"):
            return "calculator"
        raise ValueError(f"Unknown application: {app_name}")

    def find_brave_executable(self) -> str:
        for path in get_brave_candidate_paths():
            if path.exists():
                return str(path)
        raise FileNotFoundError(
            "Brave Browser was not found on this computer. Set BRAVE_EXECUTABLE_PATH in .env if installed in a custom location."
        )

    def find_chrome_executable(self) -> str:
        for path in get_chrome_candidate_paths():
            if path.exists():
                return str(path)
        raise FileNotFoundError(
            "Google Chrome was not found on this computer. Set CHROME_EXECUTABLE_PATH in .env if installed in a custom location."
        )

    def open(self, app_name: str, wait_and_focus: bool = True, screen_controller=None):
        if not app_name or not app_name.strip():
            raise ValueError("No application specified.")

        key = self._canonical_app_key(app_name)

        if key == "brave":
            proc = subprocess.Popen([self.find_brave_executable()])
        elif key == "chrome":
            proc = subprocess.Popen([self.find_chrome_executable()])
        elif key in ("notepad", "calculator"):
            cmd = self.platform.get_app_launch_command(key)
            proc = subprocess.Popen(cmd)
        else:
            raise ValueError(f"Unknown application: {app_name}")

        self._launched_processes.setdefault(key, []).append(proc)

        if wait_and_focus and key in ("notepad", "calculator"):
            if screen_controller is not None:
                screen_controller.wait_for_window_and_focus(key, timeout=3.0)
            else:
                from computer.screen import ScreenController
                ScreenController().wait_for_window_and_focus(key, timeout=3.0)

        return proc

    def open_browser_window(self, app_name: str):
        """Open a normal browser window using the user's existing profile with CDP debugging enabled."""
        from config import CDP_DEBUG_PORT

        key = self._canonical_app_key(app_name)
        if key == "brave":
            executable = self.find_brave_executable()
        elif key == "chrome":
            executable = self.find_chrome_executable()
        else:
            raise ValueError(f"Native browser mode requires Brave or Chrome, not: {app_name}")

        proc = subprocess.Popen(
            [executable, f"--remote-debugging-port={CDP_DEBUG_PORT}", "--new-window"]
        )
        self._launched_processes.setdefault(key, []).append(proc)
        return proc

    def close(self, app_name: str, force: bool = False) -> int:
        if not app_name or not app_name.strip():
            raise ValueError("No application specified.")

        key = self._canonical_app_key(app_name)
        force_opt_in = force or os.environ.get("LIGHT_FORCE_KILL_BROWSERS", "").strip() == "1"

        # 1. Close any processes directly tracked/started by LIGHT
        closed_count = 0
        tracked = self._launched_processes.get(key, [])
        remaining = []
        for proc in tracked:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    closed_count += 1
            except Exception as err:
                log_debug(f"Failed terminating tracked {key} process: {err}")
                remaining.append(proc)
        self._launched_processes[key] = remaining

        # 2. For Brave/Chrome, NEVER run force-kill by default across the user's session.
        # Only run force-kill if explicitly opted in via force=True or LIGHT_FORCE_KILL_BROWSERS=1.
        if key in ("brave", "chrome"):
            if force_opt_in:
                for cmd in self.platform.get_app_close_commands(key, force=True):
                    subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                    )
                    closed_count += 1
            elif closed_count == 0:
                log_warning(
                    f"No LIGHT-started {key.title()} process to close (skipping force kill to protect user browser tabs). "
                    "Set LIGHT_FORCE_KILL_BROWSERS=1 or force=True to force-close all instances."
                )
            return closed_count

        # 3. For standard desktop utilities (Notepad, Calculator)
        for cmd in self.platform.get_app_close_commands(key, force=True):
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
            )
            closed_count += 1
        return closed_count
