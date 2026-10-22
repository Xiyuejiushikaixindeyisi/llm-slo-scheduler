from pathlib import Path
import ast
import hashlib
import json

r=Path("/home/zhangxiyue/llm-slo-scheduler")
raw=r/"evidence/source_drops/slo_patch/g4-20261015/slo_patch"
dst=r/"src/slo_patch"
for p in raw.rglob("*.py"):
    target=dst/p.relative_to(raw)
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists():
        target.write_bytes(p.read_bytes())
(dst/"slo/__init__.py").write_text('"""Legacy predictor implementation and P batch transport."""\n')
p=dst/"patch_core.py"
s=p.read_text()
s=s.replace("import time\n", "import time\nimport uuid\n\nfrom fgjsq.snapshot import freeze_snapshot\n\n_ENGINE_EPOCH = uuid.uuid4().hex\n")
s=s.replace("def _emit_batch_event(self, scheduler_output):", '''def _capture_batch_event(self, scheduler_output):
    seq = getattr(self, "_fgjsq_batch_seq", 0)
    self._fgjsq_batch_seq = seq + 1
    scheduler_output._fgjsq_batch_seq = seq
    scheduler_output._fgjsq_snapshot = freeze_snapshot(
        scheduler_output, self.scheduler.requests, _ENGINE_EPOCH, seq)


def _trace_completion(scheduler_output):
    seq = getattr(scheduler_output, "_fgjsq_batch_seq", -1)
    if seq < 5 or seq % 100 == 0:
        logger.info("[fgjsq-batch] epoch=%s batch=%s B=%s Lavg=%s residual=%s predicted_ms=%s actual_ms=%s",
                    _ENGINE_EPOCH, seq, getattr(scheduler_output, "exec_batch_size", None),
                    getattr(scheduler_output, "avg_prompt_length", None),
                    getattr(scheduler_output, "total_cache_hit_rate", None),
                    getattr(scheduler_output, "predicted_batch_exec_time", None),
                    getattr(scheduler_output, "actual_batch_exec_time", None))


def _emit_batch_event(self, scheduler_output):''')
s=s.replace('_predict_batch_exec_time(self.scheduler, scheduler_output, "core-step schedule()")',
            '_predict_batch_exec_time(self.scheduler, scheduler_output, "core-step schedule()")\n    _capture_batch_event(self, scheduler_output)')
s=s.replace('_predict_batch_exec_time(self.scheduler, scheduler_output, "step_with_batch_queue schedule()")',
            '_predict_batch_exec_time(self.scheduler, scheduler_output, "step_with_batch_queue schedule()")\n        _capture_batch_event(self, scheduler_output)')
s=s.replace("    assert batch_queue is not None\n", "    assert batch_queue is not None\n    assert len(batch_queue) < self.batch_queue_size\n")
s=s.replace("        scheduler_output.actual_batch_exec_time = (t3 - scheduler_output.exec_submit_time) * 1000",
            "        scheduler_output.actual_batch_exec_time = (t3 - scheduler_output.exec_submit_time) * 1000\n        _trace_completion(scheduler_output)")
s=s.replace("        self.last_exec_finish_time = t4", "        self.last_exec_finish_time = t4\n        _trace_completion(scheduler_output)")
s=s.replace("如 P", "由实际 async_scheduling 决定").replace("如 D", "由实际 async_scheduling 决定")
ast.parse(s);p.write_text(s)
p=dst/"patch_runtime.py";s=p.read_text()
t=ast.parse(s);f=next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=="apply_all")
ls=s.splitlines(keepends=True)
ls[f.lineno-1:f.end_lineno]=['''def apply_all() -> None:
    """Strict P installation. Admission remains disabled."""
    _patch_scheduler_swap()
    _patch_engine_core_step()
    if os.getenv(_ENV_TOLERATE_BAD_TOOL_ARGS, "0") == "1":
        _patch_chat_utils_tool_args()
    if os.getenv("P3D_KV_DEBUG", "0") == "1":
        _patch_kv_events_debug()
    if os.getenv("P3D_KV_EVENTS_FIX", "0") == "1":
        _patch_multi_connector_kv_events()
    logger.info("[fgjsq] P hooks installed; feature=g4_legacy_v1 label=g4_host_observed_v1")
''']
s="".join(ls)
s=s.replace("        additional_config = vllm_config.additional_config or {}",
            '        additional_config = vllm_config.additional_config or {}\n        if not additional_config.get("scheduler_with_predictor_enable", False):\n            raise RuntimeError("P FGJSQ requires scheduler_with_predictor_enable=true")')
ast.parse(s);p.write_text(s)
p=dst/"slo/scheduler_with_predictor.py";s=p.read_text()
s=s.replace("        self._slo_enabled = ttft_slo_ms > 0",
            '        if ttft_slo_ms != 0:\n            raise ValueError("Admission scheduling is outside the FGJSQ baseline")\n        self._slo_enabled = False')
s=s.replace('            else:\n                self._batch_event_reporter = None\n                logger.warning("[slo] batch_event: no api_server_host/port in additional_config, "\n                               "reporter disabled")',
            '            else:\n                raise RuntimeError("P reporter requires api_server_host and api_server_port")')
s=s.replace("            self.predictor = None\n\n    def add_request", '            raise RuntimeError("P predictor initialization failed") from e\n\n    def add_request')
p.write_text(s);ast.parse(s)
modules={
 "vllm.v1.engine.core":"upstream/vllm-v0.23.0/vllm/v1/engine/core.py",
 "vllm.v1.core.sched.async_scheduler":"upstream/vllm-v0.23.0/vllm/v1/core/sched/async_scheduler.py",
 "vllm_ascend.core.recompute_scheduler":"upstream/vllm-ascend-v0.23.0/vllm_ascend/core/recompute_scheduler.py",
}
(dst/"engine_files.json").write_text(json.dumps({m:hashlib.sha256((r/p).read_bytes()).hexdigest() for m,p in modules.items()},indent=2)+"\n")
p=r/"src/motor_adapter/bindings.py"
s=p.read_text()+'''

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
'''
p.write_text(s)
p=r/"src/motor_adapter/service.py";s=p.read_text()
s=s.replace("        self.metrics = Counter()", "        self.metrics = Counter()\n        self.cancelled: dict[str, float] = {}")
s=s.replace("    def _prune(self) -> None:\n", "    def _prune(self) -> None:\n        self.cancelled = {key: expiry for key, expiry in self.cancelled.items() if expiry > self.clock()}\n")
s=s.replace('            if r is None:\n                # Never subtract',
'''            if r is None:
                if op == "abort" and data.get("key"):
                    self.cancelled[data["key"]] = self.clock() + self.config.tombstone_s
                    return {"ok": True, "reason": "cancelled_before_reserve"}
                # Never subtract''')
s=s.replace('        key = data["key"]\n', '        key = data["key"]\n        if key in self.cancelled:\n            raise ValueError("attempt cancelled before reserve")\n')
p.write_text(s)
p=r/"pyproject.toml";p.write_text(p.read_text()+'\n[tool.setuptools.package-data]\nslo_patch = ["engine_files.json"]\n')
print("Engine overlay prepared; predictor implementation bytes preserved.")
