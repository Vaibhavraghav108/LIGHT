"""
computer/platform_factory.py
Provides factory instantiation for the appropriate PlatformController
based on the active operating system (sys.platform).
"""

import sys
from computer.platform_base import PlatformController

_CURRENT_PLATFORM: PlatformController | None = None


def get_platform_controller() -> PlatformController:
    """Return the singleton PlatformController instance for the current operating system."""
    global _CURRENT_PLATFORM
    if _CURRENT_PLATFORM is None:
        if sys.platform == "darwin":
            try:
                from computer.platform_macos import MacOSPlatformController
                _CURRENT_PLATFORM = MacOSPlatformController()
            except ImportError:
                from computer.platform_windows import WindowsPlatformController
                _CURRENT_PLATFORM = WindowsPlatformController()
        elif sys.platform == "win32":
            from computer.platform_windows import WindowsPlatformController
            _CURRENT_PLATFORM = WindowsPlatformController()
        else:
            # Fallback for Linux or unspecified platforms
            try:
                from computer.platform_windows import WindowsPlatformController
                _CURRENT_PLATFORM = WindowsPlatformController()
            except Exception:
                from computer.platform_macos import MacOSPlatformController
                _CURRENT_PLATFORM = MacOSPlatformController()
    return _CURRENT_PLATFORM


def set_platform_controller(controller: PlatformController | None) -> None:
    """Override or reset the singleton platform controller (used in unit tests)."""
    global _CURRENT_PLATFORM
    _CURRENT_PLATFORM = controller
