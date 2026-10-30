"""Additional rc2 review invariants. Production code is not modified."""
import asyncio
import json
from test_admission_broker import stack, enqueue, command, seed_pressure
from gf_admission.client import AdmissionClient
import pytest

@pytest.mark.asyncio
async def test_review_round_one_lost_ack_queries_same_reservation():
    b, service, ledger, _ = stack()
    lost = False
    async def send(data):
        nonlocal lost
        if data['op'] == 'hello':
            return dict(admission_digest=b.config.digest, admission_schema=2,
                        admission_mode='enforce', coordinator_epoch=service.epoch)
        reply = await b.handle(data)
        if data['op'] == 'admission_enqueue' and data.get('submission_round') == 1 and not lost:
            lost = True
            return None
        return reply
    client = AdmissionClient(send, b.config)
    payload = dict(req_id='review', estimated_tokens=10, native_tokens=5, cost=None)
    try:
        ledger.available = False
        assert await client.allocate('review', 1, payload) is None
        ledger.available = True
        second = await client.allocate('review', 1, dict(payload, estimated_tokens=20))
        assert lost and second['key'] == 'review:1:s1' and second['state'] == 'CLAIMED'
        assert len(ledger.adds) == 1 and b.classifier.arrivals == 1
        assert b.metrics['submissions'] == 2
        await client.finish('review')
        assert not client.rounds and sum(ledger.loads.values()) == 0
        print('ROUND_ACK_RECOVERY', json.dumps({'key':second['key'], 'native_adds':len(ledger.adds), 'logical_arrivals':b.classifier.arrivals, 'submissions':b.metrics['submissions']}))
    finally:
        await client.close(); await b.close()

@pytest.mark.asyncio
async def test_review_pressure_respects_target_and_stale_promotion():
    b, service, ledger, clock = stack(high_pressure_threshold=10, release_threshold=1)
    try:
        await seed_pressure(b, service)
        service.policy.release('synthetic')  # P2 is low-pressure; P1 remains busy.
        unrestricted = await enqueue(b, 'unrestricted', 1)
        assert unrestricted['state'] == 'CLAIMED'
        await b.handle(command(b, 'finish', 'unrestricted'))
        data = command(b, 'enqueue', 'targeted', payload=dict(req_id='targeted', estimated_tokens=10, native_tokens=5, cost=1, target_instance_id=1))
        targeted = await b.handle(data)
        assert targeted['state'] == 'QUEUED' and 'targeted:1' in b.queue.tail
        assert b.metrics['decision_pressure'] == 1
        # Staleness must be distinguishable from age promotion and must protect.
        clock.now += b.config.event_fresh_ms + 1
        # Keep owner live while making only pressure stale.
        b.workers['worker1'].seen = clock.now
        await b.step()
        assert b.metrics['promoted_stale'] == 1 and b.metrics['dispatch_protected'] == 1
        assert b.logicals['targeted'].protected
        for nonce in ('targeted','seed'):
            await b.handle(command(b, 'finish', nonce))
        assert sum(ledger.loads.values()) == 0
        print('PRESSURE_SCOPE',json.dumps({'targeted':'pressure tail', 'unrestricted':'normal', 'promoted_stale':b.metrics['promoted_stale']}))
    finally:
        await b.close()
