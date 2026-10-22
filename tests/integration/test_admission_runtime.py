"""Real Motor DEALER/ROUTER serialization, fake SHM; no NPU claim."""

import asyncio
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import zmq
import zmq.asyncio
from motor.common.resources.instance import PDRole
from motor.coordinator.scheduler.runtime.scheduler_client import _SchedulerTransport
from motor.coordinator.scheduler.runtime.zmq_protocol import ZMQMessageSerializer
from test_admission_broker import config
from test_motor_adapter import (
    enabled_config as enabled_config,  # noqa: PLC0414 - pytest fixture reuse
)
from test_motor_adapter import (
    make_stack,
    request,
)

from gf_admission.broker import AdmissionBroker
from gf_admission.client import AdmissionClient, motor_sender
from gf_admission.runtime_config import load_config
from motor_adapter import bindings


def cfg():
    return replace(
        load_config(
            str(
                Path(__file__).resolve().parents[2]
                / "configs/gf_admission/shadow.example.json"
            )
        ),
        mode="enforce",
        high_pressure_threshold=10000,
        release_threshold=0.000001,
        wait_ms=30,
        worker_lease_ms=3000,
        feature_kind="unknown",
        ready_lease_ms=1000,
        request_wait_ms=3000,
        tombstone_ms=10000,
    )


@pytest.mark.asyncio
async def test_real_zmq_two_workers_lost_ack_cancel_and_no_double_reserve(
    enabled_config, tmp_path, monkeypatch
):
    runtime_config = replace(
        cfg(),
        classifier=replace(cfg().classifier, quota_every=1),
        high_pressure_threshold=10,
        limits=replace(cfg().limits, max_tail_wait_ms=5000),
    )
    monkeypatch.setattr(bindings, "admission_mode", lambda: "enforce")
    dispatcher, _legacy, native = make_stack()
    broker = AdmissionBroker(dispatcher._fgjsq_service, runtime_config)
    dispatcher._gf_admission = broker
    dispatcher._fgjsq_service.on_events = broker.notify
    serializer = ZMQMessageSerializer()
    context = zmq.asyncio.Context()
    socket = context.socket(zmq.ROUTER)
    address = "ipc://" + str(tmp_path / "admission.sock")
    socket.bind(address)
    tasks = set()
    errors = []
    dropped = False
    held = asyncio.Event()

    async def respond(identity, frames):
        nonlocal dropped
        incoming = serializer.deserialize_request(frames[1:])
        if incoming.data.get("key") == "hold-query":
            held.set()
            await asyncio.Event().wait()
        result = await dispatcher.dispatch(incoming)
        if incoming.data["op"] == "admission_enqueue" and not dropped:
            dropped = True
            return
        out = serializer.serialize_response(result)
        await socket.send_multipart(
            [identity, b""] + (out if isinstance(out, list) else [out])
        )

    async def serve():
        while True:
            identity, *frames = await socket.recv_multipart()
            task = asyncio.create_task(respond(identity, frames))
            tasks.add(task)

            def done(task):
                tasks.discard(task)
                if not task.cancelled() and task.exception():
                    errors.append(task.exception())

            task.add_done_callback(done)

    server = asyncio.create_task(serve())
    clients = []
    transports = []
    try:
        for _ in range(2):
            transport = _SchedulerTransport(address, 0.6)
            assert await transport.connect()
            transports.append(transport)
            client = SimpleNamespace(_transport=transport)
            plugin = AdmissionClient(
                motor_sender(client, runtime_config), runtime_config
            )
            client._gf_admission = plugin
            clients.append(client)
        infos = [request("w" + str(i)) for i in range(2)]
        results = await asyncio.gather(
            *(
                bindings.allocate(client, PDRole.ROLE_P, info, 1)
                for client, info in zip(clients, infos)
            )
        )
        assert all(results) and native.adds == 2 and broker.classifier.arrivals == 2
        assert len(broker.workers) == 2
        # A cancelled long poll remains cancellation through Motor's typed transport result.
        wait = asyncio.create_task(
            motor_sender(clients[0], runtime_config)(
                clients[0]._gf_admission.data("query", key="hold-query")
            )
        )
        await asyncio.wait_for(held.wait(), 1)
        wait.cancel()
        with pytest.raises(asyncio.CancelledError):
            await wait
        await asyncio.gather(
            *(
                bindings.finish_request(
                    SimpleNamespace(req_info=info, _scheduler=client)
                )
                for client, info in zip(clients, infos)
            )
        )
        child_config = tmp_path / "child-config.json"
        child_config.write_text(json.dumps(asdict(runtime_config)))
        code = """import asyncio,sys
from types import SimpleNamespace
from gf_admission.client import AdmissionClient,motor_sender
from gf_admission.runtime_config import load_config
from motor.coordinator.scheduler.runtime.scheduler_client import _SchedulerTransport
async def main():
    config=load_config(sys.argv[1])
    transport=_SchedulerTransport(sys.argv[2],.6)
    assert await transport.connect()
    client=AdmissionClient(motor_sender(SimpleNamespace(_transport=transport),config),config)
    try:
        reply=await client.allocate('cross-process',1,dict(req_id='child',estimated_tokens=10,native_tokens=5,cost=None))
        assert reply['state']=='CLAIMED'
        await client.finish('cross-process')
    finally:
        await client.close()
        await transport.disconnect()
    print('CHILD_OK')
asyncio.run(main())
"""
        child = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            code,
            str(child_config),
            address,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, error = await asyncio.wait_for(child.communicate(), 10)
        assert child.returncode == 0, error.decode()
        assert b"CHILD_OK" in output and broker.classifier.arrivals == 3
        assert not errors
        assert native.adds == native.subs == 3
        # Real IPC tail -> READY -> claim, using the same authenticated identity
        # validator for accepted FG events; native SHM remains the explicit fake.
        plugin = clients[0]._gf_admission
        seeds = []
        service = dispatcher._fgjsq_service
        for instance in (1, 2, 3):
            seed = await plugin.allocate(
                "seed" + str(instance),
                1,
                {
                    "req_id": "seed",
                    "estimated_tokens": 100,
                    "native_tokens": 5,
                    "cost": 1,
                    "target_instance_id": instance,
                },
            )
            seeds.append(seed)
            ack = seed["ack"]
            event = {
                k: ack[k]
                for k in (
                    "reservation_id",
                    "coordinator_epoch",
                    "instance_id",
                    "endpoint_id",
                    "generation",
                    "attempt_seq",
                )
            }
            event.update(
                num_prompt_tokens=100,
                num_scheduled_tokens=0,
                num_remaining_tokens=100,
                predicted_exec_ms=0,
            )
            assert (
                await service.events(
                    {
                        "schema_version": 1,
                        "engine_epoch": "test",
                        "batch_seq": 1,
                        "requests": [event],
                    }
                )
            )["matched"] == 1
        tasks_tail = []
        for name in ("tail-old", "tail-new"):
            task = asyncio.create_task(
                plugin.allocate(
                    name,
                    1,
                    {
                        "req_id": name,
                        "estimated_tokens": 100,
                        "native_tokens": 5,
                        "cost": 1,
                    },
                )
            )
            tasks_tail.append(task)
            for _ in range(100):
                if name + ":1" in broker.queue.tail:
                    break
                await asyncio.sleep(0.001)
            assert name + ":1" in broker.queue.tail
        await plugin.finish("seed1")
        newest = await asyncio.wait_for(tasks_tail[1], 1)
        assert newest["state"] == "CLAIMED" and not tasks_tail[0].done()
        assert broker.metrics["lifo_overtake_dispatches"] == 1
        tasks_tail[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks_tail[0]
        for name in ("tail-new", "seed2", "seed3"):
            await plugin.finish(name)
        assert native.adds == native.subs == 7
        snapshot = await dispatcher._fgjsq_service.snapshot()
        assert snapshot["open_fg"] == snapshot["open_native"] == 0
        await bindings.close_admission_dispatcher(dispatcher)
    finally:
        for client in clients:
            await client._gf_admission.close()
        for transport in transports:
            await transport.disconnect()
        await broker.close()
        server.cancel()
        await asyncio.gather(server, return_exceptions=True)
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*list(tasks), return_exceptions=True)
        socket.close(0)
        context.term()


@pytest.mark.asyncio
async def test_enforce_finish_and_shutdown_refuses_live_resource(
    enabled_config, monkeypatch
):
    runtime_config = cfg()
    monkeypatch.setattr(bindings, "admission_mode", lambda: "enforce")
    dispatcher, client, native = make_stack()
    broker = AdmissionBroker(dispatcher._fgjsq_service, runtime_config)
    dispatcher._gf_admission = broker

    async def send(data):
        from motor.coordinator.scheduler.runtime.zmq_protocol import SchedulerRequest

        result = await dispatcher.dispatch(SchedulerRequest("fgjsq_v1", "test", data))
        if result.response_type != "success":
            raise RuntimeError(result.error)
        return result.data

    client._gf_admission = AdmissionClient(send, runtime_config)
    info = request("guard")
    try:
        assert await bindings.allocate(client, PDRole.ROLE_P, info, 1)
        with pytest.raises(RuntimeError, match="unresolved"):
            await bindings.close_admission_dispatcher(dispatcher)
        await bindings.finish_request(SimpleNamespace(req_info=info, _scheduler=client))
        assert native.adds == native.subs == 1
        await bindings.close_admission_dispatcher(dispatcher)
    finally:
        await client._gf_admission.close()
        await broker.close()


@pytest.mark.asyncio
async def test_real_handoff_create_attempt_waits_for_p_before_d(enabled_config):
    from unittest.mock import AsyncMock, Mock

    from motor.coordinator.router.strategies.unified_pd import UnifiedPDRouter

    entered, release = asyncio.Event(), asyncio.Event()
    roles = []

    async def allocate(role, attempt):
        roles.append(role)
        entered.set()
        await release.wait()
        return SimpleNamespace(instance=SimpleNamespace(engine_type="vllm"))

    router = SimpleNamespace(
        _pd_cluster_uses_trigger=AsyncMock(return_value=False),
        _prepare_attempt_resource=allocate,
        _should_defer_decode_allocation=UnifiedPDRouter._should_defer_decode_allocation,
        config=SimpleNamespace(),
    )
    session = SimpleNamespace(_attempt_seq=0, new_attempt=Mock(return_value="created"))
    task = asyncio.create_task(UnifiedPDRouter._create_attempt(router, session))
    await entered.wait()
    assert not task.done() and roles == [PDRole.ROLE_P]
    session.new_attempt.assert_not_called()
    release.set()
    assert await task == "created"
    assert session.new_attempt.call_args.args[1] is None and roles == [PDRole.ROLE_P]


@pytest.mark.asyncio
async def test_provider_reuses_token_ids_and_requires_all_tiers(
    enabled_config, monkeypatch
):
    from motor.coordinator.api_client.conductor_api_client import (
        TENANT_ID,
        ConductorApiClient,
        conductor_instance_id,
    )
    from motor.coordinator.scheduler.policy.kv_cache_affinity import (
        KvCacheAffinityPolicy,
    )

    from gf_admission.provider import MotorFeatureProvider

    dispatcher, _client, _native = make_stack()
    provider = MotorFeatureProvider(SimpleNamespace(config=cfg()))
    info = request("features")
    info.token_ids = list(range(16))
    candidates = dispatcher._fgjsq_service.backend.candidates({})
    from motor.common.resources.instance import Instance

    raw = {
        TENANT_ID: {
            conductor_instance_id(Instance.model_validate(c["instance"])): {
                "DP": {"0": {"npu_blocks": 1, "cpu_blocks": 1, "disk_blocks": 0}}
            }
            for c in candidates
        }
    }
    monkeypatch.setattr(KvCacheAffinityPolicy, "_conductor_block_size", lambda: 4)
    monkeypatch.setattr(
        ConductorApiClient, "_kv_reg", lambda: SimpleNamespace(conductor_service="test")
    )
    monkeypatch.setattr(
        ConductorApiClient, "query_conductor", lambda instances, tokens: raw
    )
    result = provider._extract_sync(info, candidates)
    assert result["cost"] == 12 and len(result["candidate_generations"]) == 3
    first = next(iter(raw[TENANT_ID].values()))
    del first["DP"]["0"]["disk_blocks"]
    assert provider._extract_sync(info, candidates) == {"cost": None}
    assert info.token_ids == list(range(16))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "enforce"])
async def test_motor_retry_same_attempt_recovers_in_off_and_enforce(
    mode, enabled_config, monkeypatch
):
    from motor.coordinator.router.dispatch_session import PDDispatchSession
    from motor.coordinator.router.strategies.unified_pd import UnifiedPDRouter
    from motor.coordinator.scheduler.runtime.zmq_protocol import SchedulerRequest

    monkeypatch.setattr(bindings, "admission_mode", lambda: mode)
    dispatcher, client, native = make_stack()
    backend = dispatcher._fgjsq_service.backend
    original_candidates = backend.candidates
    available = False
    monkeypatch.setattr(
        backend, "candidates", lambda c: original_candidates(c) if available else []
    )
    broker = None
    if mode == "enforce":
        broker = AdmissionBroker(dispatcher._fgjsq_service, config())
        dispatcher._gf_admission = broker

        async def send(data):
            result = await dispatcher.dispatch(
                SchedulerRequest("fgjsq_v1", "review", data)
            )
            if result.response_type != "success":
                raise RuntimeError(result.error)
            return result.data

        client._gf_admission = AdmissionClient(send, broker.config)
    info = request("review-retry")
    router = SimpleNamespace(
        req_info=info,
        _scheduler=client,
        config=SimpleNamespace(),
        _request_manager=SimpleNamespace(
            add_req_attempt_workload=AsyncMock(return_value=True)
        ),
        _pd_cluster_uses_trigger=AsyncMock(return_value=False),
        _should_defer_decode_allocation=UnifiedPDRouter._should_defer_decode_allocation,
    )

    async def prepare(role, seq):
        return await UnifiedPDRouter._prepare_attempt_resource(router, role, seq)

    router._prepare_attempt_resource = prepare
    session = PDDispatchSession(info.req_id)
    try:
        with pytest.raises(RuntimeError, match="No instance available"):
            await UnifiedPDRouter._create_attempt(router, session)
        assert session._attempt_seq == 0
        available = True
        attempt = await UnifiedPDRouter._create_attempt(router, session)
        assert attempt.attempt_seq == 1 and native.adds == 1
        if broker:
            assert broker.classifier.arrivals == 1
    finally:
        await bindings.finish_request(router)
        if broker:
            await client._gf_admission.close()
            await broker.close()
        assert native.adds == native.subs
