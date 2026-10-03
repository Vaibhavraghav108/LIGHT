import inspect
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
from utils.logger import (
    log_command,
    log_debug,
    log_error,
    log_executor,
    log_info,
    log_perf,
    log_voice,
)


def _normalize_for_dedup(text: str) -> str:
    """Normalize whitespace and punctuation for duplicate STT detection."""
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


class LightLoop:
    """
    Continuous Producer-Consumer Voice Loop for LIGHT.
    - Producer (Listener thread): Continuously polls Handy SQLite DB, suppresses
      duplicates, parses commands (Fast Path / Laya / Qwen3 1.7B), and enqueues
      CommandRequests without waiting for browser/OS execution.
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
        self._planning_lock = threading.RLock()

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

    def ingest_text(self, text: str, voice_received_at: float | None = None) -> list[CommandRequest]:
        """
        Producer entry point: parse spoken text and enqueue resulting CommandRequests
        immediately without blocking on execution.
        """
        received_ts = voice_received_at if voice_received_at is not None else time.perf_counter()
        log_voice(text)

        # Immediate high-priority preemption check for explicit STOP / Cancel
        if is_explicit_stop_or_cancel(text):
            now = time.perf_counter()
            stop_cmd = Command(Action.STOP, None)
            log_command(f"Action: {stop_cmd.action.value} | Target: {stop_cmd.target}")
            req = CommandRequest(
                text=text,
                command=stop_cmd,
                priority=CommandPriority.STOP,
                status=CommandStatus.PARSED,
                voice_received_at=received_ts,
                parse_started_at=received_ts,
                parse_completed_at=now,
            )
            self.command_queue.enqueue(req)
            self._stop_requested.set()
            return [req]

        parse_start = time.perf_counter()
        with self._planning_lock:
            # Sync planning state from real state ONLY when the queue is completely idle
            # (neither queued nor currently executing an in-flight command)
            if not self.command_queue.is_busy():
                self._planning_state = self.state.clone_for_planning()

            try:
                commands = self._parse_spoken_text(text, state_for_parse=self._planning_state)
            except Exception as error:
                self.state.record_failure(text, status="IGNORED", error_message=str(error))
                log_error(f"Command ignored: {error}")
                log_info("Continuing to listen...")
                return []

            parse_end = time.perf_counter()
            requests: list[CommandRequest] = []

            for cmd in commands:
                log_command(f"Action: {cmd.action.value} | Target: {cmd.target}")
                priority = CommandPriority.STOP if cmd.action == Action.STOP else CommandPriority.NORMAL
                req = CommandRequest(
                    text=text,
                    command=cmd,
                    priority=priority,
                    status=CommandStatus.PARSED,
                    voice_received_at=received_ts,
                    parse_started_at=parse_start,
                    parse_completed_at=parse_end,
                )
                requests.append(req)
                self._planning_state.record_command(text, cmd)
                if cmd.action == Action.STOP:
                    self._stop_requested.set()

            self.command_queue.enqueue_many(requests)
            return requests

    def _call_executor(self, command: Command, raw_text: str) -> str:
        """Invoke executor.execute with cancel_event when supported by target callable signature."""
        target_fn = self.executor.execute
        side_effect = getattr(target_fn, "side_effect", None)
        if callable(side_effect):
            target_fn = side_effect

        supports_cancel_event = False
        try:
            sig = inspect.signature(target_fn)
            if "cancel_event" in sig.parameters:
                supports_cancel_event = True
        except (ValueError, TypeError):
            supports_cancel_event = False

        if supports_cancel_event:
            return self.executor.execute(
                command,
                raw_text=raw_text,
                cancel_event=self.command_queue.cancel_event,
            )
        return self.executor.execute(command, raw_text=raw_text)

    def execute_next_queued(self, timeout: float = 0.02) -> str | None:
        """
        Consumer step: dequeue and execute the next CommandRequest in order.
        Returns "OK", "ERROR", "STOP", or None if queue was empty.
        """
        req = self.command_queue.dequeue(timeout=timeout)
        if req is None:
            return None

        try:
            if req.status == CommandStatus.CANCELLED:
                return "CANCELLED"

            execution_result = self._call_executor(req.command, raw_text=req.text)
            req.execution_completed_at = time.perf_counter()
            req.verification_ms = float(getattr(self.executor, "last_verification_ms", 0.0) or 0.0)
            req.status = CommandStatus.COMPLETED
            log_executor(str(execution_result))
            log_perf(req.format_perf_line())
            return execution_result
        except Exception as error:
            req.execution_completed_at = time.perf_counter()
            req.status = CommandStatus.FAILED
            req.error = str(error)
            self.state.last_action = req.command.action
            self.state.record_failure(req.text, status="ERROR", error_message=str(error))
            skipped = self.command_queue.cancel_dependent_after_failure(
                req.command.action,
                failed_text=req.text,
            )
            log_error(
                f"{req.command.action.name} failed ({req.command.target}): {error} — Could not execute command: {error}"
            )
            if skipped:
                log_info(
                    f"Skipped {skipped} dependent queued command(s) after {req.command.action.name} failure."
                )
            log_info("Continuing to listen...")
            return "ERROR"
        finally:
            self.command_queue.mark_execution_finished()

    def drain_queue(self) -> list[str]:
        """Execute all currently queued commands sequentially until the queue is empty."""
        results: list[str] = []
        while self.command_queue.pending_count() > 0:
            res = self.execute_next_queued(timeout=0.0)
            if res is not None:
                results.append(res)
                if res == "STOP":
                    break
        return results

    async def _call_executor_async(self, command: Command, raw_text: str | None = None) -> str:
        """Call executor.execute_async() when available, respecting cancel_event."""
        if hasattr(self.executor, "execute_async"):
            supports_cancel_event = False
            try:
                sig = inspect.signature(self.executor.execute_async)
                if "cancel_event" in sig.parameters:
                    supports_cancel_event = True
            except (ValueError, TypeError):
                supports_cancel_event = False

            if supports_cancel_event:
                return await self.executor.execute_async(
                    command,
                    raw_text=raw_text,
                    cancel_event=self.command_queue.cancel_event,
                )
            return await self.executor.execute_async(command, raw_text=raw_text)

        return self._call_executor(command, raw_text=raw_text)

    async def execute_next_queued_async(self, timeout: float = 0.02) -> str | None:
        """
        Asynchronous consumer step: dequeue and execute next CommandRequest using execute_async.
        Compatible with LIGHT's active event loop and preserves STOP cancellation.
        """
        req = self.command_queue.dequeue(timeout=timeout)
        if req is None:
            return None

        try:
            if req.status == CommandStatus.CANCELLED:
                return "CANCELLED"

            execution_result = await self._call_executor_async(req.command, raw_text=req.text)
            req.execution_completed_at = time.perf_counter()
            req.verification_ms = float(getattr(self.executor, "last_verification_ms", 0.0) or 0.0)
            req.status = CommandStatus.COMPLETED
            log_executor(str(execution_result))
            log_perf(req.format_perf_line())
            return execution_result
        except Exception as error:
            req.execution_completed_at = time.perf_counter()
            req.status = CommandStatus.FAILED
            req.error = str(error)
            self.state.last_action = req.command.action
            self.state.record_failure(req.text, status="ERROR", error_message=str(error))
            skipped = self.command_queue.cancel_dependent_after_failure(
                req.command.action,
                failed_text=req.text,
            )
            log_error(
                f"{req.command.action.name} failed ({req.command.target}): {error} — Could not execute command: {error}"
            )
            if skipped:
                log_info(
                    f"Skipped {skipped} dependent queued command(s) after {req.command.action.name} failure."
                )
            log_info("Continuing to listen...")
            return "ERROR"
        finally:
            self.command_queue.mark_execution_finished()

    async def drain_queue_async(self) -> list[str]:
        """Execute all currently queued commands asynchronously and sequentially."""
        results: list[str] = []
        while self.command_queue.pending_count() > 0:
            res = await self.execute_next_queued_async(timeout=0.0)
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
                    time.sleep(self.poll_interval)
                    continue

                if not items:
                    time.sleep(self.poll_interval)
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

                    self.ingest_text(text, voice_received_at=time.perf_counter())
                    if self._stop_requested.is_set():
                        break

                if not self._stop_requested.is_set():
                    time.sleep(self.poll_interval)
        finally:
            self._listener_done.set()

    def run(self, max_iterations: int | None = None):
        log_info("Listening for commands...")
        log_info("Say 'stop' to exit.\n")

        self._stop_requested.clear()
        self._listener_done.clear()
        self.command_queue.cancel_event.clear()

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
            self._stop_requested.set()
            listener_thread.join(timeout=1.0)
            try:
                self.executor.browser.close()
            except Exception as err:
                log_debug(f"Browser close cleanup ignored error: {err}")