import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from brain.commands import Action, Command
from brain.decision import parse_deterministic_command, parse_multi_command
from brain.laya import Laya
from core.executor import Executor
from core.state import LightState


class TestNewFeatures(unittest.TestCase):

    def setUp(self):
        self.state = LightState()

    # ==========================================
    # STAGE 1: FOCUS-AWARE DESKTOP TYPING
    # ==========================================

    def test_01_open_notepad_and_type_compound_parse(self):
        """1. 'Open Notepad and type hello world' parses to [OPEN_APP(notepad), TYPE(hello world)]."""
        cmds = parse_multi_command("Open Notepad and type hello world", state=self.state)
        self.assertIsNotNone(cmds)
        self.assertEqual(len(cmds), 2)
        self.assertEqual(cmds[0].action, Action.OPEN_APP)
        self.assertEqual(cmds[0].target.lower(), "notepad")
        self.assertEqual(cmds[1].action, Action.TYPE)
        self.assertEqual(cmds[1].target, "hello world")

    def test_02_type_routes_to_desktop_when_browser_not_foreground(self):
        """2. When browser is NOT foreground (e.g. Notepad foreground), typing uses keyboard controller."""
        executor = Executor(state=self.state)
        executor.screen = MagicMock()
        executor.browser = MagicMock()
        executor.keyboard = MagicMock()

        # Browser is NOT in foreground
        executor.screen.is_browser_foreground.return_value = False
        executor.browser.is_active.return_value = True

        cmd = Command(Action.TYPE, "hello world")
        executor.execute(cmd, raw_text="type hello world")

        # Must call desktop keyboard controller
        executor.keyboard.type_text.assert_called_once_with("hello world")
        # Must NOT call browser typing
        executor.browser.type_in_browser.assert_not_called()

    def test_03_type_routes_to_browser_when_browser_is_foreground(self):
        """3. When browser IS foreground, typing routes to browser controller."""
        executor = Executor(state=self.state)
        executor.screen = MagicMock()
        executor.browser = MagicMock()
        executor.keyboard = MagicMock()

        # Browser IS in foreground
        executor.screen.is_browser_foreground.return_value = True
        executor.browser.is_active.return_value = True
        executor.browser.type_in_browser.return_value = True

        cmd = Command(Action.TYPE, "search query")
        executor.execute(cmd, raw_text="type search query")

        # Must call browser type_in_browser
        executor.browser.type_in_browser.assert_called_once_with("search query")
        # Must NOT call desktop keyboard controller
        executor.keyboard.type_text.assert_not_called()

    # ==========================================
    # STAGE 2: DETERMINISTIC CONTROLS (HOTKEYS)
    # ==========================================

    def test_04_hotkey_parsing(self):
        """4. Parse hotkeys deterministically in <1ms."""
        cases = [
            ("press ctrl c", "ctrl+c"),
            ("ctrl v", "ctrl+v"),
            ("press alt tab", "alt+tab"),
            ("press win d", "win+d"),
            ("win e", "win+e"),
            ("press ctrl shift esc", "ctrl+shift+esc"),
            ("press alt f4", "alt+f4"),
        ]
        for spoken, expected in cases:
            t0 = time.perf_counter()
            cmd = parse_deterministic_command(spoken, state=self.state)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            self.assertIsNotNone(cmd, f"Failed for '{spoken}'")
            self.assertEqual(cmd.action, Action.HOTKEY)
            self.assertEqual(cmd.target, expected)
            self.assertLess(dt_ms, 5.0, f"Parsing took too long: {dt_ms}ms")

    def test_05_hotkey_execution(self):
        """5. Executor executes hotkeys via pyautogui.hotkey."""
        executor = Executor(state=self.state)
        with patch("pyautogui.hotkey") as mock_hotkey:
            cmd = Command(Action.HOTKEY, "ctrl+c")
            res = executor.execute(cmd)
            self.assertEqual(res, "OK")
            expected_keys = ("command", "c") if sys.platform == "darwin" else ("ctrl", "c")
            mock_hotkey.assert_called_once_with(*expected_keys)

    # ==========================================
    # STAGE 2: WINDOW CONTROL
    # ==========================================

    def test_06_window_control_parsing(self):
        """6. Parse window commands: switch to, minimize, maximize, restore, show desktop."""
        cases = [
            ("switch to notepad", Action.SWITCH_WINDOW, "notepad"),
            ("switch to chrome", Action.SWITCH_WINDOW, "chrome"),
            ("minimize window", Action.MINIMIZE_WINDOW, None),
            ("maximize window", Action.MAXIMIZE_WINDOW, None),
            ("restore window", Action.RESTORE_WINDOW, None),
            ("show desktop", Action.SHOW_DESKTOP, None),
        ]
        for spoken, expected_action, expected_target in cases:
            cmd = parse_deterministic_command(spoken, state=self.state)
            self.assertIsNotNone(cmd, f"Failed for '{spoken}'")
            self.assertEqual(cmd.action, expected_action)
            self.assertEqual(cmd.target, expected_target)

    def test_07_window_control_execution(self):
        """7. Executor delegates window controls to screen controller."""
        executor = Executor(state=self.state)
        executor.screen = MagicMock()

        # Switch window
        executor.execute(Command(Action.SWITCH_WINDOW, "notepad"))
        executor.screen.switch_to_window.assert_called_once_with("notepad")

        # Minimize
        executor.execute(Command(Action.MINIMIZE_WINDOW, None))
        executor.screen.minimize_foreground_window.assert_called_once()

        # Maximize
        executor.execute(Command(Action.MAXIMIZE_WINDOW, None))
        executor.screen.maximize_foreground_window.assert_called_once()

        # Restore
        executor.execute(Command(Action.RESTORE_WINDOW, None))
        executor.screen.restore_foreground_window.assert_called_once()

        # Show desktop
        executor.execute(Command(Action.SHOW_DESKTOP, None))
        executor.screen.show_desktop.assert_called_once()

    # ==========================================
    # STAGE 2: MEDIA CONTROLS
    # ==========================================

    def test_08_media_control_parsing(self):
        """8. Parse media commands: pause, play, forward, backward, fullscreen, mute, volume."""
        cases = [
            ("pause video", Action.MEDIA_PLAY_PAUSE, None),
            ("play video", Action.MEDIA_PLAY_PAUSE, None),
            ("resume video", Action.MEDIA_PLAY_PAUSE, None),
            ("skip 10 seconds", Action.MEDIA_FORWARD, "10"),
            ("forward 15 seconds", Action.MEDIA_FORWARD, "15"),
            ("rewind 10 seconds", Action.MEDIA_BACKWARD, "10"),
            ("go back 10 seconds", Action.MEDIA_BACKWARD, "10"),
            ("fullscreen", Action.MEDIA_FULLSCREEN, None),
            ("exit fullscreen", Action.MEDIA_EXIT_FULLSCREEN, None),
            ("mute", Action.MEDIA_MUTE, None),
            ("unmute", Action.MEDIA_MUTE, None),
            ("volume up", Action.MEDIA_VOLUME_UP, None),
            ("volume down", Action.MEDIA_VOLUME_DOWN, None),
            ("next video", Action.MEDIA_NEXT, None),
            ("previous video", Action.MEDIA_PREVIOUS, None),
        ]
        for spoken, expected_action, expected_target in cases:
            cmd = parse_deterministic_command(spoken, state=self.state)
            self.assertIsNotNone(cmd, f"Failed for '{spoken}'")
            self.assertEqual(cmd.action, expected_action)
            self.assertEqual(cmd.target, expected_target)

    def test_09_media_dom_control_in_browser(self):
        """9. Media controls in browser use DOM evaluate without typing characters."""
        executor = Executor(state=self.state)
        executor.screen = MagicMock()
        executor.browser = MagicMock()
        executor.keyboard = MagicMock()

        # Browser is active and foreground
        executor.screen.is_browser_foreground.return_value = True
        executor.browser.has_video_element.return_value = True

        # Test pause/play
        executor.execute(Command(Action.MEDIA_PLAY_PAUSE, None))
        executor.browser.media_play_pause.assert_called_once()

        # Test forward
        executor.execute(Command(Action.MEDIA_FORWARD, "10"))
        executor.browser.media_seek.assert_called_once_with(10.0)

        # Test fullscreen
        executor.execute(Command(Action.MEDIA_FULLSCREEN, None))
        executor.browser.media_fullscreen.assert_called_once_with(True)

        # Ensure keyboard controller never typed keys into any search field
        executor.keyboard.type_text.assert_not_called()

    # ==========================================
    # STAGE 3: AUTONOMOUS BROWSER AGENT TASK
    # ==========================================

    def test_10_agent_task_parsing(self):
        """10. Autonomous research/comparison requests parse to AGENT_TASK."""
        queries = [
            "research the top 5 mechanical keyboards and compare them",
            "find five good gaming laptops on amazon and compare them",
            "compare the prices of iphone 15 across amazon and bestbuy",
            "browse and find the best wireless mice",
            "deep research on quantum computing breakthroughs",
        ]
        for q in queries:
            cmd = parse_deterministic_command(q, state=self.state)
            self.assertIsNotNone(cmd, f"Failed for '{q}'")
            self.assertEqual(cmd.action, Action.AGENT_TASK)
            self.assertEqual(cmd.target, q)

    def test_11_agent_task_not_split_in_multi_command(self):
        """11. Complex autonomous goal is not incorrectly chopped into fragments."""
        q = "find five good gaming laptops on amazon and compare them"
        cmds = parse_multi_command(q, state=self.state)
        # parse_multi_command returns None for agent tasks so it's treated as a single unified task
        self.assertIsNone(cmds)

        # And Laya.understand_many returns single Command(AGENT_TASK, ...)
        mock_agent = MagicMock()
        laya_instance = Laya(agent=mock_agent)
        result_cmds = laya_instance.understand_many(q, state=self.state)
        self.assertEqual(len(result_cmds), 1)
        self.assertEqual(result_cmds[0].action, Action.AGENT_TASK)
        self.assertEqual(result_cmds[0].target, q)

    def test_12_stop_preemption_interrupts_wait_under_5ms(self):
        """12. Emergency STOP/Cancel interrupts WAIT within <5ms."""
        executor = Executor(state=self.state)
        cancel_event = threading.Event()

        # Trigger cancel_event after 10ms
        timer = threading.Timer(0.010, cancel_event.set)
        timer.start()

        t0 = time.perf_counter()
        # Request 5 second wait
        cmd = Command(Action.WAIT, "5")
        executor.execute(cmd, cancel_event=cancel_event)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        timer.join()
        # Should have woken up almost immediately after timer fired (within ~15ms total instead of 5000ms)
        threshold_ms = 250.0 if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS") else 50.0
        self.assertLess(elapsed_ms, threshold_ms)

    def test_13_agent_task_cancellation(self):
        """13. Autonomous browser agent responds to cancellation."""
        from browser.agent import AutonomousBrowserAgent

        agent = AutonomousBrowserAgent()
        cancel_event = threading.Event()
        cancel_event.set()  # Already cancelled

        t0 = time.perf_counter()
        result = agent.run_task("research quantum computing", cancel_event=cancel_event)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        self.assertFalse(result["success"])
        self.assertTrue(result["cancelled"])
        self.assertLess(elapsed_ms, 10.0)

    # ==========================================
    # REGRESSION SAFETY & NORMALIZATION
    # ==========================================

    def test_14_normal_browser_search_unaffected(self):
        """14. Existing deterministic search and compound commands remain intact."""
        cmds = parse_multi_command("Open YouTube and search for Python tutorials", state=self.state)
        self.assertIsNotNone(cmds)
        self.assertEqual(len(cmds), 2)
        self.assertEqual(cmds[0].action, Action.OPEN_URL)
        self.assertEqual(cmds[1].action, Action.SEARCH)

    def test_15_bare_go_back_unaffected(self):
        """15. 'go back' remains browser navigation, while 'go back 10 seconds' is media rewind."""
        nav_cmd = parse_deterministic_command("go back", state=self.state)
        self.assertEqual(nav_cmd.action, Action.GO_BACK)

        media_cmd = parse_deterministic_command("go back 10 seconds", state=self.state)
        self.assertEqual(media_cmd.action, Action.MEDIA_BACKWARD)
        self.assertEqual(media_cmd.target, "10")

    def test_16_agent_task_initialization_logs_and_ollama(self):
        """16. Autonomous browser agent initializes the explicitly injected Ollama provider."""
        from browser.agent import AutonomousBrowserAgent
        from providers.ai import OllamaAIProvider
        from providers.configuration import AIConfig

        model = "qwen3:1.7b"
        endpoint = "http://127.0.0.1:11434"
        provider = OllamaAIProvider(
            AIConfig(
                provider="local",
                runtime="ollama",
                model=model,
                base_url=endpoint,
            )
        )
        agent = AutonomousBrowserAgent(ai_provider=provider)
        with patch("browser_use.llm.ChatOllama") as mock_chat_ollama, \
             patch("browser.agent.log_info") as mock_log_info:
            mock_chat_ollama.return_value = MagicMock()
            llm = agent._get_llm()
            self.assertIsNotNone(llm)
            mock_chat_ollama.assert_called_once()
            _, kwargs = mock_chat_ollama.call_args
            self.assertEqual(kwargs.get("model"), model)
            self.assertEqual(kwargs.get("host"), endpoint)

            # Check logging calls
            logged_messages = [call.args[0] for call in mock_log_info.call_args_list]
            self.assertTrue(any("LLM provider: Ollama" in msg for msg in logged_messages))
            self.assertTrue(any(f"LLM model: {model}" in msg for msg in logged_messages))
            self.assertTrue(any(f"LLM endpoint: {endpoint}" in msg for msg in logged_messages))
            self.assertTrue(any("Browser Use initialized" in msg for msg in logged_messages))

    def test_17_agent_task_failure_restores_state_and_records_error(self):
        """17. AGENT_TASK failure restores state and does not leave agent_running active."""
        executor = Executor(state=self.state)
        mock_browser_agent = MagicMock()
        mock_browser_agent.run_task.return_value = {
            "success": False,
            "cancelled": False,
            "final_result": "AGENT_FAILED: Could not find search results",
        }
        executor.browser_agent = mock_browser_agent

        cmd = Command(Action.AGENT_TASK, "research quantum computing")
        res = executor.execute(cmd)
        self.assertEqual(res, "OK")
        self.assertTrue(executor.join_agent(timeout=1.0))
        self.assertFalse(self.state.agent_running)
        self.assertEqual(executor.last_agent_result, "FAILED")
        self.assertIn("AGENT_FAILED", executor.last_agent_error)

    def test_18_agent_task_cancelled_reports_cancelled(self):
        """18. AGENT_TASK cancellation returns CANCELLED and resets agent_running state."""
        executor = Executor(state=self.state)
        mock_browser_agent = MagicMock()
        mock_browser_agent.run_task.return_value = {
            "success": False,
            "cancelled": True,
            "final_result": "CANCELLED",
        }
        executor.browser_agent = mock_browser_agent

        cancel_event = threading.Event()
        cancel_event.set()
        cmd = Command(Action.AGENT_TASK, "research quantum computing")
        res = executor.execute(cmd, cancel_event=cancel_event)
        self.assertEqual(res, "CANCELLED")
        self.assertFalse(self.state.agent_running)


    # ==========================================
    # STAGE 4: REGRESSION FIXES (ISSUES 1 - 5)
    # ==========================================

    def test_19_issue1_async_browser_agent_in_running_event_loop(self):
        """Issue 1: execute_task can be awaited directly in a running event loop without asyncio.run crash."""
        import asyncio
        from browser.agent import AutonomousBrowserAgent

        agent = AutonomousBrowserAgent()

        async def run_in_loop():
            # In an active event loop, execute_task should be an async coroutine
            # that executes without raising RuntimeError: asyncio.run() cannot be called from a running event loop
            with patch.object(agent, "_get_llm", return_value=MagicMock()), \
                 patch("browser_use.Agent") as mock_agent_cls, \
                 patch("browser_use.Browser"):
                mock_instance = MagicMock()
                # Mock async run method on browser_use Agent
                async def mock_run(max_steps=5):
                    mock_history = MagicMock()
                    mock_history.final_result.return_value = "https://github.com/python/cpython"
                    mock_history.is_successful.return_value = True
                    return mock_history
                mock_instance.run = mock_run
                mock_agent_cls.return_value = mock_instance

                result = await agent.execute_task("Find official GitHub page for Python", max_steps=1)
                self.assertTrue(result.startswith("AGENT_COMPLETED"))
                self.assertIn("https://github.com/python/cpython", result)

        asyncio.run(run_in_loop())

    def test_20_issue1_sync_run_task_safe_inside_running_loop(self):
        """Issue 1: sync run_task called when an event loop is running does not crash."""
        import asyncio
        from browser.agent import AutonomousBrowserAgent

        agent = AutonomousBrowserAgent()

        async def caller():
            # Calling synchronous run_task from inside an active event loop
            with patch.object(agent, "execute_task") as mock_exec:
                async def mock_coro(task_prompt, max_steps=5, cancel_event=None):
                    return "AGENT_COMPLETED: Done"
                mock_exec.side_effect = mock_coro
                res = agent.run_task("test prompt")
                self.assertTrue(res.get("success"))
                self.assertEqual(res.get("final_result"), "AGENT_COMPLETED: Done")

        asyncio.run(caller())

    def test_21_issue2_agent_task_intent_detection(self):
        """Issue 2: Natural research & autonomous goals route to AGENT_TASK, not FIND_ELEMENT."""
        agent_prompts = [
            "Find the official GitHub page for Python and tell me its URL.",
            "Find three Python AI agent frameworks and summarize their names and main purpose.",
            "Research top Python libraries for web scraping",
            "Compare React and Vue performance",
            "Summarize the latest release notes for Python 3.13",
            "Find the official LangGraph repository",
            "Look up current weather in Tokyo and tell me",
        ]
        for prompt in agent_prompts:
            cmd = parse_deterministic_command(prompt, state=self.state)
            self.assertIsNotNone(cmd, f"Failed to parse: {prompt}")
            self.assertEqual(
                cmd.action,
                Action.AGENT_TASK,
                f"Expected AGENT_TASK for '{prompt}', got {cmd.action.name}",
            )

    def test_22_issue2_find_element_preserved_for_dom_lookups(self):
        """Issue 2: Deterministic DOM element lookups cleanly route to FIND_ELEMENT."""
        find_prompts = [
            ("find the search button", "search"),
            ("find login", "login"),
            ("find the subscribe button", "subscribe"),
            ("find link Download", "Download"),
        ]
        for prompt, expected_target in find_prompts:
            cmd = parse_deterministic_command(prompt, state=self.state)
            self.assertIsNotNone(cmd, f"Failed to parse: {prompt}")
            self.assertEqual(
                cmd.action,
                Action.FIND_ELEMENT,
                f"Expected FIND_ELEMENT for '{prompt}', got {cmd.action.name}",
            )
            self.assertEqual(cmd.target, expected_target)

    def test_23_issue3_search_langgraph_and_open_official_repo(self):
        """Issue 3: 'search LangGraph and open the official repository' parses to SEARCH + CLICK_RESULT."""
        text = "search LangGraph and open the official repository"
        # When browser is already open on Google, resolves directly to [SEARCH, CLICK_RESULT]
        open_state = LightState(browser_open=True, current_site="google", current_url="https://google.com")
        cmds = parse_multi_command(text, state=open_state)
        self.assertIsNotNone(cmds)
        self.assertEqual(len(cmds), 2)
        self.assertEqual(cmds[0].action, Action.SEARCH)
        self.assertIn("LangGraph", cmds[0].target)
        self.assertEqual(cmds[1].action, Action.CLICK_RESULT)
        self.assertEqual(cmds[1].target, "official repository")

        # When browser is not yet open, Plan Normalization prepends OPEN_URL
        fresh_cmds = parse_multi_command(text, state=self.state)
        self.assertIsNotNone(fresh_cmds)
        self.assertEqual(len(fresh_cmds), 3)
        self.assertEqual(fresh_cmds[0].action, Action.OPEN_URL)
        self.assertEqual(fresh_cmds[1].action, Action.SEARCH)
        self.assertEqual(fresh_cmds[2].action, Action.CLICK_RESULT)
        self.assertEqual(fresh_cmds[2].target, "official repository")

    def test_24_issue3_named_target_passes_search_context(self):
        """Issue 3: Executor forwards search context when opening a named search target."""
        executor = Executor(state=self.state)
        executor.browser = MagicMock()
        self.state.last_search_query = "LangGraph"

        cmd = Command(Action.CLICK_RESULT, "official repository")
        executor.execute(cmd)

        executor.browser.click_result.assert_called_once_with(
            "official repository",
            mouse_controller=executor.mouse,
            search_context="LangGraph",
        )

    def test_25_issue4_first_result_variations(self):
        """Issue 4: Variations of 'first result' resolve to CLICK_RESULT('1')."""
        variations = [
            "click the first result",
            "click first result",
            "click result one",
            "click result 1",
            "open result 1",
            "select the first result",
        ]
        for phrase in variations:
            cmd = parse_deterministic_command(phrase, state=self.state)
            self.assertIsNotNone(cmd, f"Failed to parse: {phrase}")
            self.assertEqual(
                cmd.action,
                Action.CLICK_RESULT,
                f"Expected CLICK_RESULT for '{phrase}', got {cmd.action.name}",
            )
            self.assertEqual(cmd.target, "1")

    def test_26_issue4_click_first_element_safe_handling(self):
        """Issue 4: 'click the first element' never performs literal text search for 'first element'."""
        # On generic page, parses to CLICK_ELEMENT("element 1")
        cmd = parse_deterministic_command("click the first element", state=self.state)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.action, Action.CLICK_ELEMENT)
        self.assertEqual(cmd.target, "element 1")

        # In browser.py parse_element_target, "element 1" resolves to kind: nth_clickable
        from browser.browser import BrowserController
        parsed = BrowserController.parse_element_target("element 1")
        self.assertEqual(parsed.get("kind"), "nth_clickable")
        self.assertEqual(parsed.get("index"), 1)
        self.assertNotEqual(parsed.get("kind"), "element")

    def test_27_issue5_find_element_failure_raises_and_never_reports_ok(self):
        """Issue 5: When an element is not found, executor raises error and does not report OK."""
        executor = Executor(state=self.state)
        executor.browser = MagicMock()
        executor.browser.find_element.return_value = False

        cmd = Command(Action.FIND_ELEMENT, "nonexistent button")
        with self.assertRaises(RuntimeError) as ctx:
            executor.execute(cmd)
        self.assertIn("Element not found on page", str(ctx.exception))

    def test_28_issue5_click_failure_never_reports_ok(self):
        """Issue 5: When click fails verification or target is missing, executor raises error."""
        executor = Executor(state=self.state)
        executor.browser = MagicMock()
        executor.browser.click_element.side_effect = ValueError("Could not find a visible element matching 'missing'")

        cmd = Command(Action.CLICK_ELEMENT, "missing")
        with self.assertRaises(ValueError):
            executor.execute(cmd)

    # ==========================================
    # REGRESSION TESTS FOR ISSUES 1, 2, AND 3
    # ==========================================

    def test_29_click_on_first_element_never_literal_target(self):
        """Issue 1: 'Click on First Element.' never resolves to literal CLICK_ELEMENT('First Element')."""
        search_state = LightState(current_site="google", last_search_query="Langraph", browser_open=True)
        cmd_search = parse_deterministic_command("Click on First Element.", state=search_state)
        self.assertIsNotNone(cmd_search)
        self.assertEqual(cmd_search.action, Action.CLICK_RESULT)
        self.assertEqual(cmd_search.target, "1")

        generic_state = LightState(browser_open=True)
        cmd_gen = parse_deterministic_command("Click on First Element.", state=generic_state)
        self.assertIsNotNone(cmd_gen)
        self.assertEqual(cmd_gen.action, Action.CLICK_ELEMENT)
        self.assertEqual(cmd_gen.target, "element 1")

        for phrase in ("Click First Element", "click on the first element", "click element 1", "click on 1st element"):
            cmd = parse_deterministic_command(phrase, state=search_state)
            self.assertEqual(cmd.action, Action.CLICK_RESULT)
            self.assertEqual(cmd.target, "1")

            cmd2 = parse_deterministic_command(phrase, state=generic_state)
            self.assertEqual(cmd2.action, Action.CLICK_ELEMENT)
            self.assertEqual(cmd2.target, "element 1")

    def test_30_executor_normalizes_click_element_ordinals(self):
        """Issue 1: Executor normalizes any CLICK_ELEMENT ordinal targets."""
        executor = Executor(state=self.state)
        executor.browser = MagicMock()

        # In search context: CLICK_ELEMENT("First Element") forwards to click_result
        self.state.last_search_query = "Langraph"
        executor.execute(Command(Action.CLICK_ELEMENT, "First Element"))
        executor.browser.click_result.assert_called_with(1, mouse_controller=executor.mouse)

        # On generic page: CLICK_ELEMENT("First Element") calls click_element("element 1")
        self.state.last_search_query = None
        self.state.current_site = None
        executor.browser.reset_mock()
        executor.execute(Command(Action.CLICK_ELEMENT, "First Element"))
        executor.browser.click_element.assert_called_with("element 1", mouse_controller=executor.mouse)

    def test_31_multi_step_trailing_incomplete_action_preserves_pending_goal(self):
        """Issue 2: Utterance 1 preserves valid prefix commands and sets pending goal in state."""
        u1 = "Open GitHub, search for Langraph and open"
        cmds = parse_multi_command(u1, state=self.state)
        self.assertIsNotNone(cmds)
        self.assertTrue(len(cmds) >= 2)
        self.assertEqual(cmds[0].action, Action.OPEN_URL)
        self.assertEqual(cmds[-1].action, Action.SEARCH)
        self.assertIn("Langraph", cmds[-1].target)
        self.assertEqual(self.state.pending_incomplete_action, "open")
        self.assertIn("Langraph", self.state.pending_goal)

    def test_32_utterance2_official_repository_resolves_without_open_url_error(self):
        """Issue 2: Utterance 2 'Official repository' parses to CLICK_RESULT and rejects OPEN_URL."""
        from brain.decision import validate_command
        cmd = parse_deterministic_command("Official repository", state=self.state)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.action, Action.CLICK_RESULT)
        self.assertEqual(cmd.target, "official repository")

        # Confirm validate_command strictly rejects OPEN_URL for official repository
        with self.assertRaises(ValueError):
            validate_command("Official repository", Command(Action.OPEN_URL, "official repository"))

    def test_33_llm_planner_rejects_no_think_and_control_tokens(self):
        """Issue 2: LLM planner rejects /no_think control tokens and cleans them from raw output."""
        import json
        from brain.llm import validate_llm_action, QwenPlanner
        with self.assertRaises(ValueError):
            validate_llm_action("open link", {"action": "OPEN_URL", "target": "/no_think"})

        with self.assertRaises(ValueError):
            validate_llm_action("open link", {"action": "OPEN_URL", "target": "<think>tag</think>"})

        with self.assertRaises(ValueError):
            validate_llm_action("open link", {"action": "OPEN_URL", "target": "official repository"})

        # Test _call_ollama strips /no_think
        planner = QwenPlanner(enabled=True)
        raw_json_str = '{"actions": [{"action": "OPEN_URL", "target": "https://github.com"}]}'
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"message": {"content": f"/no_think {raw_json_str}"}}).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp
            result = planner._call_ollama("test")
            self.assertIn("actions", result)
            self.assertEqual(result["actions"][0]["target"], "https://github.com")

    def test_34_async_agent_task_execution_in_active_event_loop(self):
        """Issue 3: Native async execution in an active event loop thread without asyncio.run() crash."""
        import asyncio
        from core.loop import LightLoop

        mock_handy = MagicMock()
        mock_laya = MagicMock()
        agent_cmd = Command(Action.AGENT_TASK, "research three Python frameworks and compare them")
        mock_laya.understand.return_value = agent_cmd
        mock_laya.understand_many.return_value = [agent_cmd]
        mock_executor = Executor(state=self.state)
        mock_agent = MagicMock()

        async def fake_execute_task(task_prompt="", max_steps=5, cancel_event=None, task_instruction=""):
            return "AGENT_COMPLETED: Found Python frameworks"

        mock_agent.execute_task = fake_execute_task
        mock_executor.browser_agent = mock_agent

        loop = LightLoop(handy=mock_handy, laya=mock_laya, executor=mock_executor, state=self.state)

        async def run_async_test():
            res = await loop.process_text_async("research three Python frameworks and compare them")
            self.assertEqual(res, "OK")

        asyncio.run(run_async_test())

    def test_35_run_task_safe_inside_running_loop(self):
        """Issue 3: AutonomousBrowserAgent.run_task safe to call from within an active event loop."""
        import asyncio
        from browser.agent import AutonomousBrowserAgent

        agent = AutonomousBrowserAgent()

        async def fake_execute_task(task_prompt="", max_steps=5, cancel_event=None, task_instruction=""):
            return "AGENT_COMPLETED: Done"

        agent.execute_task = fake_execute_task

        async def test_caller():
            # In an active event loop, calling synchronous run_task must not raise:
            # RuntimeError: asyncio.run() cannot be called from a running event loop
            res = agent.run_task("test goal")
            self.assertTrue(res["success"])
            self.assertEqual(res["final_result"], "AGENT_COMPLETED: Done")

        asyncio.run(test_caller())

    def test_36_stop_cancellation_during_agent_task(self):
        """Issue 3: Immediate STOP cancellation during AGENT_TASK."""
        import asyncio
        from browser.agent import AutonomousBrowserAgent

        agent = AutonomousBrowserAgent()
        cancel_evt = threading.Event()
        cancel_evt.set()  # Cancelled beforehand

        res = agent.run_task("test goal", cancel_event=cancel_evt)
        self.assertTrue(res["cancelled"])
        self.assertEqual(res["final_result"], "CANCELLED")

    # ==========================================
    # BROWSER WORKFLOW RELIABILITY & OWNERSHIP
    # ==========================================

    def test_37_open_github_search_langgraph_open_official_repo(self):
        """1. Open GitHub + search LangGraph + open official repository compound flow."""
        spoken = "Open GitHub, search for LangGraph and open the official repository."
        cmds = parse_multi_command(spoken, state=self.state)
        self.assertIsNotNone(cmds)
        self.assertEqual(len(cmds), 3)
        self.assertEqual(cmds[0].action, Action.OPEN_URL)
        self.assertEqual(cmds[0].target, "https://github.com")
        self.assertEqual(cmds[1].action, Action.SEARCH)
        self.assertEqual(cmds[1].target, "github:LangGraph")
        self.assertEqual(cmds[2].action, Action.CLICK_RESULT)
        self.assertEqual(cmds[2].target, "official repository")

        # Execute with executor and mock browser
        executor = Executor(state=self.state)
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = True

        for cmd in cmds:
            res = executor.execute(cmd)
            self.assertEqual(res, "OK")

        executor.browser.open_url.assert_called_once_with("https://github.com")
        executor.browser.search.assert_called_once_with("LangGraph", engine="github")
        executor.browser.click_result.assert_called_once()
        self.assertEqual(self.state.current_site, "github")
        self.assertEqual(self.state.last_search_query, "LangGraph")

    def test_38_official_repository_continuation_after_pending_search(self):
        """2. 'Official repository' continuation after a pending search context."""
        self.state.current_site = "github"
        self.state.last_search_query = "LangGraph"
        self.state.browser_open = True

        cmd = parse_deterministic_command("Official repository", state=self.state)
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd.action, Action.CLICK_RESULT)
        self.assertEqual(cmd.target, "official repository")

        executor = Executor(state=self.state)
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = True

        res = executor.execute(cmd)
        self.assertEqual(res, "OK")
        executor.browser.click_result.assert_called_once_with(
            "official repository",
            mouse_controller=executor.mouse,
            search_context="LangGraph",
        )

    def test_39_named_result_ranking_selects_repository_over_irrelevant(self):
        """3. Named result ranking prioritizes official repository link over irrelevant math page."""
        from browser.browser import BrowserController

        bc = BrowserController()
        bc.is_active = MagicMock(return_value=True)
        bc.page = MagicMock()
        def mock_evaluate(script, params=None):
            if params and params.get("kind") == "named_result":
                target = params.get("targetQuery", "").lower()
                ctx = params.get("searchContext", "").lower()
                if "repo" in target and "langgraph" in ctx:
                    return {
                        "found": True,
                        "vp_x": 300,
                        "vp_y": 200,
                        "pre_text": "langchain-ai/langgraph",
                        "target_href": "https://github.com/langchain-ai/langgraph",
                        "matched": "langchain-ai/langgraph: Build resilient language agents as graphs",
                    }
            return {"found": False}

        bc.page.evaluate.side_effect = mock_evaluate
        info = bc.locate_element_in_viewport("official repository", search_context="LangGraph", perform_click=False)
        self.assertTrue(info["found"])
        self.assertIn("langgraph", info["target_href"].lower())
        self.assertIn("github.com", info["target_href"].lower())

    def test_40_wrong_result_detection(self):
        """4. Wrong result detection: when no repository or matching target exists, fails safely."""
        from browser.browser import BrowserController

        bc = BrowserController()
        bc.is_active = MagicMock(return_value=True)
        bc.page = MagicMock()
        bc.page.evaluate.return_value = {
            "found": False,
            "error": "Could not find a high-confidence search result matching official repository",
        }

        with self.assertRaises(RuntimeError) as ctx:
            bc.locate_element_in_viewport("official repository", search_context="LangGraph", perform_click=False)
        self.assertIn("Could not find a high-confidence search result", str(ctx.exception))

    def test_41_semantic_post_click_verification(self):
        """5. Semantic post-click verification: succeeds on valid landing, raises on wrong destination."""
        from browser.browser import BrowserController

        bc = BrowserController()
        bc.is_active = MagicMock(return_value=True)
        bc.page = MagicMock()

        # Success case: lands on github repo
        bc.get_current_url = MagicMock(return_value="https://github.com/langchain-ai/langgraph")
        bc.get_title = MagicMock(return_value="langchain-ai/langgraph: Build resilient language agents as graphs")
        bc.get_visible_text = MagicMock(return_value="LangGraph overview and documentation")

        # Must not raise
        bc.verify_destination(expected_target="official repository", expected_query="LangGraph")

        # Failure case 1: lands on wrong domain (mathworld)
        bc.get_current_url.return_value = "https://mathworld.com/graph-paper"
        bc.get_title.return_value = "Graph Paper for High School Math"
        with self.assertRaises(RuntimeError) as ctx1:
            bc.verify_destination(expected_target="official repository", expected_query="LangGraph")
        self.assertIn("Semantic verification failed", str(ctx1.exception))

        # Failure case 2: lands on github but completely unrelated project
        bc.get_current_url.return_value = "https://github.com/unrelated/calculator-app"
        bc.get_title.return_value = "unrelated/calculator-app"
        bc.get_visible_text.return_value = "A simple calculator written in C"
        with self.assertRaises(RuntimeError) as ctx2:
            bc.verify_destination(expected_target="official repository", expected_query="LangGraph")
        self.assertIn("Semantic verification failed", str(ctx2.exception))

    def test_41b_semantic_verification_rejects_inactive_and_unchanged_pages(self):
        """A dispatched click is not success when the browser closes or URL never changes."""
        from browser.browser import BrowserController

        bc = BrowserController()
        bc.page = MagicMock()
        bc.is_active = MagicMock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, "browser became inactive"):
            bc.verify_destination("official repository", expected_query="LangGraph")

        search_url = "https://github.com/search?q=langgraph&type=repositories"
        bc.is_active.return_value = True
        bc.get_current_url = MagicMock(return_value=search_url)
        bc.get_title = MagicMock(return_value="Repository search results")
        bc.get_visible_text = MagicMock(return_value="LangGraph official repository")
        with self.assertRaisesRegex(RuntimeError, "did not navigate away"):
            bc.verify_destination(
                "official repository",
                expected_query="LangGraph",
                pre_url=search_url,
                navigation_timeout=0,
            )

    def test_41c_semantic_verification_wait_is_stop_cancellable(self):
        from browser.browser import BrowserController

        bc = BrowserController()
        bc.page = MagicMock()
        bc.is_active = MagicMock(return_value=True)
        bc.get_current_url = MagicMock(return_value="https://example.com/search")
        cancel_event = threading.Event()
        cancel_event.set()

        started = time.perf_counter()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            bc.verify_destination(
                "official repository",
                pre_url="https://example.com/search",
                cancel_event=cancel_event,
                navigation_timeout=3,
            )
        self.assertLess((time.perf_counter() - started) * 1000, 50)

    def test_42_browser_ownership_transitions(self):
        """6. Browser ownership transitions: NONE -> LIGHT -> AGENT -> NONE."""
        from core.state import BrowserOwnership

        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.NONE.value)

        executor = Executor(state=self.state)
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = True

        # LIGHT ownership during normal browser commands
        executor.execute(Command(Action.OPEN_URL, "https://github.com"))
        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.LIGHT.value)

        # AGENT ownership during AGENT_TASK
        mock_agent = MagicMock()
        mock_agent.run_task.return_value = {"success": True, "final_result": "Done"}
        executor.browser_agent = mock_agent

        def check_agent_ownership(*args, **kwargs):
            self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.AGENT.value)
            return {"success": True, "final_result": "Done"}

        mock_agent.run_task.side_effect = check_agent_ownership
        executor.execute(Command(Action.AGENT_TASK, "research frameworks"))
        self.assertTrue(executor.join_agent(timeout=1.0))

        # Restores to LIGHT after agent task because browser is active
        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.LIGHT.value)

        # Transitions to NONE on STOP
        executor.execute(Command(Action.STOP, None))
        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.NONE.value)

    def test_43_normal_desktop_command_while_agent_task_running(self):
        """7. Normal desktop commands (Open Notepad, hotkeys) execute while AGENT ownership is active."""
        from core.state import BrowserOwnership

        self.state.set_browser_ownership(BrowserOwnership.AGENT)
        self.state.agent_running = True

        executor = Executor(state=self.state)
        executor.apps = MagicMock()
        executor.screen = MagicMock()
        executor.screen.get_foreground_window_info.return_value = {"title": "Notepad", "process_name": "notepad.exe"}

        # Open Notepad should execute freely
        res = executor.execute(Command(Action.OPEN_APP, "notepad"))
        self.assertEqual(res, "OK")
        executor.apps.open.assert_called_once()
        self.assertEqual(self.state.current_app, "notepad")

        # Hotkeys execute freely
        with patch("pyautogui.hotkey") as mock_hotkey:
            res_hotkey = executor.execute(Command(Action.HOTKEY, "ctrl+c"))
            self.assertEqual(res_hotkey, "OK")
            expected_keys = ("command", "c") if sys.platform == "darwin" else ("ctrl", "c")
            mock_hotkey.assert_called_once_with(*expected_keys)

    def test_43b_deterministic_browser_command_preserves_active_agent_ownership(self):
        """Concurrent isolated LIGHT navigation must not erase active AGENT ownership."""
        from core.state import BrowserOwnership

        self.state.set_browser_ownership(BrowserOwnership.AGENT)
        self.state.agent_running = True
        executor = Executor(state=self.state)
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = True

        result = executor.execute(Command(Action.OPEN_URL, "https://github.com"))

        self.assertEqual(result, "OK")
        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.AGENT.value)

    def test_44_stop_while_agent_task_running(self):
        """8. STOP while AGENT_TASK is running immediately cancels agent and resets ownership."""
        from core.state import BrowserOwnership

        self.state.set_browser_ownership(BrowserOwnership.AGENT)
        self.state.agent_running = True

        executor = Executor(state=self.state)
        mock_agent = MagicMock()
        executor.browser_agent = mock_agent
        executor.browser = MagicMock()

        res = executor.execute(Command(Action.STOP, None))
        self.assertEqual(res, "STOP")
        mock_agent.cancel.assert_called_once()
        self.assertFalse(self.state.agent_running)
        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.NONE.value)
        executor.browser.close.assert_called_once()

    def test_44b_stop_clears_stale_browser_state(self):
        self.state.current_app = "brave"
        self.state.current_browser = "brave"
        self.state.current_url = "https://github.com/example/repo"
        self.state.current_title = "Example repository"
        self.state.current_site = "github"
        self.state.browser_open = True

        executor = Executor(state=self.state)
        executor.browser = MagicMock()
        result = executor.execute(Command(Action.STOP, None), raw_text="Stop")

        self.assertEqual(result, "STOP")
        self.assertFalse(self.state.browser_open)
        self.assertIsNone(self.state.current_app)
        self.assertIsNone(self.state.current_browser)
        self.assertIsNone(self.state.current_url)
        self.assertIsNone(self.state.current_title)
        self.assertIsNone(self.state.current_site)
        executor.browser.close.assert_called_once()

    # ==========================================
    # BACKGROUND AGENT EXECUTION & PREEMPTION (TESTS A - H)
    # ==========================================

    def _create_mock_laya(self):
        mock_laya = MagicMock()
        def mock_understand(text, state=None):
            t = text.lower()
            if "research" in t or "compare" in t:
                return Command(Action.AGENT_TASK, text)
            if "open notepad" in t:
                return Command(Action.OPEN_APP, "notepad")
            if "close notepad" in t:
                return Command(Action.CLOSE_APP, "notepad")
            if "open youtube" in t:
                return Command(Action.OPEN_URL, "https://youtube.com")
            if "open google" in t:
                return Command(Action.OPEN_URL, "https://google.com")
            if "stop" in t:
                return Command(Action.STOP, None)
            return Command(Action.WAIT, "1")
        mock_laya.understand.side_effect = mock_understand
        mock_laya.understand_many.side_effect = lambda text, state=None: [mock_understand(text, state)]
        return mock_laya

    def test_45_agent_task_dispatch_is_non_blocking(self):
        """A. AGENT_TASK dispatch is non-blocking: execute_next_queued returns immediately."""
        from core.loop import LightLoop

        agent_started = threading.Event()
        agent_block = threading.Event()

        mock_agent = MagicMock()

        def slow_agent(*args, **kwargs):
            agent_started.set()
            agent_block.wait(timeout=5.0)
            return {"success": True, "cancelled": False, "final_result": "Done"}

        mock_agent.run_task.side_effect = slow_agent

        executor = Executor(state=self.state)
        executor.browser_agent = mock_agent

        mock_handy = MagicMock()
        mock_laya = self._create_mock_laya()
        loop = LightLoop(handy=mock_handy, laya=mock_laya, executor=executor, state=self.state)

        # Enqueue AGENT_TASK
        loop.ingest_text("Research three Python AI agent frameworks and compare them")

        t0 = time.perf_counter()
        res = loop.execute_next_queued(timeout=0.1)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        try:
            self.assertEqual(res, "OK")
            # Must return in under 50ms (typically <2ms), proving non-blocking dispatch
            threshold_ms = 250.0 if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS") else 50.0
            self.assertLess(elapsed_ms, threshold_ms)
            # Worker thread is active
            self.assertTrue(agent_started.wait(timeout=1.0))
            self.assertTrue(self.state.agent_running)
        finally:
            agent_block.set()
            executor.join_agent(timeout=1.0)

    def test_46_normal_command_while_agent_runs(self):
        """B. Normal desktop command executes immediately while background agent runs."""
        from core.loop import LightLoop

        agent_block = threading.Event()
        mock_agent = MagicMock()

        def slow_agent(*args, **kwargs):
            agent_block.wait(timeout=5.0)
            return {"success": True, "cancelled": False, "final_result": "Done"}

        mock_agent.run_task.side_effect = slow_agent

        executor = Executor(state=self.state)
        executor.browser_agent = mock_agent
        executor.apps = MagicMock()
        executor.screen = MagicMock()
        executor.screen.get_foreground_window_info.return_value = {"title": "Notepad", "process_name": "notepad.exe"}

        mock_handy = MagicMock()
        mock_laya = self._create_mock_laya()
        loop = LightLoop(handy=mock_handy, laya=mock_laya, executor=executor, state=self.state)

        # 1. Enqueue AGENT_TASK
        loop.ingest_text("Research frameworks")
        # 2. Enqueue normal command
        loop.ingest_text("Open Notepad")

        try:
            # Dispatch agent task
            res_agent = loop.execute_next_queued(timeout=0.1)
            self.assertEqual(res_agent, "OK")
            self.assertTrue(self.state.agent_running)

            # Next command: Open Notepad must execute immediately without waiting for agent
            t0 = time.perf_counter()
            res_notepad = loop.execute_next_queued(timeout=0.1)
            notepad_ms = (time.perf_counter() - t0) * 1000.0

            self.assertEqual(res_notepad, "OK")
            self.assertLess(notepad_ms, 50.0)
            executor.apps.open.assert_called_once()
            self.assertEqual(self.state.current_app, "notepad")
            # Agent should still be running in the background
            self.assertTrue(self.state.agent_running)
        finally:
            agent_block.set()
            executor.join_agent(timeout=1.0)

    def test_47_multiple_normal_commands_execute_in_queue_order_during_agent_task(self):
        """C. Multiple normal commands execute in queue order with low latency while agent runs."""
        from core.loop import LightLoop

        agent_block = threading.Event()
        mock_agent = MagicMock()

        def slow_agent(*args, **kwargs):
            agent_block.wait(timeout=5.0)
            return {"success": True, "cancelled": False, "final_result": "Done"}

        mock_agent.run_task.side_effect = slow_agent

        executor = Executor(state=self.state)
        executor.browser_agent = mock_agent
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = True
        executor.apps = MagicMock()

        mock_handy = MagicMock()
        mock_laya = self._create_mock_laya()
        loop = LightLoop(handy=mock_handy, laya=mock_laya, executor=executor, state=self.state)

        # Ingest agent task then multiple normal commands
        loop.ingest_text("Research frameworks")
        loop.ingest_text("Open YouTube")
        loop.ingest_text("Open Google")
        loop.ingest_text("Close Notepad")

        execution_order = []

        executor.browser.open_url.side_effect = lambda url: execution_order.append(f"url:{url}")
        executor.apps.close.side_effect = lambda app: execution_order.append(f"close:{app}")

        try:
            # 1. Dispatch agent task
            res0 = loop.execute_next_queued(timeout=0.1)
            self.assertEqual(res0, "OK")

            # 2. Open YouTube
            res1 = loop.execute_next_queued(timeout=0.1)
            self.assertEqual(res1, "OK")

            # 3. Open Google
            res2 = loop.execute_next_queued(timeout=0.1)
            self.assertEqual(res2, "OK")

            # 4. Close Notepad
            res3 = loop.execute_next_queued(timeout=0.1)
            self.assertEqual(res3, "OK")

            # Verify exact order
            self.assertEqual(
                execution_order,
                ["url:https://youtube.com", "url:https://google.com", "close:notepad"],
            )
        finally:
            agent_block.set()
            executor.join_agent(timeout=1.0)

    def test_48_stop_preemption_cancels_background_agent_within_bounded_time(self):
        """D. STOP preemption cancels running background agent and resets state within bounded time."""
        from core.loop import LightLoop
        from core.state import BrowserOwnership

        agent_started = threading.Event()
        mock_agent = MagicMock()

        def slow_agent(*args, **kwargs):
            agent_started.set()
            cancel_evt = kwargs.get("cancel_event")
            if cancel_evt:
                cancel_evt.wait(timeout=5.0)
            return {"success": False, "cancelled": True, "final_result": "CANCELLED"}

        mock_agent.run_task.side_effect = slow_agent

        executor = Executor(state=self.state)
        executor.browser_agent = mock_agent
        executor.browser = MagicMock()

        mock_handy = MagicMock()
        mock_laya = self._create_mock_laya()
        loop = LightLoop(handy=mock_handy, laya=mock_laya, executor=executor, state=self.state)

        loop.ingest_text("Research frameworks")
        loop.execute_next_queued(timeout=0.1)
        self.assertTrue(agent_started.wait(timeout=1.0))
        self.assertTrue(self.state.agent_running)

        # Issue STOP
        loop.ingest_text("stop")

        t0 = time.perf_counter()
        res_stop = loop.execute_next_queued(timeout=0.1)
        stop_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(res_stop, "STOP")
        # STOP preemption must be bounded and fast (under 300ms)
        self.assertLess(stop_ms, 300.0)
        mock_agent.cancel.assert_called_once()
        self.assertFalse(self.state.agent_running)
        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.NONE.value)
        self.assertTrue(executor.join_agent(timeout=0.5))

    def test_49_duplicate_agent_task_rejected_while_active(self):
        """E. Duplicate AGENT_TASK while an agent is active is rejected with clear logging."""
        from core.loop import LightLoop

        agent_block = threading.Event()
        mock_agent = MagicMock()

        def slow_agent(*args, **kwargs):
            agent_block.wait(timeout=5.0)
            return {"success": True, "cancelled": False, "final_result": "Done"}

        mock_agent.run_task.side_effect = slow_agent

        executor = Executor(state=self.state)
        executor.browser_agent = mock_agent

        mock_handy = MagicMock()
        mock_laya = self._create_mock_laya()
        loop = LightLoop(handy=mock_handy, laya=mock_laya, executor=executor, state=self.state)

        # 1. First agent task
        loop.ingest_text("Research frameworks")
        res1 = loop.execute_next_queued(timeout=0.1)
        self.assertEqual(res1, "OK")
        self.assertTrue(self.state.agent_running)

        try:
            # 2. Duplicate agent task
            loop.ingest_text("Compare React and Vue")
            res2 = loop.execute_next_queued(timeout=0.1)
            self.assertEqual(res2, "REJECTED")

            # Ensure run_task was invoked only once
            self.assertEqual(mock_agent.run_task.call_count, 1)
            self.assertTrue(self.state.agent_running)
        finally:
            agent_block.set()
            executor.join_agent(timeout=1.0)

    def test_49b_agent_admission_uses_one_atomic_critical_section(self):
        """Admission, state publication, and worker publication share one lock hold."""
        class CountingLock:
            def __init__(self):
                self._lock = threading.Lock()
                self.entries = 0

            def __enter__(self):
                self._lock.acquire()
                self.entries += 1
                return self

            def __exit__(self, exc_type, exc, tb):
                self._lock.release()

        agent_block = threading.Event()
        mock_agent = MagicMock()

        def slow_agent(*args, **kwargs):
            agent_block.wait(timeout=5.0)
            return {"success": True, "cancelled": False, "final_result": "Done"}

        mock_agent.run_task.side_effect = slow_agent
        executor = Executor(state=self.state)
        executor.browser_agent = mock_agent
        counting_lock = CountingLock()
        executor._agent_lock = counting_lock

        try:
            self.assertEqual(executor.execute(Command(Action.AGENT_TASK, "research frameworks")), "OK")
            self.assertEqual(counting_lock.entries, 1)
            self.assertTrue(self.state.agent_running)
        finally:
            agent_block.set()
            executor.join_agent(timeout=1.0)

    def test_50_agent_completion_restores_state_safely(self):
        """F. Successful agent completion restores correct state and ownership."""
        from core.state import BrowserOwnership

        executor = Executor(state=self.state)
        mock_agent = MagicMock()
        mock_agent.run_task.return_value = {
            "success": True,
            "cancelled": False,
            "final_result": "AGENT_COMPLETED: Research finished.",
        }
        executor.browser_agent = mock_agent

        cmd = Command(Action.AGENT_TASK, "research quantum computing")
        res = executor.execute(cmd)
        self.assertEqual(res, "OK")

        # Wait for worker thread to complete
        self.assertTrue(executor.join_agent(timeout=1.0))
        self.assertFalse(self.state.agent_running)
        self.assertEqual(executor.last_agent_result, "COMPLETED")
        self.assertIsNone(executor.last_agent_error)
        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.NONE.value)

    def test_51_agent_failure_restores_state_safely(self):
        """G. Agent failure restores correct state and records failure."""
        from core.state import BrowserOwnership

        executor = Executor(state=self.state)
        mock_agent = MagicMock()
        mock_agent.run_task.return_value = {
            "success": False,
            "cancelled": False,
            "final_result": "AGENT_FAILED: Out of memory",
        }
        executor.browser_agent = mock_agent

        cmd = Command(Action.AGENT_TASK, "research quantum computing")
        res = executor.execute(cmd)
        self.assertEqual(res, "OK")

        self.assertTrue(executor.join_agent(timeout=1.0))
        self.assertFalse(self.state.agent_running)
        self.assertEqual(executor.last_agent_result, "FAILED")
        self.assertEqual(executor.last_agent_error, "AGENT_FAILED: Out of memory")
        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.NONE.value)

    def test_52_shutdown_cancels_active_agent_with_bounded_cleanup(self):
        """H. Shutdown cancels active agent worker and joins with bounded timeout."""
        from core.state import BrowserOwnership

        agent_block = threading.Event()
        mock_agent = MagicMock()

        def slow_agent(*args, **kwargs):
            agent_block.wait(timeout=5.0)
            return {"success": False, "cancelled": True, "final_result": "CANCELLED"}

        mock_agent.run_task.side_effect = slow_agent

        executor = Executor(state=self.state)
        executor.browser_agent = mock_agent
        executor.browser = MagicMock()

        # Start agent
        cmd = Command(Action.AGENT_TASK, "research quantum computing")
        res = executor.execute(cmd)
        self.assertEqual(res, "OK")
        self.assertTrue(self.state.agent_running)

        # Trigger shutdown
        t0 = time.perf_counter()
        executor.close(timeout=0.3)
        shutdown_ms = (time.perf_counter() - t0) * 1000.0

        # Shutdown must be bounded (e.g. <500ms) and not hang indefinitely
        self.assertLess(shutdown_ms, 500.0)
        mock_agent.cancel.assert_called_once()
        self.assertFalse(self.state.agent_running)
        self.assertEqual(self.state.get_browser_ownership(), BrowserOwnership.NONE.value)
        agent_block.set()

    def test_53_browser_agent_defaults_are_local_and_private(self):
        from browser.agent import AutonomousBrowserAgent

        with patch.dict(os.environ, {}, clear=True):
            AutonomousBrowserAgent()
            self.assertEqual(os.environ["ANONYMIZED_TELEMETRY"], "false")
            self.assertEqual(os.environ["BROWSER_USE_CLOUD_SYNC"], "false")
            self.assertTrue(os.environ["BROWSER_USE_CONFIG_DIR"].endswith(".light_browseruse"))


if __name__ == "__main__":
    unittest.main()
