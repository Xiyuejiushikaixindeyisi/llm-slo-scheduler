"""Worker-side transactions and one shared long-poll task per worker."""

import asyncio
import logging
import uuid

import anyio

logger = logging.getLogger(__name__)


class AdmissionClient:
    def __init__(self, send, config, provider=None, *, rpc_attempts=3):
        self.send, self.config, self.provider = send, config, provider
        self.rpc_attempts = rpc_attempts
        self.worker = uuid.uuid4().hex
        self.epoch = None
        self.hello_lock = asyncio.Lock()
        self.pending = {}
        self.pending_identity = {}
        self.rounds = {}
        self.hub = None
        self.revision = 0
        self.closed = False
        self.fault = None
        self.shadow_tasks = set()
        self.metrics = {"shadow_dropped": 0, "shadow_failed": 0, "cleanup_failed": 0}

    async def hello(self):
        if self.closed or self.fault:
            raise RuntimeError("admission requires a fresh client after close/fault")
        async with self.hello_lock:
            if self.epoch is not None:
                return
            reply = await self.send({"op": "hello"})
            if reply is None or reply.get("admission_digest") != self.config.digest:
                raise RuntimeError("Mgmt admission capability/config mismatch")
            if (
                reply.get("admission_schema") != 2
                or reply.get("admission_mode") != self.config.mode
            ):
                raise RuntimeError("Mgmt admission mode/schema mismatch")
            self.epoch = reply["coordinator_epoch"]
            self.hub = asyncio.create_task(self._hub(), name="gf-admission-worker-wait")

    def data(self, op, nonce=None, attempt=None, **extra):
        value = {
            "op": "admission_" + op,
            "coordinator_epoch": self.epoch,
            "config_digest": self.config.digest,
            "worker_epoch": self.worker,
            **extra,
        }
        if nonce is not None:
            value.update(logical_nonce=nonce)
        if attempt is not None:
            round_id = self.rounds.get((nonce, attempt), 0)
            key = nonce + ":" + str(attempt)
            if round_id:
                key += ":s" + str(round_id)
            value.update(attempt_seq=attempt, submission_round=round_id, key=key)
        return value

    async def rpc(self, data):
        for _ in range(self.rpc_attempts):
            reply = await self.send(data)
            if reply is not None:
                return reply
            if data["op"] in ("admission_enqueue", "admission_claim"):
                query = self.data("query", key=data["key"])
                reply = await self.send(query)
                if reply is not None and reply.get("state") != "NOT_FOUND":
                    return reply
        raise RuntimeError(
            "admission RPC outcome unknown; no fallback allocation permitted"
        )

    async def _hub(self):
        try:
            while not self.closed:
                result = await self.rpc(self.data("wait", after_revision=self.revision))
                self.revision = result["revision"]
                for reply in result["changes"]:
                    future = self.pending.get(reply["key"])
                    if (
                        future is not None
                        and not future.done()
                        and reply["state"] != "QUEUED"
                    ):
                        future.set_result(reply)
        except asyncio.CancelledError:
            for future in self.pending.values():
                if not future.done():
                    future.cancel()
            raise
        except Exception as error:  # noqa: BLE001 - transaction/task fault boundary
            self.fault = type(error).__name__
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(error)
        finally:
            self.hub = None

    async def cancel(self, nonce, attempt):
        if self.epoch is None:
            return
        # Shield only a bounded cleanup section. Cancellation resumes afterwards.
        try:
            with anyio.move_on_after(
                self.config.wait_ms * self.rpc_attempts / 1000 + 1, shield=True
            ) as scope:
                result = await self.rpc(self.data("cancel", nonce, attempt))
                if result.get("state") == "CLEANUP_PENDING":
                    self.metrics["cleanup_failed"] += 1
            if scope.cancel_called:
                self.metrics["cleanup_failed"] += 1
        except (Exception, asyncio.CancelledError):  # noqa: BLE001 - bounded best-effort cleanup
            self.metrics["cleanup_failed"] += 1
            logger.error(
                "Admission cancellation not confirmed; Mgmt reconciliation required"
            )

    async def allocate(self, nonce, attempt, payload, request=None):
        if self.closed or self.fault:
            raise RuntimeError("admission client closed or faulted: " + str(self.fault))
        if len(self.pending) >= self.config.limits.max_pending:
            raise RuntimeError("worker admission capacity reached")
        await self.hello()
        if (nonce, attempt) not in self.rounds:
            if len(self.rounds) >= self.config.max_records:
                raise RuntimeError("worker logical transaction capacity reached")
            self.rounds[nonce, attempt] = 0
        key = self.data("enqueue", nonce, attempt)["key"]
        if key in self.pending:
            raise RuntimeError("concurrent allocation for the same logical attempt")
        future = asyncio.get_running_loop().create_future()
        self.pending[key] = future
        self.pending_identity[key] = (nonce, attempt)
        try:
            if self.provider is not None:
                payload = dict(
                    payload, **(await self.provider.extract(request, payload))
                )
            reply = await self.rpc(
                self.data("enqueue", nonce, attempt, payload=payload)
            )
            if reply["state"] == "QUEUED":
                if self.hub is None:
                    self.hub = asyncio.create_task(
                        self._hub(), name="gf-admission-worker-wait"
                    )
                reply = await asyncio.wait_for(
                    asyncio.shield(future), self.config.request_wait_ms / 1000
                )
            for _ in range(self.rpc_attempts):
                if reply["state"] != "READY_RESERVED":
                    break
                reply = await self.rpc(
                    self.data(
                        "claim",
                        nonce,
                        attempt,
                        lease_id=reply["lease_id"],
                        expected_revision=reply["revision"],
                    )
                )
            if reply["state"] == "UNAVAILABLE":
                # Advance only after an authoritative no-reservation result.
                # RPC retries and ACK recovery within this call keep the same key.
                self.rounds[nonce, attempt] += 1
                return None
            if reply["state"] != "CLAIMED":
                raise RuntimeError("admission transaction ended: " + reply["state"])
            return reply
        except BaseException:
            await self.cancel(nonce, attempt)
            raise
        finally:
            self.pending.pop(key, None)
            self.pending_identity.pop(key, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # collect a concurrent WaitHub failure

    def shadow(self, nonce, attempt, payload, request):
        if self.closed or len(self.shadow_tasks) >= self.config.feature_max_inflight:
            self.metrics["shadow_dropped"] += 1
            return

        async def observe():
            await self.hello()
            features = (
                await self.provider.extract(request, payload)
                if self.provider
                else {"cost": None}
            )
            await self.rpc(
                self.data("enqueue", nonce, attempt, payload=dict(payload, **features))
            )
            await self.rpc(self.data("finish", nonce))

        task = asyncio.create_task(observe(), name="gf-admission-shadow")
        self.shadow_tasks.add(task)

        def done(task):
            self.shadow_tasks.discard(task)
            if not task.cancelled() and task.exception() is not None:
                self.metrics["shadow_failed"] += 1
                logger.error(
                    "Admission shadow observation failed: %s",
                    type(task.exception()).__name__,
                )

        task.add_done_callback(done)

    async def finish(self, nonce):
        if self.epoch is not None and self.config.mode == "enforce":
            await self.rpc(self.data("finish", nonce))
            self.rounds = {k: v for k, v in self.rounds.items() if k[0] != nonce}

    async def close(self):
        self.closed = True
        tasks = list(self.shadow_tasks)
        if self.hub is not None:
            tasks.append(self.hub)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for nonce, attempt in list(self.pending_identity.values()):
            await self.cancel(nonce, attempt)
        if self.provider is not None:
            await self.provider.close()
        logger.info(
            "gf_admission_client_close counters=%s pending=%s",
            self.metrics,
            len(self.pending),
        )


def motor_sender(client, config):
    """Use the pinned transport's typed cancellation result, not send_request()."""
    from motor.coordinator.scheduler.runtime.zmq_protocol import SchedulerRequest

    if config.wait_ms + 500 >= client._transport._timeout * 1000:
        raise ValueError("admission wait exceeds Motor client timeout minus headroom")

    async def send(data):
        result = await client._transport.send_request_result(
            SchedulerRequest(
                request_type="fgjsq_v1", request_id=uuid.uuid4().hex, data=data
            )
        )
        if result.failure_reason == "cancelled":
            raise asyncio.CancelledError()
        response = result.response
        if response is None:
            return None
        if response.response_type != "success":
            raise RuntimeError("admission RPC refused: " + str(response.error))
        return response.data or {}

    return send
