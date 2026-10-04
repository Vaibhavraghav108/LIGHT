import os
import sys
import unittest

import pyperclip

from computer.apps import AppController
from computer.mouse import MouseController
from computer.screen import ScreenController
from voice.handy import Handy


@unittest.skipUnless(
    sys.platform == "win32" and os.environ.get("LIGHT_RUN_WINDOWS_SMOKE") == "1",
    "Opt-in Windows smoke tests are disabled by default. Set LIGHT_RUN_WINDOWS_SMOKE=1 on Windows to run.",
)
class TestWindowsSmoke(unittest.TestCase):
    """
    Non-destructive opt-in smoke tests for verifying real Windows environment
    integration (Brave/Chrome executable discovery, clipboard round-trip,
    screen/mouse coordinates, and Handy SQLite database connectivity).
    """

    def test_browser_executable_discovery(self):
        apps = AppController()
        brave_path = apps.find_brave_executable()
        self.assertTrue(os.path.exists(brave_path))

    def test_clipboard_roundtrip(self):
        previous = pyperclip.paste()
        try:
            probe = "LIGHT_SMOKE_CLIPBOARD_TEST"
            pyperclip.copy(probe)
            self.assertEqual(pyperclip.paste(), probe)
        finally:
            pyperclip.copy(previous)

    def test_screen_and_mouse_observation(self):
        screen = ScreenController()
        mouse = MouseController()

        width, height = screen.get_screen_size()
        self.assertGreater(width, 100)
        self.assertGreater(height, 100)

        mx, my = screen.get_mouse_position()
        clamped_x, clamped_y = mouse.clamp_to_screen(mx, my)
        self.assertTrue(5 <= clamped_x < width - 5)
        self.assertTrue(5 <= clamped_y < height - 5)

    def test_handy_database_read(self):
        handy = Handy()
        latest = handy.get_latest_transcription()
        if latest is not None:
            self.assertIn("id", latest)
            self.assertIn("text", latest)


if __name__ == "__main__":
    unittest.main()
