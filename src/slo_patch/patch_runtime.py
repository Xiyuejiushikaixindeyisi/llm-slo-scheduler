# 来源：调度器替换钩子对照 260807 dev 仓 ascend_vllm/platform.py:62-71（PatchNPUPlatform.check_and_update_config
#       中 scheduler_with_predictor_enable 分支），改写为对容器 vllm_ascend.platform.NPUPlatform 的
#       classmethod 包装（不继承、不注册 platform，避免 OOT 平台插件冲突——见 exp_records/PHASE0_closure.md §3）
# 生效时机：arg_utils create_engine_config 前 load_general_plugins() 已调用 activate()，
#       早于 VllmConfig 最终化 → check_and_update_config 被包装后才会被调用
import os

from vllm.logger import logger

_ENV_ENABLE_SLO_MS = "ENABLE_VLLM_TTFT_SLO_MS"
_ENV_ENABLE_BATCH_REPORTER = "ENABLE_BATCH_REPORTER"
# [p3d] 生产重放兼容开关（FGJSQ_3P3D）：默认 0=不干预，行为与上游 vllm 完全一致
_ENV_TOLERATE_BAD_TOOL_ARGS = "P3D_TOLERATE_BAD_TOOL_ARGS"


def apply_all() -> None:
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


def _patch_multi_connector_kv_events() -> None:
    """[p3d] Hook 5：补 MultiConnector.get_kv_connector_kv_cache_events 透传。

    背景（E0 2026-09-28 实证）：本镜像 vllm 的 MultiConnector 未实现
    get_kv_connector_kv_cache_events（multi_connector.py:372 TODO，WIP PR#31811），
    基类返回 None → KVConnectorOutput.kv_cache_events 恒 None → 调度器侧
    AscendStoreConnector.update_connector_output 收不到事件 → take_events 空 →
    ZmqEventPublisher 从不发布。kv_connector_model_runner_mixin.py:108 会调
    connector.get_kv_connector_kv_cache_events()（worker 侧），子连接器
    AscendStoreConnector/MooncakeStoreConnector 均已正确实现——只差 Multi 层透传。

    语义：按序取第一个非 None 的子连接器事件集**原对象透传**（调度器侧子连接器
    update_connector_output 按 isinstance(AscendStoreKVEvents/MooncakeStoreKVEvents)
    校验，故不能跨类型合并；当前拓扑实际只有 AscendStore 一处生产）。多生产者
    场景记 WARNING 取首个（本实验不出现）。
    """
    from vllm.distributed.kv_transfer.kv_connector.v1.multi_connector import (
        MultiConnector,
    )

    if getattr(MultiConnector, "_p3d_kv_events_patched", False):
        return

    def get_events(self):  # noqa: ANN001
        picked = None
        for c in getattr(self, "_connectors", []):
            try:
                ev = c.get_kv_connector_kv_cache_events()
            except Exception:  # noqa: BLE001
                ev = None
            if ev is None:
                continue
            if picked is not None and type(picked) is not type(ev):
                logger.warning("[slo_patch] multi-connector kv-events: 多类型生产者，仅透传首个（%s）",
                               type(picked).__name__)
                continue
            if picked is None:
                picked = ev
            else:
                picked.add_events(ev.get_all_events())
                picked.increment_workers(1)
        return picked

    MultiConnector.get_kv_connector_kv_cache_events = get_events
    MultiConnector._p3d_kv_events_patched = True
    logger.info("[slo_patch] MultiConnector.get_kv_connector_kv_cache_events "
                "-> 子连接器透传（p3d kv-events fix）")


def _patch_kv_events_debug() -> None:
    """[p3d] Hook 4（临时诊断）：包 BlockPool.cache_blocks / take_events /
    KVCacheManager.take_events / ZmqEventPublisher.publish，打 [kvdbg] 行。

    目的：E0 观测门实证 6 引擎 ZMQ publisher 已起、update_from_output 已跑，
    但 collector 收到 0 事件——定位断点在哪一环。仅诊断，不改行为。
    """
    counts = {"cb": 0, "bt": 0, "mt": 0, "pub": 0}

    import vllm.v1.core.block_pool as _bp
    import vllm.v1.core.kv_cache_manager as _km
    from vllm.distributed import kv_events as _ke

    orig_cb = getattr(_bp.BlockPool, "cache_full_blocks", None) \
        or getattr(_bp.BlockPool, "cache_blocks", None)
    if orig_cb is not None:
        def cb(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
            r = orig_cb(self, *a, **k)
            counts["cb"] += 1
            if counts["cb"] <= 3 or counts["cb"] % 200 == 0:
                logger.info("[kvdbg] cache_full_blocks#%d enabled=%s qsize=%d",
                            counts["cb"],
                            getattr(self, "enable_kv_cache_events", "MISSING"),
                            len(getattr(self, "kv_event_queue", [])))
            return r
        setattr(_bp.BlockPool, orig_cb.__name__, cb)

    orig_bt = _bp.BlockPool.take_events

    def bt(self):  # noqa: ANN001
        r = orig_bt(self)
        counts["bt"] += 1
        if r:
            logger.info("[kvdbg] block_pool.take_events -> %d events (call#%d)",
                        len(r), counts["bt"])
        return r

    _bp.BlockPool.take_events = bt

    orig_mt = _km.KVCacheManager.take_events

    def mt(self):  # noqa: ANN001
        r = orig_mt(self)
        counts["mt"] += 1
        if r:
            logger.info("[kvdbg] manager.take_events -> %d events (call#%d)",
                        len(r), counts["mt"])
        return r

    _km.KVCacheManager.take_events = mt

    orig_pub = _ke.ZmqEventPublisher.publish

    def pub(self, events):  # noqa: ANN001
        counts["pub"] += 1
        if counts["pub"] <= 5 or counts["pub"] % 200 == 0:
            logger.info("[kvdbg] publish#%d events=%d", counts["pub"],
                        len(getattr(events, "events", [])))
        return orig_pub(self, events)

    _ke.ZmqEventPublisher.publish = pub

    # ── connector 链（ascend store：worker 发射 → KVConnectorOutput → scheduler 汇聚）──
    try:
        from vllm_ascend.distributed.kv_transfer.kv_pool.ascend_store import (
            ascend_store_connector as _asc_conn,
        )

        orig_uco = getattr(_asc_conn.AscendStoreConnector, "update_connector_output", None)
        if orig_uco:
            def uco(self, connector_output):  # noqa: ANN001
                r = orig_uco(self, connector_output)
                ev = getattr(connector_output, "kv_cache_events", None)
                counts["uco"] = counts.get("uco", 0) + 1
                if counts["uco"] <= 3 or counts["uco"] % 200 == 0:
                    logger.info("[kvdbg] update_connector_output#%d kv_cache_events=%s",
                                counts["uco"], type(ev).__name__ if ev is not None else None)
                return r
            _asc_conn.AscendStoreConnector.update_connector_output = uco

        orig_ate = getattr(_asc_conn.AscendStoreConnector, "take_events", None)
        if orig_ate:
            def ate(self):  # noqa: ANN001
                r = list(orig_ate(self))
                counts["ate"] = counts.get("ate", 0) + 1
                if r:
                    logger.info("[kvdbg] AscendStoreConnector.take_events -> %d (call#%d)",
                                len(r), counts["ate"])
                return r
            _asc_conn.AscendStoreConnector.take_events = ate
    except Exception as e:  # noqa: BLE001
        logger.warning("[kvdbg] ascend_store_connector hooks skipped: %s", e)

    try:
        from vllm_ascend.distributed.kv_transfer.kv_pool.ascend_store import (
            pool_worker as _pw,
        )

        orig_wge = getattr(_pw.KVPoolWorker, "get_kv_events", None)
        if orig_wge:
            def wge(self):  # noqa: ANN001
                r = orig_wge(self)
                counts["wge"] = counts.get("wge", 0) + 1
                if counts["wge"] <= 5 or counts["wge"] % 500 == 0:
                    logger.info("[kvdbg] pool_worker.get_kv_events -> %s (call#%d enabled=%s)",
                                len(r) if r is not None else None, counts["wge"],
                                getattr(self, "enable_kv_events", "?"))
                return r
            _pw.KVPoolWorker.get_kv_events = wge

        from vllm_ascend.distributed.kv_transfer.kv_pool.ascend_store import (
            kv_transfer as _kt,
        )
        _send_cls = getattr(_kt, "KVCacheStoreSendingThread", None)
        if _send_cls is not None:
            orig_sge = getattr(_send_cls, "get_kv_events", None)
            if orig_sge:
                def sge(self):  # noqa: ANN001
                    r = orig_sge(self)
                    counts["sge"] = counts.get("sge", 0) + 1
                    if counts["sge"] <= 5 or counts["sge"] % 500 == 0:
                        logger.info("[kvdbg] send_thread.get_kv_events -> %s (call#%d enable_kv_event=%s)",
                                    len(r) if r is not None else None, counts["sge"],
                                    getattr(self, "enable_kv_event", "?"))
                    return r
                _send_cls.get_kv_events = sge

            orig_hsr = getattr(_send_cls, "_handle_stored_request", None)
            if orig_hsr:
                def hsr(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
                    counts["hsr"] = counts.get("hsr", 0) + 1
                    if counts["hsr"] <= 5 or counts["hsr"] % 100 == 0:
                        logger.info("[kvdbg] _handle_stored_request#%d enable_kv_event=%s",
                                    counts["hsr"], getattr(self, "enable_kv_event", "?"))
                    return orig_hsr(self, *a, **k)
                _send_cls._handle_stored_request = hsr
    except Exception as e:  # noqa: BLE001
        logger.warning("[kvdbg] pool_worker hooks skipped: %s", e)

    logger.info("[kvdbg] hooks installed: cache_blocks/take_events(bp,mgr)/publish/connector")


def _patch_scheduler_swap() -> None:
    from vllm_ascend.platform import NPUPlatform

    orig = NPUPlatform.__dict__.get("check_and_update_config")
    if orig is None:
        return
    orig_func = getattr(orig, "__func__", orig)
    if getattr(orig_func, "_slo_patch_wrapped", False):
        return  # already wrapped (double-load protection)

    @classmethod
    def wrapped(cls, vllm_config):  # noqa: ANN001
        orig_func(cls, vllm_config)
        additional_config = vllm_config.additional_config or {}
        if not additional_config.get("scheduler_with_predictor_enable", False):
            raise RuntimeError("P FGJSQ requires scheduler_with_predictor_enable=true")
        if additional_config.get("scheduler_with_predictor_enable", False):
            from vllm_ascend.core.recompute_scheduler import RecomputeSchedulerConfig

            recompute_scheduler_config = RecomputeSchedulerConfig.initialize_from_config(vllm_config)
            vllm_config.scheduler_config = recompute_scheduler_config
            # [fix-async] async-scheduling 实例（D）必须保留 AsyncScheduler 契约
            # （原生 D 该场景下选用 AsyncRecomputeScheduler；直接指到同步
            # SchedulerWithPredictor 会丢 MTP spec-token 记账 → 引擎 assert 崩溃，
            # 见 scheduler_with_predictor.py [fix-async] 注释与 manifest 2026-09-22 条目）
            if vllm_config.scheduler_config.async_scheduling:
                vllm_config.scheduler_config.scheduler_cls = (
                    "slo_patch.slo.scheduler_with_predictor.SchedulerWithPredictorAsync"
                )
                logger.info("[slo_patch] scheduler_cls -> SchedulerWithPredictorAsync "
                            "(async_scheduling=true)")
            else:
                vllm_config.scheduler_config.scheduler_cls = (
                    "slo_patch.slo.scheduler_with_predictor.SchedulerWithPredictor"
                )
                logger.info("[slo_patch] scheduler_cls -> SchedulerWithPredictor")

    wrapped.__func__._slo_patch_wrapped = True
    NPUPlatform.check_and_update_config = wrapped
    logger.debug("[slo_patch] NPUPlatform.check_and_update_config wrapped (dormant until flag set)")


def _patch_engine_core_step() -> None:
    from vllm.v1.engine.core import EngineCore

    from slo_patch.patch_core import patched_step, patched_step_with_batch_queue

    EngineCore.step = patched_step
    EngineCore.step_with_batch_queue = patched_step_with_batch_queue
    logger.info("[slo_patch] EngineCore.step / step_with_batch_queue instrumented "
                "(slo_ms=%s reporter=%s)",
                os.getenv(_ENV_ENABLE_SLO_MS, "0"), os.getenv(_ENV_ENABLE_BATCH_REPORTER, "0"))


def _patch_chat_utils_tool_args() -> None:
    """[p3d] Hook 3：tool_calls.arguments 为截断 JSON 时不再 400（生产重放兼容）。

    背景（FGJSQ_3P3D P1 实证，2026-09-28）：vllm chat_utils._postprocess_messages
    对字符串型 arguments 无保护 json.loads（/vllm-workspace .../chat_utils.py:1857）。
    生产数据存在 75/16334 行（228 处）截断 arguments——生产引擎（旧版）容忍并
    正常服务（对话有后续轮次），重放引擎则 JSONDecodeError → 400 → proxy 3 次
    重试后 500。

    语义（round2 实证后修正）：Qwen3.6 chat template 对 arguments 做 `|items`
    （模板渲染报 "Can only get item pairs from a mapping"），**保留原字符串会在
    模板层再次崩溃**。故与数据集转换器同口径（convert_prod_csv_to_replay.py
    L88-117：arguments 字符串→dict（模板需要 mapping），解析失败 fallback {}
    ——est_tokens 即按此渲染）：**不可解析 → 永久置 {}**。可解析项照常转 dict。
    """
    import json as _json

    import vllm.entrypoints.chat_utils as _cu

    orig = getattr(_cu, "_postprocess_messages", None)
    if orig is None:
        return
    if getattr(orig, "_slo_patch_wrapped", False):
        return  # already wrapped (double-load protection)

    def wrapped(messages, *args, **kwargs):
        n_fixed = 0
        for message in messages:
            if not (isinstance(message, dict) and message.get("role") == "assistant"):
                continue
            for tc in message.get("tool_calls") or []:
                fn = tc.get("function") if isinstance(tc, dict) else None
                if not isinstance(fn, dict):
                    continue
                args_v = fn.get("arguments")
                if isinstance(args_v, str) and args_v:
                    try:
                        _json.loads(args_v)
                    except _json.JSONDecodeError:
                        fn["arguments"] = {}  # 与转换器 fallback 同口径
                        n_fixed += 1
        if n_fixed:
            logger.info("[slo_patch] tool_args_fix: %d unparseable "
                        "tool_calls.arguments -> {} (p3d replay compat)", n_fixed)
        return orig(messages, *args, **kwargs)

    wrapped._slo_patch_wrapped = True
    _cu._postprocess_messages = wrapped
    logger.info("[slo_patch] chat_utils._postprocess_messages wrapped "
                "(P3D_TOLERATE_BAD_TOOL_ARGS=1: unparseable tool_calls.arguments -> {})")