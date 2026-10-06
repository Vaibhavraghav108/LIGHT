"""Pure registry tests and real Executor routing with mocked OS/browser primitives."""

import asyncio
from dataclasses import replace
import threading
import unittest
from unittest.mock import MagicMock, patch

from brain.commands import Action, Command
from core.capabilities import (
    Backend, CapabilityError, CapabilityPlan, CapabilityRegistry,
    ExecutionMode, Risk, Verification, default_registry,
)
from core.capability_adapter import CapabilityAdapter
from core.executor import Executor
from core.loop import LightLoop
from core.queue_manager import CommandStatus
from core.tasks import TaskRecord, TaskStatus
from tests.provider_test_utils import make_test_ai_provider, make_test_laya
from utils.logger import logger


class TestCapabilityRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.task = TaskRecord(1, 0)
        self.plan = CapabilityPlan("browser.open_site", {"url": "https://example.com"},
                                   1, 0, Backend.PLAYWRIGHT)

    def validate(self, plan=None, **kwargs):
        return self.registry.validate(plan or self.plan, task=kwargs.pop("task", self.task),
                                      generation=kwargs.pop("generation", 0), **kwargs)

    def test_register_lookup_and_availability(self):
        empty = CapabilityRegistry()
        definition = self.registry.lookup("browser.open_site")
        empty.register(definition)
        self.assertIs(empty.lookup(definition.name), definition)
        self.assertTrue(empty.available(definition.name, Backend.PLAYWRIGHT))
        self.assertFalse(empty.available(definition.name, Backend.PLATFORM))
        self.assertFalse(empty.available(definition.name, "playwright"))
        self.assertFalse(empty.available("browser.read"))

    def test_duplicate_registration_rejected(self):
        with self.assertRaises(CapabilityError):
            self.registry.register(self.registry.lookup("browser.open_site"))

    def test_unknown_capability_rejected(self):
        with self.assertRaises(CapabilityError):
            self.validate(replace(self.plan, capability="browser.read"))

    def test_missing_argument_rejected(self):
        with self.assertRaises(CapabilityError):
            self.validate(replace(self.plan, arguments={}))

    def test_unknown_argument_rejected(self):
        for key in ("shell", "risk", "verification", "model", 4):
            with self.subTest(key=key), self.assertRaises(CapabilityError):
                self.validate(replace(self.plan, arguments={"url": "https://example.com", key: "x"}))

    def test_wrong_argument_types_rejected(self):
        for value in (None, True, 4, 4.0, ["https://example.com"], {"url": "https://example.com"}):
            with self.subTest(value=value), self.assertRaises(CapabilityError):
                self.validate(replace(self.plan, arguments={"url": value}))

    def test_empty_arguments_rejected(self):
        for value in ("", "  ", "\t"):
            with self.subTest(value=value), self.assertRaises(CapabilityError):
                self.validate(replace(self.plan, arguments={"url": value}))

    def test_valid_plan_accepted_and_metadata_authoritative(self):
        definition = self.validate()
        self.assertEqual(definition.risk, Risk.MEDIUM)
        self.assertEqual(definition.verification, Verification.BROWSER_READINESS)
        self.assertEqual(definition.execution_mode, ExecutionMode.ORDERED)

    def test_invalid_plan_container_rejected(self):
        with self.assertRaises(CapabilityError):
            self.registry.validate({}, task=self.task, generation=0)
        with self.assertRaises(CapabilityError):
            replace(self.plan, arguments=["https://example.com"])

    def test_task_identity_validation(self):
        for value in (0, -1, True, "1", 2):
            with self.subTest(value=value), self.assertRaises(CapabilityError):
                self.validate(replace(self.plan, task_id=value))
        with self.assertRaises(CapabilityError):
            self.validate(task=TaskRecord(True, 0))
        with self.assertRaises(CapabilityError):
            self.validate(task=None)

    def test_generation_validation(self):
        for value in (-1, True, "0", 1):
            with self.subTest(value=value), self.assertRaises(CapabilityError):
                self.validate(replace(self.plan, generation=value))
        with self.assertRaises(CapabilityError):
            self.validate(task=TaskRecord(1, True))

    def test_stale_plan_rejected_even_if_cancellation_event_cleared(self):
        with self.assertRaises(CapabilityError):
            self.validate(generation=1, cancelled=False)

    def test_cancelled_and_terminal_tasks_rejected(self):
        with self.assertRaises(CapabilityError):
            self.validate(cancelled=True)
        for status in (TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.AMBIGUOUS,
                       TaskStatus.SUCCEEDED, TaskStatus.VERIFIED):
            with self.subTest(status=status), self.assertRaises(CapabilityError):
                self.validate(task=TaskRecord(1, 0, status=status))

    def test_unsupported_backend_mode_and_source_rejected(self):
        for field, value in (("backend", Backend.PLATFORM), ("backend", "playwright"),
                             ("execution_mode", "agent"), ("source", "llm")):
            with self.subTest(field=field, value=value), self.assertRaises(CapabilityError):
                self.validate(replace(self.plan, **{field: value}))

    def test_unsafe_urls_rejected(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "example.com", "https://",
                    "https://user:password@example.com", "https://example.com:bad",
                    "https://example.com:0", "https://example.com\n", "https:\\example.com"):
            with self.subTest(url=url), self.assertRaises(CapabilityError):
                self.validate(replace(self.plan, arguments={"url": url}))

    def test_explicit_http_localhost_and_https_supported(self):
        for url in ("http://127.0.0.1:8080/index.html", "http://localhost:8080", "https://example.com/a?q=b"):
            with self.subTest(url=url):
                self.validate(replace(self.plan, arguments={"url": url}))

    def test_confirmation_is_required_and_strictly_boolean(self):
        plan = CapabilityPlan("keyboard.type", {"text": "hello"}, 1, 0,
                              Backend.FOREGROUND_KEYBOARD)
        for confirmed in (False, "true", 1):
            with self.subTest(confirmed=confirmed), self.assertRaises(CapabilityError):
                self.validate(replace(plan, confirmed=confirmed))
        self.validate(replace(plan, confirmed=True))

    def test_narrow_app_key_engine_and_scroll_values(self):
        for name, args, backend in (
            ("desktop.open_app", {"app": "powershell"}, Backend.PLATFORM),
            ("desktop.open_app", {"app": "brave"}, Backend.PLATFORM),
            ("keyboard.press", {"key": "ctrl+alt+delete"}, Backend.FOREGROUND_KEYBOARD),
            ("browser.search", {"query": "hello", "engine": "agent"}, Backend.PLAYWRIGHT),
            ("browser.scroll", {"direction": "sideways"}, Backend.PLAYWRIGHT),
        ):
            with self.subTest(name=name, args=args), self.assertRaises(CapabilityError):
                self.validate(CapabilityPlan(name, args, 1, 0, backend, confirmed=True))

    def test_activation_never_interprets_ordinals_as_named_elements(self):
        for target in ("1", "first", "element 1", "the first clickable element", "item two",
                       "the clickable element first", "first result", "the second youtube short",
                       "on the first element", "search result number 2", "onto to the first result"):
            with self.subTest(target=target), self.assertRaises(CapabilityError):
                self.validate(CapabilityPlan("browser.activate", {"target": target}, 1, 0,
                                             Backend.PLAYWRIGHT, confirmed=True))

    def test_plan_arguments_are_isolated_and_immutable(self):
        args = {"url": "https://example.com"}
        plan = replace(self.plan, arguments=args)
        args["url"] = "javascript:alert(1)"
        self.assertEqual(plan.arguments["url"], "https://example.com")
        with self.assertRaises(TypeError):
            plan.arguments["url"] = "x"

    def test_dependencies_fail_closed_without_a_new_scheduler(self):
        for dependencies in ((1,), (2,), [], "none"):
            with self.subTest(dependencies=dependencies), self.assertRaises(CapabilityError):
                self.validate(replace(self.plan, dependencies=dependencies))

    def test_registry_is_deterministic_and_has_no_io(self):
        with patch("builtins.open", side_effect=AssertionError("filesystem")), \
                patch("socket.socket", side_effect=AssertionError("network")), \
                patch("subprocess.run", side_effect=AssertionError("process")):
            for _ in range(10):
                fresh = default_registry()
                self.assertEqual(fresh.names(), self.registry.names())
                self.assertEqual(fresh.validate(self.plan, task=self.task, generation=0), self.validate())
        self.assertEqual(len(self.registry.names()), 8)

    def test_all_capabilities_lower_to_existing_actions(self):
        cases = (
            ("browser.open_site", {"url": "https://example.com"}, Action.OPEN_URL, "https://example.com"),
            ("browser.search", {"query": "python"}, Action.SEARCH, "google:python"),
            ("browser.search", {"query": "python", "engine": "github"}, Action.SEARCH, "github:python"),
            ("browser.scroll", {"direction": "down"}, Action.SCROLL, "down"),
            ("browser.activate", {"target": "Subscriptions"}, Action.CLICK_ELEMENT, "Subscriptions"),
            ("desktop.open_app", {"app": "notepad"}, Action.OPEN_APP, "notepad"),
            ("desktop.switch_window", {"target": "Calculator"}, Action.SWITCH_WINDOW, "Calculator"),
            ("keyboard.type", {"text": "hello"}, Action.TYPE, "hello"),
            ("keyboard.press", {"key": "enter"}, Action.PRESS_KEY, "enter"),
        )
        adapter = CapabilityAdapter(self.registry)
        for name, args, action, target in cases:
            with self.subTest(name=name, args=args):
                plan = CapabilityPlan(name, args, 1, 0, self.registry.lookup(name).backends[0], confirmed=True)
                self.assertEqual(adapter.lower(plan, task=self.task, generation=0), Command(action, target))

    def test_adapter_always_validates_before_lowering(self):
        with self.assertRaises(CapabilityError):
            CapabilityAdapter(self.registry).lower(replace(self.plan, arguments={"shell": "x"}),
                                                  task=self.task, generation=0)


class TestCapabilityExecution(unittest.TestCase):
    def setUp(self):
        quiet = patch.object(logger, "disabled", True)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.executor = Executor(ai_provider=make_test_ai_provider())
        for name in ("browser", "screen", "apps", "keyboard", "mouse"):
            setattr(self.executor, name, MagicMock())
        self.executor.browser.is_active.return_value = True
        self.executor.browser.get_current_url.return_value = "https://example.com"
        self.executor.browser.get_title.return_value = "Example"
        self.executor.screen.get_foreground_window_info.return_value = {"title": "Example", "process_name": ""}
        self.executor.screen.get_mouse_position.return_value = (0, 0)
        self.executor.apps._canonical_app_key.side_effect = lambda value: value
        self.brain = make_test_laya(MagicMock())
        self.loop = LightLoop(MagicMock(), self.brain, self.executor)
        self.addCleanup(self.loop.close)

    def submit(self, name, args, **kwargs):
        return self.loop.ingest_capability(name, args, **kwargs)

    def test_open_site_reuses_browser_and_existing_verification(self):
        req = self.submit("browser.open_site", {"url": "https://example.com"})
        self.assertEqual(self.loop.execute_next_queued(), "OK")
        self.executor.browser.open_url.assert_called_once_with("https://example.com")
        self.assertEqual(req.task.status, TaskStatus.VERIFIED)
        self.assertEqual(self.loop.state.current_url, "https://example.com")
        self.assertIsNotNone(req.task.duration_ms("verification_started", "verification_finished"))

    def test_search_reuses_selected_structured_engine(self):
        self.submit("browser.search", {"query": "light", "engine": "github"})
        self.assertEqual(self.loop.execute_next_queued(), "OK")
        self.executor.browser.search.assert_called_once_with("light", engine="github")
        self.assertEqual(self.loop.state.last_search_query, "light")

    def test_scroll_reuses_browser_without_claiming_verification(self):
        req = self.submit("browser.scroll", {"direction": "down"})
        self.assertEqual(self.loop.execute_next_queued(), "OK")
        self.executor.browser.scroll.assert_called_once_with("down")
        self.executor.mouse.scroll.assert_not_called()
        self.assertEqual(req.task.status, TaskStatus.SUCCEEDED)
        self.assertNotIn("verification_finished", req.task.timestamps)

    def test_inactive_browser_rejected_before_dispatch(self):
        for name, args in (("browser.scroll", {"direction": "down"}),
                           ("browser.activate", {"target": "Subscriptions"})):
            with self.subTest(name=name):
                self.executor.browser.is_active.return_value = False
                req = self.submit(name, args, confirmed=True)
                self.assertEqual(self.loop.execute_next_queued(), "ERROR")
                self.assertEqual(req.task.status, TaskStatus.FAILED)
                self.executor.browser.scroll.assert_not_called()
                self.executor.browser.click_element.assert_not_called()
                self.executor.mouse.scroll.assert_not_called()

    def test_browser_closes_between_gate_and_dispatch_never_scrolls_desktop(self):
        self.executor.browser.is_active.side_effect = [True, False]
        req = self.submit("browser.scroll", {"direction": "down"})
        self.assertEqual(self.loop.execute_next_queued(), "ERROR")
        self.executor.browser.scroll.assert_not_called()
        self.executor.mouse.scroll.assert_not_called()
        self.assertEqual(req.task.status, TaskStatus.FAILED)

    def test_named_activation_reuses_existing_click(self):
        self.submit("browser.activate", {"target": "Subscriptions"}, confirmed=True)
        self.assertEqual(self.loop.execute_next_queued(), "OK")
        self.executor.browser.click_element.assert_called_once_with("Subscriptions", mouse_controller=self.executor.mouse)
        self.executor.browser.click_result.assert_not_called()

    def test_native_app_reuses_existing_focus_and_state(self):
        req = self.submit("desktop.open_app", {"app": "notepad"})
        self.assertEqual(self.loop.execute_next_queued(), "OK")
        self.executor.apps.open.assert_called_once_with("notepad", wait_and_focus=True,
                                                       screen_controller=self.executor.screen)
        self.assertEqual(self.loop.state.current_app, "notepad")
        # Foreground checks are not the timestamped browser-verification contract.
        self.assertEqual(req.task.status, TaskStatus.SUCCEEDED)

    def test_switch_window_reuses_existing_platform_route(self):
        self.submit("desktop.switch_window", {"target": "Calculator"})
        self.assertEqual(self.loop.execute_next_queued(), "OK")
        self.executor.screen.switch_to_window.assert_called_once_with("Calculator")

    def test_missing_window_is_failure_not_dispatch_success(self):
        self.executor.screen.switch_to_window.return_value = False
        req = self.submit("desktop.switch_window", {"target": "missing"})
        self.assertEqual(self.loop.execute_next_queued(), "ERROR")
        self.assertEqual(req.task.status, TaskStatus.FAILED)

    def test_keyboard_typing_reuses_foreground_routing(self):
        self.executor.screen.is_browser_foreground.return_value = False
        req = self.submit("keyboard.type", {"text": "hello"}, confirmed=True)
        self.assertEqual(self.loop.execute_next_queued(), "OK")
        self.executor.keyboard.type_text.assert_called_once_with("hello")
        self.executor.browser.type_in_browser.assert_not_called()
        self.assertEqual(req.task.status, TaskStatus.SUCCEEDED)

    def test_keyboard_typing_preserves_dom_route_and_fallback(self):
        self.executor.screen.is_browser_foreground.return_value = True
        for handled in (True, False):
            with self.subTest(handled=handled):
                self.executor.keyboard.reset_mock()
                self.executor.browser.type_in_browser.reset_mock()
                self.executor.browser.type_in_browser.return_value = handled
                self.submit("keyboard.type", {"text": "hello"}, confirmed=True)
                self.assertEqual(self.loop.execute_next_queued(), "OK")
                self.executor.browser.type_in_browser.assert_called_once_with("hello")
                if handled:
                    self.executor.keyboard.type_text.assert_not_called()
                else:
                    self.executor.keyboard.type_text.assert_called_once_with("hello")

    def test_keyboard_press_reuses_existing_keyboard(self):
        self.submit("keyboard.press", {"key": "enter"}, confirmed=True)
        self.assertEqual(self.loop.execute_next_queued(), "OK")
        self.executor.keyboard.press.assert_called_once_with("enter")

    def test_invalid_plan_has_no_queue_or_observed_state_effect(self):
        before = self.loop.state.snapshot()
        with self.assertRaises(CapabilityError):
            self.submit("desktop.open_app", {"app": "powershell"})
        self.assertEqual(self.loop.command_queue.pending_count(), 0)
        self.assertEqual(self.loop.state.snapshot(), before)
        self.assertEqual(self.loop.task_status()[-1]["status"], "failed")
        self.executor.apps.open.assert_not_called()

    def test_stop_cancels_capability_without_browser_effects(self):
        req = self.submit("browser.open_site", {"url": "https://example.com"})
        stop = self.loop.ingest_text("STOP")[0]
        self.assertEqual(req.task.status, TaskStatus.CANCELLED)
        self.assertLess(stop.task.duration_ms("ingested", "cancellation_signalled"), 5.0)
        self.assertEqual(self.loop.drain_queue(), ["STOP"])
        self.executor.browser.open_url.assert_not_called()
        with self.assertRaises(CapabilityError):
            self.submit("browser.open_site", {"url": "https://example.com"})

    def test_cancelled_task_rejected_at_consumer(self):
        req = self.submit("browser.open_site", {"url": "https://example.com"})
        req.task.fail(TaskStatus.CANCELLED, "test cancellation")
        self.assertEqual(self.loop.execute_next_queued(), "CANCELLED")
        self.executor.browser.open_url.assert_not_called()

    def test_stale_generation_rejected_at_consumer(self):
        req = self.submit("browser.open_site", {"url": "https://example.com"})
        req.capability_plan = replace(req.capability_plan, generation=1)
        self.assertEqual(self.loop.execute_next_queued(), "ERROR")
        self.executor.browser.open_url.assert_not_called()
        self.assertEqual(req.task.status, TaskStatus.FAILED)

    def test_mutated_action_rejected_at_consumer(self):
        req = self.submit("browser.open_site", {"url": "https://example.com"})
        req.command = Command(Action.TYPE, "unexpected")
        self.assertEqual(self.loop.execute_next_queued(), "ERROR")
        self.executor.keyboard.type_text.assert_not_called()
        self.executor.browser.open_url.assert_not_called()

    def test_capabilities_and_voice_share_fifo_task_identity(self):
        first = self.submit("keyboard.press", {"key": "enter"}, confirmed=True)
        second = self.loop.ingest_text("press tab")[0]
        self.assertLess(first.task.id, second.task.id)
        self.assertEqual(self.loop.drain_queue(), ["OK", "OK"])
        self.assertEqual([call.args[0] for call in self.executor.keyboard.press.call_args_list], ["enter", "tab"])

    def test_stop_cancels_backlog_even_after_task_snapshot_eviction(self):
        requests = [self.submit("keyboard.press", {"key": "tab"}, confirmed=True) for _ in range(300)]
        self.assertEqual(len(self.loop.task_status()), 256)
        self.loop.ingest_text("stop")
        self.assertTrue(all(req.task.status == TaskStatus.CANCELLED for req in requests))
        self.assertEqual(self.loop.command_queue.pending_count(), 1)
        self.assertEqual(self.loop.drain_queue(), ["STOP"])
        self.executor.keyboard.press.assert_not_called()

    def test_idle_typed_admission_refreshes_observed_planning_context(self):
        self.loop.state.current_site = "youtube"
        self.submit("keyboard.press", {"key": "tab"}, confirmed=True)
        request = self.loop.ingest_text("search lofi")[0]
        self.assertEqual(request.command, Command(Action.SEARCH, "youtube:lofi"))

    def test_ordinary_fast_path_does_not_use_registry_or_models(self):
        with patch.object(self.loop.capabilities, "validate", side_effect=AssertionError("registry")), \
                patch.object(self.brain.llm, "plan_actions", side_effect=AssertionError("LLM")), \
                patch.object(self.brain.agent, "predict", side_effect=AssertionError("Laya")):
            self.assertEqual(self.loop.process_text("press tab"), "OK")

    def test_typed_ingestion_never_uses_models_or_agent(self):
        with patch.object(self.brain, "understand_many", side_effect=AssertionError("planner")), \
                patch.object(self.executor.browser_agent, "execute_task", side_effect=AssertionError("agent")):
            self.submit("keyboard.press", {"key": "tab"}, confirmed=True)
            self.assertEqual(self.loop.execute_next_queued(), "OK")

    def test_pending_semantic_snapshot_cannot_overwrite_typed_predictions(self):
        from tests.test_planning_foundation import BlockingBrain
        brain = BlockingBrain()
        self.loop.laya = brain
        self.addCleanup(brain.release.set)
        self.loop.ingest_text("semantic fixture")
        worker = self.loop._planner_thread
        try:
            self.assertTrue(brain.started.wait(1.0))
            with self.assertRaises(CapabilityError):
                self.submit("desktop.open_app", {"app": "notepad"})
            self.assertEqual(self.loop.command_queue.pending_count(), 1)
        finally:
            brain.release.set()
            worker.join(2.0)
        self.assertFalse(worker.is_alive())
        self.submit("desktop.open_app", {"app": "notepad"})
        self.assertEqual(self.loop._planning_state.current_app, "notepad")

    def test_stop_signals_while_typed_validation_holds_admission_lock(self):
        entered, release = threading.Event(), threading.Event()
        original = self.loop.capabilities.validate
        def blocked_validation(*args, **kwargs):
            entered.set()
            if not release.wait(2.0):
                raise AssertionError("Test did not release validation")
            return original(*args, **kwargs)
        submissions = []
        def submit():
            submissions.append(self.submit("browser.open_site", {"url": "https://example.com"}))
        with patch.object(self.loop.capabilities, "validate", side_effect=blocked_validation):
            producer = threading.Thread(target=submit)
            stopper = threading.Thread(target=lambda: self.loop.ingest_text("stop"))
            producer.start()
            try:
                self.assertTrue(entered.wait(1.0))
                stopper.start()
                self.assertTrue(self.loop.command_queue.cancel_event.wait(1.0))
            finally:
                release.set()
                producer.join(2.0)
                if stopper.ident is not None:
                    stopper.join(2.0)
        self.assertFalse(producer.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual(len(submissions), 1)
        self.assertEqual(submissions[0].task.status, TaskStatus.CANCELLED)
        self.executor.browser.open_url.assert_not_called()

    def test_legacy_scroll_still_uses_desktop_when_browser_inactive(self):
        self.executor.browser.is_active.return_value = False
        self.assertEqual(self.loop.process_text("scroll down"), "OK")
        self.executor.mouse.scroll.assert_called_once_with("down")

    def test_async_path_reuses_executor_and_truthful_status(self):
        req = self.submit("browser.open_site", {"url": "https://example.com"})
        self.assertEqual(asyncio.run(self.loop.execute_next_queued_async()), "OK")
        self.executor.browser.open_url.assert_called_once_with("https://example.com")
        self.assertEqual(req.task.status, TaskStatus.VERIFIED)

    def test_async_stop_cancels_capabilities(self):
        req = self.submit("browser.open_site", {"url": "https://example.com"})
        self.loop.ingest_text("cancel")
        self.assertEqual(asyncio.run(self.loop.drain_queue_async()), ["STOP"])
        self.assertEqual(req.task.status, TaskStatus.CANCELLED)
        self.executor.browser.open_url.assert_not_called()

    def test_close_cancels_typed_work_and_leaves_no_queue(self):
        req = self.submit("keyboard.press", {"key": "enter"}, confirmed=True)
        self.assertTrue(self.loop.close())
        self.assertEqual(req.task.status, TaskStatus.CANCELLED)
        self.assertFalse(self.loop.command_queue.is_busy())
        with self.assertRaises(CapabilityError):
            self.submit("keyboard.press", {"key": "enter"}, confirmed=True)
        self.executor.keyboard.press.assert_not_called()

    def test_stop_during_typed_dispatch_overrides_success(self):
        started, release = threading.Event(), threading.Event()
        def blocked_open(*args):
            started.set()
            if not release.wait(2.0):
                raise AssertionError("Test did not release browser call")
        self.executor.browser.open_url.side_effect = blocked_open
        req = self.submit("browser.open_site", {"url": "https://example.com"})
        results = []
        worker = threading.Thread(target=lambda: results.append(self.loop.execute_next_queued()))
        worker.start()
        try:
            self.assertTrue(started.wait(1.0))
            self.loop.ingest_text("stop")
        finally:
            release.set()
            worker.join(2.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, ["CANCELLED"])
        self.assertEqual(req.task.status, TaskStatus.CANCELLED)
        self.assertEqual(self.loop.execute_next_queued(), "STOP")
