"""Bounded pre-reservation FIFO/LIFO store, owned by a single broker lock.

There are no FG/native resources or transaction tombstones in this container.
Removal means leaving the pending queue, never releasing an engine reservation.
"""
from collections import OrderedDict
from dataclasses import dataclass, replace
from itertools import islice
from typing import Callable

from .config import QueueLimits, finite, integer


class CapacityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Entry:
    key: str
    sequence: int
    enqueued_ms: float
    cost: float | None
    tail: bool
    protected: bool = False


class DualQueueStore:
    def __init__(self, limits: QueueLimits, clock_ms: Callable[[], float]):
        self.limits = limits
        self.clock_ms = clock_ms
        self.normal: OrderedDict[str, Entry] = OrderedDict()
        self.tail: OrderedDict[str, Entry] = OrderedDict()
        self._cost_sum = 0.0
        self._cost_correction = 0.0
        self.sequence = 0
        self.promotions = 0
        self._last_ms = 0.0

    def _now(self) -> float:
        now = self.clock_ms()
        finite("clock_ms", now)
        if now < self._last_ms:
            raise ValueError("clock must be monotonic")
        self._last_ms = now
        return now

    def __len__(self) -> int:
        return len(self.normal) + len(self.tail)

    @property
    def tail_cost(self) -> float:
        return self._cost_sum + self._cost_correction

    def _adjust_tail_cost(self, delta: float) -> None:
        # Neumaier compensated summation retains small costs when a much larger
        # entry is later cancelled. This is numerical bookkeeping, not a policy
        # tolerance or a reason to admit work beyond the configured V limit.
        previous = self._cost_sum
        total = previous + delta
        if abs(previous) >= abs(delta):
            self._cost_correction += (previous - total) + delta
        else:
            self._cost_correction += (delta - total) + previous
        self._cost_sum = total

    def check_capacity(self, key: str) -> None:
        if not isinstance(key, str) or not key or len(key.encode("utf-8")) > self.limits.max_key_bytes:
            raise ValueError("invalid or oversized queue key")
        if key in self.normal or key in self.tail:
            raise ValueError("duplicate queue key; broker must resolve transaction retries")
        if len(self) >= self.limits.max_pending:
            raise CapacityError("pending capacity reached")

    def tail_allows(self, cost: float | None) -> bool:
        if cost is None:
            return False
        finite("cost", cost)
        return (cost > 0 and len(self.tail) < self.limits.max_tail_requests
                and self.tail_cost + cost <= self.limits.max_tail_cost)

    def add(self, key: str, cost: float | None, *, tail: bool, protected: bool = False) -> Entry:
        self.check_capacity(key)
        if type(tail) is not bool or type(protected) is not bool:
            raise ValueError("tail and protected must be booleans")
        if cost is not None:
            finite("cost", cost)
        if tail and (protected or not self.tail_allows(cost)):
            raise ValueError("tail classification violates protection or S/V budget")
        now = self._now()
        self.sequence += 1
        entry = Entry(key, self.sequence, now, cost, tail, protected)
        (self.tail if tail else self.normal)[key] = entry
        if tail:
            self._adjust_tail_cost(cost)
        return entry

    def remove(self, key: str) -> Entry | None:
        entry = self.normal.pop(key, None)
        if entry is not None:
            return entry
        entry = self.tail.pop(key, None)
        if entry is not None:
            self._adjust_tail_cost(-entry.cost)
            if not self.tail:
                self._cost_sum = self._cost_correction = 0.0
        return entry

    def promote(self, *, max_items: int, force: bool = False) -> tuple[str, ...]:
        """Promote oldest tail entries to the normal tail, in bounded batches.

        A fixed residence limit makes tail insertion order deadline order.
        Therefore no expiry heap, tombstones, or stale heap rebuild is needed.
        READY leases belong to the broker and are not represented here.
        """
        integer("max_items", max_items, minimum=1)
        now = self._now()
        promoted = []
        while self.tail and len(promoted) < max_items:
            entry = next(iter(self.tail.values()))
            if not force and now - entry.enqueued_ms < self.limits.max_tail_wait_ms:
                break
            self.remove(entry.key)
            self.normal[entry.key] = replace(entry, tail=False, protected=True)
            promoted.append(entry.key)
        self.promotions += len(promoted)
        return tuple(promoted)

    def candidates(self) -> tuple[Entry, ...]:
        """Normal head, else at most K newest tail entries.

        The broker may skip tail candidates only for resource ineligibility.
        Pressure denial must stop dispatch, not search for a cheaper request.
        Candidates are not removed until a confirmed transaction outcome.
        """
        if self.normal:
            return (next(iter(self.normal.values())),)
        return tuple(self.tail[k] for k in islice(reversed(self.tail), self.limits.scan_limit))

    def next_promotion_ms(self) -> float | None:
        if not self.tail:
            return None
        return next(iter(self.tail.values())).enqueued_ms + self.limits.max_tail_wait_ms
