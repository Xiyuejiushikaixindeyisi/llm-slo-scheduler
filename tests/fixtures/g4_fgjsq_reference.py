"""Frozen G4 oracle excerpts; injected clock/logger supplied by test_fgjsq.py.

Source and excerpt hashes: g4_fgjsq_reference.provenance.json.
Do not modify this fixture to match a new implementation.
"""
from __future__ import annotations

class FgRequestInfo:
    """Go fgRequestInfo (fine_grained_token_jsq.go:40-46)。"""

    __slots__ = ("inst_id", "original_load", "committed_load", "timestamp_ms", "batch_info")

    def __init__(self, inst_id: str, original_load: int, committed_load: int):
        self.inst_id = inst_id
        self.original_load = original_load
        self.committed_load = committed_load
        self.timestamp_ms = 0
        self.batch_info: dict[str, Any] | None = None

class FineGrainedTokenJSQ:
    """细粒度剩余负载估计 + 最短队列调度（T3）。

    状态（对照 go:28-38）：
      inst_loads[inst] = [req_num, req_len_total]        # go instLoads
      unavailable_inst_loads                             # go unavailableInstLoads（drain 隔离）
      req_dispatch_info[req_id] = FgRequestInfo          # go reqDispatchInfo
      inst_active_reqs[inst] = {req_id}                  # go instActiveReqs（已见过 batch 事件的请求）
      inst_batch_size[inst] = max_num_seqs               # go instBatchSize（Go 取自实例上报，
                                                          #   本 proxy 取 --p/d-max-seqs 配置注入）
    """

    def __init__(self, default_batch_size: int, role: str, min_retention_ratio: float = 0.05, log_every: int = 10):
        self.inst_loads: dict[str, list[int]] = {}
        self.unavailable_inst_loads: dict[str, list[int]] = {}
        self.req_dispatch_info: dict[str, FgRequestInfo] = {}
        self.inst_active_reqs: dict[str, set[str]] = {}
        self.inst_batch_size: dict[str, int] = {}
        self.default_batch_size = int(default_batch_size) if default_batch_size and default_batch_size > 0 else 16  # go:81-83
        if not (0 <= min_retention_ratio < 1):  # go:76-80
            min_retention_ratio = 0.05
        self.min_retention_ratio = min_retention_ratio
        self.role = role
        self.log_every = log_every
        self.dispatch_count = 0
        self.event_count = 0

    # ---- 实例生命周期（本 proxy 新增：替代 Go UpdateCluster 的入口） ----------

    def add_instance(self, inst_id: str) -> None:
        if inst_id not in self.inst_loads and inst_id not in self.unavailable_inst_loads:
            self.inst_loads[inst_id] = [0, 0]
        self.inst_batch_size.setdefault(inst_id, self.default_batch_size)

    # ---- 负载记账（go:302-338） ----------------------------------------------

    def add_load(self, inst_id: str, req_id: str, req_len: int) -> None:
        """go addLoad：req_num+1、req_len_total+=req_len，登记 reqDispatchInfo。"""
        load = self.inst_loads.get(inst_id)
        if load is not None:
            load[0] += 1
            load[1] += req_len
        else:
            logger.warning("[fg-jsq] instance %s not in inst_loads", inst_id)
            self.inst_loads[inst_id] = [1, req_len]
        self.req_dispatch_info[req_id] = FgRequestInfo(inst_id, req_len, req_len)

    def reduce_load(self, req_id: str) -> bool:
        """go reduceLoad：请求结束/中止时回收 committed 负载。返回是否存在该请求。"""
        req_info = self.req_dispatch_info.pop(req_id, None)
        if req_info is None:
            return False
        inst_id = req_info.inst_id
        load = self.inst_loads.get(inst_id)
        if load is None:
            load = self.unavailable_inst_loads.get(inst_id)
        if load is not None:
            load[0] -= 1
            load[1] -= req_info.committed_load
        if req_info.batch_info is not None:
            req_set = self.inst_active_reqs.get(inst_id)
            if req_set is not None:
                req_set.discard(req_id)
        return True

    # ---- 核心公式（go:348-380） ------------------------------------------------

    def get_inst_batch_size(self, inst_id: str) -> int:
        """go getInstBatchSize：实例级 max_num_seqs，缺省 default。"""
        return self.inst_batch_size.get(inst_id, self.default_batch_size)

    def compute_inst_load(self, inst_id: str, load: list[int]) -> float:
        """go computeInstLoad：req_len_total × (ceil(req_num/batch_size)+1)/2。"""
        if len(load) != 2:
            return 0.0
        req_num, req_len = load
        batch_size = self.get_inst_batch_size(inst_id)
        return float(req_len) * (math.ceil(req_num / float(batch_size)) + 1) / 2.0

    def compute_actual_load(self, req_info: FgRequestInfo, now_ms: int) -> int:
        """go computeActualLoad：
        waiting = original × remaining/prompt；running = original × scheduled/prompt；
        progress = min(elapsed_ms/predicted_exec_ms, 1−min_retention_ratio)；
        actual = waiting + running×(1−progress)。
        """
        bi = req_info.batch_info
        if bi is None or bi.get("num_prompt_tokens", 0) <= 0:
            return req_info.original_load
        num_prompt = float(bi["num_prompt_tokens"])
        num_remaining = float(bi.get("num_remaining_tokens", 0) or 0)
        num_scheduled = float(bi.get("num_scheduled_tokens", 0) or 0)
        original = float(req_info.original_load)

        waiting = original * num_remaining / num_prompt
        running = original * num_scheduled / num_prompt

        elapsed_ms = float(now_ms - req_info.timestamp_ms)
        progress = 0.0
        predicted_exec_ms = float(bi.get("predicted_exec_ms", 0) or 0)
        if predicted_exec_ms > 0 and elapsed_ms > 0:
            # preventing the estimated load from decaying to zero before completion.
            progress = min(elapsed_ms / predicted_exec_ms, 1.0 - self.min_retention_ratio)

        result = waiting + running * (1.0 - progress)
        return int(round(result))

    def recompute_and_commit(self, now_ms: int) -> None:
        """go recomputeAndCommit：把所有 active 请求的修正负载差量提交进实例负载。"""
        for inst_id, req_set in self.inst_active_reqs.items():
            if not req_set:
                continue
            load = self.inst_loads.get(inst_id)
            if load is None:
                load = self.unavailable_inst_loads.get(inst_id)
                if load is None:
                    continue
            for req_id in list(req_set):
                req_info = self.req_dispatch_info.get(req_id)
                if req_info is None:
                    continue
                new_committed = self.compute_actual_load(req_info, now_ms)
                delta = new_committed - req_info.committed_load
                if delta != 0:
                    load[1] += delta
                    req_info.committed_load = new_committed

    # ---- 派发（go:409-454） ----------------------------------------------------

    def dispatch(self, req_id: str, req_len: int) -> str:
        """go DispatchRequest：recompute → 按修正负载升序 → 取最小 → addLoad。

        偏离：insBlackMap/skipped 不移植（无 RS 重试层；隔离实例由外层 resync 移出
        inst_loads，效果等同 Go 的 unavailable 不参与派发）。
        """
        if not self.inst_loads:
            raise RuntimeError(f"No available {self.role} servers (fg-jsq)")
        now_ms = _now_ms()
        self.recompute_and_commit(now_ms)

        compare = sorted(
            ((inst_id, self.compute_inst_load(inst_id, load)) for inst_id, load in self.inst_loads.items()),
            key=lambda item: item[1],
        )

        self.dispatch_count += 1
        if self.log_every and self.dispatch_count % self.log_every == 0:
            # [fg-jsq] 改动 5：负载快照日志（EXP_PLAN §9 调度指标数据源）
            logger.info(
                "[fg-jsq] role=%s dispatch#%d req=%s est_tokens=%d computed_loads=%s "
                "(inst: (load, req_num, req_len_total, max_num_seqs))",
                self.role, self.dispatch_count, req_id, req_len,
                {k: (round(v, 1), self.inst_loads[k][0], self.inst_loads[k][1], self.get_inst_batch_size(k))
                 for k, v in compare},
            )
        logger.debug("[fg-jsq] role=%s pick %s for req=%s est_tokens=%d", self.role, compare[0][0], req_id, req_len)

        picked = compare[0][0]
        self.add_load(picked, req_id, req_len)
        return picked

    # ---- 事件消费（go:464-499 + remote_scheduler.go:179-183 时间戳回填） -------

    def match_request(self, rid: str) -> str | None:
        """事件 request_id → 派发 request_id。

        chat 链路精确匹配（引擎 id="chatcmpl-"+uuid，reporter [: -9] 剥前缀后 == uuid）；
        其他前缀约定退化为前缀匹配（full.startswith(rid)）。
        """
        if rid in self.req_dispatch_info:
            return rid
        for full_id in self.req_dispatch_info:
            if full_id.startswith(rid):
                return full_id
        return None

    def on_batch_event(self, inst_id: str, timestamp: float, requests: list[dict[str, Any]]) -> int:
        """go OnBatchEvent：时间戳单调、首事件注册 active、更新 batchInfo+timestampMs。

        附加（D3 已批）：首个事件到达时用 num_prompt_tokens 校正 original/committed 负载
        （派发时的 len(body)/4 估计）。
        """
        updated = 0
        for detail in requests:
            rid = detail.get("request_id")
            if not rid:
                continue
            full_id = self.match_request(str(rid))
            if full_id is None:
                continue
            req_info = self.req_dispatch_info[full_id]
            if req_info.inst_id != inst_id:
                continue

            # Go RS remote_scheduler.go:179-183：request detail 无 timestamp 时用顶层值回填
            ts = float(detail.get("timestamp") or timestamp or 0.0)

            if req_info.batch_info is not None:
                if ts <= req_info.batch_info.get("timestamp", 0.0):
                    continue
            else:
                # register the request to instance active request list (go:487-491)
                self.inst_active_reqs.setdefault(inst_id, set()).add(full_id)
                # D3 校正（已批决策）
                num_prompt_tokens = int(detail.get("num_prompt_tokens") or 0)
                if num_prompt_tokens > 0 and num_prompt_tokens != req_info.original_load:
                    delta = num_prompt_tokens - req_info.original_load
                    load = self.inst_loads.get(inst_id)
                    if load is None:
                        load = self.unavailable_inst_loads.get(inst_id)
                    if load is not None:
                        load[1] += delta
                    req_info.original_load = num_prompt_tokens
                    req_info.committed_load += delta

            req_info.batch_info = {
                "num_prompt_tokens": int(detail.get("num_prompt_tokens") or 0),
                "num_computed_tokens": int(detail.get("num_computed_tokens") or 0),
                "num_scheduled_tokens": int(detail.get("num_scheduled_tokens") or 0),
                "num_remaining_tokens": int(detail.get("num_remaining_tokens") or 0),
                "predicted_exec_ms": float(detail.get("predicted_exec_ms") or 0.0),
                "timestamp": ts,
            }
            req_info.timestamp_ms = _now_ms()  # go:494
            updated += 1

        self.event_count += len(requests)
        return updated

    # ---- 观测（go ReportLoads 的最小子集，供 /fg_loads 与冒烟验证） -------------

    def report_loads(self) -> list[dict[str, Any]]:
        self.recompute_and_commit(_now_ms())
        out = []
        for inst_id, load in self.inst_loads.items():
            out.append({
                "id": inst_id,
                "available": True,
                "load": round(self.compute_inst_load(inst_id, load), 3),
                "req_num": load[0],
                "req_len_total": load[1],
                "max_num_seqs": self.get_inst_batch_size(inst_id),
                "active_reqs": len(self.inst_active_reqs.get(inst_id, ())),
            })
        for inst_id, load in self.unavailable_inst_loads.items():
            out.append({
                "id": inst_id,
                "available": False,
                "load": round(self.compute_inst_load(inst_id, load), 3),
                "req_num": load[0],
                "req_len_total": load[1],
                "max_num_seqs": self.get_inst_batch_size(inst_id),
                "active_reqs": len(self.inst_active_reqs.get(inst_id, ())),
            })
        return out
