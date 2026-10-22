"""Deterministic G4 formulas; no routing transport or engine dependencies."""
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class Progress:
    prompt: int
    scheduled: int
    remaining: int
    predicted_ms: float


@dataclass
class Reservation:
    instance: str
    original: int
    committed: int
    received_ms: int = 0
    progress: Progress | None = None


class FineGrainedPolicy:
    def __init__(self, max_seqs: int = 24, retention: float = 0.05, clock=None):
        if max_seqs <= 0 or not 0 <= retention < 1:
            raise ValueError("invalid FGJSQ parameters")
        self.max_seqs = max_seqs
        self.retention = retention
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.requests: dict[str, Reservation] = {}
        self.loads: dict[str, list[int]] = {}
        self.limits: dict[str, int] = {}

    def add_instance(self, instance: str, max_seqs: int | None = None) -> None:
        self.loads.setdefault(instance, [0, 0])
        self.limits[instance] = max_seqs or self.max_seqs

    def actual(self, request: Reservation, now_ms: int) -> int:
        p = request.progress
        if p is None or p.prompt <= 0:
            return request.original
        waiting = request.original * p.remaining / p.prompt
        running = request.original * p.scheduled / p.prompt
        elapsed = now_ms - request.received_ms
        progress = min(elapsed / p.predicted_ms, 1 - self.retention) if p.predicted_ms > 0 and elapsed > 0 else 0
        return int(round(waiting + running * (1 - progress)))

    def recompute(self) -> None:
        now = self.clock()
        for request in self.requests.values():
            if request.progress is not None:
                value = self.actual(request, now)
                self.loads[request.instance][1] += value - request.committed
                request.committed = value

    def score(self, instance: str) -> float:
        count, load = self.loads[instance]
        return float(load) * (math.ceil(count / self.limits[instance]) + 1) / 2

    def rank(self, eligible: list[str]) -> list[str]:
        for instance in eligible:
            self.add_instance(instance, self.limits.get(instance))
        self.recompute()
        allowed = set(eligible)
        return sorted((i for i in self.loads if i in allowed), key=self.score)

    def reserve(self, key: str, instance: str, estimated_tokens: int) -> None:
        if key in self.requests:
            raise ValueError("duplicate reservation")
        self.add_instance(instance, self.limits.get(instance))
        self.loads[instance][0] += 1
        self.loads[instance][1] += estimated_tokens
        self.requests[key] = Reservation(instance, estimated_tokens, estimated_tokens)

    def event(self, key: str, progress: Progress) -> None:
        request = self.requests[key]
        if request.progress is None and progress.prompt > 0 and progress.prompt != request.original:
            delta = progress.prompt - request.original
            self.loads[request.instance][1] += delta
            request.original = progress.prompt
            request.committed += delta
        request.progress = progress
        request.received_ms = self.clock()

    def release(self, key: str) -> bool:
        request = self.requests.pop(key, None)
        if request is None:
            return False
        self.loads[request.instance][0] -= 1
        self.loads[request.instance][1] -= request.committed
        return True

    def snapshot(self) -> dict:
        self.recompute()
        return {i: {"requests": n, "committed_tokens": w, "score": self.score(i),
                    "max_num_seqs": self.limits[i]} for i, (n, w) in self.loads.items()}
