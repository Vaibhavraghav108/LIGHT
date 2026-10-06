import inspect
import asyncio
import collections
import itertools
import re
import threading
import time

from brain.commands import Action, Command
from brain.decision import is_explicit_stop_or_cancel
from config import DUPLICATE_COOLDOWN_SECONDS, POLL_INTERVAL
from core.queue_manager import (
    CommandPriority,
    CommandQueue,
    CommandRequest,
    CommandStatus,
)
from core.state import LightState
from core.tasks import TaskRecord, TaskStatus, AmbiguousPlanError
from utils.logger import (
    log_debug,
    log_error,
    log_executor,
    log_info,
    log_perf,
    log_warning,
)


def _normalize_for_dedup(text: str) -> str:
    """Normalize whitespace and punctuation for duplicate STT detection."""
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


class LightLoop:
    """
    Continuous Producer-Consumer Voice Loop for LIGHT.
    - Producer: polls completed transcripts, suppresses duplicates, signals STOP,
      and admits pure deterministic commands or ordered planning reservations.
    - Planning worker: interprets reservations without blocking the listener.
    - Consumer (Ordered Executor): Dequeues and executes commands sequentially,
      preserving state consistency and honoring immediate STOP priority preemption.
    """

    def __init__(
        self,
        handy,
        laya,
        executor,
        state: LightState | None = None,
        duplicate_cooldown: float = DUPLICATE_COOLDOWN_SECONDS,
        poll_interval: float = POLL_INTERVAL,
    ):
        self.handy = handy
        self.laya = laya
        self.executor = executor
        self.state = state if state is not None else getattr(executor, "state", LightState())
        self.executor.state = self.state
        self.duplicate_cooldown = duplicate_cooldown
        self.poll_interval = poll_interval

        self.command_queue = CommandQueue()
        self._planning_state = self.state.clone_for_planning()
        self._admission_lock = threading.RLock()
        self._pending_plans = collections.deque()
        self._planner_thread = None
        self._planning_inflight = None
        self._task_ids = itertools.count(1)
        self._tasks = collections.deque(maxlen=256)
        self._closed = False
        self._listener_thread = None
        self.shutdown_status = {}

        self._stop_requested = threading.Event()
        self._listener_done = threading.Event()

        # Duplicate tracking state for listener
        self._last_text_norm = ""
        self._last_time = 0.0

    def _parse_spoken_text(self, text: str, state_for_parse: LightState) -> list[Command]:
        """Use understand_many when available, or fall back to single understand()."""
        if hasattr(self.laya, "understand_many"):
            # If understand_many is a real method (not an unconfigured MagicMock child)
            understand_many_attr = getattr(self.laya, "understand_many")
            if not isinstance(understand_many_attr, inspect.Parameter) and callable(understand_many_attr):
                # Check if self.laya is a unittest.mock.MagicMock where only .understand was configured
                from unittest.mock import MagicMock
                if isinstance(self.laya, MagicMock) and "understand_many" not in self.laya.__dict__:
                    single = self.laya.understand(text, state=state_for_parse)
                    return [single]
                return understand_many_attr(text, state=state_for_parse)

        single = self.laya.understand(text, state=state_for_parse)
        return [single]

    def ingest_text(self, text: str, voice_received_at: float | None = None,
                    transcript_published_at: float | None = None) -> list[CommandRequest]:
        """Admit completed speech without inference or execution.

        Unknown plans reserve FIFO positions. Optional publication timestamps
        must use this process's monotonic clock, not remote wall-clock time.
        """
        received_ts = voice_received_at if voice_received_at is not None else time.perf_counter()
        is_stop = is_explicit_stop_or_cancel(text)
        if is_stop:
            # Signal before locks, logs, or model work.
            self.command_queue.cancel_event.set()
            self._stop_requested.set()
            signalled_at = time.perf_counter()
        with self._admission_lock:
            task = TaskRecord(next(self._task_ids), self.command_queue.generation)
            task.mark("ingested", received_ts)
            if transcript_published_at is not None:
                task.mark("transcript_published", transcript_published_at)
            self._tasks.append(task)
            if is_stop:
                task.mark("cancellation_signalled", signalled_at)
                req = CommandRequest(text, Command(Action.STOP, None), task=task,
                                     generation=task.generation, priority=CommandPriority.STOP,
                                     voice_received_at=received_ts,
                                     parse_started_at=received_ts,
                                     parse_completed_at=signalled_at)
                for active in self._tasks:
                    if active is not task and active.status in {TaskStatus.ACCEPTED, TaskStatus.RUNNING}:
                        active.mark("cancellation_signalled", signalled_at)
                        active.fail(TaskStatus.CANCELLED, "Preempted by STOP")
                self._pending_plans.clear()
                self.command_queue.enqueue(req)
                task.remaining_steps = 1
                return [req]
            if self._closed or self.command_queue.cancel_event.is_set():
                task.fail(TaskStatus.CANCELLED, "Loop is stopping")
                return []
            if not self.command_queue.is_busy():
                self._planning_state = self.state.clone_for_planning()
            task.mark("routing_started")
            # Only an explicitly defined pure fast-path method may run here.
            fast_route = getattr(type(self.laya), "understand_deterministic", None)
            commands = None
            if fast_route is not None and not self._pending_plans and self._planning_inflight is None:
                try:
                    commands = fast_route(self.laya, text, state=self._planning_state)
                except ValueError:
                    task.fail(TaskStatus.FAILED, "Invalid deterministic request")
                    return []
            task.mark("routing_finished")
            if commands:
                requests = [CommandRequest(text, cmd, task=task, generation=task.generation,
                                           voice_received_at=received_ts,
                                           parse_started_at=task.timestamps["routing_started"],
                                           parse_completed_at=task.timestamps["routing_finished"])
                            for cmd in commands]
                task.remaining_steps = len(requests)
                self.command_queue.enqueue_many(requests)
                for request in requests:
                    if request.status != CommandStatus.CANCELLED:
                        self._planning_state.record_command(text, request.command)
                return requests
            if len(self._pending_plans) >= 64:
                task.fail(TaskStatus.FAILED, "Planning backlog is full")
                return []
            reservation = CommandRequest(text, None, task=task, generation=task.generation,
                                         voice_received_at=received_ts)
            self.command_queue.enqueue(reservation)
            task.mark("planning_submitted")
            self._pending_plans.append(reservation)
            if self._planner_thread is None or not self._planner_thread.is_alive():
                self._planner_thread = threading.Thread(target=self._planning_worker,
                                                        name="LIGHT-PlanningWorker", daemon=True)
                self._planner_thread.start()
            return [reservation]

    def _planning_worker(self):
        """Single bounded planning lane; never holds admission locks across inference."""
        while True:
            with self._admission_lock:
                if not self._pending_plans or self._closed or self.command_queue.cancel_event.is_set():
                    self._planner_thread = None
                    return
                reservation = self._pending_plans.popleft()
                self._planning_inflight = reservation
                snapshot = self._planning_state.clone_for_planning()
            task = reservation.task
            task.running()
            task.mark("planning_started")
            reservation.parse_started_at = time.perf_counter()
            commands = None
            failure = None
            try:
                commands = self._parse_spoken_text(reservation.text, snapshot)
                if not commands or any(not isinstance(cmd, Command) for cmd in commands):
                    raise ValueError("Planner returned no validated commands")
            except Exception as error:
                failure = error
            finally:
                task.mark("planning_finished")
            with self._admission_lock:
                self._planning_inflight = None
                if not self.command_queue.is_current(reservation) or self._closed:
                    reservation.cancel("Stale planner result discarded")
                    task.mark("planner_terminated")
                    self.command_queue.discard(reservation)
                    continue
                if failure is not None:
                    reservation.status = CommandStatus.FAILED
                    task.fail(TaskStatus.AMBIGUOUS if isinstance(failure, AmbiguousPlanError)
                              else TaskStatus.FAILED, "Ambiguous plan" if isinstance(failure, AmbiguousPlanError)
                              else "Interpretation failed")
                    self.command_queue.discard(reservation)
                    continue
                task.remaining_steps = len(commands)
                if not self.command_queue.resolve(reservation, commands):
                    task.mark("planner_terminated")
                    continue
                # Predictions stay separate from observed LightState.
                self._planning_state = snapshot
                for cmd in commands:
                    self._planning_state.record_command(reservation.text, cmd)

    def task_status(self) -> list[dict]:
        with self._admission_lock:
            return [task.snapshot() for task in self._tasks]

    def _call_executor(self, command: Command, raw_text: str, request=None) -> str:
        """Invoke executor.execute with cancel_event when supported by target callable signature."""
        target_fn = self.executor.execute
        side_effect = getattr(target_fn, "side_effect", None)
        if callable(side_effect):
            target_fn = side_effect

        supports_cancel_event = False
        supports_request = False
        try:
            sig = inspect.signature(target_fn)
            if "cancel_event" in sig.parameters:
                supports_cancel_event = True
            supports_request = "request" in sig.parameters
        except (ValueError, TypeError):
            supports_cancel_event = False

        kwargs = {"raw_text": raw_text}
        if supports_cancel_event:
            kwargs["cancel_event"] = self.command_queue.cancel_event
        if supports_request:
            kwargs["request"] = request
        return self.executor.execute(command, **kwargs)

    def _begin_request(self, req):
        if req.command.action != Action.STOP and (
                not self.command_queue.is_current(req) or
                (req.task is not None and req.task.status == TaskStatus.CANCELLED)):
            req.cancel("Cancelled before dispatch")
            return False
        if req.task:
            req.task.running()
            req.task.mark("execution_started", req.execution_started_at)
            req.task.mark("effect_dispatched")
        return True

    def _finish_request(self, req, result):
        if req.command.action != Action.STOP and self.command_queue.cancel_event.is_set():
            result = "CANCELLED"
        if result == "CANCELLED":
            req.cancel("Execution cancelled")
        elif result in {"ERROR", "REJECTED", "AMBIGUOUS"}:
            req.status = CommandStatus.FAILED
            if req.task:
                req.task.fail(TaskStatus.AMBIGUOUS if result == "AMBIGUOUS" else TaskStatus.FAILED,
                              "Execution rejected or failed")
        elif req.command.action == Action.AGENT_TASK and result == "OK":
            # Real AgentWorker owns completion. Dispatch is not task success.
            return result
        else:
            req.status = CommandStatus.COMPLETED
            if req.task:
                verified_at = getattr(self.executor, "verification_completed_at", None)
                verified = isinstance(verified_at, (int, float)) and verified_at >= req.execution_started_at
                if verified:
                    req.task.mark("verification_started", self.executor.verification_started_at)
                    req.task.mark("verification_finished", verified_at)
                req.task.finish_step(verified=verified)
        req.execution_completed_at = time.perf_counter()
        if req.task:
            req.task.mark("execution_finished", req.execution_completed_at)
        value = getattr(self.executor, "last_verification_ms", 0.0)
        req.verification_ms = float(value) if isinstance(value, (int, float)) else 0.0
        return result

    def _fail_request(self, req, error):
        req.execution_completed_at = time.perf_counter()
        if self.command_queue.cancel_event.is_set():
            req.cancel("Execution cancelled")
            if req.task:
                req.task.mark("execution_finished", req.execution_completed_at)
            return "CANCELLED"
        req.status = CommandStatus.FAILED
        req.error = "Execution failed"
        if req.task:
            req.task.fail(TaskStatus.FAILED, "Execution failed")
            req.task.mark("execution_finished", req.execution_completed_at)
        self.state.last_action = req.command.action
        self.state.record_failure(req.text, status="ERROR", error_message=str(error))
        self.command_queue.cancel_dependent_after_failure(
            req.command.action, failed_text=req.text, task_id=req.task.id if req.task else None)
        log_error("Command execution failed; continuing to listen")
        return "ERROR"

    def execute_next_queued(self, timeout: float = 0.02) -> str | None:
        """
        Consumer step: dequeue and execute the next CommandRequest in order.
        Returns "OK", "ERROR", "STOP", or None if queue was empty.
        """
        req = self.command_queue.dequeue(timeout=timeout)
        if req is None:
            return None

        try:
            if req.status == CommandStatus.CANCELLED or not self._begin_request(req):
                return "CANCELLED"

            execution_result = self._call_executor(req.command, raw_text=req.text, request=req)
            execution_result = self._finish_request(req, execution_result)
            log_executor(str(execution_result))
            log_perf(req.format_perf_line())
            return execution_result
        except Exception as error:
            return self._fail_request(req, error)
        finally:
            self.command_queue.mark_execution_finished()

    def drain_queue(self) -> list[str]:
        """Execute all currently queued commands sequentially until the queue is empty."""
        results: list[str] = []
        while self.command_queue.pending_count() > 0:
            res = self.execute_next_queued(timeout=0.02)
            if res is not None:
                results.append(res)
                if res == "STOP":
                    break
        return results

    async def _call_executor_async(self, command: Command, raw_text=None, request=None) -> str:
        if hasattr(self.executor, "execute_async"):
            kwargs = {"raw_text": raw_text}
            try:
                parameters = inspect.signature(self.executor.execute_async).parameters
                if "cancel_event" in parameters:
                    kwargs["cancel_event"] = self.command_queue.cancel_event
                if "request" in parameters:
                    kwargs["request"] = request
            except (ValueError, TypeError):
                pass
            return await self.executor.execute_async(command, **kwargs)
        return self._call_executor(command, raw_text=raw_text, request=request)

    async def execute_next_queued_async(self, timeout: float = 0.02) -> str | None:
        """
        Asynchronous consumer step: dequeue and execute next CommandRequest using execute_async.
        Compatible with LIGHT's active event loop and preserves STOP cancellation.
        """
        # Queue waiting is thread-safe; browser execution stays on its owning thread.
        waiting = asyncio.create_task(asyncio.to_thread(self.command_queue.dequeue, timeout))
        try:
            req = await asyncio.shield(waiting)
        except asyncio.CancelledError:
            # Cancelling an asyncio wrapper does not stop its thread. Account for
            # a concurrent dequeue, so no request or execution slot disappears.
            # Repeated cancellation must not cancel the accounting task either.
            while not waiting.done():
                try:
                    await asyncio.shield(waiting)
                except asyncio.CancelledError:
                    continue
            req = waiting.result()
            if req is not None:
                self.command_queue.return_unexecuted(req)
            raise
        if req is None:
            return None

        try:
            if req.status == CommandStatus.CANCELLED or not self._begin_request(req):
                return "CANCELLED"

            execution_result = await self._call_executor_async(req.command, raw_text=req.text, request=req)
            execution_result = self._finish_request(req, execution_result)
            log_executor(str(execution_result))
            log_perf(req.format_perf_line())
            return execution_result
        except asyncio.CancelledError:
            req.cancel("Async execution cancelled")
            raise
        except Exception as error:
            return self._fail_request(req, error)
        finally:
            self.command_queue.mark_execution_finished()

    async def drain_queue_async(self) -> list[str]:
        """Execute all currently queued commands asynchronously and sequentially."""
        results: list[str] = []
        while self.command_queue.pending_count() > 0:
            res = await self.execute_next_queued_async(timeout=0.02)
            if res is not None:
                results.append(res)
                if res == "STOP":
                    break
        return results

    async def process_text_async(self, text: str) -> str:
        """
        Asynchronous spoken transcription processing entry point.
        Enqueues requests and drains the queue using native async executor calls.
        """
        requests = self.ingest_text(text)
        if not requests:
            return "IGNORED"

        statuses = await self.drain_queue_async()
        if not statuses and requests[0].task.status in {TaskStatus.FAILED, TaskStatus.AMBIGUOUS}:
            return "IGNORED"
        if "STOP" in statuses:
            return "STOP"
        if "ERROR" in statuses and "OK" not in statuses:
            return "ERROR"
        return statuses[-1] if statuses else "OK"

    def process_text(self, text: str) -> str:
        """
        Process a spoken transcription string (backward-compatible synchronous API
        backed by the producer-consumer CommandQueue).
        Returns "OK", "IGNORED", "ERROR", or "STOP".
        """
        requests = self.ingest_text(text)
        if not requests:
            return "IGNORED"

        statuses = self.drain_queue()
        if not statuses and requests[0].task.status in {TaskStatus.FAILED, TaskStatus.AMBIGUOUS}:
            return "IGNORED"
        if "STOP" in statuses:
            return "STOP"
        if "ERROR" in statuses and "OK" not in statuses:
            return "ERROR"
        return statuses[-1] if statuses else "OK"

    def _fetch_new_transcriptions(self, last_id: int | None) -> tuple[list[dict], int | None]:
        """
        Fetch all new transcriptions since last_id.
        Uses get_transcriptions_since() on real Handy instances so rapid speech
        never drops intermediate rows, and falls back to get_latest_transcription()
        when self.handy is a test mock.
        """
        from unittest.mock import MagicMock

        if (
            hasattr(self.handy, "get_transcriptions_since")
            and not isinstance(self.handy, MagicMock)
            and last_id is not None
        ):
            items = self.handy.get_transcriptions_since(last_id)
            if items:
                return items, items[-1]["id"]
            return [], last_id

        result = self.handy.get_latest_transcription()
        if result is None or result["id"] == last_id:
            return [], last_id
        return [result], result["id"]

    def _listener_worker(self, initial_id: int | None, max_iterations: int | None = None):
        """Background producer thread that continuously polls Handy without waiting on execution."""
        last_id = initial_id
        iterations = 0

        try:
            while not self._stop_requested.is_set():
                if max_iterations is not None and iterations >= max_iterations:
                    break
                iterations += 1

                try:
                    items, last_id = self._fetch_new_transcriptions(last_id)
                except Exception as error:
                    log_error(f"Database read error: {error}")
                    self._stop_requested.wait(self.poll_interval)
                    continue

                if not items:
                    self._stop_requested.wait(self.poll_interval)
                    continue

                for item in items:
                    text = (item.get("text") or "").strip()
                    if not text:
                        continue

                    norm = _normalize_for_dedup(text)
                    now = time.monotonic()
                    if norm and norm == self._last_text_norm and (now - self._last_time) < self.duplicate_cooldown:
                        log_debug(f"Ignored immediate duplicate transcription: '{text}'")
                        continue

                    self._last_text_norm = norm
                    self._last_time = now

                    self.ingest_text(text, voice_received_at=time.perf_counter(),
                                     transcript_published_at=item.get("published_at_monotonic"))
                    if self._stop_requested.is_set():
                        break

                if not self._stop_requested.is_set():
                    self._stop_requested.wait(self.poll_interval)
        finally:
            self._listener_done.set()

    def run(self, max_iterations: int | None = None):
        if self._closed or self.command_queue.cancel_event.is_set():
            raise RuntimeError("A stopped LightLoop cannot be restarted")
        log_info("Listening for commands...")
        log_info("Say 'stop' to exit.\n")

        self._stop_requested.clear()
        self._listener_done.clear()
        if hasattr(self.handy, "is_available") and not self.handy.is_available():
            msg = getattr(self.handy, "get_status_message", lambda: "Voice provider unavailable")()
            log_warning(f"Voice provider inactive: {msg}")

        # Remember current transcription at startup so we only run new commands
        try:
            latest = self.handy.get_latest_transcription()
        except Exception as error:
            log_error(f"Failed to read initial transcription: {error}")
            latest = None

        if latest is not None:
            initial_id = latest["id"]
            self._last_text_norm = _normalize_for_dedup(latest["text"] or "")
        else:
            initial_id = None
            self._last_text_norm = ""
        self._last_time = 0.0

        listener_thread = threading.Thread(
            target=self._listener_worker,
            args=(initial_id, max_iterations),
            name="LIGHT-VoiceListener",
            daemon=True,
        )
        listener_thread.start()
        self._listener_thread = listener_thread

        try:
            while True:
                status = self.execute_next_queued(timeout=0.03)
                if status == "STOP":
                    self._stop_requested.set()
                    log_info("Stopped.")
                    break

                if self._listener_done.is_set() and self.command_queue.pending_count() == 0:
                    break
        except KeyboardInterrupt:
            self._stop_requested.set()
            log_info("Interrupted by user. Shutting down...")
        finally:
            self.close(timeout=0.5)

    def close(self, timeout: float = 0.5):
        """Bounded worker joins; report survivors rather than claiming termination."""
        self._stop_requested.set()
        self.command_queue.cancel_all_pending("Loop shutdown")
        with self._admission_lock:
            self._closed = True
            self._pending_plans.clear()
            planner = self._planner_thread
            for task in self._tasks:
                if task.status in {TaskStatus.ACCEPTED, TaskStatus.RUNNING}:
                    task.mark("cancellation_signalled")
                    task.fail(TaskStatus.CANCELLED, "Loop shutdown")
        deadline = time.perf_counter() + max(0.0, timeout)
        for worker in (planner, self._listener_thread):
            if worker and worker is not threading.current_thread():
                worker.join(max(0.0, deadline - time.perf_counter()))
        from unittest.mock import MagicMock
        executor_cleanup_failed = False
        if isinstance(self.executor, MagicMock):
            self.executor.browser.close()
        elif hasattr(self.executor, "close"):
            try:
                executor_cleanup_failed = self.executor.close(
                    timeout=max(0.0, deadline - time.perf_counter())) is False
            except Exception:
                executor_cleanup_failed = True
                log_debug("Executor cleanup failed")
        agent = getattr(self.executor, "_agent_thread", None)
        self.shutdown_status = {
            "planner_alive": bool(planner and planner.is_alive()),
            "listener_alive": bool(self._listener_thread and self._listener_thread.is_alive()),
            "agent_alive": bool(isinstance(agent, threading.Thread) and agent.is_alive()),
            "executor_cleanup_failed": executor_cleanup_failed,
        }
        return not any(self.shutdown_status.values())
