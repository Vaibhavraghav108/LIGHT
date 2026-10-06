"""In-memory inference metrics. No prompts, transcripts, URLs, or credentials."""

import collections
import threading
import time
from contextlib import contextmanager


class InferenceMetrics:
    def __init__(self, limit: int = 256):
        self._samples = collections.deque(maxlen=limit)
        self._counts = collections.Counter()
        self._lock = threading.Lock()

    @contextmanager
    def measure(self, stage: str):
        start = time.perf_counter()
        outcome = {"value": "failed"}
        try:
            yield outcome
        finally:
            with self._lock:
                self._counts[(stage, outcome["value"])] += 1
                self._samples.append({"stage": stage, "outcome": outcome["value"],
                                      "latency_ms": (time.perf_counter() - start) * 1000.0})

    def snapshot(self) -> dict:
        with self._lock:
            return {"counts": {f"{stage}:{outcome}": count
                               for (stage, outcome), count in self._counts.items()},
                    "samples": list(self._samples)}
