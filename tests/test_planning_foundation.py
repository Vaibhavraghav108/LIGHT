"""Event-controlled planning/cancellation tests; no live models, microphone, or GUI."""

import asyncio
import threading
import time
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from brain.commands import Action, Command
from brain.decision import parse_deterministic_command, parse_multi_command
from core.executor import Executor
from core.loop import LightLoop
from core.queue_manager import CommandQueue, CommandRequest, CommandStatus
from core.state import LightState, BrowserOwnership
from core.tasks import AmbiguousPlanError, TaskRecord, TaskStatus
from tests.provider_test_utils import make_test_ai_provider, make_test_laya, make_test_planner
from utils.logger import logger


class RecordingExecutor:
    def __init__(self):
        self.state = LightState()
        self.calls = []
        self.browser = MagicMock()

    def execute(self, command, raw_text=None, cancel_event=None):
        self.calls.append(command)
        self.state.record_command(raw_text, command)
        return "STOP" if command.action == Action.STOP else "OK"

    async def execute_async(self, command, raw_text=None, cancel_event=None):
        return self.execute(command, raw_text, cancel_event)

    def close(self, timeout=0.5):
        return True


class BlockingBrain:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def understand_deterministic(self, text, state=None):
        return parse_multi_command(text, state) or (
            [cmd] if (cmd := parse_deterministic_command(text, state)) is not None else None)

    def understand_many(self, text, state=None):
        self.calls.append(text)
        if text == "semantic fixture":
            self.started.set()
            if not self.release.wait(2.0):
                raise AssertionError("Test did not release planner")
            return [Command(Action.OPEN_URL, "https://youtube.com")]
        return self.understand_deterministic(text, state)


class TestPlanningFoundation(unittest.TestCase):
    def setUp(self):
        quiet = patch.object(logger, "disabled", True)
        quiet.start()
        self.addCleanup(quiet.stop)

    def make_loop(self, brain=None, executor=None):
        executor = executor or RecordingExecutor()
        loop = LightLoop(MagicMock(), brain or BlockingBrain(), executor, poll_interval=0.001)
        self.addCleanup(loop.close)
        return loop

    def block_plan(self, loop):
        req = loop.ingest_text("semantic fixture")[0]
        self.assertTrue(loop.laya.started.wait(1.0))
        self.addCleanup(loop.laya.release.set)
        return req

    def test_slow_planning_ingestion_returns_without_waiting(self):
        loop = self.make_loop()
        start = time.perf_counter()
        req = loop.ingest_text("semantic fixture")[0]
        self.assertLess(time.perf_counter() - start, 0.1)
        self.assertTrue(loop.laya.started.wait(1.0))
        self.addCleanup(loop.laya.release.set)
        self.assertFalse(req.ready.is_set())
        self.assertEqual(loop.executor.calls, [])
        self.assertEqual(req.task.status, TaskStatus.RUNNING)

    def test_stop_signals_before_planning_finishes(self):
        loop = self.make_loop()
        req = self.block_plan(loop)
        stop = loop.ingest_text("Stop")[0]
        self.assertTrue(loop.command_queue.cancel_event.is_set())
        self.assertLess(stop.task.duration_ms("ingested", "cancellation_signalled"), 5.0)
        self.assertEqual(req.task.status, TaskStatus.CANCELLED)
        self.assertFalse(loop.laya.release.is_set())
        self.assertEqual(loop.execute_next_queued(), "STOP")
        self.assertEqual([cmd.action for cmd in loop.executor.calls], [Action.STOP])
        self.assertNotIn("Stop", loop.laya.calls)

    def test_stale_result_after_stop_has_no_state_or_queue_effect(self):
        loop = self.make_loop()
        req = self.block_plan(loop)
        worker = loop._planner_thread
        loop.ingest_text("Stop")
        loop.drain_queue()
        snapshot = loop.state.snapshot()
        loop.laya.release.set()
        worker.join(1.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(loop.command_queue.pending_count(), 0)
        self.assertEqual(loop.state.snapshot(), snapshot)
        self.assertEqual(req.status, CommandStatus.CANCELLED)
        self.assertIsNotNone(req.task.duration_ms("cancellation_signalled", "planner_terminated"))

    def test_later_fast_commands_cannot_overtake_and_use_planned_context(self):
        loop = self.make_loop()
        first = self.block_plan(loop)
        second = loop.ingest_text("Search Python")[0]
        third = loop.ingest_text("Open Google")[0]
        self.assertEqual(loop.command_queue.pending_count(), 3)
        self.assertIsNone(loop.execute_next_queued(timeout=0.0))
        self.assertEqual(loop.executor.calls, [])
        loop.laya.release.set()
        self.assertEqual(loop.drain_queue(), ["OK"] * 3)
        self.assertEqual(loop.executor.calls, [Command(Action.OPEN_URL, "https://youtube.com"),
                                               Command(Action.SEARCH, "youtube:Python"),
                                               Command(Action.OPEN_URL, "https://google.com")])
        self.assertLess(first.task.id, second.task.id)
        self.assertLess(second.task.id, third.task.id)
        self.assertEqual(first.task.status, TaskStatus.SUCCEEDED)

    def test_observed_state_not_mutated_by_predictions(self):
        loop = self.make_loop()
        req = self.block_plan(loop)
        worker = loop._planner_thread
        loop.laya.release.set()
        self.assertTrue(req.ready.wait(1.0))
        worker.join(1.0)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(loop.state.current_site)
        self.assertEqual(loop._planning_state.current_site, "youtube")
        loop.drain_queue()
        self.assertEqual(loop.state.current_site, "youtube")

    def test_concurrent_ingestion_has_unique_ordered_task_ids(self):
        loop = self.make_loop()
        self.block_plan(loop)
        producers = [threading.Thread(target=loop.ingest_text, args=("Scroll down",)) for _ in range(20)]
        for thread in producers:
            thread.start()
        for thread in producers:
            thread.join(1.0)
            self.assertFalse(thread.is_alive())
        loop.laya.release.set()
        self.assertEqual(len(loop.drain_queue()), 21)
        ids = [request.task.id for request in loop.command_queue.get_history()]
        self.assertEqual(ids, sorted(set(ids)))
        self.assertEqual(len(loop.executor.calls), 21)

    def test_dequeued_work_rechecks_generation_before_dispatch(self):
        loop = self.make_loop()
        req = loop.ingest_text("Scroll down")[0]
        self.assertIs(loop.command_queue.dequeue(0), req)
        loop.ingest_text("Stop")
        self.assertFalse(loop._begin_request(req))
        loop.command_queue.mark_execution_finished()
        self.assertEqual(loop.executor.calls, [])
        self.assertEqual(req.status, CommandStatus.CANCELLED)

    def test_fast_path_accepted_is_not_completed_or_verified(self):
        loop = self.make_loop()
        req = loop.ingest_text("Scroll down")[0]
        self.assertEqual(req.task.status, TaskStatus.ACCEPTED)
        self.assertEqual(req.execution_completed_at, 0)
        loop.drain_queue()
        self.assertEqual(req.task.status, TaskStatus.SUCCEEDED)
        self.assertIsNone(req.task.snapshot()["latency_ms"]["verification"])

    def test_failed_and_ambiguous_plans_never_execute(self):
        for error, expected in [(ValueError("private content"), TaskStatus.FAILED),
                                (AmbiguousPlanError("private content"), TaskStatus.AMBIGUOUS)]:
            with self.subTest(expected=expected):
                class Brain:
                    def understand_many(self, text, state=None):
                        raise error
                loop = self.make_loop(Brain())
                req = loop.ingest_text("sensitive transcript")[0]
                self.assertEqual(loop.drain_queue(), [])
                self.assertEqual(req.task.status, expected)
                self.assertEqual(loop.executor.calls, [])
                self.assertNotIn("private content", str(loop.task_status()))
                self.assertNotIn("sensitive transcript", str(loop.task_status()))

    def test_invalid_plan_cannot_partially_execute(self):
        class Brain:
            def understand_many(self, text, state=None):
                return [Command(Action.SCROLL, "down"), {"action": "shell"}]
        loop = self.make_loop(Brain())
        req = loop.ingest_text("semantic fixture")[0]
        self.assertEqual(loop.drain_queue(), [])
        self.assertEqual(req.task.status, TaskStatus.FAILED)
        self.assertEqual(loop.executor.calls, [])

    def test_planning_backlog_is_bounded_without_dropping_accepted_work(self):
        loop = self.make_loop()
        self.block_plan(loop)
        for _ in range(64):
            self.assertTrue(loop.ingest_text("Scroll down"))
        self.assertEqual(loop.ingest_text("Scroll down"), [])
        self.assertEqual(loop.task_status()[-1]["reason"], "Planning backlog is full")
        self.assertEqual(loop.command_queue.pending_count(), 65)
        loop.ingest_text("Stop")
        self.assertEqual(loop.command_queue.pending_count(), 1)

    def test_shutdown_reports_surviving_planner_and_rejects_late_results(self):
        loop = self.make_loop()
        self.block_plan(loop)
        worker = loop._planner_thread
        self.assertFalse(loop.close(timeout=0.01))
        self.assertTrue(loop.shutdown_status["planner_alive"])
        self.assertEqual(loop.ingest_text("Scroll down"), [])
        loop.laya.release.set()
        worker.join(1.0)
        self.assertTrue(loop.close(timeout=0.1))
        self.assertEqual(loop.executor.calls, [])

    def test_listener_ingests_spoken_stop_while_planner_is_blocked(self):
        brain = BlockingBrain()
        class Feed:
            count = 0
            def get_latest_transcription(self):
                self.count += 1
                if self.count == 1:
                    return None
                if self.count == 2:
                    return {"id": 1, "text": "semantic fixture"}
                if not brain.started.wait(1.0):
                    raise AssertionError("Planner did not start")
                return {"id": 2, "text": "Stop"}
        loop = self.make_loop(brain)
        loop.handy = Feed()
        runner = threading.Thread(target=loop.run, kwargs={"max_iterations": 3})
        self.addCleanup(brain.release.set)
        runner.start()
        runner.join(1.0)
        try:
            self.assertFalse(runner.is_alive())
            self.assertTrue(loop._listener_done.is_set())
            self.assertEqual([c.action for c in loop.executor.calls], [Action.STOP])
            self.assertTrue(loop.shutdown_status["planner_alive"])
        finally:
            brain.release.set()
            runner.join(1.0)

    def test_metrics_are_bounded_and_do_not_infer_missing_publication_or_effect(self):
        loop = self.make_loop()
        for _ in range(300):
            loop.process_text("Scroll down")
        records = loop.task_status()
        self.assertEqual(len(records), 256)
        self.assertIsNone(records[-1]["latency_ms"]["publication_to_ingestion"])
        self.assertIsNone(records[-1]["latency_ms"]["first_visible_effect"])
        self.assertNotIn("Scroll down", str(records))
        req = loop.ingest_text("Scroll down", transcript_published_at=time.perf_counter() - .01)[0]
        self.assertGreaterEqual(req.task.snapshot()["latency_ms"]["publication_to_ingestion"], 10.0)

    def test_failed_dependency_identity_does_not_use_repeated_transcript_text(self):
        queue = CommandQueue()
        first = CommandRequest("same words", Command(Action.CLICK_RESULT, "1"), task=TaskRecord(1, 0))
        second = CommandRequest("same words", Command(Action.CLICK_RESULT, "1"), task=TaskRecord(2, 0))
        queue.enqueue_many([first, second])
        self.assertEqual(queue.cancel_dependent_after_failure(Action.SEARCH, task_id=1), 1)
        self.assertEqual(first.status, CommandStatus.CANCELLED)
        self.assertEqual(second.status, CommandStatus.QUEUED)

    def test_laya_false_positive_guard_and_provider_timing_are_instrumented(self):
        agent = MagicMock()
        agent.predict.return_value = {"answers": {"action": {"choice": "STOP"}}}
        brain = make_test_laya(agent)
        with self.assertRaises(ValueError):
            brain.understand_many("How are you")
        self.assertEqual(brain.metrics.snapshot()["counts"]["laya:failed"], 1)
        self.assertNotIn("How are you", str(brain.metrics.snapshot()))
        planner = make_test_planner(enabled=True, transport=lambda _: {"actions": [{"action": "SCROLL", "target": "down"}]})
        planner.plan_actions("Please scroll down")
        self.assertEqual(planner.metrics.snapshot()["counts"]["provider_completion:success"], 1)

    def test_async_planning_wait_does_not_block_stop(self):
        loop = self.make_loop()
        async def scenario():
            processing = asyncio.create_task(loop.process_text_async("semantic fixture"))
            self.assertTrue(await asyncio.to_thread(loop.laya.started.wait, 1.0))
            self.addCleanup(loop.laya.release.set)
            loop.ingest_text("Stop")
            self.assertEqual(await asyncio.wait_for(processing, 1.0), "STOP")
            self.assertEqual([c.action for c in loop.executor.calls], [Action.STOP])
            loop.laya.release.set()
        asyncio.run(scenario())

    def test_async_cancelled_dequeue_does_not_lose_request_or_execution_slot(self):
        loop = self.make_loop()
        async def scenario():
            consumer = asyncio.create_task(loop.execute_next_queued_async(timeout=.02))
            await asyncio.sleep(0)
            consumer.cancel()
            req = loop.ingest_text("Scroll down")[0]
            with self.assertRaises(asyncio.CancelledError):
                await consumer
            self.assertEqual(await loop.execute_next_queued_async(), "OK")
            self.assertEqual(req.task.status, TaskStatus.SUCCEEDED)
            self.assertFalse(loop.command_queue.is_busy())
        asyncio.run(scenario())

    def test_agent_dispatch_result_and_shutdown_ownership_are_truthful(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = False
        release = threading.Event()
        started = threading.Event()
        def agent(**kwargs):
            started.set()
            release.wait(2.0)
            return {"success": True, "final_result": "AGENT_COMPLETED: done"}
        executor.browser_agent = MagicMock()
        executor.browser_agent.run_task.side_effect = agent
        loop = self.make_loop(executor=executor)
        req = loop.ingest_text("Research three laptops and compare them")[0]
        try:
            self.assertEqual(loop.execute_next_queued(), "OK")
            self.assertTrue(started.wait(1.0))
            self.assertEqual(req.task.status, TaskStatus.RUNNING)
            self.assertEqual(req.execution_completed_at, 0)
            self.assertFalse(loop.close(timeout=.01))
            self.assertTrue(loop.shutdown_status["agent_alive"])
            self.assertTrue(loop.state.agent_running)
            self.assertEqual(loop.state.get_browser_ownership(), BrowserOwnership.AGENT.value)
        finally:
            release.set()
            self.assertTrue(executor.join_agent(1.0))
        self.assertEqual(req.task.status, TaskStatus.CANCELLED)
        self.assertFalse(loop.state.agent_running)
        self.assertEqual(loop.state.get_browser_ownership(), BrowserOwnership.NONE.value)

    def test_verified_browser_result_has_verification_evidence(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = True
        executor.browser.get_current_url.return_value = "https://youtube.com"
        executor.screen = MagicMock()
        loop = self.make_loop(executor=executor)
        req = loop.ingest_text("Open YouTube")[0]
        loop.drain_queue()
        self.assertEqual(req.task.status, TaskStatus.VERIFIED)
        self.assertIsNotNone(req.task.snapshot()["latency_ms"]["verification"])

    def test_executor_never_dispatches_already_cancelled_command(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.keyboard = MagicMock()
        event = threading.Event()
        event.set()
        self.assertEqual(executor.execute(Command(Action.PRESS_KEY, "enter"), cancel_event=event), "CANCELLED")
        executor.keyboard.press.assert_not_called()

    def test_agent_reported_success_and_duplicate_rejection_are_not_verified(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = False
        started, release = threading.Event(), threading.Event()
        def agent(**kwargs):
            started.set()
            release.wait(2.0)
            return {"success": True, "final_result": "AGENT_COMPLETED: done"}
        executor.browser_agent = MagicMock()
        executor.browser_agent.run_task.side_effect = agent
        loop = self.make_loop(executor=executor)
        first = loop.ingest_text("Research laptops and compare them")[0]
        try:
            loop.drain_queue()
            self.assertTrue(started.wait(1.0))
            second = loop.ingest_text("Compare React and Vue")[0]
            self.assertEqual(loop.drain_queue(), ["REJECTED"])
            self.assertEqual(second.task.status, TaskStatus.FAILED)
            self.assertEqual(first.task.status, TaskStatus.RUNNING)
        finally:
            release.set()
            self.assertTrue(executor.join_agent(1.0))
        self.assertEqual(first.task.status, TaskStatus.SUCCEEDED)
        self.assertGreater(first.execution_completed_at, 0)

    def test_stop_keeps_stubborn_agent_ownership_until_worker_exit(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        executor.browser.is_active.return_value = False
        started, release = threading.Event(), threading.Event()
        def agent(**kwargs):
            started.set()
            release.wait(2.0)
            return {"success": True, "final_result": "done"}
        executor.browser_agent = MagicMock()
        executor.browser_agent.run_task.side_effect = agent
        loop = self.make_loop(executor=executor)
        loop.ingest_text("Research laptops and compare them")
        try:
            loop.drain_queue()
            self.assertTrue(started.wait(1.0))
            loop.ingest_text("Stop")
            self.assertEqual(loop.drain_queue(), ["STOP"])
            self.assertTrue(loop.state.agent_running)
            self.assertEqual(loop.state.get_browser_ownership(), BrowserOwnership.AGENT.value)
        finally:
            release.set()
            self.assertTrue(executor.join_agent(1.0))
        self.assertFalse(loop.state.agent_running)
        self.assertEqual(loop.state.get_browser_ownership(), BrowserOwnership.NONE.value)

    def test_repeated_stop_generations_do_not_reenable_normal_work(self):
        loop = self.make_loop()
        req = self.block_plan(loop)
        for _ in range(50):
            loop.ingest_text("Stop")
            self.assertEqual(loop.ingest_text("Scroll down"), [])
        self.assertEqual(loop.command_queue.pending_count(), 1)
        self.assertEqual(req.task.status, TaskStatus.CANCELLED)
        self.assertEqual(loop.drain_queue(), ["STOP"])
        self.assertEqual(loop.command_queue.generation, 50)

    def test_browser_agent_initialization_failure_closes_created_browser(self):
        from browser.agent import AutonomousBrowserAgent
        agent = AutonomousBrowserAgent(ai_provider=make_test_ai_provider())
        browser = MagicMock()
        browser.close = AsyncMock()
        with patch.object(agent, "_get_llm", return_value=object()), \
             patch("browser_use.Browser", return_value=browser), \
             patch("browser_use.Agent", side_effect=RuntimeError("fixture constructor failure")):
            result = asyncio.run(agent.execute_task("research fixture"))
        self.assertTrue(result.startswith("ERROR:"))
        browser.close.assert_awaited_once()
        self.assertFalse(agent.is_running())

    def test_async_multiple_commands_preserve_order_after_planning(self):
        loop = self.make_loop()
        self.block_plan(loop)
        loop.ingest_text("Search Python")
        loop.ingest_text("Scroll down")
        loop.laya.release.set()
        self.assertEqual(asyncio.run(loop.drain_queue_async()), ["OK"] * 3)
        self.assertEqual([cmd.action for cmd in loop.executor.calls],
                         [Action.OPEN_URL, Action.SEARCH, Action.SCROLL])

    def test_cancellation_during_verification_never_starts_recovery(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        event = threading.Event()
        def dropped_session():
            event.set()
            return False
        executor.browser.is_active.side_effect = dropped_session
        self.assertEqual(executor.execute(Command(Action.OPEN_URL, "https://youtube.com"),
                                          cancel_event=event), "CANCELLED")
        executor.browser.start.assert_not_called()
        executor.browser.open_url.assert_called_once()
        self.assertEqual(executor.verification_completed_at, 0)
        self.assertIsNone(executor.state.current_site)

    def test_browser_startup_metrics_record_success_and_failure_without_prompts(self):
        from browser.browser import BrowserController
        browser = BrowserController()
        with patch.object(browser, "is_active", return_value=False), \
             patch.object(browser, "_start_session") as start:
            browser.start()
            start.side_effect = RuntimeError("private diagnostic")
            with self.assertRaises(RuntimeError):
                browser.start()
        metrics = browser.metrics.snapshot()
        self.assertEqual(metrics["counts"], {"browser_startup:success": 1, "browser_startup:failed": 1})
        self.assertNotIn("private diagnostic", str(metrics))

    def test_stop_between_planner_check_and_publication_rejects_context_update(self):
        loop = self.make_loop()
        req = self.block_plan(loop)
        worker = loop._planner_thread
        resolve = loop.command_queue.resolve
        def preempt(reservation, commands):
            loop.ingest_text("Stop")
            return resolve(reservation, commands)
        with patch.object(loop.command_queue, "resolve", side_effect=preempt):
            loop.laya.release.set()
            worker.join(1.0)
            self.assertFalse(worker.is_alive())
        self.assertEqual(req.task.status, TaskStatus.CANCELLED)
        self.assertIsNone(loop._planning_state.current_site)
        self.assertEqual(loop.drain_queue(), ["STOP"])

    def test_async_cancelled_task_cannot_execute_its_remaining_steps(self):
        class PausingExecutor(RecordingExecutor):
            async def execute_async(self, command, raw_text=None, cancel_event=None):
                self.calls.append(command)
                await asyncio.Event().wait()
        loop = self.make_loop(executor=PausingExecutor())
        req = loop.ingest_text("Open Notepad and type hello")[0]
        async def scenario():
            consumer = asyncio.create_task(loop.execute_next_queued_async())
            while not loop.executor.calls:
                await asyncio.sleep(0)
            consumer.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await consumer
            self.assertEqual(await loop.execute_next_queued_async(), "CANCELLED")
        asyncio.run(scenario())
        self.assertEqual(req.task.status, TaskStatus.CANCELLED)
        self.assertEqual([command.action for command in loop.executor.calls], [Action.OPEN_APP])
        self.assertFalse(loop.command_queue.is_busy())

    def test_repeated_async_dequeue_cancellation_does_not_lose_accounting(self):
        loop = self.make_loop()
        req = loop.ingest_text("Scroll down")[0]
        started, release = threading.Event(), threading.Event()
        dequeue = loop.command_queue.dequeue
        def delayed_dequeue(timeout):
            started.set()
            if not release.wait(1.0):
                raise AssertionError("Test did not release dequeue")
            return dequeue(timeout)
        async def scenario():
            with patch.object(loop.command_queue, "dequeue", side_effect=delayed_dequeue):
                consumer = asyncio.create_task(loop.execute_next_queued_async())
                self.assertTrue(await asyncio.to_thread(started.wait, 1.0))
                try:
                    consumer.cancel()
                    await asyncio.sleep(0)
                    consumer.cancel()
                finally:
                    release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await consumer
            self.assertEqual(await loop.execute_next_queued_async(), "OK")
        asyncio.run(scenario())
        self.assertEqual(req.task.status, TaskStatus.SUCCEEDED)
        self.assertFalse(loop.command_queue.is_busy())

    def test_browser_cleanup_failure_is_not_reported_as_successful_shutdown(self):
        executor = Executor(ai_provider=make_test_ai_provider())
        executor.browser = MagicMock()
        executor.browser.close.side_effect = RuntimeError("private cleanup diagnostic")
        executor.browser_agent = MagicMock()
        loop = self.make_loop(executor=executor)
        self.assertFalse(loop.close())
        self.assertTrue(loop.shutdown_status["executor_cleanup_failed"])
        self.assertFalse(loop.shutdown_status["agent_alive"])
        self.assertNotIn("private cleanup diagnostic", str(loop.shutdown_status))

    def test_executor_cleanup_exception_remains_visible_in_shutdown_status(self):
        executor = RecordingExecutor()
        executor.close = MagicMock(side_effect=RuntimeError("private cleanup diagnostic"))
        loop = self.make_loop(executor=executor)
        self.assertFalse(loop.close())
        self.assertTrue(loop.shutdown_status["executor_cleanup_failed"])
        self.assertNotIn("private cleanup diagnostic", str(loop.shutdown_status))
