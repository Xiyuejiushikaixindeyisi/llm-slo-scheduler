"""Mgmt-owned, attempt-idempotent reservations with independent P release flags."""
from collections import Counter
from dataclasses import dataclass
import asyncio
import math
import time
import uuid

from fgjsq.policy import FineGrainedPolicy, Progress
from motor_adapter.config import Config


@dataclass
class Record:
    key: str
    reservation_id: str
    candidate: dict
    native_tokens: float
    request: dict
    native_released: bool = False
    fg_released: bool = False
    closed_at: float | None = None
    engine_epoch: str | None = None
    batch_seq: int = -1


class FgjsqService:
    def __init__(self, backend, config: Config, lock=None, clock=None):
        self.backend = backend
        self.config = config
        self.lock = lock or asyncio.Lock()
        self.clock = clock or time.time
        self.epoch = uuid.uuid4().hex
        self.policy = FineGrainedPolicy(config.max_num_seqs, config.retention, lambda: int(self.clock() * 1000))
        self.records: dict[str, Record] = {}
        self.keys: dict[str, str] = {}
        self.metrics = Counter()
        self.cancelled: dict[str, float] = {}

    def _prune(self) -> None:
        self.cancelled = {key: expiry for key, expiry in self.cancelled.items() if expiry > self.clock()}
        for rid, r in list(self.records.items()):
            if r.closed_at is not None and self.clock() - r.closed_at > self.config.tombstone_s:
                del self.records[rid]
                self.keys.pop(r.key, None)

    def _ack(self, r: Record) -> dict:
        return {"schema_version": 1, "coordinator_epoch": self.epoch, "reservation_id": r.reservation_id,
                "key": r.key, "attempt_seq": r.request["attempt_seq"],
                "instance_id": r.candidate["instance_id"], "endpoint_id": r.candidate["endpoint_id"],
                "generation": r.candidate["generation"], "native_tokens": r.native_tokens,
                "native_released": r.native_released, "fg_released": r.fg_released,
                "instance": r.candidate["instance"], "endpoint": r.candidate["endpoint"],
                "event_url": self.config.event_url}

    async def command(self, data: dict) -> dict:
        async with self.lock:
            self._prune()
            op = data.get("op")
            if op == "hello":
                return {"schema_version": 1, "coordinator_epoch": self.epoch}
            if data.get("coordinator_epoch") != self.epoch:
                raise ValueError("coordinator epoch changed; drain/reconcile before retry")
            if op == "reserve":
                return self._reserve(data)
            rid = data.get("reservation_id") or self.keys.get(data.get("key"))
            r = self.records.get(rid)
            if op == "query":
                return {"found": r is not None, "record": self._ack(r) if r else None}
            if r is None:
                if op == "abort" and data.get("key"):
                    self.cancelled[data["key"]] = self.clock() + self.config.tombstone_s
                    return {"ok": True, "reason": "cancelled_before_reserve"}
                # Never subtract native tokens from a caller-supplied delta.
                return {"ok": False, "reason": "unknown_reservation"}
            if op not in ("release_native", "release_fg", "abort"):
                raise ValueError("unknown operation")
            if op in ("release_native", "abort") and not r.native_released:
                if not self.backend.release(r.candidate, r.native_tokens):
                    return {"ok": False, "reason": "native_release_unconfirmed"}
                r.native_released = True
            if op in ("release_fg", "abort") and not r.fg_released:
                self.policy.release(r.reservation_id)
                r.fg_released = True
            if r.native_released and r.fg_released and r.closed_at is None:
                r.closed_at = self.clock()
            self.metrics[op] += 1
            return {"ok": True, "record": self._ack(r)}

    def _reserve(self, data: dict) -> dict:
        key = data["key"]
        if key in self.cancelled:
            raise ValueError("attempt cancelled before reserve")
        if key in self.keys:
            r = self.records[self.keys[key]]
            if r.request != data:
                raise ValueError("idempotency key reused with different reserve parameters")
            return self._ack(r)
        deadline = float(data["reserve_deadline"])
        if not math.isfinite(deadline) or not self.clock() <= deadline <= self.clock() + self.config.reserve_window_s + 1:
            raise ValueError("expired/invalid reserve deadline")
        tokens = data["estimated_tokens"]
        native = float(data["native_tokens"])
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 1:
            raise ValueError("invalid estimated tokens")
        if not math.isfinite(native) or native < 0:
            raise ValueError("invalid native tokens")
        if len(self.records) >= self.config.max_records:
            raise RuntimeError("reservation capacity reached; drain or wait for tombstones")
        candidates = self.backend.candidates(data)
        by_instance = {str(c["instance_id"]): c for c in candidates}
        if len(by_instance) != len(candidates):
            raise ValueError("FGJSQ v1 requires one endpoint per P instance")
        for instance in self.policy.rank(list(by_instance)):
            c = by_instance[instance]
            if not self.backend.reserve(c, native):
                continue
            rid = uuid.uuid4().hex
            r = Record(key, rid, c, native, dict(data))
            try:
                self.policy.reserve(rid, instance, tokens)
                self.records[rid] = r
                self.keys[key] = rid
            except BaseException:
                self.policy.release(rid)
                self.records.pop(rid, None)
                self.keys.pop(key, None)
                self.backend.release(c, native)
                raise
            self.metrics["reserved"] += 1
            return self._ack(r)
        return {"unavailable": True}

    async def events(self, payload: dict) -> dict:
        async with self.lock:
            if payload.get("schema_version") != 1:
                raise ValueError("unsupported event schema")
            counts = Counter()
            for item in payload.get("requests", []):
                counts["received"] += 1
                r = self.records.get(item.get("reservation_id"))
                if r is None or r.fg_released:
                    counts["unknown_or_released"] += 1
                    continue
                if (item.get("coordinator_epoch") != self.epoch or
                        item.get("instance_id") != r.candidate["instance_id"] or
                        item.get("endpoint_id") != r.candidate["endpoint_id"] or
                        item.get("generation") != r.candidate["generation"] or
                        item.get("attempt_seq") != r.request["attempt_seq"]):
                    counts["wrong_identity"] += 1
                    continue
                seq, epoch = payload.get("batch_seq"), payload.get("engine_epoch")
                if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0 or not isinstance(epoch, str) or not epoch:
                    counts["invalid"] += 1
                    continue
                if r.engine_epoch is not None and r.engine_epoch != epoch:
                    counts["wrong_engine_epoch"] += 1
                    continue
                if seq <= r.batch_seq:
                    counts["stale"] += 1
                    continue
                try:
                    values = [item[k] for k in ("num_prompt_tokens", "num_scheduled_tokens", "num_remaining_tokens")]
                    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
                        raise ValueError("invalid token counts")
                    predicted = float(item["predicted_exec_ms"])
                    if values[0] <= 0 or not math.isfinite(predicted) or predicted < 0:
                        raise ValueError("invalid prediction")
                    p = Progress(*values, predicted)
                except (KeyError, TypeError, ValueError):
                    counts["invalid"] += 1
                    continue
                self.policy.event(r.reservation_id, p)
                r.engine_epoch, r.batch_seq = epoch, seq
                counts["matched"] += 1
            self.metrics.update(counts)
            return dict(counts)

    async def snapshot(self) -> dict:
        async with self.lock:
            active = [r for r in self.records.values() if r.closed_at is None]
            return {"schema_version": 1, "coordinator_epoch": self.epoch,
                    "policy": self.policy.snapshot(), "metrics": dict(self.metrics),
                    "open_native": sum(not r.native_released for r in active),
                    "open_fg": sum(not r.fg_released for r in active),
                    "records": len(self.records), "tombstones": len(self.records) - len(active)}
