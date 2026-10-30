"""Review-only reproductions for 546bc7d; passing means the documented defect exists.
These do not modify production code. Motor SHM is a fake; no NPU/P/D is used.
"""
import asyncio
import json
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from test_admission_broker import stack, enqueue, command, config
from test_motor_adapter import enabled_config, make_stack, request
from gf_admission.broker import AdmissionBroker
from gf_admission.client import AdmissionClient
from gf_admission.provider import MotorFeatureProvider
from motor_adapter import bindings

@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['off', 'enforce'])
async def test_observe_motor_retry_same_attempt(mode, enabled_config, monkeypatch):
    from motor.coordinator.router.strategies.unified_pd import UnifiedPDRouter
    from motor.coordinator.router.dispatch_session import PDDispatchSession
    from motor.coordinator.scheduler.runtime.zmq_protocol import SchedulerRequest
    monkeypatch.setattr(bindings, 'admission_mode', lambda: mode)
    dispatcher, client, native = make_stack()
    backend = dispatcher._fgjsq_service.backend
    original_candidates = backend.candidates
    available = False
    monkeypatch.setattr(backend, 'candidates', lambda c: original_candidates(c) if available else [])
    broker = None
    if mode == 'enforce':
        broker = AdmissionBroker(dispatcher._fgjsq_service, config())
        dispatcher._gf_admission = broker
        async def send(data):
            result = await dispatcher.dispatch(SchedulerRequest('fgjsq_v1', 'review', data))
            if result.response_type != 'success':
                raise RuntimeError(result.error)
            return result.data
        client._gf_admission = AdmissionClient(send, broker.config)
    info = request('review-retry')
    router = SimpleNamespace(
        req_info=info, _scheduler=client, config=SimpleNamespace(),
        _request_manager=SimpleNamespace(add_req_attempt_workload=AsyncMock(return_value=True)),
        _pd_cluster_uses_trigger=AsyncMock(return_value=False),
        _should_defer_decode_allocation=UnifiedPDRouter._should_defer_decode_allocation,
    )
    async def prepare(role, seq):
        return await UnifiedPDRouter._prepare_attempt_resource(router, role, seq)
    router._prepare_attempt_resource = prepare
    session = PDDispatchSession(info.req_id)
    try:
        with pytest.raises(RuntimeError, match='No instance available'):
            await UnifiedPDRouter._create_attempt(router, session)
        assert session._attempt_seq == 0
        available = True
        if mode == 'enforce':
            with pytest.raises(RuntimeError, match='No instance available'):
                await UnifiedPDRouter._create_attempt(router, session)
            assert session._attempt_seq == 0 and native.adds == 0
            observed = {'mode': mode, 'second_attempt': 'UNAVAILABLE despite available P',
                        'session_sequence': session._attempt_seq, 'native_adds': native.adds,
                        'broker_states': (await broker.snapshot())['states']}
        else:
            attempt = await UnifiedPDRouter._create_attempt(router, session)
            assert attempt.attempt_seq == 1 and native.adds == 1
            observed = {'mode': mode, 'second_attempt': 'success',
                        'session_sequence': session._attempt_seq, 'native_adds': native.adds}
        print('REVIEW_R1', json.dumps(observed))
    finally:
        await bindings.finish_request(router)
        if broker:
            await client._gf_admission.close()
            await broker.close()
        assert native.adds == native.subs

@pytest.mark.asyncio
async def test_observe_expired_worker_cannot_close_released_ticket():
    b, s, ledger, clock = stack()
    try:
        result = await enqueue(b, 'stale', None)
        assert result['state'] == 'CLAIMED'
        clock.now += b.config.worker_lease_ms + 1
        await b.step()
        # Existing g5 cleanup can prove BOTH ledgers released even after heartbeat loss.
        release = await s.command({'op': 'abort', 'key': 'stale:1', 'coordinator_epoch': s.epoch})
        assert release['ok'] and sum(ledger.loads.values()) == 0
        rejected = []
        for op in ['query', 'cancel', 'finish']:
            with pytest.raises(ValueError, match='worker lease expired'):
                await b.handle(command(b, op, 'stale'))
            rejected.append(op)
        await b.drain()
        await b.step()
        snap = await b.snapshot()
        fg = await s.snapshot()
        assert fg['open_fg'] == fg['open_native'] == 0
        assert snap['states']['CLAIMED'] == snap['claimed_worker_lost'] == 1
        print('REVIEW_R2', json.dumps({'rejected_ops': rejected, 'states': snap['states'],
              'claimed_worker_lost': snap['claimed_worker_lost'],
              'open_fg': fg['open_fg'], 'open_native': fg['open_native']}))
    finally:
        await b.close()

@pytest.mark.asyncio
async def test_observe_feature_rpc_outside_time_and_capacity_bounds():
    calls = 0
    active = 0
    peak = 0
    async def rpc(_):
        nonlocal calls, active, peak
        calls += 1
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.25)
            return {'candidates': []}
        finally:
            active -= 1
    cfg = config(feature_kind='motor_conductor', feature_timeout_ms=20, feature_max_inflight=2)
    client = SimpleNamespace(config=cfg, rpc=rpc, data=lambda *a, **kw: kw)
    provider = MotorFeatureProvider(client)
    start = time.perf_counter()
    results = await asyncio.gather(*(provider.extract(None, {}) for _ in range(8)))
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms >= 200 and peak == 8 and all(r == {'cost': None} for r in results)
    print('REVIEW_R3', json.dumps({'configured_ms': 20, 'configured_inflight': 2,
          'elapsed_ms': round(elapsed_ms, 2), 'metadata_rpc_peak': peak,
          'thread_futures': len(provider.futures)}))
    await provider.close()

@pytest.mark.asyncio
async def test_observe_residual_sample_hidden_by_closed_records():
    b, s, ledger, clock = stack()
    try:
        for i in range(b.config.changes_batch):
            nonce = 'closed-' + str(i)
            await enqueue(b, nonce, None)
            await b.handle(command(b, 'finish', nonce))
        await enqueue(b, 'live', None)
        snap = await b.snapshot()
        assert snap['states']['CLAIMED'] == 1 and snap['residual_sample'] == []
        print('REVIEW_R4', json.dumps({'changes_batch': b.config.changes_batch,
              'states': snap['states'], 'residual_sample': snap['residual_sample']}))
        await b.handle(command(b, 'finish', 'live'))
    finally:
        await b.close()
