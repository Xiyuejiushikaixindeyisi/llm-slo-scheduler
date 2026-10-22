"""Bounded adapter to the pinned Motor tokenizer/Conductor protocol.

The compatibility provider deliberately reuses Motor's existing query client,
including its authentication/tenant/encoding behavior. No new TLS assumptions.
It is synchronous in a single dedicated thread, never under the scheduler lock.
"""

import asyncio
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

logger = logging.getLogger(__name__)


class MotorFeatureProvider:
    def __init__(self, admission_client):
        self.client = admission_client
        self.config = admission_client.config
        self.executor = None
        self.futures = set()
        self.closed = False
        self.metrics = Counter()

    def _done(self, future):
        self.futures.discard(future)
        if not future.cancelled():
            future.exception()

    def _extract_sync(self, request, candidates):
        from motor.common.resources.instance import Instance
        from motor.coordinator.api_client.conductor_api_client import (
            TENANT_ID,
            ConductorApiClient,
            conductor_instance_id,
        )
        from motor.coordinator.scheduler.policy.kv_cache_affinity import (
            KvCacheAffinityPolicy,
        )

        from .features import CostModel, FeatureSnapshot, TierCoverage

        # A separate metadata holder prevents late thread completion modifying
        # an HTTP request that has already timed out or begun forwarding.
        view = SimpleNamespace(
            req_data=request.req_data,
            token_ids=getattr(request, "token_ids", None),
            engine_token_ids=getattr(request, "engine_token_ids", None),
            effective_entry_api=lambda: request.entry_api or request.api,
        )
        tokens = KvCacheAffinityPolicy._ensure_token_ids(view)
        if not tokens:
            return {"cost": None}
        instances = [Instance.model_validate(c["instance"]) for c in candidates]
        block_size = KvCacheAffinityPolicy._conductor_block_size()
        if block_size <= 0 or not ConductorApiClient._kv_reg().conductor_service:
            return {"cost": None}
        raw = ConductorApiClient.query_conductor(instances, tokens)
        tenant = raw.get(TENANT_ID)
        if not isinstance(tenant, dict):
            return {"cost": None}
        coverages = []
        for instance, candidate in zip(instances, candidates):
            instance_data = tenant.get(conductor_instance_id(instance))
            if not isinstance(instance_data, dict):
                return {"cost": None}
            hit = instance_data.get("DP", {}).get(str(candidate["endpoint_id"]))
            # Missing entries differ from explicit zero blocks. Unlike the
            # original affinity router, absence must not classify as zero hits.
            if not isinstance(hit, dict) or any(
                k not in hit for k in ("npu_blocks", "cpu_blocks", "disk_blocks")
            ):
                return {"cost": None}
            values = [hit[k] for k in ("npu_blocks", "cpu_blocks", "disk_blocks")]
            if any(type(v) is not int or v < 0 for v in values):
                return {"cost": None}
            coverages.append(
                TierCoverage(
                    candidate["instance_id"],
                    candidate["endpoint_id"],
                    candidate["generation"],
                    *(v * block_size for v in values),
                )
            )
        snapshot = FeatureSnapshot(
            len(tokens),
            tuple(coverages),
            "motor-f203263d-tier-blocks",
            0,
            True,
            "known",
        )
        identities = tuple(
            (c.instance_id, c.endpoint_id, c.generation) for c in coverages
        )
        cost, _ = CostModel(
            self.config.beta_cpu, self.config.beta_disk, "experiment-tier-tokens-v1"
        ).estimate(snapshot, identities, now_ms=0, max_age_ms=1)
        return {"cost": cost, "candidate_generations": [list(i) for i in identities]}

    async def extract(self, request, payload):
        if self.closed or self.config.feature_kind == "unknown":
            self.metrics["unknown"] += 1
            return {"cost": None}
        if len(self.futures) >= self.config.feature_max_inflight:
            self.metrics["capacity_unknown"] += 1
            return {"cost": None}
        try:
            constraints = {
                k: v
                for k, v in payload.items()
                if k
                in (
                    "target_instance_id",
                    "required_engine_type",
                    "required_dispatch_capability",
                )
            }
            result = await self.client.rpc(
                self.client.data("features", constraints=constraints)
            )
            if not result["candidates"]:
                return {"cost": None}
            # Recheck after the RPC await: other requests may have filled slots.
            if len(self.futures) >= self.config.feature_max_inflight:
                self.metrics["capacity_unknown"] += 1
                return {"cost": None}
            if self.executor is None:
                self.executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="gf-feature"
                )
            future = asyncio.get_running_loop().run_in_executor(
                self.executor, self._extract_sync, request, result["candidates"]
            )
            self.futures.add(future)
            future.add_done_callback(self._done)
            result = await asyncio.wait_for(
                asyncio.shield(future), self.config.feature_timeout_ms / 1000
            )
            self.metrics["known" if result["cost"] is not None else "unknown"] += 1
            return result
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - transaction/task fault boundary
            self.metrics["unknown_" + type(error).__name__] += 1
            return {"cost": None}

    async def close(self):
        self.closed = True
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)
        if self.futures:
            # Existing Motor HTTP timeout is 3 seconds. A stuck tokenizer cannot
            # be force-killed by Python; report the bounded residual explicitly.
            _, pending = await asyncio.wait(
                tuple(self.futures), timeout=3 + self.config.feature_timeout_ms / 1000
            )
            self.metrics["shutdown_residual"] = len(pending)
        logger.info(
            "gf_admission_feature_close counters=%s outstanding=%s",
            dict(self.metrics),
            len(self.futures),
        )
