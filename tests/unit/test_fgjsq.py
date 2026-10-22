"""Behavior checks against the supplied G4 implementation and lifecycle contracts."""
import ast
import asyncio
import json
import logging
import math
from pathlib import Path
import random
from types import SimpleNamespace

import pytest

from fgjsq.policy import FineGrainedPolicy, Progress
from fgjsq.snapshot import freeze_snapshot
from motor_adapter.config import Config
from motor_adapter.service import FgjsqService

ROOT = Path(__file__).resolve().parents[2]


def test_original_policy_matches_random_deterministic_trace():
    source = ROOT / "tests/fixtures/g4_fgjsq_reference.py"
    tree = ast.parse(source.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in ("FgRequestInfo", "FineGrainedTokenJSQ")]
    now = [1000]
    scope = {"math": math, "_now_ms": lambda: now[0], "logger": logging.getLogger("oracle")}
    module = ast.Module(body=ast.parse("from __future__ import annotations").body + nodes, type_ignores=[])
    exec(compile(module, str(source), "exec"), scope)
    old = scope["FineGrainedTokenJSQ"](24, "P", log_every=0)
    new = FineGrainedPolicy(clock=lambda: now[0])
    for name in ("P0", "P1", "P2"):
        old.add_instance(name)
        new.add_instance(name)
    rng = random.Random(20261019)
    for i in range(200):
        rid = str(i)
        size = rng.randint(1, 100000)
        picked = new.rank(["P0", "P1", "P2"])[0]
        assert old.dispatch(rid, size) == picked
        new.reserve(rid, picked, size)
        q = rng.randint(1, size)
        event = dict(request_id=rid, num_prompt_tokens=size + 300, num_scheduled_tokens=q,
                     num_remaining_tokens=size + 300 - q, predicted_exec_ms=50)
        old.on_batch_event(picked, i + 1, [event])
        new.event(rid, Progress(size + 300, q, size + 300 - q, 50))
        now[0] += rng.randint(0, 100)
        old.recompute_and_commit(now[0])
        new.recompute()
        assert new.loads == old.inst_loads
        if i % 2:
            assert new.release(str(i - 1)) == old.reduce_load(str(i - 1))
            assert new.release(str(i - 1)) == old.reduce_load(str(i - 1))
    for rid in list(new.requests):
        new.release(rid)
        old.reduce_load(rid)
    assert new.loads == old.inst_loads == {"P0": [0, 0], "P1": [0, 0], "P2": [0, 0]}


def test_snapshot_preserves_progress_and_identity_after_request_mutation():
    meta = dict(schema_version=1, reservation_id="r", coordinator_epoch="c", attempt_seq=1,
                instance_id=1, endpoint_id=0, generation=1, event_url="http://example.invalid/fgjsq/v1/events")
    req = SimpleNamespace(kv_transfer_params={"fgjsq": meta}, num_prompt_tokens=1000,
                          num_tokens=1000, num_computed_tokens=400)
    output = SimpleNamespace(num_scheduled_tokens={"chatcmpl-r-randomxx": 200}, predicted_batch_exec_time=100)
    snap = freeze_snapshot(output, {"chatcmpl-r-randomxx": req}, "engine", 5)
    req.num_computed_tokens = 800
    meta["reservation_id"] = "corrupted"
    value = json.loads(snap.payloads[0][1])["requests"][0]
    assert (value["num_computed_tokens"], value["num_remaining_tokens"]) == (200, 600)
    assert value["reservation_id"] == "r"


class MemoryLedger:
    def __init__(self):
        self.loads = {1: 0.0, 2: 0.0, 3: 0.0}
        self.reserves = 0
        self.releases = 0

    def candidates(self, data):
        return [dict(instance_id=i, endpoint_id=0, generation=1, instance={}, endpoint={}) for i in self.loads]

    def reserve(self, candidate, tokens):
        self.loads[candidate["instance_id"]] += tokens
        self.reserves += 1
        return True

    def release(self, candidate, tokens):
        self.loads[candidate["instance_id"]] -= tokens
        self.releases += 1
        return True


def make_command(service, key):
    return dict(op="reserve", coordinator_epoch=service.epoch, key=key, attempt_seq=1,
                reserve_deadline=1020, estimated_tokens=1000, native_tokens=500.0)


@pytest.mark.asyncio
async def test_shared_reservation_ack_loss_and_independent_release():
    ledger = MemoryLedger()
    service = FgjsqService(ledger, Config(), clock=lambda: 1000)
    commands = [make_command(service, str(i)) for i in range(60)]
    acks = await asyncio.gather(*(service.command(x) for x in commands))
    assert ledger.reserves == 60
    assert [a["instance_id"] for a in acks[:3]] == [1, 2, 3]
    duplicate = await service.command(commands[0])
    assert duplicate["reservation_id"] == acks[0]["reservation_id"]
    assert ledger.reserves == 60
    for ack in acks:
        data = dict(coordinator_epoch=service.epoch, reservation_id=ack["reservation_id"])
        await service.command(dict(data, op="release_native"))
        await service.command(dict(data, op="release_native"))
    assert ledger.releases == 60 and sum(ledger.loads.values()) == 0
    assert (await service.snapshot())["open_fg"] == 60
    for ack in acks:
        await service.command(dict(op="release_fg", coordinator_epoch=service.epoch,
                                   reservation_id=ack["reservation_id"]))
    result = await service.snapshot()
    assert result["open_native"] == result["open_fg"] == 0


@pytest.mark.asyncio
async def test_cancel_before_reserve_and_old_epoch_cannot_create_load():
    ledger = MemoryLedger()
    service = FgjsqService(ledger, Config(), clock=lambda: 1000)
    await service.command(dict(op="abort", key="cancel", coordinator_epoch=service.epoch))
    with pytest.raises(ValueError, match="cancelled"):
        await service.command(make_command(service, "cancel"))
    command = make_command(service, "old")
    command["coordinator_epoch"] = "old-process"
    with pytest.raises(ValueError, match="epoch"):
        await service.command(command)
    assert ledger.reserves == 0


@pytest.mark.asyncio
async def test_events_reject_reordering_wrong_identity_and_late_delivery():
    service = FgjsqService(MemoryLedger(), Config(), clock=lambda: 1000)
    ack = await service.command(make_command(service, "event"))
    item = {k: ack[k] for k in ("reservation_id", "coordinator_epoch", "attempt_seq",
                                "instance_id", "endpoint_id", "generation")}
    item.update(num_prompt_tokens=2000, num_scheduled_tokens=200, num_remaining_tokens=1800, predicted_exec_ms=100)
    payload = dict(schema_version=1, engine_epoch="engine", batch_seq=3, requests=[item])
    assert (await service.events(payload))["matched"] == 1
    assert (await service.events(payload))["stale"] == 1
    assert (await service.events(dict(payload, batch_seq=2)))["stale"] == 1
    wrong = dict(item, instance_id=2)
    assert (await service.events(dict(payload, requests=[wrong], batch_seq=4)))["wrong_identity"] == 1
    invalid = dict(item, predicted_exec_ms=float("nan"))
    assert (await service.events(dict(payload, requests=[invalid], batch_seq=4)))["invalid"] == 1
    await service.command(dict(op="abort", coordinator_epoch=service.epoch, reservation_id=ack["reservation_id"]))
    assert (await service.events(dict(payload, batch_seq=5)))["unknown_or_released"] == 1
