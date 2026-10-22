"""Run original and instrumented EngineCore methods against identical CPU fakes."""
import ast
from collections import deque
from concurrent.futures import Future
from contextlib import nullcontext
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_function(path, name):
    tree = ast.parse(path.read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    clock = iter(range(10000))
    ns = {"Future": Future, "ModelRunnerOutput": object, "cast": cast,
          "time": SimpleNamespace(monotonic=lambda: next(clock) / 1000),
          "logger": logging.getLogger("engine-test"),
          "_log_empty_batch": lambda *a: None,
          "_emit_batch_event": lambda *a: None,
          "_trace_completion": lambda *a: None,
          "_capture_batch_event": lambda *a: None}
    def predict(scheduler, output, prefix):
        output.feature_batch_id = output.batch_id
        output.predicted_batch_exec_time = 42
    ns["_predict_batch_exec_time"] = predict
    module = ast.Module(body=ast.parse("from __future__ import annotations").body + [node], type_ignores=[])
    exec(compile(module, str(path), "exec"), ns)
    return ns[name]


class Scheduler:
    def __init__(self):
        self.left = deque(range(3))
        self.results = []
    def has_requests(self):
        return bool(self.left)
    def schedule(self):
        i = self.left.popleft()
        return SimpleNamespace(batch_id=i, total_num_scheduled_tokens=100*(i+1),
                               pending_structured_output_tokens=False)
    def get_grammar_bitmask(self, output):
        return output.batch_id
    def update_from_output(self, output, value):
        assert value == output.batch_id
        if hasattr(output, "feature_batch_id"):
            assert output.feature_batch_id == value
            assert output.actual_batch_exec_time >= 0
        self.results.append(value)
        return {0: value}


class Executor:
    def execute_model(self, output, non_block=True):
        self.current = output.batch_id
        future = Future()
        future.set_result(output.batch_id)
        return future
    def sample_tokens(self, grammar, non_block=True):
        future = Future()
        future.set_result(grammar)
        return future


@pytest.mark.parametrize("async_mode", [False, True])
def test_overlay_preserves_batch_order_and_feature_label_pairing(async_mode):
    name = "step_with_batch_queue" if async_mode else "step"
    native = load_function(ROOT/"upstream/vllm-v0.23.0/vllm/v1/engine/core.py", name)
    patched = load_function(ROOT/"src/slo_patch/patch_core.py", "patched_"+name)
    runs = []
    for fn in (native, patched):
        scheduler = Scheduler()
        engine = SimpleNamespace(scheduler=scheduler, model_executor=Executor(), batch_queue=deque(),
                                 batch_queue_size=2, is_ec_consumer=True, is_pooling_model=False,
                                 use_spec_decode=False, _process_aborts_queue=lambda: None,
                                 log_error_detail=lambda output: nullcontext(),
                                 log_iteration_details=lambda output: nullcontext())
        outputs = []
        while scheduler.has_requests() or engine.batch_queue:
            outputs.append(fn(engine))
        runs.append((outputs, scheduler.results))
    assert runs[0] == runs[1]


def test_overlay_keeps_upstream_queue_capacity_assertion():
    fn = load_function(ROOT/"src/slo_patch/patch_core.py", "patched_step_with_batch_queue")
    with pytest.raises(AssertionError):
        fn(SimpleNamespace(batch_queue=deque([1,2]),batch_queue_size=2))
