import tempfile
import threading
import time
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock

from browser.browser import BrowserController
from core.executor import Executor
from core.loop import LightLoop
from core.tasks import TaskStatus
from tests.provider_test_utils import make_test_ai_provider, make_test_laya


INDEX_HTML = """<!DOCTYPE html>
<html>
<head><title>LIGHT Local Test Home</title></head>
<body>
  <h1>Welcome to LIGHT Local Test</h1>
  <input id="search" name="search_query" type="text" placeholder="Search items..." />
  <button id="ask-btn" onclick="document.body.setAttribute('data-clicked', 'ask')">Ask about files</button>
  <button id="sub-btn" onclick="document.body.setAttribute('data-clicked', 'subscribe')">Subscribe</button>

  <!-- Hidden duplicate element that must be ignored -->
  <div style="display:none">
    <a href="#hidden" title="Subscriptions">Subscriptions</a>
  </div>

  <!-- Visible element that should be selected -->
  <div id="mini-guide">
    <a id="vis-sub" href="/page2.html" title="Subscriptions" onclick="document.body.setAttribute('data-clicked', 'vis-sub')">Subscriptions</a>
  </div>

  <div id="results">
    <ytd-video-renderer>
      <a id="video-title" href="/page2.html">How to Build Logic in Programming</a>
    </ytd-video-renderer>
    <ytd-video-renderer>
      <a id="video-title" href="/page2.html">Second Video Tutorial</a>
    </ytd-video-renderer>
  </div>

  <article id="wiki-story">
    <p id="story-para">
      Early morning mist covered the valley. I know this one will hurt because the old stone bridge stood for a century before they decided to demolish. Afterward the town built a new crossing.
    </p>
    <p id="ambiguous-1">Ambiguous start phrase alpha omega end marker.</p>
    <p id="ambiguous-2">Ambiguous start phrase beta omega end marker.</p>
  </article>

  <div style="height: 1600px;">Spacer content for scrolling</div>
</body>
</html>
"""

PAGE2_HTML = """<!DOCTYPE html>
<html>
<head><title>Second Test Page</title></head>
<body>
  <h1>Second Page Loaded</h1>
  <p>You navigated to the second page successfully.</p>
</body>
</html>
"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class TestLocalBrowserIntegration(unittest.TestCase):
    """
    Integration tests using a real headless Playwright browser against a local
    ephemeral HTTP server (no external internet access required).
    """

    @classmethod
    def setUpClass(cls):
        workspace_tmp_root = Path(__file__).resolve().parent / ".tmp_integration"
        workspace_tmp_root.mkdir(parents=True, exist_ok=True)
        cls.temp_dir = tempfile.TemporaryDirectory(
            prefix="light_local_test_",
            dir=str(workspace_tmp_root),
        )
        cls.web_dir = Path(cls.temp_dir.name) / "www"
        cls.profile_dir = Path(cls.temp_dir.name) / "profile"
        cls.web_dir.mkdir(parents=True, exist_ok=True)
        cls.profile_dir.mkdir(parents=True, exist_ok=True)

        (cls.web_dir / "index.html").write_text(INDEX_HTML, encoding="utf-8")
        (cls.web_dir / "page2.html").write_text(PAGE2_HTML, encoding="utf-8")

        handler = partial(QuietHandler, directory=str(cls.web_dir))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        cls.browser = BrowserController(
            headless=True,
            user_data_dir=str(cls.profile_dir),
        )
        try:
            cls.browser.start()
        except Exception:
            cls.server.shutdown()
            cls.server.server_close()
            cls.temp_dir.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "browser") and cls.browser is not None:
            cls.browser.close()
        if hasattr(cls, "server") and cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        if hasattr(cls, "temp_dir") and cls.temp_dir is not None:
            cls.temp_dir.cleanup()
        workspace_tmp_root = Path(__file__).resolve().parent / ".tmp_integration"
        try:
            if workspace_tmp_root.exists() and not any(workspace_tmp_root.iterdir()):
                workspace_tmp_root.rmdir()
        except OSError:
            pass

    def setUp(self):
        self.browser.open_url(f"{self.base_url}/index.html")

    def test_title_and_visible_text_reading(self):
        title = self.browser.get_title()
        self.assertEqual(title, "LIGHT Local Test Home")

        visible_text = self.browser.get_visible_text(max_chars=200)
        self.assertIn("Welcome to LIGHT Local Test", visible_text)

    def test_capability_open_scroll_and_typing_reuse_real_local_browser(self):
        """Typed queue/Executor path reaches real DOM, with OS primitives mocked."""
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = self.browser
        executor.screen = MagicMock()
        executor.screen.is_browser_foreground.return_value = True
        executor.screen.get_foreground_window_info.return_value = {"title": "Local fixture", "process_name": ""}
        executor.screen.get_mouse_position.return_value = (0, 0)
        executor.keyboard = MagicMock()
        executor.mouse = MagicMock()
        # This class fixture, not the loop, owns the shared browser's lifetime.
        executor.close = MagicMock(return_value=True)
        loop = LightLoop(MagicMock(), make_test_laya(MagicMock()), executor)
        self.addCleanup(loop.close)
        opened = loop.ingest_capability("browser.open_site", {"url": f"{self.base_url}/index.html"})
        self.assertEqual(loop.execute_next_queued(), "OK")
        self.assertEqual(self.browser.get_title(), "LIGHT Local Test Home")
        self.assertEqual(opened.task.status, TaskStatus.VERIFIED)
        typed = loop.ingest_capability("keyboard.type", {"text": "typed capability"}, confirmed=True)
        self.assertEqual(loop.execute_next_queued(), "OK")
        self.assertEqual(self.browser.page.locator("#search").input_value(), "typed capability")
        self.assertEqual(typed.task.status, TaskStatus.SUCCEEDED)
        executor.keyboard.type_text.assert_not_called()
        scrolled = loop.ingest_capability("browser.scroll", {"direction": "down"})
        self.assertEqual(loop.execute_next_queued(), "OK")
        self.assertGreater(self.browser.page.evaluate("() => window.scrollY"), 0)
        self.assertEqual(scrolled.task.status, TaskStatus.SUCCEEDED)
        executor.mouse.scroll.assert_not_called()

    def test_type_in_search_bar_and_locate_elements(self):
        # Verify search bar locating and typing
        info = self.browser.locate_element_in_viewport("the search bar")
        self.assertTrue(info["found"])
        self.assertTrue(info["is_input"])

        typed_ok = self.browser.type_in_browser("Coldplay")
        self.assertTrue(typed_ok)
        val = self.browser.page.locator("#search").input_value()
        self.assertEqual(val, "Coldplay")

        # Simulate Handy sending a delayed duplicate keystroke/input event.
        # The short browser-only guard must restore the exact requested value.
        self.browser.page.evaluate(
            """() => {
                const search = document.querySelector('#search');
                search.value = 'ColdplayColdplay';
                search.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )
        self.browser.page.wait_for_timeout(100)
        self.assertEqual(self.browser.page.locator("#search").input_value(), "Coldplay")

    def test_click_element_skips_hidden_duplicate_and_clicks_visible(self):
        self.browser.click_element("Ask about files")
        clicked_attr = self.browser.page.locator("body").get_attribute("data-clicked")
        self.assertEqual(clicked_attr, "ask")

        # Clicking "Subscriptions" must skip the display:none link and click #vis-sub -> navigates to page2.html
        self.browser.click_element("Subscriptions")
        self.browser.page.wait_for_load_state("domcontentloaded")
        self.assertIn("page2.html", self.browser.get_current_url())
        self.assertEqual(self.browser.get_title(), "Second Test Page")

        # Test navigation back, forward, refresh
        self.browser.go_back()
        self.assertIn("index.html", self.browser.get_current_url())

        self.browser.go_forward()
        self.assertIn("page2.html", self.browser.get_current_url())

        self.browser.refresh()
        self.assertEqual(self.browser.get_title(), "Second Test Page")

    def test_click_nth_result_and_scroll(self):
        self.browser.scroll("down")
        scroll_y = self.browser.page.evaluate("() => window.scrollY")
        self.assertGreater(scroll_y, 0)

        self.browser.scroll("up")

        self.browser.click_result(1)
        self.browser.page.wait_for_load_state("domcontentloaded")
        self.assertIn("page2.html", self.browser.get_current_url())

    def test_copy_text_range_inclusive_slicing_and_highlight_cleanup(self):
        copied = self.browser.copy_text_range(
            "i know this one will hurt|||demolish",
            highlight_ms=5000,
        )
        self.assertEqual(
            copied,
            "I know this one will hurt because the old stone bridge stood for a century before they decided to demolish",
        )

        # Verify visual highlight attribute was applied to #story-para
        is_highlighted = self.browser.page.locator("#story-para").get_attribute("data-light-highlighted")
        self.assertEqual(is_highlighted, "true")

        # Deterministically clean up highlights and verify original style is restored
        self.browser.clear_highlights()
        is_highlighted_after = self.browser.page.locator("#story-para").get_attribute("data-light-highlighted")
        self.assertIsNone(is_highlighted_after)

        # Missing start phrase must raise clear ValueError
        with self.assertRaises(ValueError) as ctx_missing:
            self.browser.copy_text_range("nonexistent phrase xyz|||demolish")
        self.assertIn("Could not find start phrase", str(ctx_missing.exception))

        # Missing end phrase must raise clear ValueError
        with self.assertRaises(ValueError) as ctx_end:
            self.browser.copy_text_range("I know this one will hurt|||nonexistent end marker")
        self.assertIn("Could not find end phrase", str(ctx_end.exception))

        # Ambiguous start/end range must raise clear ValueError
        with self.assertRaises(ValueError) as ctx_ambig:
            self.browser.copy_text_range("Ambiguous start phrase|||omega end marker")
        self.assertIn("Ambiguous text range", str(ctx_ambig.exception))


if __name__ == "__main__":
    unittest.main()
