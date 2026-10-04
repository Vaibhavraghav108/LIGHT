"""
tests/test_platform_macos.py
Unit tests for MacOSPlatformController using mocked macOS system calls.
"""

from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from computer.platform_macos import MacOSPlatformController


class TestMacOSPlatform(unittest.TestCase):

    def setUp(self):
        self.mac = MacOSPlatformController()

    def test_platform_name(self):
        self.assertEqual(self.mac.platform_name, "macos")

    def test_app_launch_commands(self):
        self.assertEqual(self.mac.get_app_launch_command("notepad"), ["open", "-a", "TextEdit"])
        self.assertEqual(self.mac.get_app_launch_command("calculator"), ["open", "-a", "Calculator"])
        self.assertEqual(self.mac.get_app_launch_command("chrome"), ["open", "-a", "Google Chrome"])
        self.assertEqual(self.mac.get_app_launch_command("brave"), ["open", "-a", "Brave Browser"])
        self.assertEqual(
            self.mac.get_app_launch_command("chrome", custom_executable="/custom/chrome"),
            ["/custom/chrome"],
        )
        with self.assertRaises(ValueError):
            self.mac.get_app_launch_command("unknown_app")

    def test_app_close_commands(self):
        # Non-forced graceful close
        notepad_close = self.mac.get_app_close_commands("notepad", force=False)
        self.assertEqual(len(notepad_close), 1)
        self.assertEqual(notepad_close[0][0], "osascript")
        self.assertIn("TextEdit", notepad_close[0][2])

        # Forced close
        notepad_force = self.mac.get_app_close_commands("notepad", force=True)
        self.assertEqual(notepad_force, [["pkill", "-f", "TextEdit"]])

        brave_force = self.mac.get_app_close_commands("brave", force=True)
        self.assertEqual(brave_force, [["pkill", "-f", "Brave Browser"]])

    def test_browser_candidate_paths(self):
        chrome_paths = self.mac.get_browser_candidate_paths("chrome")
        self.assertTrue(any(p.name == "Google Chrome" for p in chrome_paths))
        self.assertTrue(any("/Applications/" in p.as_posix() for p in chrome_paths))

        brave_paths = self.mac.get_browser_candidate_paths("brave")
        self.assertTrue(any(p.name == "Brave Browser" for p in brave_paths))
        self.assertTrue(any("/Applications/" in p.as_posix() for p in brave_paths))

    def test_hotkey_modifier_mapping(self):
        # Ctrl -> Command mapping for standard clipboard/shortcut commands
        self.assertEqual(self.mac.map_hotkey("ctrl", "c"), ["command", "c"])
        self.assertEqual(self.mac.map_hotkey("win", "d"), ["command", "d"])
        self.assertEqual(self.mac.map_hotkey("shift", "tab"), ["shift", "tab"])

    @patch("computer.platform_macos.subprocess.run")
    def test_foreground_window_info_parsing(self, mock_run):
        mock_proc = MagicMock()
        mock_proc.stdout = "Google Chrome|||GitHub - Vaibhavraghav108/LIGHT: Voice automation\n"
        mock_run.return_value = mock_proc

        info = self.mac.get_foreground_window_info()
        self.assertEqual(info["process_name"], "google chrome")
        self.assertEqual(info["title"], "GitHub - Vaibhavraghav108/LIGHT: Voice automation")

    @patch("computer.platform_macos.subprocess.run")
    def test_screen_scale_factor_detection(self, mock_run):
        # Retina detection
        mock_proc = MagicMock()
        mock_proc.stdout = "Resolution: 2560 x 1600 Retina\n"
        mock_run.return_value = mock_proc
        self.assertEqual(self.mac.get_screen_scale_factor(), 2.0)

        # Standard non-retina display
        mock_proc.stdout = "Resolution: 1920 x 1080\n"
        self.assertEqual(self.mac.get_screen_scale_factor(), 1.0)

    def test_process_scan_parsing(self):
        raw_ps = (
            "  PID  PPID COMMAND\n"
            "  101     1 /System/Library/CoreServices/launchd\n"
            " 1420   500 /usr/local/bin/python3 main.py\n"
            " 1425  1420 /usr/local/bin/python3 child.py\n"
            " 2050   500 python3.11 /Users/test/LIGHT/main.py\n"
        )
        parsed = self.mac.parse_process_scan_output(raw_ps)
        self.assertEqual(parsed, [(1420, 500), (2050, 500)])

    def test_kill_pid_tree_command(self):
        cmd = self.mac.get_kill_pid_tree_command(1420)
        self.assertEqual(cmd, ["kill", "-9", "1420"])


if __name__ == "__main__":
    unittest.main()
