"""Mgmt-owned admission transactions. All resource changes share the FG lock."""

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum

from .classifier import Classifier, Decision
from .config import finite, integer
from .pressure import Pressure, ScoreThreshold
from .queue import CapacityError, DualQueueStore
from .runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)


class State(str, Enum):
    QUEUED = "QUEUED"
    READY = "READY_RESERVED"
    CLAIMED = "CLAIMED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNAVAILABLE = "UNAVAILABLE"
    CLEANUP = "CLEANUP_PENDING"
    CLOSED = "CLOSED"


TERMINAL = {State.CANCELLED, State.EXPIRED, State.UNAVAILABLE, State.CLOSED}


@dataclass(slots=True)
class Ticket:
    key: str
    nonce: str
    worker: str
    fingerprint: str
    payload: dict
    expires: float
    attempt_seq: int = 1
    submission_round: int = 0
    state: State = State.QUEUED
    revision: int = 0
    command: dict | None = None
    ack: dict | None = None
    lease: str | None = None
    ready_until: float = 0
    closed_at: float | None = None
    cleanup_attempts: int = 0
    target_terminal: State = State.CANCELLED
    error: str | None = None


@dataclass(slots=True)
class Worker:
    seen: float
    keys: set[str] = field(default_factory=set)
    revision: int = 0
    event: asyncio.Event = field(default_factory=asyncio.Event)
    waiting: bool = False
    dead: bool = False


@dataclass(slots=True)
class Logical:
    worker: str
    decision: Decision
    protected: bool = False
    finished_at: float | None = None


class AdmissionBroker:
    def __init__(self, service, config: RuntimeConfig, clock_ms=None):
        self.service, self.config = service, config
        self.clock = clock_ms or (lambda: time.monotonic() * 1000)
        self.lock = service.lock
        self.queue = DualQueueStore(config.limits, self.clock)
        self.classifier = Classifier(config.classifier)
        self.gate = ScoreThreshold(config.release_threshold)
        self.tickets: dict[str, Ticket] = {}
        self.workers: dict[str, Worker] = {}
        self.logicals: dict[str, Logical] = {}
        self.metrics = Counter()
        self.last_event: dict[str, float] = {}
        self.events = deque(maxlen=config.changes_batch)
        self.event_sequence = 0
        self.checked_score = None
        self.revision = 0
        self.draining = False
        self.closed = False
        self.fault: str | None = None
        self.wake = asyncio.Event()
        self.task = None
        self.loop = None

    def _start(self):
        loop = asyncio.get_running_loop()
        if self.loop is not None and self.loop is not loop:
            raise RuntimeError("admission broker loop ownership changed")
        self.loop = loop
        if self.closed or self.fault:
            raise RuntimeError("admission broker closed or faulted: " + str(self.fault))
        if self.task is None:
            self.task = loop.create_task(self._run(), name="gf-admission-pump")

    def notify(self, accepted_instances=()):
        for instance in accepted_instances:
            key = str(instance)
            self.last_event.pop(key, None)
            if len(self.last_event) >= self.config.max_records:
                self.last_event.pop(next(iter(self.last_event)))
            self.last_event[key] = self.clock()
        self.wake.set()

    def _change(self, ticket, state=None):
        if state is not None:
            ticket.state = state
        self.revision += 1
        ticket.revision = self.revision
        if ticket.state in TERMINAL:
            ticket.closed_at = self.clock()
        worker = self.workers[ticket.worker]
        worker.revision = self.revision
        worker.event.set()
        self._event(
            "state", key=ticket.key, state=ticket.state.value, error=ticket.error
        )

    def _event(self, event, **fields):
        # Bounded diagnostics, consumed through authenticated snapshot polling.
        # No logger/file I/O while the shared reservation lock is held.
        self.event_sequence += 1
        if len(self.events) == self.events.maxlen:
            self.metrics["event_ring_overwritten"] += 1
        self.events.append(
            dict(
                sequence=self.event_sequence,
                monotonic_ms=self.clock(),
                event=event,
                **fields,
            )
        )

    def _reply(self, ticket):
        return {
            "key": ticket.key,
            "ticket_id": ticket.key,
            "state": ticket.state.value,
            "revision": ticket.revision,
            "lease_id": ticket.lease,
            "reserve_command": ticket.command,
            "ack": ticket.ack,
            "error": ticket.error,
        }

    def _worker(self, name, *, cleanup=False):
        if not isinstance(name, str) or not 1 <= len(name) <= 128:
            raise ValueError("invalid worker_epoch")
        worker = self.workers.get(name)
        now = self.clock()
        if worker is None:
            if len(self.workers) >= self.config.max_workers:
                raise CapacityError("worker capacity reached")
            worker = self.workers[name] = Worker(now)
        elif worker.dead or now - worker.seen > self.config.worker_lease_ms:
            worker.dead = True
            if cleanup:
                return worker  # owner/epoch checks still apply; no lease renewal
            raise ValueError("worker lease expired; old tickets must not be replayed")
        worker.seen = now
        return worker

    def _validate(self, data):
        if (
            len(json.dumps(data, allow_nan=False).encode())
            > self.config.max_payload_bytes
        ):
            raise ValueError("admission payload too large")
        if (
            data.get("coordinator_epoch") != self.service.epoch
            or data.get("config_digest") != self.config.digest
        ):
            raise ValueError("admission epoch/config mismatch")

    def _identity(self, data):
        nonce, attempt = data.get("logical_nonce"), data.get("attempt_seq")
        if not isinstance(nonce, str) or not 1 <= len(nonce) <= 128:
            raise ValueError("invalid logical nonce")
        integer("attempt_seq", attempt, minimum=1)
        round_id = data.get("submission_round", 0)
        integer("submission_round", round_id)
        key = nonce + ":" + str(attempt)
        if round_id:
            key += ":s" + str(round_id)
        if data.get("key") != key:
            raise ValueError("key does not match logical attempt identity")
        return nonce, key

    def _pressure_valid(self):
        now = self.clock()
        # Empty FG accounting is usable before the first batch event. Active
        # requests without a fresh accepted event cannot justify new sacrifice.
        return all(
            now - self.last_event.get(str(r.candidate["instance_id"]), -float("inf"))
            <= self.config.event_fresh_ms
            for r in self.service.records.values()
            if not r.fg_released
        )

    def _minimum_pressure(self, payload):
        candidates = self.service.backend.candidates(payload)
        ranked = self.service.policy.rank([str(c["instance_id"]) for c in candidates])
        if not ranked or not self._pressure_valid():
            return None
        return self.service.policy.score(ranked[0])

    def _guard(self, candidate):
        if not self._pressure_valid():
            return False
        instance = str(candidate["instance_id"])
        self.checked_score = self.service.policy.score(instance)
        return self.gate.allows(Pressure(self.checked_score, True, "fg_ledger"))

    def _enqueue(self, data):
        nonce, key = self._identity(data)
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("payload required")
        allowed = {
            "req_id",
            "estimated_tokens",
            "native_tokens",
            "target_instance_id",
            "required_engine_type",
            "required_dispatch_capability",
            "cost",
            "candidate_generations",
        }
        if set(payload) - allowed:
            raise ValueError("unexpected enqueue fields")
        integer("estimated_tokens", payload.get("estimated_tokens"), minimum=1)
        finite("native_tokens", payload.get("native_tokens"))
        cost = payload.get("cost")
        if cost is not None:
            finite("cost", cost)
            if self.config.feature_kind == "motor_conductor":
                expected = [
                    [c["instance_id"], c["endpoint_id"], c["generation"]]
                    for c in self.service.backend.candidates(payload)
                ]
                if not expected or payload.get("candidate_generations") != expected:
                    cost = None
                    self.metrics["feature_generation_changed"] += 1
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()
        old = self.tickets.get(key)
        if old is not None:
            if old.worker != data["worker_epoch"] or (
                old.fingerprint and old.fingerprint != fingerprint
            ):
                raise ValueError("ticket owner or immutable fields changed")
            self.metrics["duplicate_enqueue"] += 1
            return self._reply(old)
        if (
            len(self.tickets) >= self.config.max_records
            or len(self.logicals) >= self.config.max_records
        ):
            raise CapacityError("admission transaction capacity reached")
        round_id = data.get("submission_round", 0)
        if round_id:
            previous_key = nonce + ":" + str(data["attempt_seq"])
            if round_id > 1:
                previous_key += ":s" + str(round_id - 1)
            previous = self.tickets.get(previous_key)
            if (
                previous is None
                or previous.worker != data["worker_epoch"]
                or previous.state is not State.UNAVAILABLE
                or previous.key in self.service.keys
            ):
                raise ValueError(
                    "new submission requires confirmed UNAVAILABLE without reservation"
                )
        self.queue.check_capacity(key)
        logical = self.logicals.get(nonce)
        if logical is None:
            pressure = self._minimum_pressure(payload)
            decision = self.classifier.decide(
                cost,
                budget_allows=self.queue.tail_allows(cost),
                pressure_valid=self._pressure_valid(),
                protected=self.draining,
                high_pressure=pressure is not None
                and pressure >= self.config.high_pressure_threshold,
            )
            logical = self.logicals[nonce] = Logical(data["worker_epoch"], decision)
            self.metrics["decision_" + decision.reason.value] += 1
            self._event(
                "classification",
                key=key,
                reason=decision.reason.value,
                cost=cost,
                minimum_score=pressure,
            )
        elif logical.worker != data["worker_epoch"] or logical.finished_at is not None:
            raise ValueError("logical request finished or owner changed")
        # A true new attempt cannot overlap a live reservation or queued attempt.
        if any(
            t.nonce == nonce and t.state not in TERMINAL for t in self.tickets.values()
        ):
            raise ValueError("logical request already has a live attempt")
        self.metrics["submissions"] += 1
        tail = (
            logical.decision.tail
            and not logical.protected
            and not self.draining
            and self._pressure_valid()
            and self.queue.tail_allows(cost)
        )
        ticket = Ticket(
            key,
            nonce,
            data["worker_epoch"],
            fingerprint,
            dict(payload),
            self.clock() + self.config.request_wait_ms,
        )
        ticket.attempt_seq = data["attempt_seq"]
        ticket.submission_round = round_id
        self.tickets[key] = ticket
        self.workers[ticket.worker].keys.add(key)
        self.queue.add(key, cost, tail=tail, protected=logical.protected)
        self._change(ticket)
        self.metrics["tail_enqueued" if tail else "normal_enqueued"] += 1
        if self.config.mode == "shadow":
            # Shadow observes classification only: it cannot reserve or delay
            # the real g5 request, and must not accumulate a virtual waiting queue.
            self.queue.remove(key)
            self._change(ticket, State.CLOSED)
        else:
            self._pump_locked(fast_key=key)
        self.wake.set()
        return self._reply(ticket)

    def _cleanup(self, ticket, terminal):
        self.queue.remove(ticket.key)
        ticket.target_terminal = terminal
        if ticket.key not in self.service.keys:
            self._change(ticket, terminal)
            return
        ticket.cleanup_attempts += 1
        try:
            result = self.service._command_locked(
                {
                    "op": "abort",
                    "key": ticket.key,
                    "coordinator_epoch": self.service.epoch,
                }
            )
            if not result.get("ok"):
                ticket.error = result.get("reason", "release_unconfirmed")
                self._change(ticket, State.CLEANUP)
                return
        except Exception as error:  # noqa: BLE001 - transaction/task fault boundary
            ticket.error = type(error).__name__
            self._change(ticket, State.CLEANUP)
            return
        ticket.error = None
        self._change(ticket, terminal)

    def _maintenance_locked(self):
        now = self.clock()
        for name, worker in list(self.workers.items()):
            if now - worker.seen > self.config.worker_lease_ms:
                worker.dead = True
                worker.event.set()
        for key, ticket in list(self.tickets.items()):
            if ticket.state is State.CLAIMED and self.workers[ticket.worker].dead:
                record = self.service.records.get(self.service.keys.get(key))
                if (
                    record is not None
                    and not record.uncertain_native
                    and record.native_released
                    and record.fg_released
                ):
                    self._change(ticket, State.CLOSED)
                    self.metrics["reconciled_released_claim"] += 1
                    self._event(
                        "reconciled", key=key, evidence="native_and_fg_released"
                    )
            if (
                ticket.state is State.QUEUED
                and (now >= ticket.expires or self.workers[ticket.worker].dead)
                or ticket.state is State.READY
                and (now >= ticket.ready_until or self.workers[ticket.worker].dead)
            ):
                self._cleanup(ticket, State.EXPIRED)
            elif (
                ticket.state is State.CLEANUP
                and ticket.cleanup_attempts < self.config.cleanup_retries
            ):
                self._cleanup(ticket, ticket.target_terminal)
            elif (
                ticket.closed_at is not None
                and now - ticket.closed_at >= self.config.tombstone_ms
            ):
                self.workers[ticket.worker].keys.discard(key)
                del self.tickets[key]
        live_nonces = {t.nonce for t in self.tickets.values()}
        for nonce, logical in list(self.logicals.items()):
            if logical.finished_at is None and nonce not in live_nonces:
                logical.finished_at = now
            if (
                logical.finished_at is not None
                and now - logical.finished_at >= self.config.tombstone_ms
            ):
                del self.logicals[nonce]
        for name, worker in list(self.workers.items()):
            if worker.dead and not worker.keys and not worker.waiting:
                del self.workers[name]

    def _pump_locked(self, fast_key=None):
        if self.config.mode != "enforce" or self.closed or self.fault:
            return
        promotion_reason = (
            "drain"
            if self.draining
            else ("stale" if not self._pressure_valid() else "age")
        )
        for key in self.queue.promote(
            max_items=self.config.pump_items,
            force=promotion_reason != "age",
        ):
            self.logicals[self.tickets[key].nonce].protected = True
            self.metrics["promoted"] += 1
            self.metrics["promoted_" + promotion_reason] += 1
            self._event("promotion", key=key, reason=promotion_reason)
        started = time.perf_counter()
        count = 0
        while (
            count < self.config.pump_items
            and (time.perf_counter() - started) * 1000 < self.config.pump_ms
        ):
            candidates = self.queue.candidates()
            if not candidates:
                break
            progressed = False
            for entry in candidates:
                ticket = self.tickets[entry.key]
                command = {
                    k: v
                    for k, v in ticket.payload.items()
                    if k not in ("cost", "candidate_generations")
                }
                command.update(
                    op="reserve",
                    key=ticket.key,
                    attempt_seq=ticket.attempt_seq,
                    coordinator_epoch=self.service.epoch,
                    reserve_deadline=self.service.clock()
                    + self.service.config.reserve_window_s,
                )
                try:
                    self.service._prune()
                    # Observe BEFORE CAS: diagnostics must never interrupt a
                    # successful reservation before its ticket records ownership.
                    older = 0
                    if entry.tail:
                        for older_entry in self.queue.tail.values():
                            older_ticket = self.tickets[older_entry.key]
                            if (
                                older_entry.sequence >= entry.sequence
                                or self.clock() >= older_ticket.expires
                                or self.workers[older_ticket.worker].dead
                            ):
                                continue
                            pressure = self._minimum_pressure(older_ticket.payload)
                            if (
                                pressure is not None
                                and pressure <= self.config.release_threshold
                            ):
                                older += 1
                    self.checked_score = None
                    ack = self.service._reserve(
                        command,
                        self._guard if entry.tail else None,
                        retain_failures=True,
                    )
                except Exception as error:  # noqa: BLE001 - transaction/task fault boundary
                    ticket.command = command
                    ticket.error = type(error).__name__
                    self._cleanup(ticket, State.CANCELLED)
                    # Stop new dispatch after a partial commit/unknown native outcome.
                    if ticket.state is State.CLEANUP:
                        self.fault = "reservation_cleanup_requires_reconciliation"
                    progressed = True
                    break
                if ack.get("deferred"):
                    self.metrics["pressure_deferred"] += 1
                    return
                if ack.get("unavailable"):
                    if entry.tail:
                        continue  # Only native resource ineligibility permits K-scan.
                    self.queue.remove(ticket.key)
                    self._change(ticket, State.UNAVAILABLE)
                else:
                    ticket.command, ticket.ack = command, ack
                    if older:
                        self.metrics["lifo_overtake_dispatches"] += 1
                    source = (
                        "tail"
                        if entry.tail
                        else ("protected" if entry.protected else "normal")
                    )
                    self.metrics["dispatch_" + source] += 1
                    instance = str(ack["instance_id"])
                    self._event(
                        "dispatch",
                        key=ticket.key,
                        source=source,
                        older_eligible=older,
                        instance_id=instance,
                        score_checked=self.checked_score,
                        score_after=self.service.policy.score(instance),
                        wait_ms=self.clock() - entry.enqueued_ms,
                    )
                    self.queue.remove(ticket.key)
                    ticket.command, ticket.ack = command, ack
                    if ticket.key == fast_key and not entry.tail:
                        self._change(ticket, State.CLAIMED)
                    else:
                        ticket.lease = uuid.uuid4().hex
                        ticket.ready_until = min(
                            ticket.expires, self.clock() + self.config.ready_lease_ms
                        )
                        self._change(ticket, State.READY)
                    self.metrics["reserved"] += 1
                progressed = True
                break
            if not progressed or self.fault:
                break
            count += 1

    def _changes(self, worker, after):
        changes = sorted(
            (self.tickets[k] for k in worker.keys if self.tickets[k].revision > after),
            key=lambda t: t.revision,
        )[: self.config.changes_batch]
        revision = changes[-1].revision if changes else worker.revision
        return {"revision": revision, "changes": [self._reply(t) for t in changes]}

    async def handle(self, data):
        self._validate(data)
        # Query and cancellation remain available after a pump fault.
        if data.get("op") not in (
            "admission_cancel",
            "admission_query",
            "admission_finish",
        ):
            self._start()
        worker_name = data.get("worker_epoch")
        async with self.lock:
            op = data.get("op")
            worker = self._worker(
                worker_name,
                cleanup=op
                in ("admission_query", "admission_cancel", "admission_finish"),
            )
            if op == "admission_enqueue":
                return self._enqueue(data)
            if op == "admission_features":
                constraints = data.get("constraints", {})
                if set(constraints) - {
                    "target_instance_id",
                    "required_engine_type",
                    "required_dispatch_capability",
                }:
                    raise ValueError("unexpected feature constraints")
                candidates = self.service.backend.candidates(constraints)
                if len(candidates) > 16:
                    raise ValueError(
                        "admission v1 feature snapshot supports at most 16 P endpoints"
                    )
                return {
                    "candidates": [
                        {
                            k: c[k]
                            for k in (
                                "instance_id",
                                "endpoint_id",
                                "generation",
                                "instance",
                            )
                        }
                        for c in candidates
                    ]
                }
            if op == "admission_wait":
                after = data.get("after_revision", 0)
                integer("after_revision", after)
                if worker.waiting:
                    raise ValueError("one wait RPC per worker")
                result = self._changes(worker, after)
                if result["changes"]:
                    return result
                worker.event.clear()
                worker.waiting = True
            elif op == "admission_finish":
                nonce = data["logical_nonce"]
                logical = self.logicals.get(nonce)
                if logical is not None:
                    if logical.worker != worker_name:
                        raise ValueError("logical owner mismatch")
                    for ticket in list(self.tickets.values()):
                        if ticket.nonce == nonce and ticket.state not in TERMINAL:
                            self._cleanup(ticket, State.CLOSED)
                    logical.finished_at = self.clock()
                self.wake.set()
                return {"ok": True}
            else:
                key = data.get("key")
                ticket = self.tickets.get(key)
                if ticket is not None and ticket.worker != worker_name:
                    raise ValueError("ticket owner mismatch")
                if op == "admission_query":
                    return (
                        self._reply(ticket)
                        if ticket
                        else {"state": "NOT_FOUND", "key": key}
                    )
                if op == "admission_cancel":
                    if ticket is None:
                        nonce, key = self._identity(data)
                        logical = self.logicals.get(nonce)
                        if (
                            logical is not None and logical.worker != worker_name
                        ) or any(
                            t.nonce == nonce and t.worker != worker_name
                            for t in self.tickets.values()
                        ):
                            raise ValueError("logical owner mismatch")
                        if len(self.tickets) >= self.config.max_records:
                            raise CapacityError(
                                "cancellation tombstone capacity reached"
                            )
                        ticket = Ticket(
                            key,
                            nonce,
                            worker_name,
                            "",
                            {},
                            self.clock(),
                            attempt_seq=data["attempt_seq"],
                            submission_round=data.get("submission_round", 0),
                        )
                        self.tickets[key] = ticket
                        worker.keys.add(key)
                    # A delayed cancellation also covers later confirmed-no-reserve
                    # submission rounds of this Motor attempt.
                    for related in self.tickets.values():
                        if (
                            related.nonce == ticket.nonce
                            and related.attempt_seq == ticket.attempt_seq
                            and (
                                related.state not in TERMINAL
                                or related.state is State.UNAVAILABLE
                            )
                        ):
                            self._cleanup(related, State.CANCELLED)
                    self.wake.set()
                    return self._reply(ticket)
                if op == "admission_claim":
                    if ticket is None:
                        raise ValueError("unknown ticket")
                    if data.get("lease_id") != ticket.lease or ticket.lease is None:
                        raise ValueError("claim lease mismatch")
                    if ticket.state is State.READY:
                        if self.clock() >= ticket.ready_until:
                            self._cleanup(ticket, State.EXPIRED)
                        elif data.get("expected_revision") != ticket.revision:
                            raise ValueError("claim revision mismatch")
                        else:
                            self._change(ticket, State.CLAIMED)
                    return self._reply(ticket)
                raise ValueError("unknown admission operation")
        try:
            try:
                await asyncio.wait_for(worker.event.wait(), self.config.wait_ms / 1000)
            except asyncio.TimeoutError:
                pass
            async with self.lock:
                return self._changes(worker, after)
        finally:
            worker.waiting = False

    async def step(self):
        """Deterministic test entry; production uses the same bounded pump."""
        async with self.lock:
            self._maintenance_locked()
            self._pump_locked()

    async def _run(self):
        try:
            while not self.closed:
                self.wake.clear()
                await self.step()
                now = self.clock()
                deadlines = [
                    w.seen + self.config.worker_lease_ms
                    for w in self.workers.values()
                    if not w.dead
                ]
                deadlines += [
                    t.closed_at + self.config.tombstone_ms
                    for t in self.tickets.values()
                    if t.closed_at is not None
                ]
                deadlines += [
                    v.finished_at + self.config.tombstone_ms
                    for v in self.logicals.values()
                    if v.finished_at is not None
                ]
                deadlines += [
                    t.ready_until
                    for t in self.tickets.values()
                    if t.state is State.READY
                ]
                if len(self.queue) or any(
                    t.state is State.CLEANUP
                    and t.cleanup_attempts < self.config.cleanup_retries
                    for t in self.tickets.values()
                ):
                    deadlines.append(now + self.config.tick_ms)
                timeout = (
                    max(0.001, (min(deadlines) - now) / 1000) if deadlines else None
                )
                try:
                    await asyncio.wait_for(self.wake.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - transaction/task fault boundary
            self.fault = type(error).__name__
            for worker in self.workers.values():
                worker.event.set()

    async def snapshot(self):
        async with self.lock:
            residual = [
                t
                for t in self.tickets.values()
                if t.state in (State.CLAIMED, State.CLEANUP)
            ]
            policy = self.service.policy.snapshot()
            now = self.clock()
            return {
                "schema_version": 2,
                "monotonic_ms": now,
                "wall_time_s": time.time(),
                "pressure": {
                    i: dict(
                        values,
                        event_age_ms=(now - self.last_event[i])
                        if i in self.last_event
                        else None,
                    )
                    for i, values in policy.items()
                },
                "events": list(self.events),
                "event_sequence": self.event_sequence,
                "residual_total": len(residual),
                "residual_truncated": len(residual) > self.config.changes_batch,
                "mode": self.config.mode,
                "config_digest": self.config.digest,
                "residual_sample": [
                    {
                        "key": t.key,
                        "state": t.state.value,
                        "error": t.error,
                        "reservation_id": self.service.keys.get(t.key),
                    }
                    for t in residual[: self.config.changes_batch]
                ],
                "states": dict(Counter(t.state.value for t in self.tickets.values())),
                "normal": len(self.queue.normal),
                "tail": len(self.queue.tail),
                "tail_cost": self.queue.tail_cost,
                "credit": self.classifier.credit,
                "logical_arrivals": self.classifier.arrivals,
                "workers": len(self.workers),
                "metrics": dict(self.metrics),
                "fault": self.fault,
                "draining": self.draining,
                "claimed_worker_lost": sum(
                    t.state is State.CLAIMED and self.workers[t.worker].dead
                    for t in self.tickets.values()
                ),
            }

    async def drain(self):
        async with self.lock:
            self.draining = True
            self.wake.set()
        return await self.snapshot()

    async def close(self):
        self.closed = True
        self.wake.set()
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        async with self.lock:
            for ticket in self.tickets.values():
                if ticket.state in (State.QUEUED, State.READY, State.CLEANUP):
                    self._cleanup(ticket, State.CANCELLED)
            for worker in self.workers.values():
                worker.event.set()
        # CLAIMED remains the existing Motor owner; shutdown must drain clients
        # before tearing down SHM. Never infer completion from a READY timer.
        return await self.snapshot()
