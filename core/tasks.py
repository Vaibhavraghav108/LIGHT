"""Bounded, transcript-free task results and monotonic timing evidence."""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    VERIFIED = "verified"
    SUCCEEDED = "succeeded"  # executor success without independent verification
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    CANCELLED = "cancelled"


class AmbiguousPlanError(ValueError):
    """A planner cannot safely choose a unique interpretation; do not execute."""


@dataclass
class TaskRecord:
    id: int
    generation: int
    status: TaskStatus = TaskStatus.ACCEPTED
    reason: str | None = None
    timestamps: dict[str, float] = field(default_factory=dict)
    remaining_steps: int = 0
    _all_verified: bool = True
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def mark(self, name: str, timestamp: float | None = None):
        with self._lock:
            self.timestamps[name] = time.perf_counter() if timestamp is None else timestamp

    def running(self):
        with self._lock:
            if self.status == TaskStatus.ACCEPTED:
                self.status = TaskStatus.RUNNING

    def fail(self, status: TaskStatus, reason: str):
        with self._lock:
            if self.status not in {TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.AMBIGUOUS}:
                self.status = status
                self.reason = reason  # fixed diagnostic, never provider text

    def finish_step(self, verified: bool = False):
        with self._lock:
            self.remaining_steps = max(0, self.remaining_steps - 1)
            self._all_verified = self._all_verified and verified
            if self.remaining_steps == 0 and self.status in {TaskStatus.ACCEPTED, TaskStatus.RUNNING}:
                self.status = TaskStatus.VERIFIED if self._all_verified else TaskStatus.SUCCEEDED
                self.timestamps["task_finished"] = time.perf_counter()

    def snapshot(self) -> dict:
        with self._lock:
            return {"id": self.id, "generation": self.generation, "status": self.status.value,
                    "reason": self.reason, "timestamps": dict(self.timestamps),
                    "remaining_steps": self.remaining_steps,
                    "latency_ms": {name: self.duration_ms(start, end) for name, start, end in (
                        ("publication_to_ingestion", "transcript_published", "ingested"),
                        ("deterministic_routing", "routing_started", "routing_finished"),
                        ("planning_submission", "ingested", "planning_submitted"),
                        ("planning", "planning_started", "planning_finished"),
                        ("admission", "ingested", "admitted"),
                        ("queue_wait", "admitted", "execution_started"),
                        ("first_visible_effect", "ingested", "first_visible_effect"),
                        ("execution", "execution_started", "execution_finished"),
                        ("verification", "verification_started", "verification_finished"),
                        ("stop_signal", "ingested", "cancellation_signalled"),
                        ("planner_cancellation", "cancellation_signalled", "planner_terminated"),
                        ("agent_cancellation", "cancellation_signalled", "agent_terminated"))}}

    def duration_ms(self, start: str, end: str) -> float | None:
        with self._lock:
            if start not in self.timestamps or end not in self.timestamps:
                return None  # unavailable is not zero latency
            return max(0.0, (self.timestamps[end] - self.timestamps[start]) * 1000.0)
