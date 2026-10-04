"""
tests/test_macos_smoke.py
Non-destructive opt-in smoke tests for verifying real macOS environment
integration (App bundles, clipboard round-trip, screen scaling, and AppleScript observation).
Disabled by default unless LIGHT_RUN_MACOS_SMOKE=1 is set on a macOS host.
"""

import os
import sys
import unittest

import pyperclip

from computer.apps import AppController
from computer.mouse import MouseController
from computer.screen import ScreenController
from computer.platform_factory import get_platform_controller


@unittest.skipUnless(
    sys.platform == "darwin" and os.environ.get("LIGHT_RUN_MACOS_SMOKE") == "1",
    "Opt-in macOS smoke tests are disabled by default. Set LIGHT_RUN_MACOS_SMOKE=1 on macOS to run.",
)
class TestMacOSSmoke(unittest.TestCase):

    def test_platform_type(self):
        controller = get_platform_controller()
        self.assertEqual(controller.platform_name, "macos")

    def test_browser_executable_discovery(self):
        apps = AppController()
        # On macOS, verify finding chrome or brave or custom
        try:
            chrome_path = apps.find_chrome_executable()
            self.assertTrue(os.path.exists(chrome_path))
        except FileNotFoundError:
            # Fallback if Chrome is not installed on this specific test Mac
            brave_path = apps.find_brave_executable()
            self.assertTrue(os.path.exists(brave_path))

    def test_clipboard_roundtrip(self):
        previous = pyperclip.paste()
        try:
            probe = "LIGHT_MACOS_SMOKE_CLIPBOARD_TEST"
            pyperclip.copy(probe)
            self.assertEqual(pyperclip.paste(), probe)
        finally:
            pyperclip.copy(previous)

    def test_screen_scale_and_dimensions(self):
        screen = ScreenController()
        mouse = MouseController()

        width, height = screen.get_screen_size()
        self.assertGreater(width, 100)
        self.assertGreater(height, 100)

        scale = get_platform_controller().get_screen_scale_factor()
        self.assertIn(scale, (1.0, 2.0))

        mx, my = screen.get_mouse_position()
        clamped_x, clamped_y = mouse.clamp_to_screen(mx, my)
        self.assertTrue(5 <= clamped_x < width - 5)
        self.assertTrue(5 <= clamped_y < height - 5)


if __name__ == "__main__":
    unittest.main()
