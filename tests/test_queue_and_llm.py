import os
import sqlite3
import tempfile
import json
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock

from brain.commands import Action, Command
from brain.laya import Laya
from brain.llm import QwenPlanner, validate_llm_action
from core.executor import Executor
from core.loop import LightLoop
from core.queue_manager import CommandPriority, CommandQueue, CommandRequest, CommandStatus
from core.state import LightState
from voice.handy import Handy


class TestProducerConsumerQueueAndLLM(unittest.TestCase):

    def setUp(self):
        self.state = LightState()
        self.mock_agent = MagicMock()
        self.mock_agent.predict.return_value = {
            "answers": {"action": {"choice": "CLICK"}}
        }

    def test_01_listener_does_not_block_on_slow_executor_and_preserves_dependency_order(self):
        """
        Phase 3, 6 & 17 Test:
        'Open YouTube' followed immediately by 'Search Python tutorials' while YouTube is loading:
        1. Listener captures 'Search Python tutorials' while 'Open YouTube' is still executing.
        2. Virtual planning state tags 'Search Python tutorials' as 'youtube:Python tutorials'.
        3. Actual execution strictly finishes OPEN_URL first, verifies, and only then runs SEARCH.
        """
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "history.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE transcription_history (id INTEGER PRIMARY KEY AUTOINCREMENT, transcription_text TEXT)"
        )
        conn.commit()

        handy = Handy(db_path=db_path)
        laya = Laya(agent=self.mock_agent)
        executor = MagicMock()
        executor.state = self.state

        events: list[str] = []

        def slow_execute(cmd: Command, raw_text=None, cancel_event=None):
            events.append(f"EXEC_START:{cmd.action.value}:{cmd.target}")
            if cmd.action == Action.OPEN_URL:
                time.sleep(0.22)
            events.append(f"EXEC_END:{cmd.action.value}:{cmd.target}")
            self.state.record_command(raw_text, cmd)
            return "STOP" if cmd.action == Action.STOP else "OK"

        executor.execute.side_effect = slow_execute

        loop = LightLoop(
            handy=handy,
            laya=laya,
            executor=executor,
            state=self.state,
            duplicate_cooldown=0.05,
            poll_interval=0.015,
        )

        def producer_writer():
            time.sleep(0.08)
            c = sqlite3.connect(db_path)
            c.execute(
                "INSERT INTO transcription_history (transcription_text) VALUES (?)",
                ("Open YouTube",),
            )
            c.commit()
            time.sleep(0.04)  # While Open YouTube is still sleeping (220ms)!
            c.execute(
                "INSERT INTO transcription_history (transcription_text) VALUES (?)",
                ("Search Python tutorials",),
            )
            c.commit()
            time.sleep(0.35)  # Let both execute before sending Stop
            c.execute(
                "INSERT INTO transcription_history (transcription_text) VALUES (?)",
                ("Stop",),
            )
            c.commit()
            c.close()

        writer = threading.Thread(target=producer_writer, daemon=True)
        writer.start()
        loop.run(max_iterations=60)
        writer.join()
        conn.close()
        temp_dir.cleanup()

        self.assertEqual(
            events,
            [
                "EXEC_START:open_url:https://youtube.com",
                "EXEC_END:open_url:https://youtube.com",
                "EXEC_START:search:youtube:Python tutorials",
                "EXEC_END:search:youtube:Python tutorials",
                "EXEC_START:stop:None",
                "EXEC_END:stop:None",
            ],
        )

    def test_02_rapid_stress_sequence_preserves_exact_order_and_drops_nothing(self):
        """
        Phase 4 & 19 Rapid Command Test:
        Exact sequence:
        'Open Google', 'Search Python', 'Click first result', 'Scroll down',
        'Scroll down', 'Press Enter', 'Go back', 'Refresh'
        """
        laya = Laya(agent=self.mock_agent)
        executor = MagicMock()
        executor.state = self.state

        executed: list[tuple[Action, str | None]] = []

        def fake_execute(cmd: Command, raw_text=None, cancel_event=None):
            time.sleep(0.01)
            executed.append((cmd.action, cmd.target))
            self.state.record_command(raw_text, cmd)
            return "OK"

        executor.execute.side_effect = fake_execute

        loop = LightLoop(
            handy=MagicMock(),
            laya=laya,
            executor=executor,
            state=self.state,
            duplicate_cooldown=0.0,
        )

        rapid_commands = [
            "Open Google",
            "Search Python",
            "Click first result",
            "Scroll down",
            "Scroll down",
            "Press Enter",
            "Go back",
            "Refresh",
        ]

        t0 = time.perf_counter()
        for phrase in rapid_commands:
            loop.ingest_text(phrase)
        ingest_total_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(loop.command_queue.pending_count(), 8)
        self.assertLess(ingest_total_ms, 50.0, f"Ingestion took too long: {ingest_total_ms:.2f}ms")

        statuses = loop.drain_queue()
        self.assertEqual(statuses, ["OK"] * 8)
        self.assertEqual(
            executed,
            [
                (Action.OPEN_URL, "https://google.com"),
                (Action.SEARCH, "Python"),
                (Action.CLICK_RESULT, "1"),
                (Action.SCROLL, "down"),
                (Action.SCROLL, "down"),
                (Action.PRESS_KEY, "enter"),
                (Action.GO_BACK, None),
                (Action.REFRESH, None),
            ],
        )

    def test_03_stop_and_cancel_priority_preempts_wait_and_queued_commands(self):
        """
        Phase 7 & 8 STOP / CANCEL Priority & 10-Second WAIT Interruption Test:
        Queue:
        'Open YouTube' -> 'Search Python' -> 'Wait 10 seconds' -> 'Click first result'
        Then trigger 'Stop' while 'Wait 10 seconds' is running:
        1. 'Wait 10 seconds' is interrupted in < 80ms (measured from STOP arrival).
        2. 'Click first result' is cancelled before executing.
        3. 'Stop' executes immediately.
        """
        state = LightState()
        executor = Executor(state=state)
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = True
        executor.browser.get_current_url.return_value = "https://youtube.com"
        laya = Laya(agent=self.mock_agent)

        loop = LightLoop(handy=MagicMock(), laya=laya, executor=executor, state=state)

        loop.ingest_text("Open YouTube")
        loop.ingest_text("Search Python")
        loop.ingest_text("Wait 10 seconds")
        loop.ingest_text("Click first result")

        stop_sent_at = [0.0]

        def send_stop_during_wait():
            time.sleep(0.06)  # Allow Open YouTube & Search Python to finish and Wait 10s to begin
            stop_sent_at[0] = time.perf_counter()
            loop.ingest_text("Stop")

        stopper = threading.Thread(target=send_stop_during_wait, daemon=True)
        stopper.start()

        statuses = loop.drain_queue()
        stop_completed_at = time.perf_counter()
        stopper.join()

        stop_latency_ms = (stop_completed_at - stop_sent_at[0]) * 1000.0
        self.assertIn("STOP", statuses)
        threshold_ms = 500.0 if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS") else 80.0
        self.assertLess(
            stop_latency_ms,
            threshold_ms,
            f"Expected STOP to interrupt 10s WAIT within {threshold_ms}ms, took {stop_latency_ms:.2f}ms",
        )
        # Verify 'Click first result' was cancelled and NEVER clicked
        executor.browser.click_result.assert_not_called()

    def test_04_phase9_all_22_fast_path_commands_have_zero_llm_calls(self):
        """
        Phase 5 & 9 Fast Path Validation:
        Verify all 22 required simple commands + multi-step natural commands execute
        with LLM call count == 0.
        """
        mock_transport = MagicMock()
        planner = QwenPlanner(enabled=True, transport=mock_transport)
        laya = Laya(agent=self.mock_agent, llm_planner=planner)

        fast_path_22 = [
            ("Open YouTube", [Command(Action.OPEN_URL, "https://youtube.com")]),
            ("Open Google", [Command(Action.OPEN_URL, "https://google.com")]),
            ("Open Chrome", [Command(Action.OPEN_APP, "Chrome")]),
            ("Search Python", [Command(Action.SEARCH, "Python")]),
            ("Search YouTube for AI", [Command(Action.SEARCH, "youtube:AI")]),
            ("Click first result", [Command(Action.CLICK_RESULT, "1")]),
            ("Click Subscribe", [Command(Action.CLICK_ELEMENT, "Subscribe")]),
            ("Scroll down", [Command(Action.SCROLL, "down")]),
            ("Scroll up", [Command(Action.SCROLL, "up")]),
            ("Go back", [Command(Action.GO_BACK, None)]),
            ("Go forward", [Command(Action.GO_FORWARD, None)]),
            ("Refresh", [Command(Action.REFRESH, None)]),
            ("Press Enter", [Command(Action.PRESS_KEY, "enter")]),
            ("Press Escape", [Command(Action.PRESS_KEY, "esc")]),
            ("Type hello", [Command(Action.TYPE, "hello")]),
            ("Paste", [Command(Action.PASTE, None)]),
            ("Copy selection", [Command(Action.COPY_TEXT, None)]),
            ("Move mouse", [Command(Action.MOVE_MOUSE, "center")]),
            ("Find Subscribe", [Command(Action.FIND_ELEMENT, "Subscribe")]),
            ("Read title", [Command(Action.READ_TITLE, None)]),
            ("Wait 3 seconds", [Command(Action.WAIT, "3")]),
            ("Stop", [Command(Action.STOP, None)]),
            (
                "Open YouTube, search for Python tutorials, click the first video and scroll down.",
                [
                    Command(Action.OPEN_URL, "https://youtube.com"),
                    Command(Action.SEARCH, "youtube:Python tutorials"),
                    Command(Action.CLICK_RESULT, "1"),
                    Command(Action.SCROLL, "down"),
                ],
            ),
            (
                "Open YouTube, search for AI agents, then open the first relevant video.",
                [
                    Command(Action.OPEN_URL, "https://youtube.com"),
                    Command(Action.SEARCH, "youtube:AI agents"),
                    Command(Action.CLICK_RESULT, "1"),
                ],
            ),
        ]

        t0 = time.perf_counter()
        for phrase, expected in fast_path_22:
            actual = laya.understand_many(phrase, state=LightState())
            self.assertEqual(actual, expected, f"Failed fast path for '{phrase}'")
        avg_ms = ((time.perf_counter() - t0) * 1000.0) / len(fast_path_22)

        self.assertEqual(mock_transport.call_count, 0)
        self.assertLess(avg_ms, 1.0, f"Fast path average exceeded 1ms: {avg_ms:.3f}ms")

    def test_05_phase10_complex_command_routes_to_qwen3_and_validates(self):
        """
        Phase 10 Complex Command Validation:
        'Find a beginner Python tutorial on YouTube and open the most relevant result.'
        routes to Qwen3 1.7B, sends compact prompt, and validates output actions.
        """
        captured_prompts: list[str] = []

        def fake_ollama_transport(prompt: str) -> dict:
            captured_prompts.append(prompt)
            return {
                "actions": [
                    {"action": "OPEN_URL", "target": "youtube"},
                    {"action": "SEARCH", "target": "beginner Python tutorial"},
                    {"action": "CLICK_RESULT", "target": "most relevant"},
                ]
            }

        planner = QwenPlanner(enabled=True, transport=fake_ollama_transport)
        laya = Laya(agent=self.mock_agent, llm_planner=planner)

        cmds = laya.understand_many(
            "Find a beginner Python tutorial on YouTube and open the most relevant result.",
            state=LightState(),
        )
        self.assertEqual(len(captured_prompts), 1)
        self.assertIn("State: site=none, app=none", captured_prompts[0])
        self.assertEqual(
            cmds,
            [
                Command(Action.OPEN_URL, "https://youtube.com"),
                Command(Action.SEARCH, "youtube:beginner Python tutorial"),
                Command(Action.CLICK_RESULT, "1"),
            ],
        )

    def test_06_phase11_ollama_failures_and_invalid_actions_handled_safely(self):
        """
        Phase 11 Test:
        Verify offline Ollama, timeout, malformed JSON, and invalid actions never crash LIGHT.
        """
        # 1. Invalid actions rejected
        with self.assertRaises(ValueError):
            validate_llm_action("open youtube", {"action": "EXECUTE_SHELL", "target": "calc.exe"})
        with self.assertRaises(ValueError):
            validate_llm_action("open youtube", {"action": "STOP", "target": None})

        # 2. Offline / Timeout / Malformed JSON falls back to Laya without crashing
        for error_to_raise in [
            urllib.error.URLError("Connection refused"),
            TimeoutError("Ollama timed out"),
            ValueError("Malformed JSON"),
        ]:
            planner = QwenPlanner(
                enabled=True,
                transport=MagicMock(side_effect=error_to_raise),
            )
            laya = Laya(agent=self.mock_agent, llm_planner=planner)
            cmd = laya.understand("Click the Subscribe banner", state=LightState())
            self.assertEqual(cmd, Command(Action.CLICK_ELEMENT, "Subscribe banner"))

    def test_07_phase12_duplicate_stt_suppression_vs_intentional_repeats(self):
        """
        Phase 12 Test:
        Verify duplicate STT emissions within cooldown are suppressed, while separate
        commands after cooldown execute normally.
        """
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "history.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE transcription_history (id INTEGER PRIMARY KEY AUTOINCREMENT, transcription_text TEXT)"
        )
        conn.commit()

        handy = Handy(db_path=db_path)
        laya = Laya(agent=self.mock_agent)
        executor = MagicMock()
        executor.state = self.state
        executed: list[tuple[Action, str | None]] = []

        def fake_exec(cmd: Command, raw_text=None, cancel_event=None):
            executed.append((cmd.action, cmd.target))
            return "STOP" if cmd.action == Action.STOP else "OK"

        executor.execute.side_effect = fake_exec

        loop = LightLoop(
            handy=handy,
            laya=laya,
            executor=executor,
            state=self.state,
            duplicate_cooldown=0.12,
            poll_interval=0.015,
        )

        def writer():
            time.sleep(0.02)
            c = sqlite3.connect(db_path)
            # Immediate duplicate within 120ms cooldown -> second one suppressed
            c.execute("INSERT INTO transcription_history (transcription_text) VALUES ('Open YouTube')")
            c.execute("INSERT INTO transcription_history (transcription_text) VALUES ('Open YouTube')")
            c.commit()
            time.sleep(0.16)  # Wait past 120ms cooldown -> legitimate repeat executes
            c.execute("INSERT INTO transcription_history (transcription_text) VALUES ('Open YouTube')")
            c.commit()
            time.sleep(0.06)  # Allow legitimate repeat to execute before STOP preempts queue
            c.execute("INSERT INTO transcription_history (transcription_text) VALUES ('Stop')")
            c.commit()
            c.close()

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        loop.run(max_iterations=35)
        t.join()
        conn.close()
        temp_dir.cleanup()

        self.assertEqual(
            executed,
            [
                (Action.OPEN_URL, "https://youtube.com"),
                (Action.OPEN_URL, "https://youtube.com"),
                (Action.STOP, None),
            ],
        )

    def test_08_phase13_casual_speech_remains_strictly_safe(self):
        """
        Phase 13 Casual Speech Safety Test:
        Verify 'How are you?', 'I am hungry.', 'That's interesting.',
        'What are you doing?', 'I like YouTube.' are all ignored and never call Qwen3.
        """
        mock_transport = MagicMock()
        planner = QwenPlanner(enabled=True, transport=mock_transport)
        laya = Laya(agent=self.mock_agent, llm_planner=planner)
        executor = MagicMock()
        executor.state = self.state
        loop = LightLoop(handy=MagicMock(), laya=laya, executor=executor, state=self.state)

        casual_phrases = [
            "How are you?",
            "I am hungry.",
            "That's interesting.",
            "What are you doing?",
            "I like YouTube.",
        ]
        for phrase in casual_phrases:
            status = loop.process_text(phrase)
            self.assertEqual(status, "IGNORED", f"Casual speech '{phrase}' was not ignored!")

        executor.execute.assert_not_called()
        mock_transport.assert_not_called()

    def test_09_phase14_and_17_thread_safe_state_and_error_recovery(self):
        """
        Phase 14 & 17 Test:
        Verify concurrent state reads/writes do not corrupt LightState and executor
        recovers cleanly after a failed command.
        """
        laya = Laya(agent=self.mock_agent)
        executor = MagicMock()
        executor.state = self.state

        def fake_execute(cmd: Command, raw_text=None, cancel_event=None):
            if cmd.action == Action.CLICK_ELEMENT and cmd.target == "Subscribe":
                raise ValueError("CLICK_ELEMENT target not found: Subscribe")
            self.state.record_command(raw_text, cmd)
            return "OK"

        executor.execute.side_effect = fake_execute

        loop = LightLoop(handy=MagicMock(), laya=laya, executor=executor, state=self.state)
        loop.ingest_text("Open YouTube")
        loop.ingest_text("Search Python")
        loop.ingest_text("Click Subscribe")
        loop.ingest_text("Scroll down")

        statuses = loop.drain_queue()
        self.assertEqual(statuses, ["OK", "OK", "ERROR", "OK"])
        snap = self.state.snapshot()
        self.assertEqual(snap["current_site"], "youtube")
        self.assertEqual(len(snap["recent_commands"]), 3)

    # =========================================================================
    # COMPLEX COMMAND / BROWSER READINESS & CLOSED-CONTEXT RECOVERY TESTS
    # =========================================================================

    def test_10_complex_youtube_command_when_browser_closed_inserts_open_url(self):
        """
        Regression Test 1:
        When browser is NOT open (state.browser_open = False),
        'Find a beginner Python tutorial on YouTube and open the most relevant result'
        must produce:
        1. OPEN_URL -> https://youtube.com
        2. SEARCH -> youtube:beginner Python tutorial
        3. CLICK_RESULT -> 1
        """
        state = LightState()
        state.browser_open = False
        state.current_site = None
        state.current_url = None

        raw_llm_response = {
            "actions": [
                {"action": "SEARCH", "target": "youtube:beginner Python tutorial"},
                {"action": "CLICK_RESULT", "target": "1"},
            ]
        }
        planner = QwenPlanner(enabled=True, transport=lambda p: raw_llm_response)
        laya = Laya(agent=self.mock_agent, llm_planner=planner)

        cmds = laya.understand_many(
            "Find a beginner Python tutorial on YouTube and open the most relevant result",
            state=state,
        )
        self.assertEqual(
            cmds,
            [
                Command(Action.OPEN_URL, "https://youtube.com"),
                Command(Action.SEARCH, "youtube:beginner Python tutorial"),
                Command(Action.CLICK_RESULT, "1"),
            ],
        )

    def test_11_complex_youtube_command_when_browser_about_blank_inserts_open_url(self):
        """
        Regression Test 2:
        When browser is open on about:blank, state is NOT ready for direct YouTube search;
        planner must still insert OPEN_URL -> https://youtube.com before SEARCH.
        """
        state = LightState()
        state.browser_open = True
        state.current_site = "youtube"
        state.current_url = "about:blank"

        raw_llm_response = {
            "actions": [
                {"action": "SEARCH", "target": "youtube:beginner Python tutorial"},
                {"action": "CLICK_RESULT", "target": "1"},
            ]
        }
        planner = QwenPlanner(enabled=True, transport=lambda p: raw_llm_response)
        cmds = planner.plan_actions(
            "Find a beginner Python tutorial on YouTube and open the most relevant result",
            state=state,
        )
        self.assertEqual(
            cmds,
            [
                Command(Action.OPEN_URL, "https://youtube.com"),
                Command(Action.SEARCH, "youtube:beginner Python tutorial"),
                Command(Action.CLICK_RESULT, "1"),
            ],
        )

    def test_12_complex_youtube_command_when_youtube_already_open_skips_duplicate_open_url(self):
        """
        Regression Test 3:
        When browser is ALREADY open and ready on YouTube (current_url='https://www.youtube.com'),
        planner must NOT insert a redundant OPEN_URL.
        """
        state = LightState()
        state.browser_open = True
        state.current_site = "youtube"
        state.current_url = "https://www.youtube.com"

        raw_llm_response = {
            "actions": [
                {"action": "SEARCH", "target": "youtube:beginner Python tutorial"},
                {"action": "CLICK_RESULT", "target": "1"},
            ]
        }
        planner = QwenPlanner(enabled=True, transport=lambda p: raw_llm_response)
        cmds = planner.plan_actions(
            "Find a beginner Python tutorial on YouTube and open the most relevant result",
            state=state,
        )
        self.assertEqual(
            cmds,
            [
                Command(Action.SEARCH, "youtube:beginner Python tutorial"),
                Command(Action.CLICK_RESULT, "1"),
            ],
        )

    def test_13_llm_plan_missing_open_url_is_normalized_before_execution(self):
        """
        Regression Test 4:
        Even if Qwen3 outputs bare SEARCH -> 'beginner Python tutorial' (without youtube: prefix)
        when the spoken prompt says 'on YouTube', normalize_command_plan prefixes 'youtube:'
        and prepends OPEN_URL -> https://youtube.com.
        """
        from brain.decision import normalize_command_plan

        state = LightState()
        state.browser_open = False
        raw_cmds = [
            Command(Action.SEARCH, "beginner Python tutorial"),
            Command(Action.CLICK_RESULT, "1"),
        ]
        normalized = normalize_command_plan(
            raw_cmds,
            state=state,
            raw_text="Find a beginner Python tutorial on YouTube and open the most relevant result",
        )
        self.assertEqual(
            normalized,
            [
                Command(Action.OPEN_URL, "https://youtube.com"),
                Command(Action.SEARCH, "youtube:beginner Python tutorial"),
                Command(Action.CLICK_RESULT, "1"),
            ],
        )

    def test_14_normalize_command_plan_strips_duplicate_open_url_when_site_ready(self):
        """
        Regression Test 5:
        If Qwen3 emits [OPEN_URL(https://youtube.com), SEARCH(youtube:...), CLICK_RESULT(1)]
        while YouTube is ALREADY open and active in state, normalize_command_plan strips
        the redundant OPEN_URL so the browser does not reload YouTube unnecessarily.
        """
        from brain.decision import normalize_command_plan

        state = LightState()
        state.browser_open = True
        state.current_site = "youtube"
        state.current_url = "https://www.youtube.com/watch?v=abc123"

        raw_cmds = [
            Command(Action.OPEN_URL, "https://youtube.com"),
            Command(Action.SEARCH, "youtube:beginner Python tutorial"),
            Command(Action.CLICK_RESULT, "1"),
        ]
        normalized = normalize_command_plan(
            raw_cmds,
            state=state,
            raw_text="Find a beginner Python tutorial on YouTube and open the most relevant result",
        )
        self.assertEqual(
            normalized,
            [
                Command(Action.SEARCH, "youtube:beginner Python tutorial"),
                Command(Action.CLICK_RESULT, "1"),
            ],
        )

    def test_15_browser_closed_context_error_recovers_and_completes_search(self):
        """
        Regression Test 6:
        When Playwright raises 'Page.goto: Target page, context or browser has been closed',
        BrowserController automatically recovers the closed browser context and completes
        the YouTube search on retry without raising an error.
        """
        from browser.browser import BrowserController

        browser = BrowserController(headless=True)
        mock_page = MagicMock()
        mock_page.url = "about:blank"
        mock_page.is_closed.return_value = False
        mock_page.goto.side_effect = [
            RuntimeError("Page.goto: Target page, context or browser has been closed"),
            None,
        ]
        browser.browser = MagicMock()
        browser.page = mock_page
        browser.start = MagicMock()

        # Should recover on the first goto error and succeed on the retry
        browser.search_youtube("beginner Python tutorial")

        self.assertTrue(browser._skip_persistent_context)
        self.assertEqual(mock_page.goto.call_count, 2)

    def test_16_click_result_never_executes_when_search_fails(self):
        """
        Regression Test 7:
        If SEARCH fails for any reason, queued dependent CLICK_RESULT commands
        must be automatically cancelled and NEVER executed.
        """
        state = LightState()
        laya = Laya(agent=self.mock_agent)
        executor = MagicMock()
        executor.state = state

        executed_actions = []

        def fake_execute(cmd: Command, raw_text=None, cancel_event=None):
            executed_actions.append(cmd.action)
            if cmd.action == Action.SEARCH:
                raise RuntimeError("Simulated network outage during SEARCH")
            state.record_command(raw_text, cmd)
            return "OK"

        executor.execute.side_effect = fake_execute
        loop = LightLoop(handy=MagicMock(), laya=laya, executor=executor, state=state)

        loop.ingest_text("Open YouTube and search beginner Python tutorial and click first result")
        statuses = loop.drain_queue()

        self.assertEqual(executed_actions, [Action.OPEN_URL, Action.SEARCH])
        self.assertNotIn(Action.CLICK_RESULT, executed_actions)
        self.assertIn("ERROR", statuses)

    def test_17_click_result_refuses_about_blank_page(self):
        """
        Regression Test 8:
        BrowserController.click_result() must raise RuntimeError immediately if the page
        is still on 'about:blank' rather than blindly querying DOM elements on a blank tab.
        """
        from browser.browser import BrowserController

        browser = BrowserController(headless=True)
        browser.browser = MagicMock()
        browser.page = MagicMock()
        browser.page.url = "about:blank"
        browser.page.is_closed.return_value = False

        with self.assertRaises(RuntimeError) as ctx:
            browser.click_result(1)
        self.assertIn("about:blank", str(ctx.exception))

    def test_18_complex_deterministic_fallback_when_llm_disabled_or_offline(self):
        """
        Regression Test 9:
        Even when Qwen3 is offline or disabled, 'Find a beginner Python tutorial on YouTube
        and open the most relevant result' resolves via parse_complex_fallback into
        [OPEN_URL(https://youtube.com), SEARCH(youtube:beginner Python tutorial), CLICK_RESULT(1)].
        """
        state = LightState()
        state.browser_open = False
        planner = QwenPlanner(enabled=False)
        laya = Laya(agent=self.mock_agent, llm_planner=planner)

        cmds = laya.understand_many(
            "Find a beginner Python tutorial on YouTube and open the most relevant result",
            state=state,
        )
        self.assertEqual(
            cmds,
            [
                Command(Action.OPEN_URL, "https://youtube.com"),
                Command(Action.SEARCH, "youtube:beginner Python tutorial"),
                Command(Action.CLICK_RESULT, "1"),
            ],
        )

    def test_19_end_to_end_pipeline_complex_youtube_command_with_closed_browser_recovery(self):
        """
        Regression Test 10:
        Full end-to-end LightLoop + Executor + BrowserController test for:
        'Find a beginner Python tutorial on YouTube and open the most relevant result'
        starting with browser closed AND encountering a transient closed-page error on first goto.
        Verifies OPEN_URL -> SEARCH -> CLICK_RESULT all execute in order and succeed.
        """
        from browser.browser import BrowserController

        state = LightState()
        state.browser_open = False

        raw_llm_response = {
            "actions": [
                {"action": "SEARCH", "target": "youtube:beginner Python tutorial"},
                {"action": "CLICK_RESULT", "target": "1"},
            ]
        }
        planner = QwenPlanner(enabled=True, transport=lambda p: raw_llm_response)
        laya = Laya(agent=self.mock_agent, llm_planner=planner)

        browser = BrowserController(headless=True)
        mock_page = MagicMock()
        mock_page.is_closed.return_value = False
        mock_page.url = "about:blank"
        mock_page.locator.return_value.first.is_visible.return_value = False

        goto_urls = []

        def fake_goto(url, wait_until="domcontentloaded"):
            goto_urls.append(url)
            if len(goto_urls) == 1:
                raise RuntimeError("Page.goto: Target page, context or browser has been closed")
            mock_page.url = url

        mock_page.goto.side_effect = fake_goto
        browser.browser = MagicMock()
        browser.page = mock_page
        browser.start = MagicMock()
        browser.locate_element_in_viewport = MagicMock(
            return_value={
                "found": True,
                "vp_x": 400,
                "vp_y": 300,
                "is_input": False,
                "matched": "Python for Beginners - Full Course",
                "window_metrics": {"screenX": 0, "screenY": 0, "outerWidth": 1920, "outerHeight": 1080, "innerWidth": 1920, "innerHeight": 1080},
            }
        )

        executor = Executor(state=state)
        executor.browser = browser
        executor.mouse = MagicMock()
        executor.mouse.get_screen_size.return_value = (1920, 1080)
        executor.mouse.clamp_to_screen.side_effect = lambda x, y: (x, y)
        executor.mouse.move.side_effect = lambda x, y, duration=0.25: (x, y)
        executor.screen = MagicMock()
        executor.screen.get_active_window_title.return_value = "YouTube - Google Chrome"

        loop = LightLoop(handy=MagicMock(), laya=laya, executor=executor, state=state)
        status = loop.process_text(
            "Find a beginner Python tutorial on YouTube and open the most relevant result"
        )

        self.assertEqual(status, "OK")
        self.assertEqual(
            goto_urls,
            [
                "https://youtube.com",
                "https://youtube.com",  # Recovered retry after closed target error
                "https://www.youtube.com/results?search_query=beginner+Python+tutorial",
            ],
        )
        browser.locate_element_in_viewport.assert_called()

    # =========================================================================
    # PHYSICAL CLICK_ELEMENT, CURSOR VERIFICATION & YOUTUBE/HTML SKIP TESTS
    # =========================================================================

    def test_20_click_element_calculates_target_moves_cursor_and_sends_physical_click(self):
        """
        Verify CLICK_ELEMENT:
        1. Locates element and calculates screen coordinates.
        2. Moves physical cursor to target.
        3. Checks/corrects cursor position via verify_and_correct_position.
        4. Sends actual physical click via click_at (mouseDown + mouseUp).
        """
        from browser.browser import BrowserController

        browser = BrowserController(headless=True)
        browser.browser = MagicMock()
        browser.page = MagicMock()
        browser.page.is_closed.return_value = False
        browser.locate_element_in_viewport = MagicMock(
            return_value={
                "found": True,
                "vp_x": 500,
                "vp_y": 400,
                "is_input": False,
                "pre_text": "Skip",
                "pre_url": "https://www.youtube.com/watch?v=123",
                "pre_ad_showing": True,
                "matched": "Skip",
                "window_metrics": {
                    "screenX": 0,
                    "screenY": 0,
                    "outerWidth": 1920,
                    "outerHeight": 1080,
                    "innerWidth": 1920,
                    "innerHeight": 1080,
                },
            }
        )
        # Simulate that after click, the Skip button disappeared (activated=True)
        browser.page.evaluate.side_effect = [
            None,  # _attach_click_tracker
            None,  # OS mousemove tracker attach
            {"clientX": 500, "clientY": 400},  # __lightOsMouse
            {"count": 1, "trusted": 1},  # __lightClickStats
            {"activated": True, "reason": "target_disappeared", "clickCount": 1},  # _verify_element_click
        ]

        mouse = MagicMock()
        mouse.get_screen_size.return_value = (1920, 1080)
        mouse.get_position.return_value = (100, 100)
        mouse.clamp_to_screen.side_effect = lambda x, y: (int(x), int(y))
        mouse.move.side_effect = lambda x, y, duration=0.25: (int(x), int(y))
        mouse.verify_and_correct_position.return_value = (500, 400)

        browser.click_element("skip", mouse_controller=mouse)

        mouse.move.assert_called_with(500, 400, duration=0.25)
        mouse.verify_and_correct_position.assert_called_once_with(500, 400, tolerance=5)
        mouse.click_at.assert_called_once_with(500, 400)

    def test_21_cursor_position_verification_corrects_drift_before_physical_click(self):
        """
        Verify MouseController.verify_and_correct_position checks the actual OS cursor
        position and corrects it if it drifted outside tolerance before clicking.
        """
        from unittest.mock import patch
        from computer.mouse import MouseController

        mouse = MouseController()
        with patch("computer.mouse.pyautogui") as mock_pag:
            mock_pag.size.return_value = (1920, 1080)
            # First position read shows drift at (460, 350), second read after correction is (500, 400)
            mock_pag.position.side_effect = [(460, 350), (500, 400)]

            final_pos = mouse.click_at(500, 400, settle_delay=0.001, hold_delay=0.001, tolerance=5)

            self.assertEqual(final_pos, (500, 400))
            mock_pag.moveTo.assert_called_once_with(500, 400, duration=0.04)
            mock_pag.mouseDown.assert_called_once_with(x=500, y=400, button="left")
            mock_pag.mouseUp.assert_called_once_with(x=500, y=400, button="left")

    def test_22_local_real_world_html_skip_button_physical_click_and_verification(self):
        """
        Real Playwright HTML page test with <button id="test-button">Skip</button>:
        When physically clicked, the button changes text from 'Skip' to 'Skipped'.
        Verifies full pipeline ('Click skip') finds the button, moves the physical mouse,
        clicks it, changes the button text to 'Skipped', and reports 'OK'.
        """
        from unittest.mock import patch
        from browser.browser import BrowserController
        from computer.mouse import MouseController

        state = LightState()
        browser = BrowserController(headless=True)
        browser.start()
        try:
            browser.page.set_content(
                """
                <!DOCTYPE html>
                <html>
                <body style="margin:0; display:flex; align-items:center; justify-content:center; height:100vh;">
                    <button id="test-button"
                            style="width:160px; height:56px; font-size:20px;"
                            onclick="if (event.isTrusted) { this.innerText = 'Skipped'; this.setAttribute('data-clicked', 'true'); }">
                        Skip
                    </button>
                </body>
                </html>
                """
            )
            executor = Executor(state=state)
            executor.browser = browser
            mouse = MouseController()
            executor.mouse = mouse
            executor.screen = MagicMock()
            executor.screen.get_active_window_title.return_value = "Skip Test"

            laya = Laya(agent=self.mock_agent)
            loop = LightLoop(handy=MagicMock(), laya=laya, executor=executor, state=state)

            with patch("computer.mouse.pyautogui") as mock_pag:
                mock_pag.size.return_value = (1920, 1080)
                cur_pos = [100, 100]

                def fake_move_to(x, y, duration=0.0):
                    cur_pos[0], cur_pos[1] = int(x), int(y)

                mock_pag.moveTo.side_effect = fake_move_to
                mock_pag.position.side_effect = lambda: (cur_pos[0], cur_pos[1])

                status = loop.process_text("Click skip")

                self.assertEqual(status, "OK")
                self.assertTrue(mock_pag.mouseDown.called)
                self.assertTrue(mock_pag.mouseUp.called)
                btn_text = browser.page.locator("#test-button").inner_text().strip()
                self.assertEqual(btn_text, "Skipped")
        finally:
            browser.close()

    def test_23_click_skip_verification_failure_does_not_report_executor_ok(self):
        """
        If the Skip button remains visible with unchanged text/state after clicking
        (i.e. UI activation failed), LIGHT must report 'ERROR' instead of a false 'OK'.
        """
        from unittest.mock import patch
        from browser.browser import BrowserController
        from computer.mouse import MouseController

        state = LightState()
        browser = BrowserController(headless=True)
        browser.start()
        try:
            # Button has NO click action and stays visible with text 'Skip'
            browser.page.set_content(
                """
                <!DOCTYPE html>
                <html>
                <body style="margin:0; display:flex; align-items:center; justify-content:center; height:100vh;">
                    <div id="movie_player" class="ad-showing">
                        <button id="test-button" class="ytp-skip-ad-button" style="width:160px; height:56px;">
                            Skip
                        </button>
                    </div>
                </body>
                </html>
                """
            )
            executor = Executor(state=state)
            executor.browser = browser
            executor.mouse = MouseController()
            executor.screen = MagicMock()
            executor.screen.get_active_window_title.return_value = "YouTube Ad"

            laya = Laya(agent=self.mock_agent)
            loop = LightLoop(handy=MagicMock(), laya=laya, executor=executor, state=state)

            with patch("computer.mouse.pyautogui") as mock_pag:
                mock_pag.size.return_value = (1920, 1080)
                mock_pag.position.return_value = (500, 500)
                status = loop.process_text("Click skip")

            self.assertEqual(status, "ERROR")
        finally:
            browser.close()

    def test_24_cricket_casual_word_is_safely_ignored_and_never_becomes_move_mouse(self):
        """
        Ensure 'Cricket' is safely ignored and never becomes MOVE_MOUSE or invokes
        the Laya fallback classifier.
        """
        self.mock_agent.predict.return_value = {
            "answers": {"action": {"choice": "MOVE_MOUSE"}}
        }
        laya = Laya(agent=self.mock_agent)
        executor = MagicMock()
        executor.state = self.state
        loop = LightLoop(handy=MagicMock(), laya=laya, executor=executor, state=self.state)

        status = loop.process_text("Cricket")
        self.assertEqual(status, "IGNORED")
        self.mock_agent.predict.assert_not_called()
        executor.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()


