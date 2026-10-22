import asyncio
from dataclasses import replace

import pytest

from gf_admission.broker import AdmissionBroker, State
from gf_admission.config import ClassifierConfig, QueueLimits
from gf_admission.runtime_config import RuntimeConfig
from motor_adapter.config import Config
from motor_adapter.service import FgjsqService


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


class Ledger:
    def __init__(self):
        self.loads = {1: 0.0, 2: 0.0}
        self.adds = []
        self.release_ok = True
        self.fail_first = False
        self.available = True

    def candidates(self, command):
        return [
            {
                "instance_id": i,
                "endpoint_id": 0,
                "generation": 1,
                "instance": {},
                "endpoint": {},
            }
            for i in self.loads
            if self.available and command.get("target_instance_id") in (None, i)
        ]

    def reserve(self, candidate, tokens):
        i = candidate["instance_id"]
        if self.fail_first and i == 1:
            return False
        self.loads[i] += tokens
        self.adds.append(i)
        return True

    def release(self, candidate, tokens):
        if self.release_ok:
            self.loads[candidate["instance_id"]] -= tokens
        return self.release_ok


def config(**changes):
    return replace(
        RuntimeConfig(
            2,
            "enforce",
            "test-cluster",
            "test-model",
            "synthetic tests",
            ClassifierConfig(1, 1, 0.8, 1.5, 10),
            QueueLimits(50, 20, 100000, 100, 3, 256),
            0.000001,
            10,
            20,
            500,
            40,
            1000,
            2000,
            100,
            4,
            10000,
            10,
            10,
            100,
            3,
            500,
            10,
            2,
            1,
            1,
            "unknown",
            10000,
        ),
        **changes,
    )


def stack(**changes):
    clock, ledger = Clock(), Ledger()
    service = FgjsqService(ledger, Config(), clock=lambda: clock.now / 1000)
    broker = AdmissionBroker(service, config(**changes), clock)
    service.on_events = broker.notify
    return broker, service, ledger, clock


def command(b, op, nonce="a", worker="worker1", attempt=1, **extra):
    return dict(
        op="admission_" + op,
        coordinator_epoch=b.service.epoch,
        config_digest=b.config.digest,
        worker_epoch=worker,
        logical_nonce=nonce,
        key=nonce + ":" + str(attempt),
        attempt_seq=attempt,
        **extra,
    )


async def enqueue(b, nonce, cost, **kw):
    return await b.handle(
        command(
            b,
            "enqueue",
            nonce,
            payload={
                "req_id": nonce,
                "estimated_tokens": 10,
                "native_tokens": 5.0,
                "cost": cost,
            },
            **kw,
        )
    )


async def seed_pressure(b, s):
    first = await enqueue(b, "seed", 1)
    b.notify((1, 2))
    # Both P ledgers loaded, so the tail cannot use an empty alternate P.
    s.policy.add_instance("2")
    s.policy.reserve("synthetic", "2", 10)
    return first


@pytest.mark.asyncio
async def test_fast_ack_loss_duplicate_fields_and_global_credit():
    b, _s, l, _c = stack()
    try:
        a = await enqueue(b, "a", None)
        assert a["state"] == "CLAIMED"
        assert (await enqueue(b, "a", None)) == a
        assert len(l.adds) == 1 and b.classifier.arrivals == 1
        with pytest.raises(ValueError, match="immutable"):
            await enqueue(b, "a", 2)
        with pytest.raises(ValueError, match="owner"):
            await enqueue(b, "a", None, worker="worker2")
        await enqueue(b, "b", None, worker="worker2")
        assert b.classifier.arrivals == 2
        await b.handle(command(b, "finish", "a"))
        await b.handle(command(b, "finish", "b", worker="worker2"))
        assert sum(l.loads.values()) == 0
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_ready_claim_expiry_does_not_release_claimed():
    b, s, l, c = stack()
    try:
        await seed_pressure(b, s)
        tail = await enqueue(b, "tail", 100)
        assert tail["state"] == "QUEUED" and len(l.adds) == 1
        s.policy.release("synthetic")
        await b.handle(command(b, "finish", "seed"))
        await b.step()
        ready = await b.handle(command(b, "query", "tail"))
        assert ready["state"] == "READY_RESERVED" and len(l.adds) == 2
        claim = command(
            b,
            "claim",
            "tail",
            lease_id=ready["lease_id"],
            expected_revision=ready["revision"],
        )
        result = await b.handle(claim)
        assert result["state"] == "CLAIMED"
        assert await b.handle(claim) == result
        c.now += 100
        await b.step()
        assert b.tickets["tail:1"].state is State.CLAIMED
        assert sum(l.loads.values()) == 5
        await b.handle(command(b, "finish", "tail"))
        assert sum(l.loads.values()) == 0
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_cancel_before_enqueue_and_ready_expire_cleanup_failure():
    b, s, l, c = stack()
    try:
        await b.handle(command(b, "cancel", "early"))
        assert (await enqueue(b, "early", 100))["state"] == "CANCELLED"
        assert b.classifier.arrivals == len(l.adds) == 0
        await seed_pressure(b, s)
        await enqueue(b, "tail", 100)
        s.policy.release("synthetic")
        await b.handle(command(b, "finish", "seed"))
        await b.step()
        ready = await b.handle(command(b, "query", "tail"))
        l.release_ok = False
        c.now += 41
        await b.step()
        assert b.tickets["tail:1"].state is State.CLEANUP
        result = await b.handle(
            command(
                b,
                "claim",
                "tail",
                lease_id=ready["lease_id"],
                expected_revision=ready["revision"],
            )
        )
        assert result["state"] == "CLEANUP_PENDING"
        l.release_ok = True
        await b.step()
        assert b.tickets["tail:1"].state is State.EXPIRED
        assert sum(l.loads.values()) == 0
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_guard_rechecks_after_native_cas_fallback_and_each_reservation():
    b, s, l, _c = stack()
    try:
        s.policy.add_instance("1")
        s.policy.reserve("busy", "2", 100)
        l.fail_first = True
        data = {
            "op": "reserve",
            "key": "direct",
            "attempt_seq": 1,
            "coordinator_epoch": s.epoch,
            "reserve_deadline": 10,
            "estimated_tokens": 10,
            "native_tokens": 5,
        }
        seen = []
        async with s.lock:
            ack = s._reserve(
                data,
                lambda candidate: (
                    seen.append(candidate["instance_id"]) is None
                    and s.policy.score(str(candidate["instance_id"])) <= 0
                ),
                retain_failures=True,
            )
        assert ack == {"deferred": True} and seen == [1, 2] and not l.adds
        l.fail_first = False
        s.policy.release("busy")
        async with s.lock:
            assert "reservation_id" in s._reserve(
                data,
                lambda candidate: s.policy.score(str(candidate["instance_id"])) <= 0,
            )
            ack = s._reserve(
                dict(data, key="second"),
                lambda candidate: s.policy.score(str(candidate["instance_id"])) <= 0,
            )
            assert ack["instance_id"] == 2
            assert s._reserve(
                dict(data, key="third"),
                lambda candidate: s.policy.score(str(candidate["instance_id"])) <= 0,
            ) == {"deferred": True}
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_wait_cancellation_does_not_cancel_ticket_and_old_epoch_refused():
    b, s, _l, _c = stack()
    try:
        await seed_pressure(b, s)
        await enqueue(b, "tail", 100)
        waiter = asyncio.create_task(
            b.handle(command(b, "wait", after_revision=b.workers["worker1"].revision))
        )
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert b.tickets["tail:1"].state is State.QUEUED
        assert not b.workers["worker1"].waiting
        wrong = command(b, "query", "tail")
        wrong["coordinator_epoch"] = "old"
        with pytest.raises(ValueError, match="epoch"):
            await b.handle(wrong)
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_partial_commit_is_retained_and_uncertain_cas_stops_dispatch(monkeypatch):
    b, s, l, _c = stack()

    def uncertain(*args):
        raise RuntimeError("native result lost")

    monkeypatch.setattr(l, "reserve", uncertain)
    try:
        reply = await enqueue(b, "uncertain", None)
        assert reply["state"] == "CLEANUP_PENDING"
        assert s.records[s.keys["uncertain:1"]].uncertain_native
        assert b.fault and len(s.records) == 1
        with pytest.raises(RuntimeError, match="faulted"):
            await enqueue(b, "new", None)
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_shadow_never_reserves_and_worker_lost_does_not_release_claimed():
    b, _s, l, _c = stack(mode="shadow")
    try:
        assert (await enqueue(b, "a", 10))["state"] == "CLOSED"
        assert not l.adds and len(b.queue) == 0
    finally:
        await b.close()
    b, _s, l, c = stack()
    try:
        await enqueue(b, "a", None)
        c.now += 501
        await b.step()
        assert b.tickets["a:1"].state is State.CLAIMED and sum(l.loads.values()) == 5
        assert (await b.snapshot())["claimed_worker_lost"] == 1
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_client_lost_enqueue_ack_idle_heartbeat_and_cancellation():
    from gf_admission.client import AdmissionClient

    b, s, l, _c = stack()
    # Use the monotonic production clock for the heartbeat exercise.
    import time

    b.clock = lambda: time.monotonic() * 1000
    b.queue.clock_ms = b.clock
    lost = True

    async def send(data):
        nonlocal lost
        if data["op"] == "hello":
            return {
                "admission_digest": b.config.digest,
                "admission_schema": 2,
                "admission_mode": "enforce",
                "coordinator_epoch": s.epoch,
            }
        reply = await b.handle(data)
        if data["op"] == "admission_enqueue" and lost:
            lost = False
            return None
        return reply

    client = AdmissionClient(send, b.config)
    try:
        result = await client.allocate(
            "a",
            1,
            {"req_id": "a", "estimated_tokens": 10, "native_tokens": 5, "cost": None},
        )
        assert result["state"] == "CLAIMED" and len(l.adds) == 1
        await client.finish("a")
        await asyncio.sleep(0.65)
        assert not b.workers[client.worker].dead
        result = await client.allocate(
            "b",
            1,
            {"req_id": "b", "estimated_tokens": 10, "native_tokens": 5, "cost": None},
        )
        assert result["state"] == "CLAIMED"
        await client.finish("b")
        assert sum(l.loads.values()) == 0
    finally:
        await client.close()
        await b.close()
    assert client.hub is None


@pytest.mark.asyncio
async def test_client_cancellation_after_commit_and_provider_capacity(monkeypatch):
    import threading
    from types import SimpleNamespace

    from gf_admission.client import AdmissionClient
    from gf_admission.provider import MotorFeatureProvider

    b, s, l, _c = stack(feature_kind="motor_conductor")

    async def send(data):
        if data["op"] == "hello":
            return {
                "admission_digest": b.config.digest,
                "admission_schema": 2,
                "admission_mode": "enforce",
                "coordinator_epoch": s.epoch,
            }
        reply = await b.handle(data)
        if data["op"] == "admission_enqueue":
            raise asyncio.CancelledError()
        return reply

    client = AdmissionClient(send, b.config)
    try:
        with pytest.raises(asyncio.CancelledError):
            await client.allocate(
                "cancel",
                1,
                {
                    "req_id": "cancel",
                    "estimated_tokens": 1,
                    "native_tokens": 5,
                    "cost": None,
                },
            )
        assert len(l.adds) == 1 and sum(l.loads.values()) == 0
        provider = MotorFeatureProvider(client)
        block = threading.Event()
        monkeypatch.setattr(
            provider, "_extract_sync", lambda *a: (block.wait(2), {"cost": 1})[1]
        )
        assert await provider.extract(SimpleNamespace(), {}) == {"cost": None}
        assert await provider.extract(SimpleNamespace(), {}) == {"cost": None}
        assert len(provider.futures) == 2  # Timeout cannot free a still-running slot.
        assert await provider.extract(SimpleNamespace(), {}) == {"cost": None}
        assert provider.metrics["capacity_unknown"] == 1
        block.set()
        await provider.close()
        assert not provider.futures
    finally:
        await client.close()
        await b.close()


@pytest.mark.asyncio
async def test_attempt_budget_capacity_drain_and_generation_change():
    b, _s, l, _c = stack(feature_kind="motor_conductor")
    try:
        await enqueue(b, "first", None)
        b.notify((1, 2))
        result = await enqueue(b, "stale", 100)  # no eligible generation snapshot
        assert result["state"] == "CLAIMED" and not b.queue.tail
        assert b.metrics["feature_generation_changed"] == 1
        await b.handle(command(b, "cancel", "stale"))
        before = b.classifier.arrivals
        await enqueue(b, "stale", None, attempt=2)
        assert b.classifier.arrivals == before
        await b.drain()
        assert b.draining
        await b.handle(command(b, "finish", "first"))
        await b.handle(command(b, "finish", "stale"))
        assert sum(l.loads.values()) == 0
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_claim_cancel_race_has_one_release_and_record_backpressure():
    from gf_admission.queue import CapacityError

    b, s, l, c = stack(max_records=50)
    try:
        await seed_pressure(b, s)
        await enqueue(b, "tail", 100)
        s.policy.release("synthetic")
        await b.handle(command(b, "finish", "seed"))
        await b.step()
        ready = await b.handle(command(b, "query", "tail"))
        await asyncio.gather(
            b.handle(
                command(
                    b,
                    "claim",
                    "tail",
                    lease_id=ready["lease_id"],
                    expected_revision=ready["revision"],
                )
            ),
            b.handle(command(b, "cancel", "tail")),
        )
        assert sum(l.loads.values()) == 0
        assert b.tickets["tail:1"].state is State.CANCELLED
        for i in range(48):
            await b.handle(command(b, "cancel", "never" + str(i)))
        with pytest.raises(CapacityError):
            await enqueue(b, "full", None)
        assert len(b.tickets) == 50 and not b.queue.normal and not b.queue.tail
        c.now += 2501
        await b.step()
        assert not b.tickets
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_fg_commit_failure_retains_native_until_release_confirmed(monkeypatch):
    b, s, l, _c = stack()
    original = s.policy.reserve

    def partial(rid, instance, tokens):
        original(rid, instance, tokens)
        raise RuntimeError("FG commit callback failed")

    monkeypatch.setattr(s.policy, "reserve", partial)
    l.release_ok = False
    try:
        result = await enqueue(b, "partial", None)
        assert result["state"] == "CLEANUP_PENDING" and sum(l.loads.values()) == 5
        l.release_ok = True
        await b.step()
        assert b.tickets["partial:1"].state is State.CANCELLED
        snapshot = await s.snapshot()
        assert snapshot["open_fg"] == snapshot["open_native"] == 0
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_confirmed_unavailable_resubmits_without_reclassification():
    from gf_admission.client import AdmissionClient

    b, s, ledger, _clock = stack()

    async def send(data):
        if data["op"] == "hello":
            return {
                "admission_digest": b.config.digest,
                "admission_schema": 2,
                "admission_mode": "enforce",
                "coordinator_epoch": s.epoch,
            }
        return await b.handle(data)

    client = AdmissionClient(send, b.config)
    payload = {
        "req_id": "retry",
        "estimated_tokens": 10,
        "native_tokens": 5,
        "cost": None,
    }
    try:
        ledger.available = False
        assert await client.allocate("retry", 1, payload) is None
        ledger.available = True
        reply = await client.allocate("retry", 1, dict(payload, estimated_tokens=20))
        assert reply["state"] == "CLAIMED" and reply["key"] == "retry:1:s1"
        assert reply["ack"]["attempt_seq"] == 1 and len(ledger.adds) == 1
        assert b.classifier.arrivals == 1 and b.metrics["submissions"] == 2
        assert (await b.handle(command(b, "query", "retry", worker=client.worker)))[
            "state"
        ] == "UNAVAILABLE"
        foreign = command(b, "cancel", "retry", worker="foreign")
        foreign.update(key="retry:1:s9", submission_round=9)
        with pytest.raises(ValueError, match="owner"):
            await b.handle(foreign)
        assert sum(ledger.loads.values()) == 5
        # A late cancellation of round zero cannot leave round one executing.
        await b.handle(command(b, "cancel", "retry", worker=client.worker))
        assert sum(ledger.loads.values()) == 0
        next_round = command(
            b, "enqueue", "retry", worker=client.worker, payload=payload
        )
        next_round.update(submission_round=2, key="retry:1:s2")
        with pytest.raises(ValueError, match="UNAVAILABLE"):
            await b.handle(next_round)
    finally:
        await client.finish("retry")
        await client.close()
        await b.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup", ["query", "cancel", "finish", "reconcile"])
async def test_expired_owner_cleanup_without_reviving_lease(cleanup):
    b, s, ledger, clock = stack()
    try:
        await enqueue(b, "stale", None)
        clock.now += b.config.worker_lease_ms + 1
        await b.step()
        assert b.tickets["stale:1"].state is State.CLAIMED
        await s.command({"op": "abort", "key": "stale:1", "coordinator_epoch": s.epoch})
        if cleanup == "reconcile":
            await b.step()
        else:
            await b.handle(command(b, cleanup, "stale"))
            if cleanup == "query":
                await b.handle(command(b, "finish", "stale"))
        assert b.workers["worker1"].dead
        assert (await b.snapshot())["residual_total"] == 0
        assert sum(ledger.loads.values()) == 0
        with pytest.raises(ValueError, match="lease expired"):
            await enqueue(b, "new", None)
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_metadata_rpc_obeys_total_feature_deadline_and_capacity():
    import time
    from types import SimpleNamespace

    from gf_admission.provider import MotorFeatureProvider

    active = peak = 0

    async def rpc(data):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(1)
            return {"candidates": []}
        finally:
            active -= 1

    provider = MotorFeatureProvider(
        SimpleNamespace(
            config=config(feature_kind="motor_conductor", feature_timeout_ms=20),
            rpc=rpc,
            data=lambda *args, **kw: kw,
        )
    )
    start = time.monotonic()
    try:
        results = await asyncio.gather(*(provider.extract(None, {}) for _ in range(8)))
        assert all(x == {"cost": None} for x in results)
        assert time.monotonic() - start < 0.5 and peak == 2 and active == 0
        assert provider.inflight == 0 and provider.metrics["capacity_unknown"] == 6
        task = asyncio.create_task(provider.extract(None, {}))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert provider.inflight == 0
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_residual_sample_filters_before_limit_and_reports_truncation():
    b, _s, _ledger, _clock = stack(changes_batch=2)
    try:
        for i in range(3):
            await enqueue(b, "closed" + str(i), None)
            await b.handle(command(b, "finish", "closed" + str(i)))
        for i in range(3):
            await enqueue(b, "live" + str(i), None)
        snap = await b.snapshot()
        assert snap["residual_total"] == 3 and snap["residual_truncated"]
        assert len(snap["residual_sample"]) == 2
        assert all(t["key"].startswith("live") for t in snap["residual_sample"])
        for i in range(3):
            await b.handle(command(b, "finish", "live" + str(i)))
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_homogeneous_pressure_trigger_candidate_scope_lifo_and_age():
    b, s, _ledger, clock = stack(
        high_pressure_threshold=10, release_threshold=1, changes_batch=50
    )
    try:
        await seed_pressure(b, s)
        # Same cost as the first sample; classification no longer requires heterogeneity.
        a = await enqueue(b, "older", 1)
        z = await enqueue(b, "newer", 1)
        assert a["state"] == z["state"] == "QUEUED"
        assert b.metrics["decision_pressure"] == 2
        s.policy.release("synthetic")
        # The newly idle alternate P defeats a pool-wide max-pressure trigger.
        low = await enqueue(b, "low", 1)
        assert low["state"] == "CLAIMED"
        await b.handle(command(b, "finish", "low"))
        await b.step()
        assert b.tickets["newer:1"].state is State.READY
        assert b.tickets["older:1"].state is State.QUEUED
        assert b.metrics["lifo_overtake_dispatches"] == 1
        clock.now += b.config.limits.max_tail_wait_ms
        await b.step()
        assert b.metrics["promoted_age"] == 1
        assert b.metrics["dispatch_protected"] == 1
        for nonce in ("older", "newer", "seed"):
            await b.handle(command(b, "finish", nonce))
    finally:
        await b.close()
