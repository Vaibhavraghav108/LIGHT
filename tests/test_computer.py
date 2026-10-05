import sys
import unittest
from unittest.mock import MagicMock, patch

from brain.commands import Action, Command
from browser.browser import BrowserController
from computer.apps import AppController
from computer.keyboard import KeyboardController
from computer.mouse import MouseController
from computer.platform_macos import MacOSPlatformController
from computer.platform_windows import WindowsPlatformController
from core.executor import Executor
from tests.provider_test_utils import make_test_ai_provider


class TestComputerControl(unittest.TestCase):

    @patch("computer.apps.subprocess.Popen")
    def test_open_notepad_and_calculator(self, mock_popen):
        apps = AppController()
        apps.open("Notepad")
        expected_notepad = ["open", "-a", "TextEdit"] if sys.platform == "darwin" else ["notepad.exe"]
        mock_popen.assert_any_call(expected_notepad)

        apps.open("Calculator")
        expected_calc = ["open", "-a", "Calculator"] if sys.platform == "darwin" else ["calc.exe"]
        mock_popen.assert_any_call(expected_calc)

    @patch("computer.apps.subprocess.run")
    def test_close_apps(self, mock_run):
        apps = AppController()
        closed = apps.close("Notepad")
        self.assertEqual(closed, 0)
        mock_run.assert_not_called()

        closed = apps.close("Notepad", force=True)
        self.assertEqual(closed, 1)
        expected_cmd = ["pkill", "-f", "TextEdit"] if sys.platform == "darwin" else ["taskkill", "/IM", "notepad.exe", "/F"]
        mock_run.assert_called_with(
            expected_cmd,
            capture_output=True,
            text=True,
        )

    @patch("computer.apps.subprocess.run")
    @patch("computer.apps.subprocess.Popen")
    def test_close_notepad_only_terminates_light_tracked_process(self, mock_popen, mock_run):
        cases = [
            (WindowsPlatformController(), 1, None),
            (
                MacOSPlatformController(),
                2,
                ["osascript", "-e", 'tell application "TextEdit" to quit'],
            ),
        ]
        for platform, expected_closed, graceful_command in cases:
            with self.subTest(platform=platform.platform_name):
                mock_proc = MagicMock()
                mock_proc.poll.return_value = None
                mock_popen.return_value = mock_proc
                apps = AppController(platform=platform)
                apps.open("Notepad", wait_and_focus=False)

                closed = apps.close("Notepad")

                self.assertEqual(closed, expected_closed)
                mock_proc.terminate.assert_called_once_with()
                if graceful_command:
                    mock_run.assert_called_once_with(
                        graceful_command,
                        capture_output=True,
                        text=True,
                    )
                else:
                    mock_run.assert_not_called()
                mock_popen.reset_mock()
                mock_run.reset_mock()

    @patch("computer.apps.subprocess.run")
    @patch("computer.apps.subprocess.Popen")
    def test_close_browser_tracks_launched_process_and_does_not_force_kill_by_default(
        self,
        mock_popen,
        mock_run,
    ):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        apps = AppController()
        with patch.object(apps, "find_brave_executable", return_value=r"C:\Brave\brave.exe"):
            apps.open("Brave")

        # Closing Brave without force=True terminates only the tracked Popen process, never taskkill / force kill
        closed = apps.close("Brave")
        self.assertEqual(closed, 1)
        mock_proc.terminate.assert_called_once()
        mock_run.assert_not_called()

        # Explicit opt-in force=True runs force kill command
        apps.close("Brave", force=True)
        expected_cmd = ["pkill", "-f", "Brave Browser"] if sys.platform == "darwin" else ["taskkill", "/IM", "brave.exe", "/F"]
        mock_run.assert_called_once_with(
            expected_cmd,
            capture_output=True,
            text=True,
        )

    def test_unknown_app_raises_value_error(self):
        apps = AppController()
        with self.assertRaises(ValueError):
            apps.open("UnknownAppXYZ")

    @patch("computer.keyboard.time.sleep")
    @patch("computer.keyboard.pyautogui.write")
    def test_keyboard_type_text(self, mock_write, _mock_sleep):
        kb = KeyboardController()
        kb.type_text("hi")
        self.assertEqual(mock_write.call_count, 2)

    @patch("computer.keyboard.pyautogui.press")
    def test_keyboard_press_key(self, mock_press):
        kb = KeyboardController()
        kb.press("escape")
        mock_press.assert_called_once_with("esc")

    @patch("computer.keyboard.pyautogui.hotkey")
    def test_keyboard_hotkey(self, mock_hotkey):
        KeyboardController().hotkey("ctrl", "r")
        expected = ("command", "r") if sys.platform == "darwin" else ("ctrl", "r")
        mock_hotkey.assert_called_once_with(*expected)

    @patch("computer.mouse.pyautogui.size", return_value=(1920, 1080))
    @patch("computer.mouse.pyautogui.position", return_value=(500, 500))
    @patch("computer.mouse.pyautogui.click")
    @patch("computer.mouse.pyautogui.scroll")
    @patch("computer.mouse.pyautogui.moveTo")
    def test_mouse_actions_and_relative_precision(
        self,
        mock_move_to,
        mock_scroll,
        mock_click,
        _mock_pos,
        _mock_size,
    ):
        mouse = MouseController()
        mouse.click()
        mock_click.assert_called_once()

        mouse.scroll("down")
        mock_scroll.assert_called_with(-5)

        # Standard up move (150px up from 500,500 -> 500,350)
        mouse.move_by_command("up")
        mock_move_to.assert_called_with(500, 350, duration=0.25)

        # "a little left" (45px left from 500,500 -> 455,500)
        mouse.move_by_command("a little left")
        mock_move_to.assert_called_with(455, 500, duration=0.25)

        # "slightly up" (45px up from 500,500 -> 500,455)
        mouse.move_by_command("slightly up")
        mock_move_to.assert_called_with(500, 455, duration=0.25)

        # "100 pixels right" (100px right from 500,500 -> 600,500)
        mouse.move_by_command("100 pixels right")
        mock_move_to.assert_called_with(600, 500, duration=0.25)

        # "50 pixels down" (50px down from 500,500 -> 500,550)
        mouse.move_by_command("50 pixels down")
        mock_move_to.assert_called_with(500, 550, duration=0.25)

        # Screen boundary clamping (never goes outside [5, 1914] x [5, 1074])
        mouse.move(-999, 9999)
        mock_move_to.assert_called_with(5, 1074, duration=0.3)

    @patch("computer.apps.subprocess.Popen")
    def test_executor_routes_open_app_and_updates_state(self, mock_popen):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.screen = MagicMock()
        executor.screen.get_foreground_window_info.return_value = {
            "title": "Untitled - Notepad",
            "process_name": "notepad.exe",
        }
        result = executor.execute(Command(Action.OPEN_APP, "Notepad"), raw_text="Open Notepad")
        self.assertEqual(result, "OK")
        self.assertEqual(executor.state.current_app, "notepad")
        expected_cmd = ["open", "-a", "TextEdit"] if sys.platform == "darwin" else ["notepad.exe"]
        mock_popen.assert_any_call(expected_cmd)

    def test_executor_uses_playwright_chromium_for_browser_commands(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        executor.apps = MagicMock()
        executor.keyboard = MagicMock()
        executor.browser.is_active.return_value = True
        executor.browser.get_current_url.return_value = "about:blank"
        executor.browser.get_title.return_value = "New Tab"
        executor.screen = MagicMock()

        result = executor.execute(Command(Action.OPEN_APP, "Chrome"), raw_text="Open Chrome")

        self.assertEqual(result, "OK")
        executor.browser.start.assert_called_once_with()
        executor.apps.open.assert_not_called()
        self.assertEqual(executor.state.current_browser, "chrome")

        executor.execute(Command(Action.SEARCH, "Amitabh Bachchan"), raw_text="Search for Amitabh Bachchan")
        executor.browser.search.assert_called_once_with("Amitabh Bachchan")

        executor.execute(Command(Action.CLICK_ELEMENT, "Think School"), raw_text="Click on Think School")
        executor.browser.click_element.assert_called_once_with("Think School", mouse_controller=executor.mouse)

        executor.execute(Command(Action.CLICK_RESULT, "1"), raw_text="Click first result")
        executor.browser.click_result.assert_called_once_with(1, mouse_controller=executor.mouse)

    def test_executor_close_browser_only_closes_controlled_session(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        executor.apps = MagicMock()
        executor.browser.is_active.return_value = False
        executor.screen = MagicMock()

        result = executor.execute(Command(Action.CLOSE_APP, "Brave"), raw_text="Close Brave")

        self.assertEqual(result, "OK")
        executor.browser.close.assert_called_once_with()
        executor.apps.close.assert_not_called()

    def test_executor_routes_move_mouse_to_browser_element(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = True
        executor.browser.move_mouse_to_element.return_value = (740, 195)

        result = executor.execute(
            Command(Action.MOVE_MOUSE, "the search bar"),
            raw_text="Move mouse to the search bar",
        )
        self.assertEqual(result, "OK")
        executor.browser.move_mouse_to_element.assert_called_once_with(
            "the search bar",
            executor.mouse,
        )

    def test_executor_routes_clipboard_shortcuts_through_platform_keyboard(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = False
        executor.keyboard = MagicMock()

        self.assertEqual(executor.execute(Command(Action.COPY_TEXT, None)), "OK")
        self.assertEqual(executor.execute(Command(Action.PASTE, None)), "OK")

        self.assertEqual(
            executor.keyboard.hotkey.call_args_list,
            [unittest.mock.call("ctrl", "c"), unittest.mock.call("ctrl", "v")],
        )


if __name__ == "__main__":
    unittest.main()
