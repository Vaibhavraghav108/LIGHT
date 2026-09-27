import unittest
from unittest.mock import MagicMock

from brain.commands import Action, Command
from brain.laya import Laya
from browser.browser import BrowserController
from core.executor import Executor
from core.loop import LightLoop
from core.state import LightState


class TestBrowserAndContextFlow(unittest.TestCase):

    def setUp(self):
        self.browser = BrowserController()
        self.mock_page = MagicMock()
        self.mock_page.is_closed.return_value = False
        self.mock_page.url = "https://youtube.com"
        self.mock_page.title.return_value = "YouTube"

        self.browser.browser = MagicMock()
        self.browser.page = self.mock_page

    def test_open_url_adds_https(self):
        self.browser.open_url("github.com")
        self.mock_page.goto.assert_called_once_with(
            "https://github.com",
            wait_until="domcontentloaded",
        )

    def test_navigation_methods(self):
        self.browser.go_back()
        self.mock_page.go_back.assert_called_once_with(wait_until="domcontentloaded")

        self.browser.go_forward()
        self.mock_page.go_forward.assert_called_once_with(wait_until="domcontentloaded")

        self.browser.refresh()
        self.mock_page.reload.assert_called_once_with(wait_until="domcontentloaded")

    def test_scroll_webpage(self):
        self.browser.scroll("down")
        self.mock_page.mouse.wheel.assert_called_once_with(0, 500)

    def test_parse_element_target_semantics(self):
        self.assertEqual(
            self.browser.parse_element_target("the search bar"),
            {"kind": "search_bar", "query": "search", "semantic": "input"},
        )
        self.assertEqual(
            self.browser.parse_element_target("onto the Subscribe button"),
            {"kind": "element", "query": "Subscribe", "semantic": "button"},
        )
        self.assertEqual(
            self.browser.parse_element_target("to Shorts"),
            {"kind": "element", "query": "Shorts", "semantic": "any"},
        )
        self.assertEqual(
            self.browser.parse_element_target("onto the text 'Coldplay'"),
            {"kind": "element", "query": "Coldplay", "semantic": "text"},
        )
        self.assertEqual(
            self.browser.parse_element_target("to the first video"),
            {"kind": "nth_result", "index": 1, "semantic": "link"},
        )
        self.assertEqual(
            self.browser.parse_element_target("to the second result"),
            {"kind": "nth_result", "index": 2, "semantic": "link"},
        )

    def test_viewport_to_physical_screen_coordinate_conversion_with_dpi(self):
        # Simulate a 1920x1080 monitor at 125% Windows scaling (1536x864 CSS pixels)
        # Browser maximized at (0, 0) with outer=(1536, 824), inner=(1520, 736)
        # border_x = (1536 - 1520)/2 = 8 CSS px
        # chrome_top = (824 - 736) - 8 = 80 CSS px
        metrics = {
            "screenX": 0,
            "screenY": 0,
            "outerWidth": 1536,
            "outerHeight": 824,
            "innerWidth": 1520,
            "innerHeight": 736,
            "screenWidth": 1536,
            "screenHeight": 864,
            "devicePixelRatio": 1.25,
        }
        # Element at viewport (400, 120) -> CSS screen (408, 200) -> Physical (510, 250)
        phys_x, phys_y = self.browser.convert_viewport_to_screen(
            400,
            120,
            metrics,
            screen_size=(1920, 1080),
        )
        self.assertEqual((phys_x, phys_y), (510, 250))

    def test_end_to_end_context_loop_with_mocks(self):
        state = LightState()
        mock_agent = MagicMock()
        mock_agent.predict.return_value = {
            "answers": {"action": {"choice": "STOP"}}
        }
        laya = Laya(agent=mock_agent)

        executor = Executor(state=state)
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = True
        executor.browser.get_current_url.return_value = "https://youtube.com"
        executor.browser.get_title.return_value = "YouTube"
        executor.screen = MagicMock()
        executor.screen.get_active_window_title.return_value = "YouTube - Brave"

        loop = LightLoop(handy=MagicMock(), laya=laya, executor=executor, state=state)

        # Step 1: Open YouTube
        self.assertEqual(loop.process_text("Open YouTube"), "OK")
        executor.browser.open_url.assert_called_once_with("https://youtube.com")
        self.assertEqual(state.current_site, "youtube")

        # Step 2: Search for Coldplay (uses short-term state to search YouTube!)
        self.assertEqual(loop.process_text("Search for Coldplay"), "OK")
        executor.browser.search.assert_called_once_with("Coldplay", engine="youtube")

        # Step 3: Click the first result
        self.assertEqual(loop.process_text("Click the first result"), "OK")
        executor.browser.click_result.assert_called_once_with(1)

        # Step 4: Invalid/conversational speech does NOT stop or crash LIGHT
        self.assertEqual(loop.process_text("How are you"), "IGNORED")

        # Step 5: Explicit stop closes browser and returns STOP
        self.assertEqual(loop.process_text("Stop"), "STOP")
        executor.browser.close.assert_called_once()

    def test_start_falls_back_to_playwright_chromium_on_winerror_5(self):
        from unittest.mock import patch

        bc = BrowserController(
            headless=True,
            executable_path=r"C:\Users\vaibh\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe",
        )
        mock_pw_cm = MagicMock()
        mock_pw = MagicMock()
        mock_pw_cm.start.return_value = mock_pw

        mock_fallback_browser = MagicMock()
        mock_fallback_page = MagicMock()
        mock_fallback_page.is_closed.return_value = False
        mock_fallback_browser.new_page.return_value = mock_fallback_page

        def launch_side_effect(*, headless=False, executable_path=None, args=None):
            if executable_path and "brave.exe" in executable_path.lower():
                raise PermissionError(5, "Access is denied", executable_path)
            return mock_fallback_browser

        mock_pw.chromium.launch.side_effect = launch_side_effect

        with patch("browser.browser.sync_playwright", return_value=mock_pw_cm):
            bc.start()

        self.assertTrue(bc.is_active())
        self.assertEqual(bc.active_browser_label, "Playwright Chromium")
        self.assertIsNone(bc.active_executable_path)


if __name__ == "__main__":
    unittest.main()
