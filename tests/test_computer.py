import unittest
from unittest.mock import MagicMock, patch

from brain.commands import Action, Command
from browser.browser import BrowserController
from computer.apps import AppController
from computer.keyboard import KeyboardController
from computer.mouse import MouseController
from core.executor import Executor


class TestComputerControl(unittest.TestCase):

    @patch("computer.apps.subprocess.Popen")
    def test_open_notepad_and_calculator(self, mock_popen):
        apps = AppController()
        apps.open("Notepad")
        mock_popen.assert_called_with(["notepad.exe"])

        apps.open("Calculator")
        mock_popen.assert_called_with(["calc.exe"])

    @patch("computer.apps.subprocess.run")
    def test_close_apps(self, mock_run):
        apps = AppController()
        apps.close("Notepad")
        mock_run.assert_called_with(
            ["taskkill", "/IM", "notepad.exe", "/F"],
            capture_output=True,
            text=True,
        )

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

        # Closing Brave without force=True terminates only the tracked Popen process, never taskkill /F
        closed = apps.close("Brave")
        self.assertEqual(closed, 1)
        mock_proc.terminate.assert_called_once()
        mock_run.assert_not_called()

        # Explicit opt-in force=True runs taskkill /F
        apps.close("Brave", force=True)
        mock_run.assert_called_once_with(
            ["taskkill", "/IM", "brave.exe", "/F"],
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
        mock_hotkey.assert_called_once_with("ctrl", "r")

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
        executor = Executor()
        result = executor.execute(Command(Action.OPEN_APP, "Notepad"), raw_text="Open Notepad")
        self.assertEqual(result, "OK")
        self.assertEqual(executor.state.current_app, "notepad")
        mock_popen.assert_called_once_with(["notepad.exe"])

    def test_executor_uses_native_browser_window_for_browser_commands(self):
        executor = Executor()
        executor.browser = MagicMock()
        executor.apps = MagicMock()
        executor.keyboard = MagicMock()
        executor.browser.is_active.return_value = True
        executor.browser.get_current_url.return_value = "about:blank"
        executor.browser.get_title.return_value = "New Tab"
        executor.screen = MagicMock()

        result = executor.execute(Command(Action.OPEN_APP, "Brave"), raw_text="Open Brave")

        self.assertEqual(result, "OK")
        executor.apps.open_browser_window.assert_called_once_with("Brave")
        executor.browser.start.assert_not_called()
        self.assertEqual(executor.state.current_browser, "brave")

        executor.browser.is_active.return_value = False
        executor.execute(Command(Action.SEARCH, "Amitabh Bachchan"), raw_text="Search for Amitabh Bachchan")
        executor.browser.search.assert_not_called()
        executor.keyboard.hotkey.assert_called_once_with("ctrl", "l")
        executor.keyboard.type_text.assert_called_once_with("https://www.google.com/search?q=Amitabh+Bachchan")
        executor.keyboard.press.assert_called_once_with("enter")

    def test_native_browser_dom_commands_do_not_start_playwright(self):
        executor = Executor()
        executor.browser = BrowserController()
        executor.browser.start = MagicMock()
        executor.browser.click_result = MagicMock()
        executor.browser.click_element = MagicMock()
        executor.apps = MagicMock()
        executor.keyboard = MagicMock()
        executor.mouse = MagicMock()
        executor.mouse.get_screen_size.return_value = (1920, 1080)
        executor.screen = MagicMock()
        executor.screen.take_screenshot.return_value = None
        executor.state.current_browser = "brave"

        res1 = executor.execute(Command(Action.CLICK_RESULT, "1"), raw_text="Click first result")
        self.assertEqual(res1, "OK")

        res2 = executor.execute(Command(Action.CLICK_ELEMENT, "Think School"), raw_text="Click on Think School")
        self.assertEqual(res2, "OK")
        executor.keyboard.hotkey.assert_any_call("ctrl", "f")
        executor.keyboard.press.assert_any_call("escape")
        executor.keyboard.press.assert_any_call("enter")

        res3 = executor.execute(Command(Action.CLICK_ELEMENT, "first shot"), raw_text="Click first shot")
        self.assertEqual(res3, "OK")

        executor.browser.click_result.assert_not_called()
        executor.browser.click_element.assert_not_called()
        executor.browser.start.assert_not_called()

    def test_executor_close_browser_only_closes_controlled_session(self):
        executor = Executor()
        executor.browser = MagicMock()
        executor.apps = MagicMock()
        executor.browser.is_active.return_value = False
        executor.screen = MagicMock()

        result = executor.execute(Command(Action.CLOSE_APP, "Brave"), raw_text="Close Brave")

        self.assertEqual(result, "OK")
        executor.browser.close.assert_called_once_with()
        executor.apps.close.assert_not_called()

    def test_executor_routes_move_mouse_to_browser_element(self):
        executor = Executor()
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


if __name__ == "__main__":
    unittest.main()
