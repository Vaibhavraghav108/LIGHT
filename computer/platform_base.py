"""
computer/platform_base.py
Abstract base class defining the operating system interface for LIGHT.
Platform-specific controllers (Windows, macOS) implement these methods to
provide hardware, window, process, and desktop interactions.
"""

from abc import ABC, abstractmethod
from pathlib import Path


class PlatformController(ABC):
    """Abstract base class for operating system specific operations."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier ('windows', 'macos', etc.)."""
        ...

    @abstractmethod
    def get_app_launch_command(self, app_key: str, custom_executable: str | None = None) -> list[str]:
        """Return the command arguments to launch an application."""
        ...

    @abstractmethod
    def get_app_close_commands(self, app_key: str, force: bool = False) -> list[list[str]]:
        """Return list of command lines to terminate an application."""
        ...

    @abstractmethod
    def get_browser_candidate_paths(self, browser_name: str) -> list[Path]:
        """Return list of candidate installation paths for the browser."""
        ...

    @abstractmethod
    def get_default_handy_db_path(self) -> Path:
        """Return default path to Handy history.db SQLite file."""
        ...

    @abstractmethod
    def set_dpi_awareness(self) -> None:
        """Set DPI awareness for high-resolution displays."""
        ...

    @abstractmethod
    def get_screen_scale_factor(self) -> float:
        """Return display backing scale factor (e.g. 1.0 for standard, 2.0 for Retina)."""
        ...

    @abstractmethod
    def get_foreground_window_info(self) -> dict:
        """
        Return dict with hwnd/id, title, class_name, pid, process_name
        of the current foreground window.
        """
        ...

    @abstractmethod
    def wait_for_window_and_focus(self, app_name: str, timeout: float = 3.0) -> bool:
        """Wait for window matching app_name and bring to foreground."""
        ...

    @abstractmethod
    def minimize_foreground_window(self) -> bool:
        """Minimize the active foreground window."""
        ...

    @abstractmethod
    def maximize_foreground_window(self) -> bool:
        """Maximize the active foreground window."""
        ...

    @abstractmethod
    def restore_foreground_window(self) -> bool:
        """Restore the active foreground window."""
        ...

    @abstractmethod
    def show_desktop(self) -> bool:
        """Show desktop / minimize all windows."""
        ...

    @abstractmethod
    def map_hotkey(self, *keys: str) -> list[str]:
        """Map key names to platform-specific key aliases or modifiers."""
        ...

    @abstractmethod
    def get_process_scan_command(self, script_name: str) -> list[str]:
        """Return command to list PIDs running script_name."""
        ...

    @abstractmethod
    def parse_process_scan_output(self, output: str) -> list[tuple[int, int]]:
        """Parse stdout of process scan into list of (pid, ppid)."""
        ...

    @abstractmethod
    def get_kill_pid_tree_command(self, pid: int) -> list[str]:
        """Return command to kill a process and its child tree."""
        ...

    @abstractmethod
    def get_cursor_position_fallback(self, last_known_pos: tuple[int, int]) -> tuple[int, int]:
        """Platform-specific fallback when cursor coordinate queries return (0, 0)."""
        ...
