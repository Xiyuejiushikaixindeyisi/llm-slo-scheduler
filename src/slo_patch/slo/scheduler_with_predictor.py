# 来源：260807 dev 仓 ascend_vllm/patch/slo/scheduler_with_predictor.py —— 逐行复制，改动：
#   1. import 路径 ascend_vllm.patch.slo.* -> slo_patch.slo.*（3 处；create_predictor/PredictorConfig
#      改从具体模块引入，对应原 ascend_vllm/patch/slo/__init__.py 的再导出）
#   2. _log_schedule_diagnostics 中 scheduled_cached_reqs.req_ids 改为防御性取 len
#      （vllm 0.23.0 的 SchedulerOutput.scheduled_cached_reqs 结构与 260807 目标版本可能不同）
"""SchedulerWithPredictor: a RecomputeScheduler subclass with SLO predictor.

SLO downgrade: when a request's predicted TTFT exceeds its SLO deadline,
we mark it with a deprioritized slo_priority but still accept it.

SLO-aware batching (3.5.3): before schedule() runs, we pre-filter the
waiting queue so that only requests compatible with the most-urgent
request's deadline are admitted. Deferred requests are re-enqueued after
schedule() completes.

Enabled via additional-config:
  {"scheduler_with_predictor_enable": true}

SLO and batch reporter are controlled by environment variables:
  ENABLE_VLLM_TTFT_SLO_MS  - TTFT SLO target in ms (0=disabled)
  ENABLE_BATCH_REPORTER     - Enable batch reporter (1=on, 0=off)
"""
import os
import queue
import threading
import time

from vllm.logger import logger
from vllm.v1.request import Request

from vllm_ascend.core.recompute_scheduler import RecomputeScheduler

# [fix-async] 2026-09-22 Phase 5.2 崩溃修复：D 侧 async-scheduling 实例的调度器
# 必须保留 AsyncScheduler 契约（_update_after_schedule/_update_request_with_output
# 中的 MTP spec-token 记账）。原生 D 在 async_scheduling 下选用
# AsyncRecomputeScheduler；若直接用同步 RecomputeScheduler 基类跑在
# step_with_batch_queue 循环里，spec 记账缺失 → SWA in_flight=-num_spec_tokens
# → recompute_scheduler.py:904 assert num_tokens_scheduled > 0 → EngineDead。
# 根因证据见 exp_records/manifest.md 2026-09-22 条目（g2/g3 崩溃定位）。
try:
    from vllm_ascend.core.recompute_scheduler import AsyncRecomputeScheduler

    _HAS_ASYNC_RECOMPUTE = True
except ImportError:  # pragma: no cover —— 容器 vllm-ascend 0.23.0 已含该类
    _HAS_ASYNC_RECOMPUTE = False

from slo_patch.slo.batch_reporter import BatchReporter
from slo_patch.slo.predictor_impl import create_predictor
from slo_patch.slo.predictor import PredictorConfig
from slo_patch.slo.batch_event_reporter import BatchEventReporter

_ENV_ENABLE_SLO_MS = "ENABLE_VLLM_TTFT_SLO_MS"
_ENV_ENABLE_BATCH_REPORTER = "ENABLE_BATCH_REPORTER"
SKIPPED_WARMUP_REQUESTS = 2


class SchedulerWithPredictor(RecomputeScheduler):
    """RecomputeScheduler with SLO predictor and batch reporter support."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        ttft_slo_ms = int(os.getenv(_ENV_ENABLE_SLO_MS, "0") or 0)
        batch_reporter_flag = int(os.getenv(_ENV_ENABLE_BATCH_REPORTER, "0") or 0)

        if ttft_slo_ms != 0:
            raise ValueError("Admission scheduling is outside the FGJSQ baseline")
        self._slo_enabled = False
        self._batch_reporter_enabled = bool(batch_reporter_flag)

        if self._slo_enabled or self._batch_reporter_enabled:
            self._init_predictor()
        else:
            self.predictor = None

        if self._slo_enabled:
            self.ttft_slo = ttft_slo_ms / 1000.0
            from vllm.v1.core.sched.request_queue import SchedulingPolicy
            self.policy = SchedulingPolicy.PRIORITY
            logger.info("[slo] scheduler config: ttft_slo=%.3fs", self.ttft_slo)

        if self._batch_reporter_enabled:
            self.batch_reporter = BatchReporter()
            logger.info("[slo] batch reporter enabled")
            additional_config = getattr(self.vllm_config, 'additional_config', None) or {}
            addr = additional_config.get("api_server_host", "")
            port = additional_config.get("api_server_port", 0)
            if addr and port:
                self._batch_event_reporter = BatchEventReporter(addr=addr, port=port)
            else:
                raise RuntimeError("P reporter requires api_server_host and api_server_port")
        else:
            self._batch_event_reporter = None

        self.skipped_warmup_requests = 0
        self._last_cache_hit_rate = 0.8

        self._schedule_step_counter = 0
        self._predict_total_ms = 0.0
        self._predict_call_count = 0
        self._max_deferred_per_step = 999

    def _init_predictor(self):
        try:
            self.predictor = create_predictor(PredictorConfig())
            logger.info(
                "[slo] predictor assigned to scheduler: id=%d, type=%s, predictor=%s",
                id(self), type(self).__name__,
                type(self.predictor).__name__ if self.predictor else "None")
        except Exception as e:
            logger.error(
                "[slo] failed to create predictor: %s. "
                "P baseline startup cannot continue.", e)
            raise RuntimeError("P predictor initialization failed") from e

    def add_request(self, request: Request) -> None:
        self.skipped_warmup_requests += 1
        if self.skipped_warmup_requests < SKIPPED_WARMUP_REQUESTS:
            return super().add_request(request)

        if self._slo_enabled:
            self._slo_downgrade(request)

        return super().add_request(request)

    def update_from_output(self, scheduler_output, model_runner_output):
        predictor = self.predictor
        exec_batch_size = getattr(scheduler_output, 'exec_batch_size', None)

        if exec_batch_size is None or predictor is None:
            return super().update_from_output(scheduler_output, model_runner_output)

        if hasattr(scheduler_output, 'total_cache_hit_rate'):
            self._last_cache_hit_rate = scheduler_output.total_cache_hit_rate

        result = super().update_from_output(scheduler_output, model_runner_output)

        t0 = time.perf_counter()
        _ensure_update_thread()
        _update_queue.put((
            predictor,
            {
                "actual_ttft": scheduler_output.actual_batch_exec_time,
                "predicted_ttft": scheduler_output.predicted_batch_exec_time,
                "batch_size": scheduler_output.exec_batch_size,
                "avg_prompt_length": scheduler_output.avg_prompt_length,
                "cache_hit_rate": scheduler_output.total_cache_hit_rate,
            },
            {
                "total_prompt_tokens": scheduler_output.total_prompt_tokens,
                "total_computed_tokens": scheduler_output.total_computed_tokens,
            },
        ))
        logger.info("[slo] update consumed %.3f ms",
                    (time.perf_counter() - t0) * 1000)

        return result

    def _slo_downgrade(self, request: Request) -> None:
        if "probe-infer-req" in request.request_id:
            logger.debug("[slo] skipping SLO check for probe request: %s",
                         request.request_id)
            return

        predictor = self.predictor
        if predictor is None:
            return

        try:
            t_pred_start = time.perf_counter()
            predicted_batch_exec_time = predictor.predict(
                batch_size=1,
                avg_prompt_length=request.num_prompt_tokens,
                cache_hit_rate=self._last_cache_hit_rate)
            t_pred_ms = (time.perf_counter() - t_pred_start) * 1000
            self._predict_total_ms += t_pred_ms
            self._predict_call_count += 1
            predicted_ttft = predicted_batch_exec_time / 1000.0
        except Exception:
            N_uncached = 1 * request.num_prompt_tokens * (1 - self._last_cache_hit_rate)
            predicted_batch_exec_time = N_uncached * 0.01
            predicted_ttft = predicted_batch_exec_time / 1000.0
            logger.warning(
                "[slo] predictor.predict failed for request_id=%s, "
                "using heuristic fallback",
                request.request_id, exc_info=True)

        deadline = request.arrival_time + self.ttft_slo
        slack_time = deadline - time.time() - predicted_ttft

        request.deadline = deadline
        request.predicted_ttft_entry = predicted_ttft

        request.slo_priority = slack_time
        request.priority = int(slack_time * 1e6)

        if slack_time < 0:
            logger.warning(
                "[slo] DOWNGRADED: request_id=%s, prompt_tokens=%d, "
                "predicted_ttft=%.3fs, slack_time=%.3fs, "
                "deadline=%.3f, priority=%d",
                request.request_id, request.num_prompt_tokens,
                predicted_ttft, slack_time, deadline, request.priority)
        else:
            logger.info(
                "[slo] request_id=%s, prompt_tokens=%d, "
                "predicted_ttft=%.3fs, slack_time=%.3fs, "
                "arrival_time=%.3f, deadline=%.3f, slo_priority=%.6f, priority=%d",
                request.request_id, request.num_prompt_tokens,
                predicted_ttft, slack_time,
                request.arrival_time, deadline, request.slo_priority, request.priority)

    def schedule(self):
        if len(self.waiting) <= 1:
            return super().schedule()

        deferred = self._slo_prefilter_waiting()

        result = super().schedule()

        if deferred:
            for r in deferred:
                self.waiting.add_request(r)

        self._schedule_step_counter += 1
        if self._schedule_step_counter % 100 == 0:
            self._log_schedule_diagnostics(result)

        return result

    def _log_schedule_diagnostics(self, result):
        waiting_reqs = []
        if self.waiting:
            for r in self.waiting:
                waiting_reqs.append({
                    'id': r.request_id[-8:],
                    'priority': getattr(r, 'priority', 0),
                    'slo_priority': getattr(r, 'slo_priority', None),
                    'prompt_tokens': r.num_prompt_tokens,
                    'arrival_time': getattr(r, 'arrival_time', 0),
                    'deadline': getattr(r, 'deadline', None),
                })

        if not waiting_reqs:
            return

        priorities = [w['priority'] for w in waiting_reqs]
        prompt_tokens = [w['prompt_tokens'] for w in waiting_reqs]
        slo_priorities = [w['slo_priority'] for w in waiting_reqs if w['slo_priority'] is not None]

        unique_priorities = len(set(priorities))

        priority_token_corr = 0.0
        if len(prompt_tokens) > 1 and len(set(prompt_tokens)) > 1:
            import statistics
            pt_mean = statistics.mean(prompt_tokens)
            pr_mean = statistics.mean(priorities)
            pt_std = statistics.stdev(prompt_tokens)
            pr_std = statistics.stdev(priorities)
            if pt_std > 0 and pr_std > 0:
                n = len(prompt_tokens)
                priority_token_corr = sum(
                    (prompt_tokens[i] - pt_mean) * (priorities[i] - pr_mean)
                    for i in range(n)
                ) / (n * pt_std * pr_std)

        try:
            num_scheduled_cached = len(result.scheduled_cached_reqs)
        except TypeError:
            num_scheduled_cached = len(getattr(result.scheduled_cached_reqs, 'req_ids', []) or [])

        logger.info(
            "[slo] step=%d, waiting=%d, running=%d, "
            "unique_priorities=%d/%d, "
            "prompt_tokens=[min=%d,max=%d,avg=%.0f], "
            "priority_range=[%d,%d], "
            "slo_priority_range=[%.3f,%.3f], "
            "priority_token_corr=%.3f, "
            "scheduled_new=%d, scheduled_cached=%d, "
            "predict_avg=%.3fms, predict_calls=%d, predict_total=%.1fms",
            self._schedule_step_counter,
            len(waiting_reqs), len(self.running),
            unique_priorities, len(priorities),
            min(prompt_tokens), max(prompt_tokens),
            sum(prompt_tokens) / len(prompt_tokens),
            min(priorities), max(priorities),
            min(slo_priorities) if slo_priorities else 0,
            max(slo_priorities) if slo_priorities else 0,
            priority_token_corr,
            len(result.scheduled_new_reqs),
            num_scheduled_cached,
            self._predict_total_ms / self._predict_call_count if self._predict_call_count > 0 else 0,
            self._predict_call_count,
            self._predict_total_ms,
        )

        if len(waiting_reqs) <= 10:
            for w in sorted(waiting_reqs, key=lambda x: x['priority']):
                # [p3d-fix] g2（SLO 关）下 slo_priority/deadline 键存在但值为 None，
                # .get(key, 0) 不生效 → %.3f 格式化 TypeError（"--- Logging error ---"
                # 刷屏并污染 crash/OOM 扫描门）。改 or 0 兜底，仅影响诊断日志显示。
                logger.info(
                    "[slo] id=%s, priority=%d, slo_priority=%.3f, "
                    "prompt_tokens=%d, arrival_time=%.3f, deadline=%.3f",
                    w['id'], w['priority'], w.get('slo_priority') or 0,
                    w['prompt_tokens'], w['arrival_time'],
                    w.get('deadline') or 0)

    def _slo_prefilter_waiting(self):
        if not self._slo_enabled or self.predictor is None:
            return None

        if not self.waiting:
            return []

        t_start = time.monotonic()

        all_requests = []
        while self.waiting:
            all_requests.append(self.waiting.pop_request())

        if not all_requests:
            return []

        slo_requests = [r for r in all_requests if hasattr(r, 'deadline')]
        no_slo_requests = [r for r in all_requests if not hasattr(r, 'deadline')]

        if not slo_requests:
            for r in all_requests:
                self.waiting.add_request(r)
            return []

        slo_requests.sort(key=lambda r: getattr(r, 'slo_priority', float('inf')))

        H = slo_requests[0]
        now = time.time()
        T_remain = H.deadline - now

        if T_remain <= 0:
            logger.debug(
                "[slo] most-urgent request H=%s already past deadline "
                "(T_remain=%.3fs), skipping SLO batch filter",
                H.request_id, T_remain)
            for r in all_requests:
                self.waiting.add_request(r)
            return []

        batch = [H] + no_slo_requests
        deferred = []

        for r in slo_requests[1:]:
            if len(deferred) >= self._max_deferred_per_step:
                batch.append(r)
                continue

            candidate_batch_size = len(self.running) + len(batch) + 1
            avg_prompt_len = (
                sum(req.num_prompt_tokens for req in batch) + r.num_prompt_tokens
            ) / (len(batch) + 1)

            try:
                predicted_ttft_ms = self.predictor.predict(
                    batch_size=candidate_batch_size,
                    avg_prompt_length=avg_prompt_len,
                    cache_hit_rate=self._last_cache_hit_rate)
                predicted_ttft = predicted_ttft_ms / 1000.0
            except Exception:
                predicted_ttft = self.ttft_slo * 0.5
                logger.warning(
                    "[slo] predictor.predict() failed, using fallback "
                    "predicted_ttft=%.3fs", predicted_ttft)

            if predicted_ttft <= T_remain:
                batch.append(r)
            else:
                deferred.append(r)
                logger.info(
                    "[slo] DEFERRED: request_id=%s, predicted_ttft=%.3fs, "
                    "T_remain=%.3fs, candidate_batch_size=%d, "
                    "avg_prompt_len=%.1f",
                    r.request_id, predicted_ttft, T_remain,
                    candidate_batch_size, avg_prompt_len)

        for r in batch:
            self.waiting.add_request(r)

        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.info(
            "[slo] prefilter done: admitted=%d, deferred=%d, "
            "T_remain=%.3fs, elapsed=%.3fms",
            len(batch), len(deferred), T_remain, elapsed_ms)

        return deferred


_update_queue = queue.Queue()
_update_thread_started = False
_update_lock = threading.Lock()


def _update_worker():
    while True:
        try:
            item = _update_queue.get()
            if item is None:
                break
            predictor, kwargs, log_extra = item

            batch_size = kwargs["batch_size"]
            avg_prompt_length = kwargs["avg_prompt_length"]
            cache_hit_rate = kwargs["cache_hit_rate"]
            actual_ttft = kwargs["actual_ttft"]
            predicted_ttft = kwargs["predicted_ttft"]

            if (
                    batch_size <= 0 or
                    avg_prompt_length <= 0 or
                    cache_hit_rate < 0 or cache_hit_rate > 1 or
                    actual_ttft < 0 or actual_ttft > 100000
            ):
                logger.warning(
                    "[slo] predictor.update skipped: invalid input "
                    "batch_size=%d, avg_prompt_length=%.2f, cache_hit_rate=%.4f, "
                    "actual_ttft=%.2fms, predicted_ttft=%.2fms",
                    batch_size, avg_prompt_length, cache_hit_rate,
                    actual_ttft, predicted_ttft)
                continue

            predictor.update(**kwargs)
            # [Phase 5.5 Q1 批复 2026-09-24] 在线精度观测行默认 debug（与 260807 原版一致）；
            # SLO_LOG_ACCURACY=1 时提为 info 落盘（vllm 默认 INFO 级，debug 行不采集）。
            # env 门控：非压测运行不设置该 env → 行为零变化。
            _acc_logger = (logger.info
                           if os.getenv("SLO_LOG_ACCURACY", "0") not in ("", "0")
                           else logger.debug)
            _acc_logger(
                "[slo] predictor update:"
                "actual_batch_exec_time=%.6f, predicted_batch_exec_time=%.6f, error=%.6f, "
                "exec_batch_size=%d, "
                "total_prompt_tokens=%d, total_computed_tokens=%d, total_cache_hit_rate=%f, "
                "warmup_done=%s",
                actual_ttft,
                predicted_ttft,
                actual_ttft - predicted_ttft,
                batch_size,
                log_extra.get("total_prompt_tokens", 0),
                log_extra.get("total_computed_tokens", 0),
                cache_hit_rate,
                predictor.warmup_done,
            )
        except Exception as e:
            logger.warning(
                "[slo] predictor.update() failed for exception: %s",
                str(e), exc_info=True)
        finally:
            _update_queue.task_done()


def _ensure_update_thread():
    global _update_thread_started
    if _update_thread_started:
        return
    with _update_lock:
        if _update_thread_started:
            return
        t = threading.Thread(target=_update_worker, daemon=True)
        t.start()
        _update_thread_started = True


if _HAS_ASYNC_RECOMPUTE:
    class SchedulerWithPredictorAsync(SchedulerWithPredictor, AsyncRecomputeScheduler):
        """[fix-async] async-scheduling 实例（D 侧）的调度器载体。

        MRO = [SchedulerWithPredictorAsync, SchedulerWithPredictor,
        AsyncRecomputeScheduler, AsyncScheduler, RecomputeScheduler, Scheduler]：
        - SWP.__init__ 最先执行（predictor/reporter 装配），其 super() 链依次经过
          AsyncRecomputeScheduler（透传）、AsyncScheduler（spec 占位记账）、
          RecomputeScheduler（is_mtp_kv_consumer 等）、Scheduler；
        - SWP.schedule()/update_from_output() 覆写保持最优先（SLO 打点语义不变），
          其 super() 调用落到 Async 基类契约上（与原生 D 等价）。
        由 patch_runtime.Hook1 在 scheduler_config.async_scheduling 时选用。
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)