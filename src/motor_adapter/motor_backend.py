"""Adapter to the pinned Motor schema-4 ledger; no changes to D CAS."""
from motor.common.resources.instance import PDRole
from motor.coordinator.scheduler.runtime.workload_shm.layout import FLAG_BLOCKED, FLAG_VALID
from motor.coordinator.scheduler.runtime.workload_shm.native import STATUS_OK


class MotorBackend:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher

    @property
    def native(self):
        writer = self.dispatcher._workload_writer
        if writer is None:
            raise RuntimeError("Motor workload writer not ready")
        native = writer.native
        if native.read_header()["schema_version"] != 4:
            raise RuntimeError("FGJSQ requires Motor SHM schema 4")
        return native

    def entries(self) -> dict:
        native = self.native
        result = {}
        for slot in range(native.read_header()["entry_count"]):
            entry = native.load_entry(slot)
            if entry["flags"] & FLAG_VALID:
                result[(entry["instance_id"], entry["endpoint_id"])] = {**entry, "slot": slot}
        return result

    def candidates(self, data: dict) -> list[dict]:
        if getattr(self.dispatcher, "_snapshot_dirty", False):
            raise RuntimeError("Motor instance snapshot is not committed")
        instances = self.dispatcher._instance_manager.get_available_instances(PDRole.ROLE_P)
        entries = self.entries()
        candidates = []
        for iid in sorted(instances):
            inst = instances[iid]
            breaker = getattr(self.dispatcher, "_cb_manager", None)
            if breaker is not None and breaker.is_open(iid):
                continue
            if data.get("target_instance_id") is not None and iid != data["target_instance_id"]:
                continue
            engine = str(getattr(inst, "engine_type", "")).lower()
            if engine != "vllm" or data.get("required_engine_type") not in (None, "", "vllm"):
                continue
            caps = list(getattr(inst, "dispatch_capabilities", None) or [])
            if "concurrent_engine_sync" in caps:
                raise ValueError("FGJSQ v1 requires HANDOFF, not TRIGGER")
            required = data.get("required_dispatch_capability")
            if required and required not in caps:
                continue
            endpoints = [ep for pod in (inst.endpoints or {}).values() for ep in (pod or {}).values()]
            if len(endpoints) != 1:
                raise ValueError("FGJSQ v1 requires exactly one endpoint per P instance")
            ep = endpoints[0]
            if ep.status != "normal" or ep.headless:
                continue
            entry = entries.get((iid, ep.id))
            if entry is None or entry["flags"] & FLAG_BLOCKED:
                continue
            candidates.append({**entry, "instance": inst.model_dump(mode="json"),
                               "endpoint": ep.model_dump(mode="json")})
        return candidates

    def reserve(self, candidate: dict, tokens: float) -> bool:
        status, _ = self.native.cas_add(candidate["instance_id"], candidate["endpoint_id"],
                                        candidate["generation"], candidate["active_tokens"], tokens,
                                        slot=candidate["slot"])
        return status == STATUS_OK

    def release(self, candidate: dict, tokens: float) -> bool:
        current = self.entries().get((candidate["instance_id"], candidate["endpoint_id"]))
        if current is None or current["generation"] != candidate["generation"]:
            # The old generation no longer has a ledger entry. Never subtract from its replacement.
            return True
        status, _ = self.native.cas_sub_floor0(candidate["instance_id"], candidate["endpoint_id"],
                                               candidate["generation"], tokens, slot=current["slot"])
        return status == STATUS_OK
