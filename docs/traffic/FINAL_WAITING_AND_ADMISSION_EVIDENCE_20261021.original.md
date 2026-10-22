# FINAL_WAITING_AND_ADMISSION_EVIDENCE — 等待证据与准入逻辑的最终集中调研

日期：2026-10-21。性质：只读调研报告，无新实验、无服务请求、无代码/配置改动、无新增打点。本文件是本轮唯一新增输出。
研究对象：**GF 网关 + XPYD(3P3D) 集群**（生产 trace 所述 64K 业务，非 GB 网关）。
目的：super-p95 双等待队列（让行队列）算法讨论前的最后一次集中取证。**不承诺任何收益，不提供新实验计划。**
结论等级（全文统一）：

- **L1 原始记录事实**：日志/CSV/导出/运行实证中直接记录的数值与事件；
- **L2 源码解释**：对实际运行版本源码的语义解读（函数+行号）；
- **L3 已有分析估计**：既有报告/脚本基于 L1 数据加工的估计量（口径已随附）；
- **L4 机制假设**：由 L1–L3 推出的待验证机制叙述；
- **L5 无法判断**：数据不存在/字段无定义/不可读，已列检查位置后停止。

---

## 1. 实验数据源总表（防混总体）

| # | 数据源 | 总体（population） | 负载 | 臂/拓扑 | 时间窗 | 可 speak / 不可 speak |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | `EXP_10.9`（E02） | 5549 条生产 trace 请求的原速重放，**开环**（到点必发） | 生产 9.24 单实例（UUID 9a1c5866），混合长度 0–103K，qps≈0.771 | N=heap / F=fg-jsq，3P3D g2 栈（proxy .49:8080） | wall≈7227/7228 s | 可：开环等待形态、双臂对照；不可：闭环稳态、按 B 扫描 |
| S2 | `EXP_10.12`（E03） | aisbench 合成压测，**闭环**（Semaphore(B) 完成即重发+令牌桶爬坡） | {66158, 126000} 输入 × B{1,2,4,8,16}，PT=1200 | F 单臂（fg-jsq），同 g2 栈 | 每 job 独立窗口（1200 s 量级） | 可：B/长度扫描下稳态等待；不可：开环长尾、到达突发 |
| S3 | `EXP_10.14_TRACE`（E04） | **二次分析**（对 S1/S2 数据的再加工，非独立采集） | — | — | — | 可：等待口径对齐、前因分类；不可：新测量 |
| S4 | `TRACR_9.24_GF`（E01） | 平台库九字段导出 55166 行，选定 UUID 5549 行 | 生产 64K 档（用户口径） | 原生 proxy（用户口径，非 FGJSQ） | 07:00:02–08:59:57 UTC（模型处理起点轴） | 可：入场前流量画像（长度/命中/租户/节奏）；**不可：任何延迟结论（单位 unknown）** |
| S5 | `EXP_10.20_MOTOR` g5（E26） | Motor 3.1.0 基线栈（链路验证，**无性能压测**） | smoke/短请求 | Motor Coordinator + 3P3D | 2026-10-19/20 | 可：源码契约、账本生命周期实证；**不可：性能证据（B16 未跑成）** |
| **防混要点**：S1/S2 是 g2 世代（`load_balance_proxy_finegrained_p3d.py`，P/D 经 proxy 转发）；S5 是 Motor 世代（Coordinator 统一入口）；S4 是生产平台库。三者调度器与路由实现不同（§4-E26），数值不可跨世代直接比较。S4 的"52.5% 零命中组贡献 uncached"（Task 1 报告 F1）与 S1 的"52.5% waiting gauge 非零快照占比"（E08）是**两个无关的巧合数字**，引用时必须带全称。 |  |  |  |  |  |  |

---

## 2. 指标定义表（三种等待口径 + 相关字段）

### 2.1 三种等待口径

| 口径 | 定义 | 生产者/计算过程 | 上报时机 | 已知偏差 |
| --- | --- | --- | --- | --- |
| **(a) 客户端等待** | 开环：`waitproxy = max(0, ttft − 同 est_tokens 十分位桶内 ttft_p10)`（下包络）；闭环：`wait_est = max(0, ttft − prefill_est)`，其中 `prefill_est = uncached×r_tier + a_tier`（r/a 由同 MAX_INPUT 的 B=1 作业两次-MAD 内点回归） | `analyze_wait_r1.py` / `wait_extract_10_12.py`（E30） | 离线 | 模型化估计：开环是**下包络**（真实等待≥此值）；闭环依赖 B1 标定的线性 prefill 模型 |
| **(b) 引擎排队** | `vllm:request_queue_time_seconds` = `scheduled_ts − queued_ts`，**首个 QUEUED 事件→首个 SCHEDULED 事件**，抢占不重置 | `stats.py:420,438`（E15）；直方图在**请求 finish 时 observe**（`loggers.py:1186`，E16）；采集侧 t000/t999 窗差 + 跨实例桶合并 + histogram_quantile 线性插值（`analyze_10_9.py`） | 请求结束时 | 首 chunk 被调度即停表→**入场后的 chunk 交织/KV 迁移排队不计入**；**无逐请求实测源**（`README_engine_csv.md`：queue_time_s 列空，引擎日志无逐请求 id 行，E27）；分位数是直方图插值 |
| **(c) waiting 池水位** | `vllm:num_requests_waiting` gauge = `len(waiting) + len(skipped_waiting)`，**含** WAITING_FOR_REMOTE_KVS/blocked/deferred | `scheduler.py:1797-99`（E14）+ `loggers.py:1068-77`（E16） | 每 scheduler step set | 30 s 采集周期的瞬时采样；含尚未真正参与准入竞争的远端 KV 等待者；是**请求数不是秒** |

### 2.2 相关字段

- **TTFT（AISBench 口径，用户约定）**：HTTP POST 前记录起点 → 首个流式时间点。客户端钟。S1/S2 的 ttft_s 均此口径（E02/E03 README）。
- **九字段延迟单位**：`model_ttft/model_tpot` 单位经全量文档检索未获定义→**unknown**，已停止检索（Task 1 报告 B 节，E01）。S4 不产出任何延迟分位数/SLO 判断。
- **completion_tokens 语义**：用户口径"输入+输出"与数据矛盾（目标 UUID 5548/5549 行 completion<prompt）；另有 26 行≥8192（6 行=16384）。两种解读并列不裁定（E01 §C-1）。
- **8192**：`MAX_NUM_BATCHED_TOKENS=8192`（`run_2p2d_exp.sh:63,398`）＝**每轮组批 token 预算（chunked prefill 步预算）**，不是单请求输出上限；业务侧 max_tokens 预设 p50=16384/p90=32000（`DATA_9.24/dataset_summary.json`，经 E01 引用）。completion>8192 因此**不构成异常判据**。
- **est_tokens（GF 侧）**：`token_estimate = max(1, request_length // 4)`＝HTTP body 字节数/4（E20/E23）；首个批事件后以 `num_prompt_tokens` 校正（D3 决策）。

---

## 3. 等待研究结果（S1/S2/S3 汇总 + 本轮独立复核）

### 3.1 开环（S1，生产 trace 原速重放）

| 量 | N_heap | F_fgjsq | 等级 | 证据 |
| --- | --- | --- | --- | --- |
| waitproxy p50/p90/p99/max (s) | 4.52/11.86/19.05/30.56 | 3.81/11.09/18.53/29.19 | L3（口径 a 下包络） | E05（`wait_dist_openloop.csv`，n=5548/5549） |
| waitproxy >1s / >5s 占比 | 81.7% / 46.1% | 80.9% / 39.7% | L3 | E05 |
| P 池 queue p50/p90/p95/p99 (s，role-merged) | 0.904/8.746/10.887/14.936 | 0.285/7.811/9.721/14.752 | L1（直方图）+L3（合并口径） | E06 |
| P 池 queue **逐实例** p50/p90 (s) | P0 0.878/8.706；P2 0.915/8.711；P4 0.920/8.810 | P0 0.289/7.651；P2 0.281/7.715；P4 0.286/8.073 | L1 | E07（本轮新提取） |
| D 池 queue p50/p90 (s) | 0.150/0.270 | 0.150/0.270 | L1 | E06 |
| P waiting 池（三实例和）非零快照占比 / p90 / max | 60.0% / 6 / 12 | **52.5% / 5 / 13** | L1（原始 gauge）+L3（池化口径） | E08（本轮独立复算，与 CONTEXT 表逐位一致） |
| TTFT p50/p90/p99 (s) | 9.099/16.859/24.635 | 7.853/15.444/23.422 | L1 | E02/E05 |
| 长等待前因分类 | A 突发 10.4% / B token 突发 2.2% / **C 稳态饱和 87.4%**（1926/229/49，n=2204 事件） | 同左 | L3（1.8×median 阈值分类） | E11（本轮计数复算一致） |
| **E08 复算过程**（自包含）：取 `metrics_gauge_series_{F,N}.csv` 的 P 实例 `vllm:num_requests_waiting` 30 s 快照（每实例 240 点）；对每个快照时刻，取三实例各自最近样本（容差 ≤2.75 s，任一缺失则丢弃该时刻），求和；F 臂得 240 个池化值，非零 126 → **52.5%**，p50=1、p90=5、max=13；N 臂非零 144 → **60.0%**，p90=6、max=12。与 `CONTEXT_P_WAIT_20261013.md` §3.1 表一致。注意：**分母是池化快照数（240），不是请求数**；52.5% ≠ "52.5% 的请求在等"，也 ≠ S4 的零命中 52.5%。 |  |  |  |  |

### 3.2 闭环（S2，aisbench B 扫描，稳态段 t≥60 s）

| 档 | wait p50/p90/max (s) | >1s 占比 | pf_mean (s) | TTFT p50 (s) | 证据 |
| --- | --- | --- | --- | --- | --- |
| 66k_B4 | 0.161/0.357/0.619 | 0.0% | 6.48 | 6.64 | E09 |
| 66k_B8 | 0.264/1.492/4.381 | 19.0% | 6.48 | 6.74 | E09 |
| **66k_B16** | **4.673/6.511/7.788** | **99.5%** | 6.49 | 11.17 | E09 |
| 126k_B8 | 3.285/6.993/11.361 | 90.5% | 13.20 | 16.50 | E09 |
| **126k_B16** | **25.421/34.127/35.457** | **100%** | 13.32 | 38.78 | E09 |

- 引擎侧（口径 b，逐实例直方图）：66k_B16 三 P `queue p50=0.5/p90=0.8/p99≤1.0 s`（n≈266/实例）；**126k_B16 三 P queue p50=20–30 s**（P4 p50=20，P0/P2 p50=30；n≈124/实例）；66k_B16 三 D queue p50=0.3 s。E10。
- waiting 池（口径 c，10 s 窗三实例和，稳态）：66k_B16 mean 0.97/max 3；**126k_B16 mean 6.94/max 8，非零占比 100%**。E13。
- B4 诊断（66k_B4）：send_gap p50 4.783 s ≈ e2e/B 4.77；queue_ahead 直方图 252/1/0（0/1/≥2）；busy_P 0/31/202/20；Spearman(wait, queue_ahead)=0.048；P 驻留并发 1.398 ≈ 理论 1.361。E12。
- Erlang 对照：66k_B4 offered=1.36，Erlang-B(3) 全忙率 11.3% vs 实测 >1s 占比 0%；66k_B16 offered=4.33，预测 47.9% vs 实测 99.5%（饱和区闭环靠背压找均衡，非无界增长）。E12。

### 3.3 等待的两种模式与两个物理位置（既有分档，本轮数值全部复核通过）

| 模式 | 场景 | 形态 | 证据等级 |
| --- | --- | --- | --- |
| ① 长尾等待 | S1 开环（ρ≈1 平稳供给） | 87.4% 长等待无突发前因；长尾由稳态占满+少量突发定高度 | L3 |
| ② 全员持续等待 | S2 B16 稳态 | 99.5–100% 请求 >1s，无出口 | L3 |
| **waiting 池型** | 126k_B16（及开环长尾） | (a)25.4 ≈ (b)20–30，(c) 常驻 ~7 | L3（(a) 为估计，(b)(c) 为 L1） |
| **running 内型** | 66k_B16 | (a)4.67 − (b)0.5 ≈ 4.2 s 藏在执行段（入场后 chunk 共享步进预算+KV 迁移排队），(c) 仅 0–3 | L3 |
| **数值勘误（本轮发现）**：R1 报告 §3.4 表中 126k_B16 waiting 池"常驻 **5.87**"未能从任何 derived 文件复现——10 s 窗稳态 mean 6.94（n=114）、全窗 6.86、60 s 窗 6.79、事件时刻 mean 6.99。定性结论（非零 100%、常驻 6–8）不变；**引用数值以本轮复算 6.8–7.0 为准**，5.87 出处无法判断（L5）。E13。 |  |  |  |

---

## 4. 关键源码四类（A–D）

### A. P 引擎 v1 调度与准入（L2）

来源：`/vllm-workspace/vllm/vllm/v1/core/sched/scheduler.py`，sha256 `9ae1491f…2735e9`（本机 editable 安装 vllm-0.23.0+；与 Motor 包 upstream 快照 `recompute_scheduler.py` hash 一致互证，但本文件本身非历史 run 容器内直接取证——已按边界标注）。
`schedule()`（:340 起）：每步 `token_budget = self.max_num_scheduled_tokens`（本栈=8192），**先 RUNNING 后 WAITING**：

```
# First, schedule the RUNNING requests.
# Next, schedule the WAITING requests.
if not preempted_reqs and self._pause_state == PauseState.UNPAUSED:
    step_skipped_waiting = create_request_queue(self.policy)
    while (self.waiting or self.skipped_waiting) and token_budget > 0:
        if len(self.running) == self.max_num_running_reqs:
            break
        request_queue = self._select_waiting_queue_for_scheduling()
        request = request_queue.peek_request()
        # blocked 状态（WAITING_FOR_REMOTE_KVS 等）promote 失败 → pop 后 prepend 进 step_skipped_waiting
```

准入核心（:669 起）：`num_new_tokens = request.num_tokens − num_computed_tokens`，`long_prefill_token_threshold` 截断，`num_new_tokens = min(num_new_tokens, token_budget)`；`allocate_slots` 失败 → break（本栈无 PRIORITY 抢占路径时的行为）；成功 → `request.status = RUNNING`、`num_scheduled_tokens[rid]=num_new_tokens`、`token_budget -= num_new_tokens`：

```
num_new_tokens = min(num_new_tokens, token_budget)
assert num_new_tokens > 0
...
request.status = RequestStatus.RUNNING
request.num_computed_tokens = num_computed_tokens
# Only track requests that will still be prefilling after this chunk.
if num_computed_tokens + num_new_tokens < request.num_tokens:
    self._inflight_prefills.add(request)
```

外部前缀（PD 分离 KV）在 `num_computed_tokens==0` 时经 `self.connector.get_num_new_matched_tokens(...)` 取外部命中（:614-640）。**语义要点（对算法讨论关键）**：① 队头请求若放不进剩余预算会被**截断成 chunk 入场**（chunked prefill），而不是跳过——waiting 队头的"长请求堵门"不是全有全无，而是以 chunk 形式占用后续步预算；② RUNNING 优先意味着已入场请求保持步进，waiting 准入用**剩余**预算；③ `get_request_counts()` 返回 `(len(self.running), len(self.waiting)+len(self.skipped_waiting))`（:1797-99）——即 gauge 口径 (c) 的直接来源。

### B. SLO patch 的实际生效行为（L2）

来源：`exp_records/code/slo_patch/scheduler_with_predictor.py`，sha256 `02aed12b…9d00cb`（g2/g4 世代正本；260807 dev 仓逐行复制+3 处 import 改动）。

```
def schedule(self):
    if len(self.waiting) <= 1:
        return super().schedule()
    deferred = self._slo_prefilter_waiting()
    result = super().schedule()
    if deferred:
        for r in deferred:
            self.waiting.add_request(r)
    ...
def _slo_prefilter_waiting(self):
    if not self._slo_enabled or self.predictor is None:
        return None          # ← SLO=0 时直接回落原生 FCFS 决策
```

`_slo_enabled = ttft_slo_ms > 0`（`ENABLE_VLLM_TTFT_SLO_MS=0` → False）。本栈实测配置 SLO=0（`run_2p2d_exp.sh`），**因此 S1/S2 的 P 侧准入顺序=原生 FCFS**；SchedulerWithPredictor 在这些 run 里只承担批事件上报与诊断。SLO 开启时才切换 `SchedulingPolicy.PRIORITY` 并做"最紧急请求 predictor 试探→不满足则 defer"。
**Motor 包同文件的差异**（`EXP_10.20_MOTOR/00_intake/.../src/slo_patch/slo/scheduler_with_predictor.py`，sha256 `36c97c22…f4803a`，E18）：`if ttft_slo_ms != 0: raise ValueError("Admission scheduling is outside the FGJSQ baseline")`——g5 世代把 SLO 准入**从"默认关"升级为"构造性禁止"**；reporter 缺参从 warning 降级改为硬拒启（fix7 现场以占位值绕过）；predictor 初始化失败从降级改为拒启。

### C. GF proxy（g2 世代）的记账、派发与释放（L2）

来源：`/mnt/esfs/zhangxiyue/qwen3.6-27b/load_balance_proxy_finegrained_p3d.py`，sha256 `b6bbee28…a5796`。
**派发**（`dispatch`，:418-448）：`recompute_and_commit(now)` 后按 `compute_inst_load` 升序取最小者 `add_load`；负载快照日志 `[fg-jsq] role=… dispatch#… computed_loads=…`。**评分**（`compute_inst_load`）：

```
def compute_inst_load(self, inst_id, load):   # FGJSQ 公式
    req_num, req_len_total = load
    return req_len_total * (ceil(req_num / batch_size) + 1) / 2
```

**记账公式**（`compute_actual_load`，:352-373 语义）：

```
waiting = original * num_remaining / num_prompt       # 未入场部分：全额按剩余比例
running = original * num_scheduled / num_prompt        # 已调度部分
progress = min(elapsed_ms / predicted_exec_ms, 1 - min_retention_ratio)   # retention=0.05
actual = waiting + running * (1 - progress)
```

**派发入口与生命周期**（`assign_instances` :1403-1494；`generate_stream` :1536-1678）：

- P 选择：`token_estimate = max(1, request_length // 4)` → `fg_dispatch_prefill`（初始请求同时 `request_num+=1`）；
- P HTTP 响应返回 `kv_transfer_params` 后才选 D（`fg_pick_decoder`，同一 token_estimate）；proxy 重注入 metaserver 地址（改动 4）；
- **P 负载释放点 = 收到 D 流式响应的首个 chunk**（`release_prefill_kv_once`）；D 负载与 request_num 在流结束/取消/异常的 `finally → _finish_instance` 释放；重算路径（stop_reason=="recomputed"）先释放旧 P/D 再重派发；
- 逐请求日志 `[proxy-timing] trace=%s mode=%s p_pick_ms d_pick_ms p d`（p_pick 含 worker 线程往返；EXP_10.9 实测 p99 0.358 ms，E02）。
**事件契约**（`/update_batch_event` :1742-1787 → `on_batch_event` :465-516）：引擎 POST `{addr, port, timestamp, requests:[{request_id, num_prompt_tokens, num_computed_tokens, num_scheduled_tokens, num_remaining_tokens, predicted_exec_ms, timestamp}]}`；首个事件注册 `inst_active_reqs` 并做 **D3 校正**（`num_prompt_tokens != original_load` 时差值回补账本，修正 body/4 估计）；此后每事件更新 `batch_info`，**时间戳单调才接受**。heap 模式忽略事件。

### D. Motor 包（g5 世代）核心接口（L2）

来源：`EXP_10.20_MOTOR/00_intake/fgjsq-motor-p-0.2.0-20261019/src/`（各文件 hash 见附表）。
**D-1 账本**（`fgjsq/policy.py`，与 C 节公式同构）：

```
def actual(self, request, now_ms):
    p = request.progress
    if p is None or p.prompt <= 0:
        return request.original            # 无事件：全额记账（不衰减）
    waiting = request.original * p.remaining / p.prompt
    running = request.original * p.scheduled / p.prompt
    elapsed = now_ms - request.received_ms   # received_ms 每次事件刷新
    progress = min(elapsed / p.predicted_ms, 1 - self.retention) if p.predicted_ms > 0 and elapsed > 0 else 0
    return int(round(waiting + running * (1 - progress)))
```

**D-2 预约/释放服务**（`motor_adapter/service.py`）：`reserve` op 携带 `key=nonce:attempt_seq`（尝试级幂等）、`estimated_tokens=max(1, req_len//4)`、`native_tokens`、`reserve_deadline`；`_reserve` = `policy.rank(candidates)` 逐个试 `backend.reserve`（Motor native CAS）直至成功；释放双旗标独立——`release_native`（Motor 原生 P 配额，HANDOFF 完成时）与 `release_fg`（账本，**Coordinator 收到 D 响应流首个非空 body bytes**，`FirstBodyObserver`，E23）；`abort` 双发且幂等；迟到/重复事件按身份五元组（coordinator_epoch/instance/endpoint/generation/attempt_seq）+ engine_epoch/batch_seq 单调性过滤。
**D-3 事件快照**（`fgjsq/snapshot.py`）：在 schedule 输出冻结（防调度器状态被下一步变异），字段 `num_prompt_tokens / num_computed_tokens−count / num_scheduled_tokens=count / num_remaining_tokens / predicted_exec_ms`（取 `output.predicted_batch_exec_time`，无则 `predicted_ttft_entry×1000`）；`event_url` 从 P 请求体 `kv_transfer_params.fgjsq` 注入处取回。
**D-4 predictor**（`slo_patch/slo/predictor.py` + `predictor_impl.py`，E25）：

```
@abstractmethod
def predict(self, batch_size: int, avg_prompt_length: float, cache_hit_rate: float) -> float:
    """预测给定batch配置下的 TTFT"""
@abstractmethod
def update(self, actual_ttft, predicted_ttft, batch_size, avg_prompt_length, cache_hit_rate) -> None: ...
```

实现=进程内 LightGBM GBR（n_estimators=300, 单调约束 `[1,1,1,-1,1,-1,1,1]`），特征 `FEATURE_COLS = [N_uncached, B, L_avg, cache_hit_rate, prefill_intensity, N_cached, Cross_Attention_Proxy, Self_Attention_Proxy]`；未就绪/异常回落启发式 `N_uncached×0.01 ms`。训练标签=`scheduler_output.actual_batch_exec_time`（ms）：非 async 路径=本批提交→完成墙钟；**async 路径（g5 实际）=流水线占位间隔，含排队，不是纯计算时长**（G5 交接 §5.3）。**能力边界（G5 §5.5）**：入场前可调用（纯函数，sub-ms）；`cache_hit_rate` 实为上一步批级"剩余比例"（初值 0.8），**不是该请求真实 prefix 命中**；**无请求级剩余服务时间接口**——只有批执行毫秒，不得改称请求预测。
**D-5 g5 与 g2 的差异清单（对历史分析影响最大项，E26 §3.1/§4.8）**：

1. 路由层：g2=自研 proxy（HTTP 转发+FGJSQ 记账合一）；g5=Motor Coordinator（UnifiedPDRouter），FGJSQ 以 Mgmt 内 `FgjsqService` 存在，reserve 经 ZMQ RPC；
2. 调度器：g2 P=`SchedulerWithPredictorAsync`（SLO 默认关）；g5 同类但 SLO 非 0 **直接 raise**；
3. `max_num_seqs`：g5 运行实证 P/D 均 24（用户生产口径为 16——**世代差异，勿混**）；
4. g5 引擎 vllm git 版本串 `0fc695fc`（rc1 镜像 `vllm-ascend:v0.23.0rc1-mindie-motor-3.1.0-main-0917`）；
5. g5 §4.8 已列"入场延后"的账本反馈：**入场前无事件→全额记账→score 偏高→该实例被 rank 靠后**——延后会通过账本反馈影响后续路由（实验设计需显式对待，本轮仅转述）。

---

## 5. 七条具体说法的有限核对

| # | 说法 | 核对结果 | 等级 | 证据 |
| --- | --- | --- | --- | --- |
| 1 | 66k_B16 等待 P50≈4.67s + 引擎 queue_time P50≈0.5s **不能证明**剩余延迟在 running | **成立（方法性）**。两数为不同总体不同口径：4.67 是模型化 wait_est 的分位数（E09），0.5 是引擎直方图分位数（E10）；分位数相减≠逐请求分解。支持"running 内"定位的另有：waiting 池仅 0–3（E13）、TTFT p50 11.17≈wait 4.67+pf 6.49 的**均值级**吻合（但 pf 本身=ttft−wait 模型输出，非独立证据）。逐请求 (a)−(b) 分解**不存在**（(b) 无逐请求源，E27）→ 精确归因 L5 | L2/L3/L5 | E09,E10,E13,E27 |
| 2 | 128k_B16 "20-30s 等待 / 开环 queue P90 7.81s / waiting 非零 52.5%" 各自指标样本聚合要分清 | **成立且已量化**：20–30s=126k_B16 闭环引擎直方图分位数（E10）；7.81s=开环 F 臂 role-merged 直方图 p90（E06，n=5549）；52.5%=开环 F 臂 240 个池化 30s 快照中 P 池 waiting>0 的占比（E08 复算一致）。三者的总体、臂、样本单位互不相同 | L1/L3 | E06,E08,E10 |
| 3 | running/waiting≠0 和无短窗突发**不证明** ρ≈1 | **成立（方法性）**。Erlang-B 对照显示闭环节流效应（B4 预测 11.3% vs 实测 0%，E12）——闭环到达率是系统状态函数，不能用无突发+非零等待反推独立到达下的利用率；开环侧亦无容量测量 | L3 | E12 |
| 4 | 固定在途上限闭环≠队列无界、不用 Erlang-B 拟合有等待位置的 chunked prefill | **成立**。chunked prefill 下 waiting 队头以 chunk 入场（E14-A①），"服务位置"非整数台 M/M/c 模型可描述；Erlang 仅作对照演示偏差方向，未用于拟合 | L2/L3 | E12,E14 |
| 5 | 8192 是每轮组批预算非单请求输出上限、completion 超 8192 不构成异常 | **成立**。`MAX_NUM_BATCHED_TOKENS=8192` 是 scheduler 步预算（E14 `token_budget`）；业务 max_tokens 预设 p50=16384（E01 引 dataset_summary）；S4 中 26 行 completion≥8192 与预算字段语义冲突待裁定，但**不构成异常判据** | L2 | E14,E01 |
| 6 | 九字段延迟单位与 completion 语义若无可读定义则保持未知停止检索 | **已执行**。单位=unknown（全量文档检索无定义）；completion 双解读并列不裁定；**本轮未再新增检索** | L1 | E01 |
| 7 | 同规格多 UUID 不反证"UUID 标识集群"（原 SQL 未按 UUID 过滤） | **成立**。S4 有 9 个非空 UUID（5133–7123 行/个）；原 SQL 未在现场获得、未按 UUID 过滤的证据链已记录（E01 §A/§C-3）；多 UUID 与"UUID=集群"口径的矛盾留外网裁定，本报告仅分析选定 UUID | L1/L5 | E01 |

---

## 6. 结论汇总（六问六行）

| # | 问题 | 能下的结论（证据） | 不能下的结论（缺口） |
| --- | --- | --- | --- |
| 1 | 哪些场景**确有首次入场等待** | 126k_B16（(a)25.4≈(b)20–30，(c) 常驻 ~7，E09/E10/E13）与开环长尾（(b) p90 7.81、(c) 非零 52.5%，E06/E08）：等待主体在 **waiting 池**，确凿；66k_B16 全员 (a) 4.67s 但 (b) 仅 0.5s：有等待但**主体在 running 内**（E09/E10） | 开环逐请求"入场等待"精确值（(a) 是下包络、(b) 无逐请求源）；66k_B16 的 4.2 s 逐请求分解（L5，E27） |
| 2 | 哪些材料支持**候选请求成本不同/曾同时竞争** | S4：prompt p50 41.7K、20.3%≤8K、零命中组贡献 52.5% uncached、两租户 uncached/条差一个量级（E01）；S1/S2：混合长度下 (b) p99≈15 s 与 p50≈0.3 s 并存=同一池内长短请求同场竞争（E06/E10）；GF 记账本身按 token 差异化（E19/E21） | 入场前**可知**的成本特征（命中是事后记录；GF 只有 body/4 估计；`_last_cache_hit_rate` 非请求级，E25-D4） |
| 3 | **仅改首次入场顺序**覆盖/不覆盖什么 | 覆盖：waiting 池型等待（126k_B16、开环长尾的 (b) 段）——准入顺序、让行、分类都在此起作用（E14-A）；GF/P 放置（选哪个 P）影响三实例均衡（E07：F 臂逐实例 p50 0.28–0.29 vs N 0.88–0.92） | 不覆盖：66k_B16 型 running 内等待（入场后 chunk 共享 8192 步预算+KV 迁移，E10/E13）；D 池（queue 0.15–0.3 s 恒小，E06/E10）；P→D HANDOFF 与客户端段 |
| 4 | **GF/P 两处**信息、事件契约、控制边界 | GF（proxy/Coordinator）：入场时刻知 body 字节数（→token 估计）、三 P 修正负载评分、D 首 chunk 释放点；收批事件（num_prompt/computed/scheduled/remaining/predicted_exec_ms，单调时间戳+身份校验）（E19-E24）。P 引擎：waiting deque 内知全部排队请求的完整 prompt token、本地+外部 computed blocks、token_budget 余量；控制点=每步准入顺序与预算分配（E14）。**GF 无等待队列**（请求即到即派发）；等待只存在于 P 侧 | GF 处"持请求不放"方案的事件迟到/取消语义只部分已知（g5 §4.8：reserve_window=30 s 只管 RPC；attempt 超时上限未验证）；P 引擎 waiting 无超时机制（§4.8-5） |
| 5 | 对**分类/让行存量/最长额外等待/最低进展保护**的启示 | 分类特征须从入场前可得集合（长度档、租户、GF 估计 token、历史命中统计）构造（E01-H2/E25）；让行存量天然有账本对照——GF 账本"waiting=original×remaining/prompt"已是让行存量的量化原型（E19/E21）；最长额外等待在开环有经验尺度（waitproxy max≈29–31 s，E05）；最低进展保护有现成机制锚点——progress 衰减 5% retention 下限+首 chunk 释放即"已完成入场不可无限让"的边界（E19/E21） | 让行队列在 GF 或 P 侧放置的成本差（两处取消/超时语义差异未量化）；最长额外等待的业务上限（SLO 27 s 是 TTFT 不是等待预算）；最低进展保护的粒度（token 级 vs chunk 级 vs 请求级） |
| 6 | 哪些**未知项可直接作算法假设** | ① 66k_B16 型 running 内等待≈4 s（作为"仅入场顺序不覆盖"的量化假设）；② 开环稳态供给≈容量（87% C 类前因+17.2K uncached tok/s 画像，作 ρ≈1 工作假设而非证明）；③ 入场前成本可按（长度档×租户×历史命中）分类到足以区分让行组（S4 联合分组表即分档边界样本，E01-F2）；④ predictor 批毫秒可作让行时间预算的一级近似（接受 async 路径含排队的偏差，E25） | 四项均无逐请求验证；不承诺收益；不据此宣称容量或反事实 |
| **可立即进入讨论的机制问题（3–5 个）**： |  |  |  |

1. **放置**：让行队列放 GF/Coordinator（reserve 后延后转发）还是 P 引擎（waiting 内二级队列）？两处的存量信息（GF=估计 token+评分；P=精确 prompt+预算余量）、取消语义（GF=客户端断连即 abort 幂等；P=无引擎侧超时）与账本反馈（入场前全额记账→score 升高→路由回避，g5 §4.8-3）如何权衡？
2. **单位**：让行预算按 uncached token、GF 修正负载（token 记账）还是 predictor 批执行毫秒计？waiting 池型与 running 内型两种场景是否需要不同单位（后者入场顺序策略根本不触及）？
3. **分类特征边界**：分类器只允许入场前可得特征（E01-H2 列出的候选）——是否接受"事后命中记录"以历史统计形式入场（如租户×长度档的滚动命中率），这改变了特征的因果地位？
4. **保护参数**：最长额外等待上限与最低进展保护（token/chunk/请求级粒度）取何关系——是硬上限（超时强制入场）还是软优先级（aging）？开环 max≈30 s 与闭环 126k_B16 稳态 25–35 s 几乎同量级，上限若小于稳态等待会常态触发，如何避免退化为 FCFS？
5. **与 FGJSQ+batch 级 predictor 的兼容**：时间预算若只能由批毫秒叠加启发式构成（无请求级剩余时间接口，E25-D4），让行决策接受多大预测误差？（本阶段不加打点→接受启发式为能力边界。）
**本阶段接受的边界（不再检索、不作实验）**：九字段单位与 completion 语义（unknown，已停止）；逐请求引擎排队实测（不存在）；66k_B16 running 内等待的逐请求分解；ρ 的容量级证明；跨世代（g2/g5/生产）数值直接比较；让行策略的任何收益预估。

---

## 附：关键来源身份表（sha256 前 8 位）

| 证据 | 路径 | sha256 |
| --- | --- | --- |
| E01 | `TRACR_9.24_GF/TRACE_9.24_GF.csv`；`profile_out_9a1c5866/CLUSTER_FLOW_PROFILE_REPORT.md` | `89c3b692…`；`df8c73c9…` |
| E02 | `EXP_10.9/RESULT_10.9/analysis/analysis_report_10.9.md` + `run_manifest.json` | （run 内清单，报告 md5 冻结记录在案） |
| E03 | `EXP_10.12/RESULT_10.12/derived/*`（engine_window/per_request） | job5 P 窗 `e8f7c0ca…`；job10 P 窗 `c9948ded…` |
| E04 | `EXP_10.14_TRACE/{README,CONTEXT_P_WAIT_20261013,REPORT_R1_P_WAIT_20261013}.md`；`code/analyze_wait_r1.py` | 脚本 `1fdbc8aa…` |
| E05/E09 | `EXP_10.14_TRACE/derived/wait_dist_{openloop,closedloop}.csv` | `26de2ffe…`；`35cab93b…` |
| E06/E07 | `EXP_10.9/RESULT_10.9/derived/metrics_hist_{role_merged,window}_{F,N}.csv` | F 窗 `2a65056d…`；F 合并 `0bb7e08c…` |
| E08 | `EXP_10.9/RESULT_10.9/derived/metrics_gauge_series_{F,N}.csv`（240 池化快照复算） | F `5293f5e2…` |
| E13 | `EXP_10.14_TRACE/derived/windows_cl_{66k,126k}_B16_{1s,10s,60s}.csv` | 126k 10s `ded5321c…` |
| E12 | `EXP_10.14_TRACE/derived/{b4_diagnostics,erlang_check,precursor_summary,precursor_events*}.csv` | （本轮逐值复核） |
| E14 | `/vllm-workspace/vllm/vllm/v1/core/sched/scheduler.py`（:340-376, :562-600, :614-700, :840-860, :1795-1800） | `9ae1491f…` |
| E15 | `/vllm-workspace/vllm/vllm/v1/metrics/stats.py`（:412-450） | `08eb6bb9…` |
| E16 | `/vllm-workspace/vllm/vllm/v1/metrics/loggers.py`（:875-890, :1060-1090, :1180-1192） | `ce2a0535…` |
| E17 | `exp_records/code/slo_patch/scheduler_with_predictor.py`（:55-130, :213-229, :306-328） | `02aed12b…` |
| E18 | Motor 包同文件 diff（SLO 非 0 即 raise 等 4 处） | `36c97c22…` |
| E19/E20 | `/mnt/esfs/zhangxiyue/qwen3.6-27b/load_balance_proxy_finegrained_p3d.py`（:326-414, :418-448, :465-516, :873-933, :1403-1512, :1536-1678, :1742-1798） | `b6bbee28…` |
| E21 | `…/src/fgjsq/policy.py` | `68c2695d…` |
| E22 | `…/src/motor_adapter/service.py` | `10cca540…` |
| E23 | `…/src/motor_adapter/bindings.py`；`body_observer.py` | `053652d6…` |
| E24 | `…/src/fgjsq/snapshot.py` | `459b020b…` |
| E25 | `…/src/slo_patch/slo/{predictor.py,predictor_impl.py}` | `f08e3e40…`；`ca4f9d20…` |
| E26 | `EXP_10.20_MOTOR/G5_BASELINE_HANDOVER.md`（§1, §3.1, §4, §5） | （文档，内嵌运行实证日志） |
| E27 | `EXP_10.9/RESULT_10.9/derived/README_engine_csv.md`（queue_time_s 空：直方图聚合+日志 grep 0 命中） | — |
| E30 | `EXP_10.12/code/wait_extract_10_12.py`（prefill_est/wait_est 模型定义 :12-21, :272-281） | `f8f42227…` |
| （完。本轮调研到此停止；后续进入算法讨论，不启动任何新实验。） |  |  |