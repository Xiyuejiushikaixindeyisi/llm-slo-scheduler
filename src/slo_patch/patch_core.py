# 来源：260807 dev 仓 ascend_vllm/patch/platform/patch_core.py
#   - _predict_batch_exec_time: 原 :58-114（逐行保留）
#   - _emit_batch_event       : 原 :117-120（逐行保留）
#   - 打点插桩（patched_step / patched_step_with_batch_queue）：
#       插桩语义 = 260807 版本（[slo] 日志、exec_submit_time / was_queue_empty_at_submit /
#       actual_batch_exec_time / last_exec_finish_time、predict 与 emit 的插入位置）
#       控制流   = 容器 vllm 0.23.0 原生 EngineCore.step / step_with_batch_queue
#       （/vllm-workspace/vllm/vllm/v1/engine/core.py:443-599，Phase 2 已逐行比对；
#         差异点：260807 的 step_with_batch_queue 提前返回条件与本版本原生不同，
#         按 D8"同代码仅开关区分"原则，控制流以容器原生为准，只插入打点）
#   - 不含：_has_global_unfinished_reqs / _process_engine_step（GIL-yield、DP 补丁）
# 应用方式：patch_runtime._patch_engine_core_step()（环境变量门控，对齐原 :316-323）
import time
import uuid

from fgjsq.snapshot import freeze_snapshot

_ENGINE_EPOCH = uuid.uuid4().hex
from concurrent.futures import Future
from typing import cast

from vllm.logger import logger
from vllm.v1.engine import EngineCoreOutputs
from vllm.v1.outputs import ModelRunnerOutput


def _predict_batch_exec_time(scheduler, scheduler_output, log_prefix: str):
    predictor = getattr(scheduler, 'predictor', None)

    scheduled_req_ids = set(scheduler_output.num_scheduled_tokens.keys())
    if not predictor or len(scheduled_req_ids) == 0:
        return

    running_reqs = {
        r.request_id: r for r in scheduler.running
    }
    scheduled_reqs = [
        running_reqs[rid] for rid in scheduled_req_ids if rid in running_reqs
    ]

    total_prompt_tokens = sum(r.num_prompt_tokens for r in scheduled_reqs)
    total_computed_tokens = sum(r.num_computed_tokens for r in scheduled_reqs)
    total_cache_hit_rate = (
        (total_prompt_tokens - total_computed_tokens) / total_prompt_tokens
        if total_prompt_tokens != 0 else 0
    )
    exec_batch_size = len(scheduled_reqs)
    avg_prompt_length = total_prompt_tokens / exec_batch_size if exec_batch_size > 0 else 0
    scheduler_output.total_prompt_tokens = total_prompt_tokens if total_prompt_tokens > 0 else 0
    scheduler_output.total_computed_tokens = total_computed_tokens if total_prompt_tokens > 0 else 0
    scheduler_output.total_cache_hit_rate = total_cache_hit_rate if total_prompt_tokens > 0 else 0
    scheduler_output.exec_batch_size = exec_batch_size
    scheduler_output.avg_prompt_length = avg_prompt_length
    t1 = time.monotonic()
    predicted_batch_exec_time = predictor.predict(
        batch_size=exec_batch_size,
        avg_prompt_length=avg_prompt_length,
        cache_hit_rate=total_cache_hit_rate)
    scheduler_output.predicted_batch_exec_time = predicted_batch_exec_time
    t2 = time.monotonic()
    predict_time_consumed = (t2 - t1) * 1000
    logger.info("[slo] prediction consumed %.2f ms", predict_time_consumed)

    logger.debug(
        "[slo] %s "
        "exec_batch_size=%d "
        "total_prompt_tokens=%d "
        "total_computed_tokens=%d "
        "total_cache_hit_rate=%.4f "
        "avg_prompt_length=%.2f "
        "predicted_batch_exec_time=%.2f "
        "num_scheduled_tokens=%s "
        "scheduled_req_ids=%s",
        log_prefix,
        exec_batch_size,
        total_prompt_tokens,
        total_computed_tokens,
        total_cache_hit_rate,
        avg_prompt_length,
        predicted_batch_exec_time,
        scheduler_output.num_scheduled_tokens,
        scheduled_req_ids,
    )


def _capture_batch_event(self, scheduler_output):
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


def _emit_batch_event(self, scheduler_output):
    reporter = getattr(self.scheduler, '_batch_event_reporter', None)
    if reporter is not None:
        reporter.emit(scheduler_output, self.scheduler.requests)


def _log_empty_batch(self, scheduler_output):
    """260807 patch_step 的空批诊断，字段访问做了防御（0.23.0 的
    SchedulerOutput.scheduled_cached_reqs 结构可能与 260807 目标版本不同）。"""
    try:
        num_cached = len(scheduler_output.scheduled_cached_reqs)
    except TypeError:
        num_cached = -1
    logger.warning(
        "[slo] core-step empty batch: "
        "num_running=%d num_waiting=%d "
        "num_new_reqs=%d num_cached_reqs=%d "
        "finished_req_ids=%s",
        len(self.scheduler.running),
        len(self.scheduler.waiting),
        len(scheduler_output.scheduled_new_reqs),
        num_cached,
        scheduler_output.finished_req_ids,
    )


def patched_step(self) -> tuple[dict[int, EngineCoreOutputs], bool]:
    """vllm 0.23.0 原生 EngineCore.step + SLO 打点（用于非 async-scheduling 实例，由实际 async_scheduling 决定）。"""
    # Check for any requests remaining in the scheduler - unfinished,
    # or finished and not yet removed from the batch.
    if not self.scheduler.has_requests():
        return {}, False
    t0 = time.monotonic()
    scheduler_output = self.scheduler.schedule()
    t1 = time.monotonic()
    logger.info("[slo] core-step schedule() took %.2f ms", (t1 - t0) * 1000)

    if scheduler_output.total_num_scheduled_tokens == 0:
        _log_empty_batch(self, scheduler_output)

    _predict_batch_exec_time(self.scheduler, scheduler_output, "core-step schedule()")
    _capture_batch_event(self, scheduler_output)

    _emit_batch_event(self, scheduler_output)

    t2 = time.monotonic()
    future = self.model_executor.execute_model(scheduler_output, non_block=True)
    scheduler_output.exec_submit_time = t2
    grammar_output = self.scheduler.get_grammar_bitmask(scheduler_output)
    with (
        self.log_error_detail(scheduler_output),
        self.log_iteration_details(scheduler_output),
    ):
        model_output = future.result()
        t3 = time.monotonic()
        scheduler_output.actual_batch_exec_time = (t3 - scheduler_output.exec_submit_time) * 1000
        _trace_completion(scheduler_output)
        logger.info("[slo] core-step execute_model() took %.2f ms", scheduler_output.actual_batch_exec_time)
        if model_output is None:
            model_output = self.model_executor.sample_tokens(grammar_output)

    self._process_aborts_queue()
    engine_core_outputs = self.scheduler.update_from_output(
        scheduler_output, model_output
    )

    return engine_core_outputs, scheduler_output.total_num_scheduled_tokens > 0


def patched_step_with_batch_queue(
        self,
) -> tuple[dict[int, EngineCoreOutputs] | None, bool]:
    """vllm 0.23.0 原生 EngineCore.step_with_batch_queue + SLO 打点
    （用于 --async-scheduling 实例，由实际 async_scheduling 决定）。"""
    batch_queue = self.batch_queue
    assert batch_queue is not None
    assert len(batch_queue) < self.batch_queue_size

    model_executed = False
    deferred_scheduler_output = None

    if self.scheduler.has_requests():
        # [slo] 打点：schedule 耗时 + 批执行预测（260807 语义）
        t0 = time.monotonic()
        scheduler_output = self.scheduler.schedule()
        t1 = time.monotonic()
        logger.info("[slo] step_with_batch_queue schedule() took %.2f ms", (t1 - t0) * 1000)
        _predict_batch_exec_time(self.scheduler, scheduler_output, "step_with_batch_queue schedule()")
        _capture_batch_event(self, scheduler_output)

        with self.log_error_detail(scheduler_output):
            t2 = time.monotonic()
            exec_future = self.model_executor.execute_model(
                scheduler_output, non_block=True
            )
            t3 = time.monotonic()
            logger.info("[slo] step_with_batch_queue execute_model() submit took %.2f ms", (t3 - t2) * 1000)
        # [slo] 打点：提交时刻与队列状态（260807 语义，供 actual_batch_exec_time 计量）
        scheduler_output.exec_submit_time = t2
        scheduler_output.was_queue_empty_at_submit = len(batch_queue) == 0
        if scheduler_output.was_queue_empty_at_submit:
            _emit_batch_event(self, scheduler_output)

        if self.is_ec_consumer:
            model_executed = scheduler_output.total_num_scheduled_tokens > 0

        if self.is_pooling_model or not model_executed:
            # No sampling required (no requests scheduled).
            future = cast(Future[ModelRunnerOutput], exec_future)
        else:
            if not scheduler_output.pending_structured_output_tokens:
                # We aren't waiting for any tokens, get any grammar output
                # and sample immediately.
                grammar_output = self.scheduler.get_grammar_bitmask(
                    scheduler_output
                )
                future = self.model_executor.sample_tokens(
                    grammar_output, non_block=True
                )
            else:
                # We need to defer sampling until we have processed the model output
                # from the prior step.
                deferred_scheduler_output = scheduler_output

        if not deferred_scheduler_output:
            # Add this step's future to the queue.
            batch_queue.appendleft((future, scheduler_output, exec_future))
            if len(batch_queue) < self.batch_queue_size and (
                model_executed or self.scheduler.has_requests()
            ):
                # Don't block on next worker response unless the queue is full
                # or there are no more requests to schedule.
                return None, model_executed

    elif not batch_queue:
        # Queue is empty. We should not reach here since this method should
        # only be called when the scheduler contains requests or the queue
        # is non-empty.
        return None, False

    # Block until the next result is available.
    future, scheduler_output, exec_model_fut = batch_queue.pop()
    with (
        self.log_error_detail(scheduler_output),
        self.log_iteration_details(scheduler_output),
    ):
        # [slo] 打点：等待前上报队首批事件（260807 语义：每个 output 至少上报一次）
        if batch_queue:
            next_scheduler_output = batch_queue[-1][1]
            _emit_batch_event(self, next_scheduler_output)
        model_output = future.result()
        # [slo] 打点：实际批执行时间（流水线下用上一批完成时刻，260807 语义）
        t4 = time.monotonic()
        if scheduler_output.was_queue_empty_at_submit:
            exec_start_time = scheduler_output.exec_submit_time
        else:
            exec_start_time = getattr(self, 'last_exec_finish_time', scheduler_output.exec_submit_time)
        scheduler_output.actual_batch_exec_time = (t4 - exec_start_time) * 1000
        self.last_exec_finish_time = t4
        _trace_completion(scheduler_output)
        logger.info("[slo] step_with_batch_queue execute_model() wait took %.2f ms",
                    scheduler_output.actual_batch_exec_time)
        if model_output is None:
            # None from sample_tokens() implies that the original execute_model()
            # call failed - raise that exception.
            exec_model_fut.result()
            raise RuntimeError("unexpected error")

    # Before processing the model output, process any aborts that happened
    # during the model execution.
    self._process_aborts_queue()
    engine_core_outputs = self.scheduler.update_from_output(
        scheduler_output, model_output
    )

    if deferred_scheduler_output:
        # If we are doing speculative decoding with structured output,
        # we need to get the draft token ids from the prior step before
        # we can compute the grammar bitmask for the deferred request.
        if self.use_spec_decode:
            draft_token_ids = self.model_executor.take_draft_token_ids()
            assert draft_token_ids is not None
            self.scheduler.update_draft_token_ids_in_output(
                draft_token_ids, deferred_scheduler_output
            )
        # We now have the tokens needed to compute the bitmask for the
        # deferred request. Get the bitmask and call sample tokens.
        grammar_output = self.scheduler.get_grammar_bitmask(
            deferred_scheduler_output
        )
        future = self.model_executor.sample_tokens(grammar_output, non_block=True)
        batch_queue.appendleft((future, deferred_scheduler_output, exec_future))

    return engine_core_outputs, model_executed