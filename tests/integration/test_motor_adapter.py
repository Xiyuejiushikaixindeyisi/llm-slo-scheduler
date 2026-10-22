"""Exercise the real patched Motor classes with an in-process RPC/SHM substitute."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from motor.coordinator.api_server.management_server import ManagementServer

from motor.common.resources.endpoint import Endpoint, Workload, WorkloadAction
from motor.common.resources.instance import Instance, PDRole
from motor.coordinator.domain.scheduling import UpdateWorkloadParams
from motor.coordinator.models.request import RequestInfo
from motor.coordinator.scheduler.runtime.scheduler_client import AsyncSchedulerClient
from motor.coordinator.scheduler.runtime.scheduler_server import _SchedulerRequestDispatcher
from motor.coordinator.router.strategies.unified_pd import UnifiedPDRouter
from motor.coordinator.router.adapters.pd_protocol import VllmProtocolAdapter, LegContext, EngineEndpointMetadata
from motor_adapter import bindings
from motor_adapter.config import get_config
from motor_adapter.motor_backend import MotorBackend
from motor_adapter.service import FgjsqService


@pytest.fixture
def enabled_config(tmp_path, monkeypatch):
    path = tmp_path / "fgjsq.json"
    path.write_text(json.dumps({"enabled": True, "event_url": "http://mgmt/fgjsq/v1/events"}))
    monkeypatch.setenv("FGJSQ_CONFIG", str(path))
    get_config.cache_clear()
    yield
    get_config.cache_clear()


class FakeNative:
    def __init__(self):
        self.entries = [dict(instance_id=i, endpoint_id=0, generation=1, flags=2, active_tokens=0, role=0)
                        for i in (1, 2, 3)]
        self.adds = 0
        self.subs = 0

    def read_header(self):
        return dict(schema_version=4, entry_count=len(self.entries))

    def load_entry(self, slot):
        return dict(self.entries[slot])

    def cas_add(self, iid, eid, gen, expected, delta, slot=None):
        entry = self.entries[slot]
        assert entry["generation"] == gen and entry["active_tokens"] == expected
        entry["active_tokens"] += delta
        self.adds += 1
        return 0, entry["active_tokens"]

    def cas_sub_floor0(self, iid, eid, gen, delta, slot=None):
        entry = self.entries[slot]
        assert entry["generation"] == gen
        entry["active_tokens"] = max(0, entry["active_tokens"] - delta)
        self.subs += 1
        return 0, entry["active_tokens"]


def make_stack():
    native = FakeNative()
    instances = {}
    for i in (1, 2, 3):
        ep = Endpoint(id=0, ip="127.0.0.1", business_port=str(8000 + i), status="normal")
        instances[i] = Instance(id=i, role="prefill", job_name="audit", model_name="model",
                                engine_type="vllm", endpoints={"pod": {0: ep}})
    dispatcher = _SchedulerRequestDispatcher.__new__(_SchedulerRequestDispatcher)
    dispatcher._instance_manager = SimpleNamespace(get_available_instances=lambda role: instances)
    dispatcher._workload_writer = SimpleNamespace(native=native)
    dispatcher._fgjsq_service = FgjsqService(MotorBackend(dispatcher), get_config())
    class Transport:
        lose_ack = False
        cancel_ack = False
        async def send_request(self, request):
            response = await dispatcher.dispatch(request)
            if request.data["op"] == "reserve" and self.cancel_ack:
                self.cancel_ack = False
                raise asyncio.CancelledError()
            if request.data["op"] == "reserve" and self.lose_ack:
                self.lose_ack = False
                return None
            return response
    client = AsyncSchedulerClient.__new__(AsyncSchedulerClient)
    client._transport = Transport()
    return dispatcher, client, native


def request(rid):
    return RequestInfo(req_id=rid, req_data={"model": "model", "messages": [], "max_tokens": 5},
                       req_len=4000, api="v1/chat/completions", entry_api="v1/chat/completions")


@pytest.mark.asyncio
async def test_motor_dispatch_and_client_recover_lost_ack_release_two_ledgers(enabled_config):
    dispatcher, client, native = make_stack()
    client._transport.lose_ack = True
    info = request("chat-root")
    inst, ep, workload = await client.select_and_allocate(PDRole.ROLE_P, info, attempt_seq=1)
    assert native.adds == 1
    assert inst.id == 1
    meta = bindings.metadata(info, 1)
    params = UpdateWorkloadParams(instance_id=inst.id, endpoint_id=ep.id, role=PDRole.ROLE_P,
                                  req_id=info.req_id, workload_action=WorkloadAction.RELEASE_TOKENS,
                                  workload_change=Workload(active_tokens=-workload.active_tokens),
                                  fgjsq_reservation_id=meta["reservation_id"],
                                  fgjsq_coordinator_epoch=meta["coordinator_epoch"])
    assert await client.update_workload(params)
    assert await client.update_workload(params)
    assert native.subs == 1
    assert (await dispatcher._fgjsq_service.snapshot())["open_fg"] == 1
    router = SimpleNamespace(req_info=info, _scheduler=client)
    await bindings.finish_request(router)
    assert (await dispatcher._fgjsq_service.snapshot())["open_fg"] == 0
    assert "_fgjsq_state" not in info.model_dump()


@pytest.mark.asyncio
async def test_cancel_after_native_commit_is_reconciled(enabled_config):
    dispatcher, client, native = make_stack()
    client._transport.cancel_ack = True
    with pytest.raises(asyncio.CancelledError):
        await client.select_and_allocate(PDRole.ROLE_P, request("cancel"), attempt_seq=1)
    assert native.adds == native.subs == 1
    assert (await dispatcher._fgjsq_service.snapshot())["open_fg"] == 0


@pytest.mark.asyncio
async def test_real_router_p_metadata_and_d_bytes_boundary(enabled_config):
    dispatcher, client, _ = make_stack()
    info = request("native")
    await client.select_and_allocate(PDRole.ROLE_P, info, attempt_seq=1)
    attempt = SimpleNamespace(attempt_seq=1)
    context = LegContext(engine_request_id="native#a1", pair_id="pair", attempt_seq=1,
                         api="v1/chat/completions", endpoint=EngineEndpointMetadata(host="127.0.0.1"))
    router = SimpleNamespace(req_info=info, _scheduler=client, _native_leg_context=lambda *a: context)
    adapter = VllmProtocolAdapter()
    pbody, _ = UnifiedPDRouter._native_request_for_attempt(
        router, attempt, PDRole.ROLE_P, adapter=adapter, req=info.req_data, api=context.api)
    assert pbody["kv_transfer_params"]["fgjsq"]["reservation_id"] == bindings.metadata(info, 1)["reservation_id"]
    original_d = dict(model="model", request_id="native#a1", kv_transfer_params={"remote_block_ids": [1, 2]})
    marked = bindings.attach_request(router, attempt, PDRole.ROLE_D, original_d)
    wire, observer = bindings.prepare_forward(router, marked)
    assert wire == original_d
    observer.observe(b"")
    assert (await dispatcher._fgjsq_service.snapshot())["open_fg"] == 1
    observer.observe(b'data: {"role":"assistant"}')
    await asyncio.gather(*list(bindings.request_state(info)["tasks"]))
    assert (await dispatcher._fgjsq_service.snapshot())["open_fg"] == 0
    assert (await dispatcher._fgjsq_service.snapshot())["open_native"] == 1
    await bindings.finish_request(router)


@pytest.mark.asyncio
async def test_mgmt_http_route_reports_matched_not_only_http200(enabled_config):
    dispatcher, client, _ = make_stack()
    info = request("event")
    await client.select_and_allocate(PDRole.ROLE_P, info, attempt_seq=1)
    app = FastAPI()
    server = SimpleNamespace(management_app=app, _control_plane=SimpleNamespace(_dispatcher=dispatcher),
                             _mgmt_api_key_config=SimpleNamespace(enable_api_key=True), _mgmt_api_key="test-key")
    server._verify_mgmt_api_key = lambda request: ManagementServer._verify_mgmt_api_key(server, request)
    bindings.register_routes(server)
    item = bindings.metadata(info, 1)
    item.update(num_prompt_tokens=1000, num_scheduled_tokens=200, num_remaining_tokens=800, predicted_exec_ms=100)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        payload = dict(schema_version=1, engine_epoch="P", batch_seq=0, requests=[item])
        assert (await http.post("/fgjsq/v1/events", json=payload)).status_code == 401
        assert (await http.get("/fgjsq/v1/loads")).status_code == 401
        http.headers["X-Motor-Management-Key"] = "wrong"
        assert (await http.post("/fgjsq/v1/events", json=payload)).status_code == 403
        http.headers["X-Motor-Management-Key"] = "test-key"
        result = await http.post("/fgjsq/v1/events", json=payload)
        assert result.status_code == 200
        assert result.json()["matched"] == 1
        result = await http.post("/fgjsq/v1/events", json=dict(schema_version=1, requests=[None]))
        assert result.status_code == 422
        assert (await http.get("/fgjsq/v1/loads")).json()["open_fg"] == 1


@pytest.mark.asyncio
async def test_old_generation_release_never_subtracts_from_replacement(enabled_config):
    dispatcher, client, native = make_stack()
    info = request("replace")
    await client.select_and_allocate(PDRole.ROLE_P, info, attempt_seq=1)
    native.entries[0].update(generation=2, active_tokens=12345)
    await bindings.finish_request(SimpleNamespace(req_info=info, _scheduler=client))
    assert native.entries[0]["active_tokens"] == 12345
    assert native.subs == 0


@pytest.mark.asyncio
async def test_disabled_and_decode_client_do_not_enter_fgjsq(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.delenv("FGJSQ_CONFIG", raising=False)
    get_config.cache_clear()
    client = AsyncSchedulerClient.__new__(AsyncSchedulerClient)
    client._refresh_cache_from_workload_reader = AsyncMock()
    client._workload_reader = None
    assert await client.select_and_allocate(PDRole.ROLE_P, request("off")) is None
    assert await client.select_and_allocate(PDRole.ROLE_D, request("d")) is None

@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [True, False])
@pytest.mark.parametrize("prebuffered", [True, False])
async def test_patched_http_boundary_strips_private_marker_and_observes_d_body(enabled_config, streaming, prebuffered):
    import logging
    from unittest.mock import Mock
    from motor.coordinator.router.strategies.base import BaseRouter
    dispatcher, client, _ = make_stack()
    info = request("http-boundary")
    await client.select_and_allocate(PDRole.ROLE_P, info, attempt_seq=1)
    wire_bodies = []
    payload = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n' if streaming else b'{"ok":true}'
    async def transport(request):
        wire_bodies.append(json.loads(request.content))
        return httpx.Response(200, content=payload) if prebuffered else httpx.Response(200, stream=httpx.ByteStream(payload))
    trace = Mock()
    trace.get_trace_headers_dict.return_value = {}
    info.trace_obj = trace
    router = SimpleNamespace(req_info=info, _scheduler=client, is_meta=False, logger=logging.getLogger("http-test"),
                             _log_sched_to_p_if_needed=lambda: None, _build_request_timeout=lambda t: httpx.Timeout(t),
                             _forward_request_id=lambda body: body["request_id"])
    router._open_nonstream_response = lambda *a, **kw: BaseRouter._open_nonstream_response(router, *a, **kw)
    original = dict(model="model", request_id="http-boundary#a1", kv_transfer_params={"remote_block_ids":[1]})
    marked = bindings.attach_request(router, SimpleNamespace(attempt_seq=1), PDRole.ROLE_D, original)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport), base_url="http://d") as http:
        if streaming:
            chunks = [part async for part in BaseRouter.forward_stream_request(router, "v1/chat/completions", marked, http, 10)]
            assert b"".join(chunks) == payload
        else:
            response = await BaseRouter.forward_request(router, "v1/chat/completions", marked, http, 10)
            assert response.content == payload
    tasks = list(bindings.request_state(info)["tasks"])
    if tasks:
        await asyncio.gather(*tasks)
    assert wire_bodies == [original]
    assert (await dispatcher._fgjsq_service.snapshot())["open_fg"] == 0
    await bindings.finish_request(router)


@pytest.mark.asyncio
async def test_shared_backend_excludes_blocked_and_paused_endpoints(enabled_config):
    dispatcher, client, native = make_stack()
    native.entries[0]["flags"] |= 1
    instances = dispatcher._instance_manager.get_available_instances(PDRole.ROLE_P)
    instances[2].endpoints["pod"][0].status = "paused"
    instance, _, _ = await client.select_and_allocate(PDRole.ROLE_P, request("healthy-only"), attempt_seq=1)
    assert instance.id == 3
