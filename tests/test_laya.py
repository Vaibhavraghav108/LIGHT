import unittest
from unittest.mock import MagicMock

from brain.commands import Action, Command
from brain.laya import Laya
from core.state import LightState


class TestLayaAndDecisions(unittest.TestCase):

    def setUp(self):
        self.mock_agent = MagicMock()
        self.laya = Laya(agent=self.mock_agent)

    def _mock_laya_choice(self, choice: str):
        self.mock_agent.predict.return_value = {
            "answers": {
                "action": {
                    "choice": choice
                }
            }
        }

    def test_explicit_stop_commands(self):
        for phrase in ["Stop", "stop light", "Exit.", "quit"]:
            cmd = self.laya.understand(phrase)
            self.assertEqual(cmd.action, Action.STOP)
            self.assertIsNone(cmd.target)

    def test_laya_predicted_stop_is_rejected_for_normal_speech(self):
        self._mock_laya_choice("STOP")
        with self.assertRaises(ValueError):
            self.laya.understand("How are you")

    def test_laya_predicted_move_mouse_is_rejected_for_random_speech(self):
        self._mock_laya_choice("MOVE_MOUSE")
        with self.assertRaises(ValueError):
            self.laya.understand("At the")

    def test_empty_search_is_rejected(self):
        with self.assertRaises(ValueError):
            self.laya.understand("Search")

    def test_go_for_youtube_resolves_to_open_url(self):
        cmd = self.laya.understand("Go for YouTube.")
        self.assertEqual(cmd.action, Action.OPEN_URL)
        self.assertEqual(cmd.target, "https://youtube.com")

    def test_open_known_websites_and_apps(self):
        cmd_yt = self.laya.understand("Open YouTube")
        self.assertEqual(cmd_yt, Command(Action.OPEN_URL, "https://youtube.com"))

        cmd_chrome = self.laya.understand("Open Chrome")
        self.assertEqual(cmd_chrome, Command(Action.OPEN_APP, "Chrome"))

        cmd_close = self.laya.understand("Close Notepad")
        self.assertEqual(cmd_close, Command(Action.CLOSE_APP, "Notepad"))

    def test_keyboard_and_type_commands(self):
        self.assertEqual(
            self.laya.understand("Press Enter"),
            Command(Action.PRESS_KEY, "enter"),
        )
        self.assertEqual(
            self.laya.understand("Press Escape"),
            Command(Action.PRESS_KEY, "esc"),
        )
        self.assertEqual(
            self.laya.understand("Type Krish Naik"),
            Command(Action.TYPE, "Krish Naik"),
        )

    def test_context_aware_search_and_click_result(self):
        state = LightState(current_site="youtube", browser_open=True)
        cmd_search = self.laya.understand("Search for Coldplay", state=state)
        self.assertEqual(cmd_search, Command(Action.SEARCH, "youtube:Coldplay"))

        cmd_result = self.laya.understand("Click the first result", state=state)
        self.assertEqual(cmd_result, Command(Action.CLICK_RESULT, "1"))

    def test_browser_navigation_commands(self):
        self.assertEqual(self.laya.understand("Go back"), Command(Action.GO_BACK, None))
        self.assertEqual(self.laya.understand("Go forward"), Command(Action.GO_FORWARD, None))
        self.assertEqual(self.laya.understand("Refresh page"), Command(Action.REFRESH, None))

    def test_click_element_strips_the_article(self):
        cmd = self.laya.understand("Click on the Ask About Files")
        self.assertEqual(cmd, Command(Action.CLICK_ELEMENT, "Ask About Files"))

        self.assertEqual(
            self.laya.understand("Okay, click on nature evolution"),
            Command(Action.CLICK_ELEMENT, "nature evolution"),
        )
        self.assertEqual(
            self.laya.understand("Click first shot"),
            Command(Action.CLICK_ELEMENT, "first shot"),
        )
        self.assertEqual(
            self.laya.understand("Click on Think School"),
            Command(Action.CLICK_ELEMENT, "Think School"),
        )

    def test_move_mouse_semantic_and_relative_commands(self):
        cases = [
            ("Move mouse to the search bar", "the search bar"),
            ("Move mouse onto the Subscribe button", "the Subscribe button"),
            ("Move mouse to Shorts", "Shorts"),
            ("Move mouse onto the text 'Coldplay'", "the text 'Coldplay'"),
            ("Move mouse to the first video", "the first video"),
            ("Move mouse to the second result", "the second result"),
            ("Move mouse a little left", "a little left"),
            ("Move mouse 100 pixels right", "100 pixels right"),
            ("Move mouse slightly up", "slightly up"),
            ("Move mouse 50 pixels down", "50 pixels down"),
        ]
        for spoken, expected_target in cases:
            cmd = self.laya.understand(spoken)
            self.assertEqual(cmd.action, Action.MOVE_MOUSE)
            self.assertEqual(cmd.target, expected_target)

    def test_natural_stt_mouse_movement_variants_are_normalized_safely(self):
        cases = [
            ("Move now slightly right more", "slightly right"),
            ("Move now slightly left", "slightly left"),
            ("Move a little up", "a little up"),
            ("Move right a bit", "right a bit"),
        ]
        for spoken, expected_target in cases:
            self.assertEqual(
                self.laya.understand(spoken),
                Command(Action.MOVE_MOUSE, expected_target),
            )

    def test_ambiguous_move_phrase_is_not_promoted_to_mouse_control(self):
        self._mock_laya_choice("MOVE_MOUSE")
        with self.assertRaises(ValueError):
            self.laya.understand("Move now to the next thing")

    def test_copy_from_till_and_paste(self):
        cmd_copy = self.laya.understand("Copy from I know this one will hurt till demolish")
        self.assertEqual(cmd_copy.action, Action.COPY_TEXT)
        self.assertEqual(cmd_copy.target, "I know this one will hurt|||demolish")

        cmd_paste = self.laya.understand("Paste")
        self.assertEqual(cmd_paste, Command(Action.PASTE, None))

    def test_incomplete_and_malformed_commands_rejected(self):
        invalid_phrases = [
            "",
            "   ",
            "Open",
            "Close",
            "Type",
            "Search",
            "Search for",
            "Copy from",
            "Copy from start without end",
            "Open http://",
        ]
        for phrase in invalid_phrases:
            with self.assertRaises(ValueError, msg=f"Expected ValueError for '{phrase}'"):
                self.laya.understand(phrase)

    def test_wait_and_arbitrary_url_commands(self):
        self.assertEqual(
            self.laya.understand("Wait 5 seconds"),
            Command(Action.WAIT, "5"),
        )
        self.assertEqual(
            self.laya.understand("Open https://example.com/docs"),
            Command(Action.OPEN_URL, "https://example.com/docs"),
        )


if __name__ == "__main__":
    unittest.main()
