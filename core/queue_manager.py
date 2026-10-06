import collections
import itertools
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from brain.commands import Action, Command
from core.tasks import TaskRecord, TaskStatus

if TYPE_CHECKING:
    from core.capabilities import CapabilityPlan


class CommandStatus(Enum):
    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PLANNING = "PLANNING"


class CommandPriority:
    STOP = 0
    NORMAL = 10


_ID_COUNTER = itertools.count(1)


@dataclass
class CommandRequest:
    text: str
    command: Command | None  # None reserves FIFO position during interpretation
    id: int = field(default_factory=lambda: next(_ID_COUNTER))
    created_at: float = field(default_factory=time.perf_counter)
    priority: int = CommandPriority.NORMAL
    status: CommandStatus = CommandStatus.RECEIVED
    error: str | None = None
    task: TaskRecord | None = None
    generation: int = 0
    ready: threading.Event = field(default_factory=threading.Event, repr=False)
    capability_plan: "CapabilityPlan | None" = None

    # Latency instrumentation timestamps (perf_counter seconds)
    voice_received_at: float = field(default_factory=time.perf_counter)
    parse_started_at: float = 0.0
    parse_completed_at: float = 0.0
    queue_inserted_at: float = 0.0
    execution_started_at: float = 0.0
    execution_completed_at: float = 0.0
    verification_started_at: float = 0.0
    verification_completed_at: float = 0.0
    verification_ms: float = 0.0

    def __post_init__(self):
        if self.command is not None:
            self.ready.set()

    def cancel(self, reason: str):
        self.status = CommandStatus.CANCELLED
        self.error = reason
        if self.task:
            self.task.fail(TaskStatus.CANCELLED, reason)
        self.ready.set()

    def format_perf_line(self) -> str:
        """Return a concise single-line [PERF] summary in milliseconds."""
        v_to_p = max(0.0, (self.parse_completed_at - self.voice_received_at) * 1000.0) if self.parse_completed_at else 0.0
        p_to_q = max(0.0, (self.queue_inserted_at - self.parse_completed_at) * 1000.0) if self.queue_inserted_at and self.parse_completed_at else 0.0
        q_wait = max(0.0, (self.execution_started_at - self.queue_inserted_at) * 1000.0) if self.execution_started_at and self.queue_inserted_at else 0.0
        exec_ms = max(0.0, (self.execution_completed_at - self.execution_started_at) * 1000.0) if self.execution_completed_at and self.execution_started_at else 0.0
        return (
            f"voice_to_parse={v_to_p:.1f}ms "
            f"parse_to_queue={p_to_q:.1f}ms "
            f"queue_wait={q_wait:.1f}ms "
            f"execution={exec_ms:.1f}ms "
            f"verification={self.verification_ms:.1f}ms"
        )


class CommandQueue:
    """
    Thread-safe ordered command queue with immediate priority preemption for STOP/Cancel.
    Normal commands execute in strict FIFO order.
    STOP commands cancel pending queued work, signal cancel_event, and jump to the front.
    """

    def __init__(self):
        self._lock = threading.Condition()
        self._deque: collections.deque[CommandRequest] = collections.deque()
        self._history: collections.deque[CommandRequest] = collections.deque(maxlen=512)
        self._executing_count: int = 0
        self.cancel_event = threading.Event()
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def is_current(self, request: CommandRequest) -> bool:
        with self._lock:
            return request.generation == self._generation and not self.cancel_event.is_set()

    def enqueue(self, request: CommandRequest) -> CommandRequest:
        self.enqueue_many([request])
        return request

    def enqueue_many(self, requests: list[CommandRequest]) -> list[CommandRequest]:
        with self._lock:
            now = time.perf_counter()
            for req in requests:
                is_stop = req.priority == CommandPriority.STOP or (
                    req.command is not None and req.command.action == Action.STOP)
                if not is_stop and not self.is_current(req):
                    req.cancel("Invalidated by cancellation")
                    continue
                req.queue_inserted_at = now
                req.status = CommandStatus.QUEUED if req.command is not None else CommandStatus.PLANNING
                if req.task and req.command is not None:
                    req.task.mark("admitted", now)
                self._history.append(req)
                if is_stop:
                    req.priority = CommandPriority.STOP
                    self._generation += 1
                    self._cancel_pending_locked(reason="Preempted by STOP command")
                    self.cancel_event.set()
                    self._deque.appendleft(req)
                else:
                    self._deque.append(req)
            self._lock.notify_all()
            return requests

    def resolve(self, reservation: CommandRequest, commands: list[Command]) -> list[CommandRequest]:
        """Atomically replace a pending plan at its original FIFO position."""
        with self._lock:
            if not self.is_current(reservation) or reservation not in self._deque:
                reservation.cancel("Stale planner result discarded")
                return []
            if not commands or any(not isinstance(cmd, Command) for cmd in commands):
                raise ValueError("Planner must return a non-empty validated command list")
            requests = [reservation]
            reservation.command = commands[0]
            reservation.parse_completed_at = time.perf_counter()
            reservation.queue_inserted_at = reservation.parse_completed_at
            if reservation.task:
                reservation.task.mark("admitted", reservation.queue_inserted_at)
            reservation.status = CommandStatus.QUEUED
            reservation.ready.set()
            for command in commands[1:]:
                req = CommandRequest(text=reservation.text, command=command,
                                     task=reservation.task, generation=reservation.generation,
                                     voice_received_at=reservation.voice_received_at,
                                     parse_started_at=reservation.parse_started_at,
                                     parse_completed_at=reservation.parse_completed_at,
                                     queue_inserted_at=reservation.queue_inserted_at,
                                     status=CommandStatus.QUEUED)
                requests.append(req)
                self._history.append(req)
            position = list(self._deque).index(reservation)
            items = list(self._deque)
            items[position:position + 1] = requests
            self._deque = collections.deque(items)
            self._lock.notify_all()
            return requests

    def discard(self, reservation: CommandRequest):
        with self._lock:
            if reservation in self._deque:
                self._deque.remove(reservation)
            reservation.ready.set()
            self._lock.notify_all()

    def _cancel_pending_locked(self, reason: str = "Cancelled") -> int:
        cancelled_count = 0
        while self._deque:
            pending = self._deque.popleft()
            pending.cancel(reason)
            cancelled_count += 1
        return cancelled_count

    def cancel_all_pending(self, reason: str = "Cancelled by user") -> int:
        with self._lock:
            self.cancel_event.set()
            self._generation += 1
            count = self._cancel_pending_locked(reason=reason)
            self._lock.notify_all()
            return count

    def cancel_dependent_after_failure(
        self,
        failed_action: Action,
        failed_text: str | None = None,
        task_id: int | None = None,
    ) -> int:
        """
        When a prerequisite action (OPEN_URL or SEARCH) fails, cancel dependent
        downstream commands (e.g. CLICK_RESULT after a failed SEARCH) so they
        never execute against an unready or failed page.
        """
        dependent_actions: set[Action] = set()
        if failed_action == Action.SEARCH:
            dependent_actions = {Action.CLICK_RESULT}
        elif failed_action == Action.OPEN_URL:
            dependent_actions = {Action.SEARCH, Action.CLICK_RESULT}

        if not dependent_actions:
            return 0

        cancelled = 0
        with self._lock:
            remaining = collections.deque()
            for req in self._deque:
                same_plan = ((req.task is not None and req.task.id == task_id) if task_id is not None
                             else (failed_text is None) or (req.text == failed_text))
                if req.command is not None and req.command.action in dependent_actions and same_plan:
                    req.cancel(f"Skipped because prerequisite {failed_action.name} failed")
                    req.execution_completed_at = time.perf_counter()
                    cancelled += 1
                else:
                    remaining.append(req)
            self._deque = remaining
            if cancelled:
                self._lock.notify_all()
        return cancelled

    def dequeue(self, timeout: float = 0.05) -> CommandRequest | None:
        with self._lock:
            deadline = time.perf_counter() + timeout
            while not self._deque or self._deque[0].command is None:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return None
                self._lock.wait(timeout=remaining)
            req = self._deque.popleft()
            req.status = CommandStatus.EXECUTING
            req.execution_started_at = time.perf_counter()
            self._executing_count += 1
            return req

    def mark_execution_finished(self):
        with self._lock:
            self._executing_count = max(0, self._executing_count - 1)
            self._lock.notify_all()

    def return_unexecuted(self, request: CommandRequest):
        """Restore a dequeue whose async caller was cancelled before dispatch."""
        with self._lock:
            self._executing_count = max(0, self._executing_count - 1)
            if self.is_current(request) or request.command.action == Action.STOP:
                request.status = CommandStatus.QUEUED
                request.execution_started_at = 0.0
                self._deque.appendleft(request)
            else:
                request.cancel("Cancelled before dispatch")
            self._lock.notify_all()

    def is_busy(self) -> bool:
        """Return True if any command is either queued or currently executing."""
        with self._lock:
            return len(self._deque) > 0 or self._executing_count > 0

    def pending_count(self) -> int:
        with self._lock:
            return len(self._deque)

    def get_history(self) -> list[CommandRequest]:
        with self._lock:
            return list(self._history)
