"""Explicit hooks called by the small, version-checked Motor source patch."""
import asyncio
import copy
import logging
import time
import uuid

from motor_adapter.config import enabled, get_config, validate_motor

logger = logging.getLogger(__name__)
WIRE_TYPE = "fgjsq_v1"
BODY_MARKER = "_motor_fgjsq_observer"


def init_dispatcher(dispatcher) -> None:
    dispatcher._fgjsq_service = None
    if enabled():
        from motor_adapter.motor_backend import MotorBackend
        from motor_adapter.service import FgjsqService
        validate_motor(dispatcher._config)
        dispatcher._fgjsq_service = FgjsqService(MotorBackend(dispatcher), get_config(),
                                                dispatcher._workload_commit_lock)


async def dispatch(dispatcher, request):
    from motor.coordinator.scheduler.runtime.zmq_protocol import SchedulerResponse, SchedulerResponseType
    if dispatcher._fgjsq_service is None:
        return SchedulerResponse(response_type=SchedulerResponseType.ERROR, request_id=request.request_id,
                                 error="FGJSQ is disabled in Mgmt")
    try:
        data = await dispatcher._fgjsq_service.command(request.data)
        return SchedulerResponse(response_type=SchedulerResponseType.SUCCESS, request_id=request.request_id, data=data)
    except Exception as error:
        logger.error("FGJSQ command failed: %s", error)
        return SchedulerResponse(response_type=SchedulerResponseType.ERROR, request_id=request.request_id, error=str(error))


def register_routes(server) -> None:
    if not enabled():
        return
    from fastapi import HTTPException, Request

    def service():
        dispatcher = server._control_plane._dispatcher
        value = getattr(dispatcher, "_fgjsq_service", None)
        if value is None:
            raise HTTPException(503, "FGJSQ service is not ready")
        return value

    async def events(request: Request):
        server._verify_mgmt_api_key(request)
        try:
            payload = await request.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("requests"), list):
                raise ValueError("invalid batch payload")
            if len(payload["requests"]) > 4096 or any(not isinstance(x, dict) for x in payload["requests"]):
                raise ValueError("invalid request events")
            return await service().events(payload)
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(422, str(error)) from error

    async def loads(request: Request):
        server._verify_mgmt_api_key(request)
        return await service().snapshot()

    server.management_app.add_api_route("/fgjsq/v1/events", events, methods=["POST"])
    server.management_app.add_api_route("/fgjsq/v1/loads", loads, methods=["GET"])


def request_state(req_info) -> dict:
    state = req_info._fgjsq_state
    if not state:
        state.update(nonce=uuid.uuid4().hex, attempts={}, tasks=set())
    return state


async def _rpc(client, data: dict) -> dict:
    from motor.coordinator.scheduler.runtime.zmq_protocol import SchedulerRequest
    for _ in range(get_config().rpc_attempts):
        response = await client._transport.send_request(
            SchedulerRequest(request_type=WIRE_TYPE, request_id=uuid.uuid4().hex, data=data))
        if response is None:
            if data["op"] == "reserve":
                query = {k: v for k, v in data.items() if k in ("key", "coordinator_epoch")}
                query["op"] = "query"
                response = await client._transport.send_request(
                    SchedulerRequest(request_type=WIRE_TYPE, request_id=uuid.uuid4().hex, data=query))
                if response is not None and response.response_type == "success" and response.data.get("found"):
                    return response.data["record"]
            continue
        if response.response_type != "success":
            raise RuntimeError("FGJSQ RPC refused: " + str(response.error))
        return response.data or {}
    raise RuntimeError("FGJSQ RPC outcome unknown; no fallback allocation permitted")


async def allocate(client, role, req_info, attempt_seq, **constraints):
    from motor.common.resources.instance import Instance
    from motor.common.resources.endpoint import Endpoint, Workload
    from motor.coordinator.domain.workload_calculator import calculate_demand_workload
    from anyio import CancelScope
    if attempt_seq is None:
        raise ValueError("FGJSQ only supports UnifiedPD attempts")
    prompt = req_info.req_data.get("prompt")
    if isinstance(prompt, list) and (not prompt or not isinstance(prompt[0], int)):
        raise ValueError("FGJSQ v1 does not support batched prompts")
    if int(req_info.req_data.get("n", 1)) != 1:
        raise ValueError("FGJSQ v1 requires n=1")
    state = request_state(req_info)
    record = state["attempts"].setdefault(attempt_seq, {})
    try:
        if "command" not in record:
            hello = await _rpc(client, {"op": "hello"})
            command = {"op": "reserve", "coordinator_epoch": hello["coordinator_epoch"],
                       "key": state["nonce"] + ":" + str(attempt_seq), "req_id": req_info.req_id,
                       "attempt_seq": attempt_seq, "reserve_deadline": time.time() + get_config().reserve_window_s,
                       "estimated_tokens": max(1, req_info.req_len // 4),
                       "native_tokens": float(calculate_demand_workload(role, req_info).active_tokens), **constraints}
            record["command"] = command
        ack = await _rpc(client, record["command"])
        if ack.get("unavailable"):
            return None
        if ack["native_released"] or ack["fg_released"]:
            raise RuntimeError("attempt already closed; cannot resend")
        record["ack"] = ack
        return (Instance.model_validate(ack["instance"]), Endpoint.model_validate(ack["endpoint"]),
                Workload(active_tokens=ack["native_tokens"]))
    except BaseException:
        with CancelScope(shield=True):
            await release_record(client, record, "abort", suppress=True)
        raise


async def release_record(client, record: dict, op: str, suppress: bool = False) -> bool:
    command = record.get("command")
    if command is None:
        return True
    try:
        data = {"op": op, "coordinator_epoch": command["coordinator_epoch"], "key": command["key"]}
        result = await _rpc(client, data)
        ok = bool(result.get("ok"))
        if ok:
            record.update(ack=result.get("record", record.get("ack")))
        elif not suppress:
            raise RuntimeError("FGJSQ release not acknowledged: " + str(result))
        return ok
    except Exception as error:
        if not suppress:
            raise
        logger.error("FGJSQ pending release key=%s operation=%s: %s", command["key"], op, error)
        return False


def record_for(req_info, attempt_seq: int) -> dict:
    return request_state(req_info)["attempts"].get(attempt_seq, {})


def reservation_for(req_info, attempt_seq: int) -> str | None:
    return record_for(req_info, attempt_seq).get("ack", {}).get("reservation_id")


def metadata(req_info, attempt_seq: int) -> dict | None:
    if not enabled():
        return None
    ack = record_for(req_info, attempt_seq).get("ack")
    if not ack:
        return None
    return {k: ack[k] for k in ("schema_version", "coordinator_epoch", "reservation_id", "attempt_seq",
                                "instance_id", "endpoint_id", "generation", "event_url")}


async def native_release(client, params) -> bool:
    if not params.fgjsq_reservation_id or not params.fgjsq_coordinator_epoch:
        # Do not use the legacy non-idempotent CAS for a FGJSQ-owned P allocation.
        logger.error("P native release lacks FGJSQ identity req_id=%s; final abort will reconcile", params.req_id)
        return False
    return bool((await _rpc(client, {"op": "release_native",
                "coordinator_epoch": params.fgjsq_coordinator_epoch,
                "reservation_id": params.fgjsq_reservation_id})).get("ok"))


def attach_request(router, attempt, role, body: dict) -> dict:
    if not enabled():
        return body
    meta = metadata(router.req_info, attempt.attempt_seq)
    if not meta:
        raise RuntimeError("FGJSQ reservation missing for native leg")
    body = copy.deepcopy(body)
    body.pop(BODY_MARKER, None)
    kv = body.get("kv_transfer_params")
    if isinstance(kv, dict):
        kv.pop("fgjsq", None)
    if getattr(role, "value", role) == "prefill":
        body.setdefault("kv_transfer_params", {})["fgjsq"] = meta
    else:
        # Consumed at Coordinator HTTP boundary; never sent to D.
        body[BODY_MARKER] = {"attempt_seq": attempt.attempt_seq, "reservation_id": meta["reservation_id"]}
    return body


def validate_mode(mode) -> None:
    if enabled() and getattr(mode, "value", mode) != "handoff":
        raise ValueError("FGJSQ v1 supports HANDOFF only")


def prepare_forward(router, body: dict):
    if not enabled():
        return body, None
    body = dict(body)
    marker = body.pop(BODY_MARKER, None)
    if marker is None:
        return body, None
    record = record_for(router.req_info, marker["attempt_seq"])
    if record.get("ack", {}).get("reservation_id") != marker["reservation_id"]:
        raise RuntimeError("invalid P observer identity")
    from motor_adapter.body_observer import FirstBodyObserver
    state = request_state(router.req_info)
    return body, FirstBodyObserver(lambda: release_record(router._scheduler, record, "release_fg"),
                                   state["tasks"])


async def finish_attempt(router, attempt) -> None:
    if enabled():
        await release_record(router._scheduler, record_for(router.req_info, attempt.attempt_seq), "abort", suppress=True)


async def finish_request(router) -> None:
    if not enabled():
        return
    state = request_state(router.req_info)
    tasks = list(state["tasks"])
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    for record in state["attempts"].values():
        await release_record(router._scheduler, record, "abort", suppress=True)


def validate_router(router) -> None:
    if not enabled():
        return
    validate_motor(router.config)
    if type(router).__name__ != "UnifiedPDRouter":
        raise ValueError("FGJSQ v1 requires UnifiedPDRouter")
    api = (router.req_info.entry_api or router.req_info.api).strip("/")
    if api not in ("v1/chat/completions", "v1/completions"):
        raise ValueError("FGJSQ v1 supports Chat and scalar Completion only")
    if router.req_info.tokenized_requests:
        raise ValueError("FGJSQ v1 requires native OpenAI transport; disable Render")
