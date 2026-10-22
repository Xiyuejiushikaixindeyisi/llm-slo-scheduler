"""Create the reviewable Motor patch from the immutable design checkout."""
from pathlib import Path
import ast
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "upstream/motor"
WORK = ROOT / "artifacts/build/motor"
if not WORK.exists():
    subprocess.run(["git", "clone", "--no-hardlinks", str(BASE), str(WORK)], check=True)
    subprocess.run(["git", "-C", str(WORK), "switch", "-c", "codex/fgjsq-predictor-motor"], check=True)
changed = {}

def edit(path, replacements, imports=True):
    p = WORK / path
    source = p.read_text()
    original = subprocess.check_output(["git", "-C", str(BASE), "show", "HEAD:" + path], text=True)
    if source != original:
        raise RuntimeError("working file already modified: " + path)
    if imports:
        tree = ast.parse(source)
        nodes = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        last = max(n.end_lineno for n in nodes)
        lines = source.splitlines(keepends=True)
        lines.insert(last, "\nfrom motor_adapter import bindings as fgjsq_hooks\nfrom motor_adapter.config import enabled as fgjsq_enabled\n")
        source = "".join(lines)
    for old, new, count in replacements:
        if source.count(old) != count:
            raise RuntimeError("anchor count mismatch: " + path + " " + repr(old[:90]))
        source = source.replace(old, new)
    ast.parse(source)
    p.write_text(source)
    changed[path] = {"before": hashlib.sha256(original.encode()).hexdigest(),
                     "after": hashlib.sha256(source.encode()).hexdigest()}

edit("motor/coordinator/models/request.py", [
    ("    _p_cancel_scope: anyio.CancelScope | None = PrivateAttr(default=None)",
     "    _fgjsq_state: dict = PrivateAttr(default_factory=dict)\n    _p_cancel_scope: anyio.CancelScope | None = PrivateAttr(default=None)", 1)], imports=False)
edit("motor/coordinator/domain/scheduling.py", [
    ("    operation_id: str | None = None", "    operation_id: str | None = None\n    fgjsq_reservation_id: str | None = None\n    fgjsq_coordinator_epoch: str | None = None", 1),
    ("        target_instance_id: int | None = None,", "        attempt_seq: int | None = None,\n        target_instance_id: int | None = None,", 1)], imports=False)
edit("motor/coordinator/scheduler/runtime/scheduler_client.py", [
    ("        target_instance_id: int | None = None,", "        attempt_seq: int | None = None,\n        target_instance_id: int | None = None,", 1),
    ('        """Select locally, then CAS-commit on schema-4 SHM (no ALLOCATE_ONLY ZMQ)."""',
     '        """P FGJSQ uses Mgmt; disabled and D allocation retain native CAS."""\n        if fgjsq_enabled() and role == PDRole.ROLE_P:\n            return await fgjsq_hooks.allocate(\n                self, role, req_info, attempt_seq, target_instance_id=target_instance_id,\n                required_engine_type=required_engine_type,\n                required_dispatch_capability=required_dispatch_capability)\n', 1),
    ('        """Release path: CAS-sub floor 0 on schema-4 SHM (no UPDATE_WORKLOAD ZMQ)."""',
     '        """FGJSQ P release is idempotent; D/disabled retain CAS-sub."""\n        if fgjsq_enabled() and params.role == PDRole.ROLE_P:\n            return await fgjsq_hooks.native_release(self, params)\n', 1)])
edit("motor/coordinator/scheduler/runtime/scheduler_server.py", [
    ("        self._snapshot_dirty = False\n\n    async def dispatch", "        self._snapshot_dirty = False\n        fgjsq_hooks.init_dispatcher(self)\n\n    async def dispatch", 1),
    ('        """Dispatch control-plane request to the appropriate handler."""',
     '        """Dispatch control-plane request to the appropriate handler."""\n        if request.request_type == fgjsq_hooks.WIRE_TYPE:\n            return await fgjsq_hooks.dispatch(self, request)', 1)])
edit("motor/coordinator/api_server/management_server.py", [
    ("    def _register_routes(self) -> None:\n", "    def _register_routes(self) -> None:\n        fgjsq_hooks.register_routes(self)\n", 1)])
edit("motor/coordinator/router/strategies/unified_pd.py", [
    ("coordination_mode = self._select_coordination_mode(attempt)", "coordination_mode = self._select_coordination_mode(attempt)\n" + " "*24 + "fgjsq_hooks.validate_mode(coordination_mode)", 2),
    # Both call sites use 24 spaces; enforce compilation below.
    ('        scheduler_kwargs = {"target_instance_id": target_instance_id}',
     '        scheduler_kwargs = {"target_instance_id": target_instance_id}\n        if fgjsq_enabled() and role == PDRole.ROLE_P:\n            scheduler_kwargs["attempt_seq"] = attempt_seq', 1),
    ("        return engine_request.body, engine_request.api\n\n    @staticmethod\n    def _native_leg_context",
     "        return fgjsq_hooks.attach_request(self, attempt, role, engine_request.body), engine_request.api\n\n    @staticmethod\n    def _native_leg_context", 1),
    ("    async def _release_attempt(self, attempt: AttemptContext, *, wait: bool = True) -> None:\n",
     "    async def _release_attempt(self, attempt: AttemptContext, *, wait: bool = True) -> None:\n        await fgjsq_hooks.finish_attempt(self, attempt)\n", 1),
    ("            workload_change=workload_change,\n            # Deterministic id",
     "            workload_change=workload_change,\n            fgjsq_reservation_id=(fgjsq_hooks.metadata(self.req_info, attempt_seq) or {}).get('reservation_id')\n            if role == PDRole.ROLE_P and fgjsq_enabled() else None,\n            fgjsq_coordinator_epoch=(fgjsq_hooks.metadata(self.req_info, attempt_seq) or {}).get('coordinator_epoch')\n            if role == PDRole.ROLE_P and fgjsq_enabled() else None,\n            # Deterministic id", 1)])
edit("motor/coordinator/router/strategies/base.py", [
    ("        await self._request_manager.add_req_info(self.req_info)", "        fgjsq_hooks.validate_router(self)\n        await self._request_manager.add_req_info(self.req_info)", 1),
    ("                await self._reclaim_residual_workloads()\n                await self._request_manager.del_req_info",
     "                try:\n                    await self._reclaim_residual_workloads()\n                finally:\n                    await fgjsq_hooks.finish_request(self)\n                await self._request_manager.del_req_info", 1),
    ("        trace_obj = self.req_info.trace_obj\n        headers = {'Content-Type': 'application/json', 'X-Request-Id': self._forward_request_id(req_data)}",
     "        req_data, fg_observer = fgjsq_hooks.prepare_forward(self, req_data)\n        trace_obj = self.req_info.trace_obj\n        headers = {'Content-Type': 'application/json', 'X-Request-Id': self._forward_request_id(req_data)}", 2),
    ("            async for chunk in response.aiter_bytes():\n",
     "            async for chunk in response.aiter_bytes():\n                if fg_observer is not None:\n                    fg_observer.observe(chunk)\n", 1),
    ("            if streamed:\n                await response.aread()",
     "            if streamed:\n                if fg_observer is not None:\n                    if response.is_stream_consumed:\n                        fg_observer.observe(response.content)\n                    else:\n                        from motor_adapter.body_observer import ObservedStream\n                        response.stream = ObservedStream(response.stream, fg_observer)\n                await response.aread()\n            elif fg_observer is not None:\n                fg_observer.observe(response.content)", 1)])
(ROOT / "patches/motor/f203263d-files.json").write_text(json.dumps(changed, indent=2)+"\n")
diff = subprocess.check_output(["git", "-C", str(WORK), "diff", "--binary"], text=True)
(ROOT / "patches/motor/f203263d-p-fgjsq.patch").write_text(diff)
print("Motor working files:", len(changed))
