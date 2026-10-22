# G5 Baseline Handover — FGJSQ + Predictor + MindIE-Motor + Qwen3.6-27B 现场上下文

> 
> 交接对象：无法访问华为内网的外部开发 agent。本文自包含：关键代码、配置、日志原文、结果数据直接嵌入正文，不依赖任何内网路径。
> 报告截止：2026-10-20 02:3x (UTC)。取证原则：只读，零环境变更，零新增实验。
> 结论分级：【运行实证】=现场日志/接口实测；【源码确认】=实际运行版本的源码；【推断】=由前两者推导；【未验证】=未采集/无法确认。
> 
> 
> 内网路径仅作来源标注（如 `04_stack_logs/n49_nmp.log:129`），核对以嵌入正文为准。

---

## 1. g5 当前状态概览

### 1.1 组件与改动清单

g5 = 在华为镜像 `vllm-ascend:v0.23.0rc1-mindie-motor-3.1.0-main-0917`（arm64, 16 层, CANN 9.0.1, Entrypoint=bash）之上，拉起的 3P3D MindIE-Motor 分离部署：

| 组件 | 版本/构建标识 | 说明 |
| --- | --- | --- |
| MindIE-Motor | 3.1.0-main-0917（pip 包 `motor`@site-packages，锚 commit f203263d 的 patch 基线） | Coordinator + Controller + NodeManager |
| vLLM | 容器 `/vllm-workspace/vllm`，git 版本串 `0fc695fc`（正式版；rc1 仅是镜像 tag 里的 ascend 分支名）【源码确认】 | 引擎本体 |
| vLLM-Ascend | 容器 `/vllm-workspace/vllm-ascend` | 910B 后端 |
| slo_patch | 0.2.0（三合一 wheel `slo_patch-0.2.0-py3-none-any.whl`：fgjsq + motor_adapter + slo_patch 单 entrypoint） | P 侧插件 + FGJSQ 服务端 |
| 交付包 | `fgjsq-motor-p-0.2.0-20261019.tar.gz`（95 文件，含 src/、patches/motor/f203263d-p-fgjsq.patch、docs、tests） | 现场按包内 HUAWEI_AGENT_PROMPT_FGJSQ_MOTOR.md 规程执行 |
| 模型 | Qwen3.6-27B-w8a8（`Qwen3_5ForConditionalGeneration`，text 256k，MTP 1 层，W8A8 ascend 量化） | 权重只读挂载 |
| 硬件 | 3× 华为 910B 节点（7.193.130.49/.151/.175），每节点 8×910B2，P 与 D 同节点共卡（各 4 卡 TP4） | 910B |
| 拓扑：每节点 1 个容器 `motor3p3d-zxy`，内跑 P 引擎(:10000)与 D 引擎(:10002)各 TP4；Coordinator 在 .49（推理 :18080 / 管理 :18081）；Controller 在 .49（:18083/:18084）；mooncake master 自持于 .49:50089（24 clients）。 |  |  |
| **现场对交付包/镜像的改动**：见 §2。要点：交付包 src/ 三组件（fgjsq/motor_adapter/slo_patch）**零修改**；Motor 打了包内提供的七文件 patch + 现场一个 8 行源码补丁（fix1）；未新增任何 monkey patch 超出交付包已有内容。 |  |  |

### 1.2 截止时正在运行的项目

- **B16×128K AISBench 压测：尚未成功启动（pending）**。客户端管道（.216 宿主直跑，python3.12 venv）在逐包补依赖：已装 pyarrow/datasets/pillow/scipy/scikit-learn/matplotlib/janus/torch(cp312)；最后一次冒烟失败于 torch（已解决待复验）；01:27 有一次正式档早期失败留痕（当时 pyarrow 未装好）。g5 服务侧三节点引擎在役且空闲（/fgjsq/v1/loads open=0，见 §4.7）。
- S5 链路验证已完成：chain_pass=true（§1.3）。

### 1.3 各能力验证程度

| 能力 | 程度 | 证据等级 |
| --- | --- | --- |
| 3P3D 拓扑 | 6/6 引擎健康，Coordinator /instances count=6（p49/p151/p175 + d49/d151/d175 各唯一 JOB_NAME） | 【运行实证】 |
| 非流式+流式 | 非流式 200/1871 字符/usage 齐；流式 TTFT 0.51s/192 chunks/finish=stop | 【运行实证】`d3_single.json` |
| 三路 P 事件关联 | 双轮 smoke 路由覆盖 P 实例 1/4/5（=p49/p151/p175）各 ≥2 次 release_p_tokens；三 P `in-predictor update` batch_count 递增 | 【运行实证】 |
| predictor 预测与更新 | 预训练模型三 P 加载成功（warmup_done=True 起步）；在线 update 样本入 buffer；批级 predict 调用正常 | 【运行实证】`n49_nmp.log:680-681` |
| 负载释放 | 五计数对齐 reserved=received=matched=release_native=release_fg=15（smoke+d3+d6+d7 累计），open_native=open_fg=0 | 【运行实证】§4.7 loads 快照 |
| KV 交接（P→D） | D 侧 external prefix cache hit rate 94.9→99.9%（8k 真实长度请求后）；D 日志 0 条 fgjsq/observer 泄漏 | 【运行实证】§4.6 |
| 正确性 | 8k 长提示输出语义正确（准确复述文档主题）；smoke 3/3 done | 【运行实证】 |
| **三层证据严格区分**： |  |  |

- "链路跑通" = CHAIN_PASS（D1-D9 门槛判定，见 §7.1）。
- "冒烟通过" = 短请求 concurrency=3 全部 done + 账本归零（`smoke.json`，§7.1）。
- "性能得到改善" = **无任何证据**。B16 与十档对照矩阵均未运行；本文不含任何性能收益主张。

### 1.4 未解决问题

1. P 侧 mooncake client TRANSFER_FAIL 噪声：部分 chunk put 失败，最终高命中、输出正确；高压下是否放大=未验证（B16 观察项）。
2. AISBench 客户端管道（.216）未通（§7.3）——纯客户端问题，与 g5 服务侧无关。
3. Predictor 首批误差大（§5.4）——已知，非缺陷结论。

### 1.5 后续适配需要的环境信息

- Python import 路径（容器内）：`motor`、`slo_patch`、`motor_adapter`、`fgjsq` 均在 `/usr/local/python3.12.13/lib/python3.12/site-packages`；引擎 vllm/vllm_ascend 在 `/vllm-workspace/{vllm,vllm-ascend}`。
- 事件链 HTTP：P 引擎 → `POST [http://7.193.130.49:18081/fgjsq/v1/events](http://7.193.130.49:18081/fgjsq/v1/events)`（schema_version=1）；账本读 `GET :18081/fgjsq/v1/loads`。
- 镜像名/包版本无法证明源码一致：Motor 七文件 patch 的 before/after sha256 清单在交付包 `evidence/manifests/` 与现场 `steps/s2_3_motor_patch/state_49/manifest.json`；外部核对以 §2/§3 嵌入的 diff 与代码为准。

---

## 2. 现场遇到的问题和修复

分类：A=原镜像问题；B=原交付包问题；C=现场新增适配；D=仅配置变化。
先给结论：**src/fgjsq、src/motor_adapter、src/slo_patch 三组件文件零修改**（交付包 sha256 清单 94 文件全过，S4 preflight 复核）。改动分三类：Motor 引擎侧源码（A/C）、安装后的 engine_files.json 期望值（C）、配置与拉起规程（D）。

| # | 问题 | 现象 | 根因 | 修改位置 | 最终修复 | 分类 | 是否改变行为 | 验证证据 | 残余风险 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fix1 | nm 侧 lookup_rpc_port 读取位置与 vllm KVTransferConfig 冲突 | P/D 引擎 APIServer 起即死：`pydantic ValidationError: VllmConfig / lookup_rpc_port Unexpected keyword argument '0'` | Motor backend 写 kv_connector_extra_config（正位），Motor nm（`config/node_manager.py:279-280`）读 store 顶层键——Motor 3.1.0 内部两侧位置期待不一致 | 容器内 `motor/config/node_manager.py`（现场补丁，非交付包） | 见下方 diff；config 回归只留 extra_config | A(+C) | 否（读法兼容化：顶层缺失→回落 extra_config→缺省 "0"，原顶层语义不变） | 干跑 NM_P_OK lookup=0/NM_D_OK lookup=1；三节点 sha256 一致 `c098842c…` | 若上游 Motor 修复，此补丁幂等无冲突 |
| fix2 | D 关 prefix caching 的 bool 序列化 | `vllm: error: unrecognized arguments: false` | Motor `_add_argument_to_list`：str 生成 `--key value`，而 vllm BooleanOptionalAction 不吃裸值 | config（D engine_config） | `"no_enable_prefix_caching": true` → `--no-enable-prefix-caching` | D | 否（达到预期 False） | D 引擎 non-default args `enable_prefix_caching: False` | 无 |
| fix3 | 同节点 P/D 双 NM Controller 去重 | 每节点只起一个引擎 | `has_node_mgr(pod_ip)` 仅按 IP 匹配（`instance.py:200`） | env：P/D 各独立 JOB_NAME | `motor3p3d-zxy-p49/…/d175` 每节点每角色唯一 | D | 否（模拟 k8s 原生分 job 拓扑） | 6/6 start_cmd | 无 |
| fix4 | Controller 实例组装竞态 | P 实例 endpoints 2/1、3/1 永不 enough，无 start_cmd | filter 周期错过 1/1 窗口；`is_endpoints_enough` 要求 total==dp_size | 拉起规程 | 串行逐节点拉 NM，确认 :1026+:1027 双 start_cmd 再下一节点 | D | 否 | Controller 日志 6/6 | 无 |
| fix5 | 10.16 遗留栈占满 24 卡 | D 引擎 `Free memory (5.79/60.96 GiB) < 0.9×…` | 三节点 24 卡被 EXP_10.17 vllm 引擎占满 | 资源清理（用户批准清引擎留容器） | 按 cgroup 圈定 kill，HBM 回基线 | C（清理） | 否 | 三节点 HBM ~3414/65536、VLLM 进程 0 | 无 |
| fix6 | mooncake master 依赖 | 两套 mooncake 集群严禁共压同一 L2 | — | .49 容器内自持 master :50089 | 幂等脚本拉起 | C | 否 | Clients=24，指向 7.193.130.49:50089 | 共享集群纪律须维持 |
| fix7 | slo_patch 0.2.0 reporter 硬校验拒启 | P 引擎 `RuntimeError: P reporter requires api_server_host and api_server_port`（`scheduler_with_predictor.py:91`）；而 `BatchEventReporter.__init__` 实际不消费 addr/port（真实回调 URL 来自 reservation 的 event_url） | 交付包 0.2.0 把 g4 版的 warning 降级改成了硬 raise，但占位值即过校验 | config（P additional_config） | `api_server_host="motor3p3d-zxy-p"`（自述身份占位，代码不消费）、`api_server_port=10000` | B(绕过)+D | 否（仅过校验；上报 URL 仍由 fgjsq.json 的 event_url 决定） | 三节点 `[slo] batch reporter enabled` 且 0 条 raise | 若未来版本让 reporter 消费该 addr，占位值会失效——需复核 |
| fix8 | Coordinator 实例池按 (role, job_name) 去重级联替换 | 6/6 引擎健康但 /instances count=2 | fix3 的 role 级 job_name 使三节点 P/D 互踩（"removing stale instance and refreshing"） | env：每节点每角色唯一 job_name | p49/p151/p175 + d49/d151/d175 | D | 否 | count=6、级联替换 0、mooncake Clients=24 | 无 |
| 再锚定 | engine_files.json 与镜像 vllm-ascend 不匹配 | `Engine compatibility mismatch for vllm_ascend.core.recompute_scheduler`（期望 38111806，镜像原生 23abae3c） | 交付包期望值锚定的是 g4 世代文件；镜像 rc1 的 recompute_scheduler.py 有 6 行 failed_kv 扣减顺序差异（见下 diff） | **安装后的 `slo_patch/engine_files.json` 期望值** 38111806→23abae3c（三个模块中仅此一项） | 再锚定脚本重写期望值并三节点 commit 固化 | C | **否（引擎文件未改；改的是 hash 白名单）**。注意这确实修改了版本保护的目标值 | 三节点 `slo_patch/engine_files.json` 中该值一致；另两个模块 vllm.v1.engine.core / vllm.v1.core.sched.async_scheduler 的期望值未动 | rc1 的 6 行差异已被接受为现场基准；上游变更时需重新评估 |
| smoke 字段 | 包内 smoke.py 对本模型误判 | passed=false 但实际 3/3 完成 | Qwen3.6 思考模型流式 delta 文本在 `reasoning` 字段（非 content/reasoning_content），smoke 只读 content | **EXP 副本** `scripts/validate/smoke.py` 补三字段兼容（4 行 diff；权威包未动） | `delta.get("content") or delta.get("reasoning") or delta.get("reasoning_content")` | C | 否（采集侧） | smoke.json passed=true matched_delta=3 | 交付包正本仍为单字段版 |
| fix1 最小 diff（容器内 `motor/config/node_manager.py:279` 附近，备份 `.orig_fix1`）： |  |  |  |  |  |  |  |  |  |

```
# before（原版）:
#   lookup_rpc_port = store[LOOPUP_RPC_PORT_KEY]            # 直索引顶层，缺键即炸
# after（现场修复，读法兼容化）:
    if LOOPUP_RPC_PORT_KEY in store:
        lookup_rpc_port = store[LOOPUP_RPC_PORT_KEY]
    else:
        extra = (store.get("kv_connector_extra_config") or {})
        lookup_rpc_port = extra.get(LOOPUP_RPC_PORT_KEY, "0")
```

再锚定涉及的 6 行差异（g4 期望版 vs 镜像 rc1 现役版，`vllm_ascend/core/recompute_scheduler.py` update_from_output 内，行号 ~902）：

```
         stopped_preempted_reqs: set[Request] = set()
         for req_id, num_tokens_scheduled in num_scheduled_tokens.items():
             assert num_tokens_scheduled > 0
-            request = self.requests.get(req_id)
-            if request is not None:
-                request.num_in_flight_tokens -= num_tokens_scheduled
             if failed_kv_load_req_ids and req_id in failed_kv_load_req_ids:
                 # skip failed or rescheduled requests from KV load failure
                 continue
+            request = self.requests.get(req_id)
             if request is None or request.is_finished():
```

语义：rc1（现役）对 failed-KV 请求**先跳过再取 request**，g4 版（交付包期望）先扣减 num_in_flight_tokens 再跳过。现役版更保守（失败请求不扣减）。这是镜像原生行为，现场未改此文件。

### 2.1 明确的"未修改"清单（对 §一.2 逐项）

- **src/fgjsq（公式/账本）**：未修改。评分、负载、release 语义与交付包逐字节一致（sha256 全过）。
- **src/motor_adapter（释放/事件/路由钩子）**：未修改。
- **src/slo_patch（加载链/predictor wrapper/reporter）**：未修改。**未新增任何 monkey patch、启动注入或兼容分支**——全部 patch 行为即交付包定义（§3.2）。
- **版本保护**：`compatibility.verify_engine()` 的三个模块 sha256 检查机制未动；唯一变化是 recompute_scheduler 的期望值再锚定（见上表）。
- **FGJSQ 公式/事件字段/关联机制/释放点**：未修改（§4 全部按交付包源码描述）。
- **predictor 特征/标签 schema/训练流程**：未修改（§5）。
- **对 D 的影响**：D 引擎跑的是镜像原生 vllm-ascend `AsyncRecomputeScheduler` + `recompute_scheduler_enable=true` config（D additional_config），**不含任何 slo_patch 代码**（activate() 对 role!=prefill 直接 return）；D 无 fgjsq/observer 元数据（日志 0 条）。D 受到的间接影响=配置层面：async_scheduling=true、prefix_caching=False、mooncake consumer。
- **镜像内 Motor 七文件 fgjsq 适配**：是交付包 patch（`patches/motor/f203263d-p-fgjsq.patch`，269 行）按包内规程 `scripts/deploy/install_motor_patch.py` 应用的，**不是现场改写**；完整 diff 嵌入 §3.3。

---

## 3. 最终生效配置和插件加载链

### 3.1 P/D 运行时对照表

依据【运行实证】P/D 引擎 APIServer `non-default args`（n49_nmp.log:129 / n49_nmd.log:127，2026-10-19 12:33:41）+ 引擎日志；CLI 未出现 ≠ 未启用，以下均为运行时实际值：

| 项 | P（.49:10000，×3 节点） | D（.49:10002，×3 节点） | 证据 |
| --- | --- | --- | --- |
| scheduler class | `slo_patch.slo.scheduler_with_predictor.SchedulerWithPredictorAsync` | `vllm_ascend.core.recompute_scheduler.AsyncRecomputeScheduler`（recompute_scheduler_enable=true 走 RecomputeSchedulerConfig） | 【运行实证】n49_nmp.log:155 `[slo_patch] scheduler_cls -> SchedulerWithPredictorAsync (async_scheduling=true)`；n49_nmd.log additional_config |
| scheduler MRO（P） | `SchedulerWithPredictorAsync → SchedulerWithPredictor → AsyncRecomputeScheduler → AsyncScheduler → RecomputeScheduler → Scheduler` | — | 【源码确认】类定义（scheduler_with_predictor.py:472 注释）+【运行实证】`predictor assigned to scheduler: type=SchedulerWithPredictorAsync`（n49_nmp.log:681） |
| async_scheduling | **true**（config 未写，运行时实际为 true——patch_runtime 分支日志为证） | true（CLI 显式） | 【运行实证】 |
| max_num_seqs | 24 | 24 | non-default args |
| max_num_batched_tokens | 8192 | 8192 | 同上 |
| max_model_len | 131072 | 131072 | 同上 |
| chunked prefill | enabled（`Chunked prefill is enabled with max_num_batched_tokens=8192`，n49_nmp.log:137） | enabled | 【运行实证】 |
| long_prefill_token_threshold | 未出现在 non-default args → 引擎默认值生效（未在日志中显式 dump；vllm 默认 0=不启用单请求截断）【未完全验证，标注】 | 同 | 【推断】 |
| prefix caching | True | **False**（`--no-enable-prefix-caching`） | non-default args |
| KV connector | MultiConnector[MooncakeConnectorV1(kv_port=30000, use_ascend_direct) + AscendStoreConnector(backend=mooncake, lookup_rpc_port=实例id)]；kv_role=**kv_producer**，engine_id=1 | 同构；kv_role=**kv_consumer**，engine_id=2，Mooncake kv_port=30004 | non-default args（完整 JSON 见 §3.4） |
| enforce_eager | True | False（decode 用 cudagraph FULL_DECODE_ONLY，capture sizes 1..64） | non-default args |
| MTP speculative | num_speculative_tokens=3, method=mtp, enforce_eager=true | 同 | non-default args |
| predictor / reporter | scheduler_with_predictor_enable=true；SLO_PATCH_ROLE=prefill、ENABLE_BATCH_REPORTER=1、ENABLE_VLLM_TTFT_SLO_MS=0、SLO_PREDICTOR_MODEL_PATH=<model.pkl>（NM env，nm_launch_one.sh:13-14） | 无（D 不装 slo_patch hooks） | 【运行实证】 |
| SLO 开关 | **关**（ENABLE_VLLM_TTFT_SLO_MS=0；activate() 对非 0 直接 raise "Admission scheduling is outside the FGJSQ baseline"） | — | 【源码确认+运行实证】 |
| P 侧额外 additional_config：enable_cpu_binding、enable_flashcomm1、api_server_host/port（fix7 占位）。 |  |  |  |

### 3.2 P 侧插件加载链（源码确认 + 运行实证）

加载方式：vllm `load_general_plugins()` 在 engine config 最终化前调用 wheel 注册的 general_plugins entrypoint → `slo_patch.activate.activate()`。完整源码（交付包 src/slo_patch/activate.py，未修改）：

```
"""P-only general plugin; preserve the existing optional D chat compatibility hook."""
import os
_applied = False
def activate() -> None:
    global _applied
    if _applied:
        return
    role = os.getenv("SLO_PATCH_ROLE", "").lower()
    if role not in ("", "prefill", "decode"):
        raise ValueError("SLO_PATCH_ROLE must be prefill or decode")
    if role != "prefill":          # D 或未设：唯一可装的是可选 chat 兼容 hook
        if os.getenv("P3D_TOLERATE_BAD_TOOL_ARGS", "0") == "1":
            from slo_patch.patch_runtime import _patch_chat_utils_tool_args
            _patch_chat_utils_tool_args()
        _applied = True
        return
    if int(os.getenv("ENABLE_VLLM_TTFT_SLO_MS", "0")) != 0:
        raise ValueError("This baseline requires SLO=0; admission mechanisms are pending")
    if os.getenv("ENABLE_BATCH_REPORTER", "0") != "1":
        raise ValueError("P baseline requires ENABLE_BATCH_REPORTER=1")
    from slo_patch.compatibility import verify_engine
    verify_engine()                # ← 源码 hash 检查（见下）
    from slo_patch.patch_runtime import apply_all
    apply_all()
    _applied = True
```

**P-only 门控依据**：`SLO_PATCH_ROLE=prefill`（NM 拉起 env）。D 的 NM env 不设 SLO_PATCH_ROLE/ENABLE_BATCH_REPORTER → activate 直接空转（除非 P3D_TOLERATE_BAD_TOOL_ARGS=1，现场未设）。
`apply_all()` 安装的全部 hook（patch_runtime.py，未修改）：

```
def apply_all() -> None:
    """Strict P installation. Admission remains disabled."""
    _patch_scheduler_swap()        # 包 NPUPlatform.check_and_update_config（见下）
    _patch_engine_core_step()      # EngineCore.step / step_with_batch_queue ← 打点版
    if os.getenv("P3D_TOLERATE_BAD_TOOL_ARGS", "0") == "1":  # 现场未启用
        _patch_chat_utils_tool_args()
    if os.getenv("P3D_KV_DEBUG", "0") == "1":                 # 诊断，现场未启用
        _patch_kv_events_debug()
    if os.getenv("P3D_KV_EVENTS_FIX", "0") == "1":            # MultiConnector 事件透传，现场未启用
        _patch_multi_connector_kv_events()
```

**scheduler class 在哪里被替换**（`_patch_scheduler_swap`，包 classmethod 包装 `vllm_ascend.platform.NPUPlatform.check_and_update_config`，在 VllmConfig 最终化阶段被调用）：

```
@classmethod
def wrapped(cls, vllm_config):
    orig_func(cls, vllm_config)
    additional_config = vllm_config.additional_config or {}
    if not additional_config.get("scheduler_with_predictor_enable", False):
        raise RuntimeError("P FGJSQ requires scheduler_with_predictor_enable=true")
    if additional_config.get("scheduler_with_predictor_enable", False):
        from vllm_ascend.core.recompute_scheduler import RecomputeSchedulerConfig
        recompute_scheduler_config = RecomputeSchedulerConfig.initialize_from_config(vllm_config)
        vllm_config.scheduler_config = recompute_scheduler_config
        if vllm_config.scheduler_config.async_scheduling:
            vllm_config.scheduler_config.scheduler_cls = (
                "slo_patch.slo.scheduler_with_predictor.SchedulerWithPredictorAsync")
        else:
            vllm_config.scheduler_config.scheduler_cls = (
                "slo_patch.slo.scheduler_with_predictor.SchedulerWithPredictor")
```

**hash 检查**：`compatibility.verify_engine()`（activate 时、装 hook 前）对三个模块做 sha256 白名单校验，失配即拒启（不 patch 未验证运行时）：

```
# engine_files.json（安装后、再锚定后的现场值；安装前 recompute_scheduler 为 38111806…）
{
  "vllm.v1.engine.core": "cf9cbde601afb80925254aae814033abeab3817f9c4fe7bf01ca92edc9d10c2d",
  "vllm.v1.core.sched.async_scheduler": "0022e12f356fd46406f6e6d3c82755daf7287ca2d86e2000c27b05bb8d9621cc",
  "vllm_ascend.core.recompute_scheduler": "23abae3c…"   # 再锚定后（镜像原生 rc1 值）
}
def verify_engine() -> dict:
    expected = json.loads(Path(__file__).with_name("engine_files.json").read_text())
    for module, digest in expected.items():
        spec = importlib.util.find_spec(module)
        actual = hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest()
        if actual != digest:
            raise RuntimeError("Engine compatibility mismatch for " + module + …)
```

**重复初始化处理**：`_applied` 模块级布尔；`_patch_scheduler_swap`/`_patch_chat_utils_tool_args` 另有 `getattr(orig_func, "_slo_patch_wrapped", False)` 双重保护——二次 load_general_plugins 不重复包。
**是否存在其他插件改相同对象**：无。D 侧无插件；P 侧只有本 wheel；Motor 不改 vllm 类（只经 config/argv 传参）。
**新增独立模块的常规接入方式**：再做一个 general_plugins entrypoint wheel（同 slo_patch 模式）——vllm 自动发现安装于 site-packages 的 entrypoint 组；或以 additional_config flag + NPUPlatform wrapper 分支（本包模式）。
**关闭与回退**：

- 关闭 P 插件（保留引擎其余行为）：NM env 去掉 `SLO_PATCH_ROLE=prefill` + `ENABLE_BATCH_REPORTER=1`，或 engine additional_config 去 `scheduler_with_predictor_enable` —— 后者会触发 wrapped 的 raise（"P FGJSQ requires…"），因此**干净关闭需同时去 env 与 flag，且需重启 P 引擎进程**（hooks 在进程启动时装载，无运行时卸载路径）。
- 全量回退 g5：用固化基线镜像 `vllm-ascend:g5-motor-fgjsq-20261019`（三节点 docker commit，2026-10-19）重拉，规程=mooncake → coord_restart → ctrl_restart → 串行 NM（fix4/fix8 规程）。镜像内已含：五依赖 wheels + slo_patch 0.2.0 + Motor 七文件 patch + fix1 + 再锚定后的 engine_files.json。

### 3.3 Motor Coordinator 七文件适配 patch（交付包 `patches/motor/f203263d-p-fgjsq.patch` 全文要点）

七文件：management_server.py / scheduling.py / request.py / base.py / unified_pd.py / scheduler_client.py / scheduler_server.py。行为（完整 269 行 diff 已随包交付，此处嵌关键 hunk）：

1. **mgmt 路由注册**（management_server.py `_register_routes` 首行）：

```
fgjsq_hooks.register_routes(self)   # → POST /fgjsq/v1/events、GET /fgjsq/v1/loads
```

2. **P 分配改走 Mgmt 账本**（scheduler_client.py `select_and_allocate`）：

```
if fgjsq_enabled() and role == PDRole.ROLE_P:
    return await fgjsq_hooks.allocate(
        self, role, req_info, attempt_seq, target_instance_id=target_instance_id, …)
# D 与 disabled 保持原生 CAS 路径
```

3. **P native 释放改走幂等 RPC**（scheduler_client.py `update_workload`）：

```
if fgjsq_enabled() and params.role == PDRole.ROLE_P:
    return await fgjsq_hooks.native_release(self, params)   # 按 reservation_id 幂等
```

4. **P 请求 body 注入 fgjsq 元数据**（unified_pd.py `_build_engine_request` → `attach_request`）：P 腿 `kv_transfer_params.fgjsq = {schema_version, coordinator_epoch, reservation_id, attempt_seq, instance_id, endpoint_id, generation, event_url}`；D 腿注入 `_motor_fgjsq_observer` marker（仅 Coordinator 消费，不下发引擎）。
5. **D 转发边界挂观察器**（base.py `_forward` / buffered 路径）：`prepare_forward` 返回 FirstBodyObserver，首个非空 body chunk 触发 `release_fg`（§4.4）。
6. **request 生命周期兜底**（base.py `_lifecycle`）：finally 中 `finish_request` → 对未关闭 attempt 发 abort（幂等 suppress）。
7. **调度入参扩展**（scheduling.py / request.py）：`attempt_seq` 透传；RequestInfo 增加 `_fgjsq_state` PrivateAttr。
该 patch 由 `motor_adapter.bindings` 的显式钩子消费——即"小而受版本检查的 Motor 源码 patch + 适配包"结构。

### 3.4 运行时 KV/引擎配置原文（P，n49_nmp.log:129 摘录）

```
'max_model_len': 131072, 'quantization': 'ascend', 'enforce_eager': True,
'enable_prefix_caching': True, 'max_num_batched_tokens': 8192, 'max_num_seqs': 24,
'kv_transfer_config': KVTransferConfig(kv_connector='MultiConnector', engine_id='1',
  kv_buffer_device='npu', kv_buffer_size=1000000000.0, kv_role='kv_producer',
  kv_connector_extra_config={'connectors': [
    {'kv_connector': 'MooncakeConnectorV1', 'kv_port': '30000',
     'kv_connector_extra_config': {'use_ascend_direct': True, …, 'kv_role': 'kv_producer'}},
    {'kv_connector': 'AscendStoreConnector',
     'kv_connector_extra_config': {'backend': 'mooncake', 'lookup_rpc_port': '1'}}]}),
'additional_config': {'enable_cpu_binding': True, 'enable_flashcomm1': True,
  'scheduler_with_predictor_enable': True, 'api_server_host': 'motor3p3d-zxy-p',
  'api_server_port': 10000, …}
```

fgjsq.json（Coordinator 侧服务配置，未修改）：

```
{"enabled": true, "event_url": "[http://7.193.130.49:18081/fgjsq/v1/events](http://7.193.130.49:18081/fgjsq/v1/events)",
 "max_num_seqs": 24, "retention": 0.05, "reserve_window_s": 30,
 "tombstone_s": 3600, "max_records": 100000, "rpc_attempts": 3}
```

---

## 4. FGJSQ 最终行为及与新入场策略的接口

以下全部依据交付包源码（未修改，sha256 与包一致）+ 现场运行证据。

### 4.1 核心账本（`src/fgjsq/policy.py` 全文语义）

- **P 候选集合**：`MotorBackend.candidates()`——Motor 实例池中 role=P、engine=vllm、单 endpoint、非熔断、非 BLOCKED、dispatch_capabilities 不含 concurrent_engine_sync（TRIGGER 拒绝）的实例；支持 target_instance_id 约束。g5 现场恒为实例 1/4/5（三节点 P）。
- **负载初值**：`reserve(key, instance, estimated_tokens)`，其中 `estimated_tokens = max(1, req_len // 4)`（HTTP body 字节数/4，bindings.allocate）；loads[instance] = [count+1, tokens+estimated]。
- **首次事件校正**：首个批事件到达时若 `progress.prompt != request.original`，差额 delta 加回负载并更新 original/committed（policy.event）。
- **评分公式**：

```
def score(self, instance: str) -> float:
    count, load = self.loads[instance]
    return float(load) * (math.ceil(count / self.limits[instance]) + 1) / 2
# rank = sorted(eligible, key=score)；同分→stable sort（list 顺序=eligible 顺序=实例 id 升序，因 MotorBackend 按 sorted(instances) 生成）
```

- **进度衰减（无新事件时的负载估计）**：

```
def actual(self, request, now_ms):
    p = request.progress
    if p is None or p.prompt <= 0:
        return request.original                      # 无事件：全额记账
    waiting = request.original * p.remaining / p.prompt
    running = request.original * p.scheduled / p.prompt
    elapsed = now_ms - request.received_ms
    progress = min(elapsed / p.predicted_ms, 1 - self.retention) if p.predicted_ms > 0 and elapsed > 0 else 0
    return int(round(waiting + running * (1 - progress)))
# recompute() 在每次 rank/snapshot 前对所有有 progress 的请求重算 committed（predicted_exec_ms 作线性衰减分母）
```

- **predicted_exec_ms 的使用与时间起点**：事件携带（snapshot.py:30）；`received_ms` 在**每次事件到达时刷新**（policy.event:84），elapsed 从最近一次事件时刻起算——即衰减以事件节拍为基准，不是请求入场时刻。
- **无批事件时**：progress=None → 全额 estimated_tokens 记账（不衰减）。

### 4.2 请求/预约/尝试/纪元/批次序列/世代的关联

- `key = nonce:attempt_seq`（bindings.allocate）——尝试级幂等键；同一 UnifiedPD attempt 重发 reserve 返回同 record（service._reserve 幂等校验：参数不同才拒）。
- `reservation_id` = uuid4（Mgmt 生成）；`coordinator_epoch` = Mgmt 进程 uuid（重启即换，RPC 失配报 "coordinator epoch changed; drain/reconcile"）。
- `engine_epoch` = P EngineCore 进程 uuid（patch_core `_ENGINE_EPOCH`）；`batch_seq` = 引擎内批序号（单调）。事件校验：record 的 engine_epoch 首次绑定后必须一致，`seq <= r.batch_seq` 判 stale 丢弃。
- `generation` = Motor 实例代次（实例重启换代）；release 时换代则不再向新代扣减（motor_backend.release 直接返回 True）。
- HTTP 侧关联：P 引擎请求体内 `kv_transfer_params.fgjsq`（含 event_url）；事件 POST 带 `engine_request_id`（引擎内 rid）+ reservation_id。

### 4.3 记账边界：waiting / 已调度未完成 / P 完成-D 未首包

- **waiting（未入场）**：FG 账本=estimated_tokens 全额（无事件）。native 账本=native_tokens（calculate_demand_workload 的 active_tokens）已 CAS-add。
- **running（已调度未完成）**：随批事件衰减（actual()）。
- **P 完成、D 未首包**：release_native 已发（HANDOFF 完成时，§4.4）→ native 账本已扣；FG 账本仍持有残余（retention=5% 下限），等 D 首非空 bytes 的 release_fg。

### 4.4 两个释放时点（确认，勿与客户端首 token 混同）

1. **FG 释放 = Coordinator 收到 D 响应流的首个非空 HTTP body bytes**（不是 P 完成时刻，也不是客户端首 token）：

```
# body_observer.py（未修改）
class FirstBodyObserver:
    def observe(self, chunk: bytes) -> None:
        if not chunk or self.seen:
            return
        self.seen = True
        task = asyncio.create_task(self.release())   # → release_record(..., "release_fg")
# 挂接点：base.py _forward 流式 aiter_bytes 循环 / buffered aread 前 ObservedStream 包装 / 非流式 response.content
```

2. **native P 释放 = HANDOFF 完成、attempt 资源回收时**（unified_pd.py `_release_attempt` → `_update_workload` → scheduler_client.update_workload → `fgjsq_hooks.native_release`，按 reservation_id 幂等）。现场 trace（n49_coord.log:1651）：

```
(InferenceWorker-0) [scheduler][scheduler_client.py:1211] scheduled role=decode req_id=1792458…d104c71a input_tokens=0 instance=2 endpoint=0 …
(InferenceWorker-0) [router][unified_pd.py:2432] [1792458…] Release workload succeeded stage=release_d_tokens elapsed_ms=0.08 instance_id=2 endpoint_id=0 role=decode action=Release_Tokens
```

（release_p_tokens 同构行在 P 腿释放时出现；D 走原生 CAS。）

### 4.5 取消/重试/迟到事件/重复释放

- **attempt 失败/取消**：`finish_attempt` → abort（suppress=True 幂等）；allocate 内 BaseException → shielded abort。abort 同时置 native_released 与 fg_released。
- **request 收尾兜底**：`finish_request` 等 FirstBodyObserver 任务组后，对全部 records 发 abort（幂等）。
- **reserve 前取消**：cancelled 字典记 tombstone，后续同 key reserve 直接拒绝。
- **迟到/重复事件**：service.events 对 fg_released 后的事件计 unknown_or_released；身份五元组（epoch/instance/endpoint/generation/attempt_seq）失配计 wrong_identity；batch_seq 回退计 stale。**重复 release**：已 closed 的 record 再收到 release op 返回 {"ok": true}（幂等 ack）。
- **abort 的 +2/请求 定量**（现场实验 d6 验证）：正常完成路径=release_native+release_fg 各 1；aborted 路径=abort 1 次。账本 abort 计数 34 ≈ 17 请求×2（P/D attempt 清理路径各发一次 abort op 计数，suppress 幂等）——**计数口径含重复尝试清理，非故障信号**。

### 4.6 一条完整生命周期 trace（现场实采，smoke 请求之一）

```
[T0] 客户端 POST :18080/v1/chat/completions (stream)
[T0] Coordinator UnifiedPDRouter:
     allocate(P) → Mgmt FgjsqService._reserve: rank([1,4,5]) → 选 instance=1
       metrics.reserved+1；P native CAS-add；FG loads[1]=[1, est_tokens]
     attach_request: P body kv_transfer_params.fgjsq={reservation_id=…, event_url=…, epoch=…}
[T0+ε] P 引擎(SchedulerWithPredictorAsync.add_request → waiting deque) → admission → prefill
[T1] P EngineCore.step_with_batch_queue → _capture_batch_event(freeze_snapshot) → BatchEventReporter.emit
     → POST /fgjsq/v1/events {engine_epoch, batch_seq=0, requests:[{reservation_id, num_prompt_tokens=20,
        num_scheduled_tokens=20, num_remaining_tokens=0, predicted_exec_ms=821.0, …}]}
     → Mgmt: counts matched+1；policy.event 首次校正
（n49_nmp.log:745）[fgjsq-batch] epoch=bab2cdcf… batch=0 B=1 Lavg=20.0 residual=0.0
        predicted_ms=820.9995 actual_ms=6172.52        ← 首批含预热，误差大（§5.4）
[T2] P 完成 HANDOFF → _release_attempt → update_workload(P) → native_release（幂等）→ release_native+1
[T3] Coordinator 转发 D；D 首个非空 SSE body chunk → FirstBodyObserver.observe → release_fg+1
[T4] D 完成 → unified_pd.py:2432 Release release_d_tokens（D 走原生 CAS）
[T5] finish_request 兜底 abort（幂等空操作，metrics.abort 计数仍 +，见 §4.5 口径注）
```

缺失环节（如实标注）：P/D 引擎内部各阶段无统一 monotonic 时间戳可跨进程相减；T1-T4 间隔未逐项采集（跨节点时钟不可比，未造时间）。

### 4.7 账本快照（2026-10-20 02:2x，空闲态，GET /fgjsq/v1/loads 原文摘录）

```
{"schema_version": 1, "coordinator_epoch": "7e5e4b6f…",
 "policy": {"1": {"requests": 0, "committed_tokens": 0, "score": 0.0, "max_num_seqs": 24},
            "4": {…同…}, "5": {…同…}},
 "metrics": {"reserved": 15, "received": 17, "matched": 17,
             "release_native": 15, "release_fg": 15, "abort": 34},
 "open_native": 0, "open_fg": 0, "records": 15, "tombstones": 15}
```

判读：received(17)>reserved(15) 的 2 条=事件先于 reserve 到达或身份失配被丢（unknown_or_released 不进 metrics 顶层；D 轮重复上报）；open 双零=无泄漏。**matched>0 且三实例都有事件=链路门槛**（HTTP 200 不能替代）。

### 4.8 对"首次入场前延后部分请求"实验的接口影响清单（只列依赖，不设计算法）

更长 waiting 将影响：

1. **reserve_window_s=30**：reserve 与实际入场间隔拉长不影响（deadline 只管 reserve RPC 本身），但**事件迟到窗口**变大——事件到达时请求可能仍在 waiting，此时 num_scheduled_tokens=0、num_remaining_tokens=full → actual() 按全额+无 progress 记账（正确但保守）。
2. **tombstone_s=3600 / max_records=100000**：延后请求的 record 生命周期变长，records 上限压力增大。
3. **predicted_exec_ms 衰减基准**：入场前无事件 → 负载不衰减 → score 偏高 → 该实例被 rank 靠后——**入场延后会通过账本反馈影响后续路由**（需在实验设计中显式对待）。
4. **取消路径**：客户端超时/断连在长 waiting 段更常见 → finish_request 兜底 abort 频率上升（幂等安全，但 abort 计数口径需在结果分析中扣除）。
5. **P 引擎侧**：waiting 队列无超时机制（引擎不主动 abort waiting 请求，除非客户端断开）——延后策略若在引擎侧实现，须自管超时与取消；若在 Coordinator 侧实现（reserve 后不立即转发），则受 Motor attempt 生命周期约束（未见显式 attempt 超时上限，【未验证】）。

---

## 5. predictor 实际能力与局限

### 5.1 特征（FEATURE_COLS，源码确认）

```
FEATURE_COLS = ["N_uncached", "B", "L_avg", "cache_hit_rate", "prefill_intensity",
                "N_cached", "Cross_Attention_Proxy", "Self_Attention_Proxy"]
def compute_features(batch_size, avg_prompt_length, cache_hit_rate,
                     total_scheduled_tokens=None, total_cached_tokens=None):
    B = float(batch_size); L_avg = float(avg_prompt_length)
    cache_hit_rate = float(np.clip(cache_hit_rate, 0.0, 1.0))
    if total_cached_tokens is None:
        total_cached_tokens = int(B * L_avg * cache_hit_rate)
    if total_scheduled_tokens is None:
        total_scheduled_tokens = int(B * L_avg - total_cached_tokens)
    N_uncached = float(total_scheduled_tokens)      # 批内待计算 token
    N_cached = float(total_cached_tokens)
    prefill_intensity = N_uncached / (B + 1e-6)
    safe_b = max(B, 1.0)
    Cross_Attention_Proxy = (N_uncached * N_cached) / safe_b
    Self_Attention_Proxy = (N_uncached ** 2) / safe_b
```

**关键澄清（对应核查清单）**：

- `cache_hit_rate` **仍是 legacy 的剩余比例**：来源=patch_core._predict_batch_exec_time 的
  `(total_prompt_tokens - total_computed_tokens) / total_prompt_tokens`（已 running 批的"未算完比例"），
  **不是真实 prefix-cache hit**，也不是 P→D external KV hit。初值 0.8（scheduler_with_predictor.py:96 `_last_cache_hit_rate = 0.8`），每步被 scheduler_output.total_cache_hit_rate 覆盖。
- `N_uncached`/`N_cached` 的实际含义：**本步调度批**的"剩余未算 token ×（1-剩余率）/已算比例"推算值——包含**尚未完成的已计划 token**（基于 num_scheduled_tokens 与 num_computed_tokens 的当步快照），不是完整 prompt 语义。
- 本批 token（num_scheduled_tokens）、累计 token（num_computed_tokens）、完整 prompt 长度（num_prompt_tokens）三者在事件快照中是独立字段（snapshot.py:27-29），但进入 predictor 特征时被压成 B/L_avg/剩余率三参。

### 5.2 模型状态（运行实证）

- **加载**：三 P 各自从 `SLO_PREDICTOR_MODEL_PATH=/mnt/…/code/predictor_pretrained/model.pkl` 加载成功（scaler+gbr split pickle），`warmup_done=True` 自加载起（n49_nmp.log:680 `[slo] loaded pre-trained model`；:681 `predictor=PurePythonPredictor`）。模型来源 hash【未采集】。
- **每 P 引擎独立实例**（进程内对象，不共享；在线再训练各自进行）。
- **在线训练**：update 每 batch 入 BucketedSlidingWindow（L 桶宽 1000 / hit 桶宽 0.2 / 桶深 100）；`batch_count>=2 或每 100 批` 触发 `_train_model`（后台 daemon 线程，LGBMRegressor n_estimators=300 depth=5 lr=0.05，单调约束 `[1,1,1,-1,1,-1,1,1]`，n_jobs=1）；训练有 60s 卡死强复位；产物 pickle 落 save_dir（容器内 `predictor_results_<ts>/model.pkl` + eval CSV；现场拷出的 9 个目录均在训练阈值前创建，尚无产物=**模型版本仍为预训练版**，【运行实证】batch_count 至 2 后无新训练记录）。
- **特征/标签 schema 现场未改**。

### 5.3 训练标签的实际公式与时序（源码确认）

标签 = `scheduler_output.actual_batch_exec_time`（毫秒），其语义按两条路径不同：

```
# 非 async（patched_step）：
model_output = future.result();  t3 = time.monotonic()
scheduler_output.actual_batch_exec_time = (t3 - scheduler_output.exec_submit_time) * 1000
#   = 本批 execute_model 提交→完成的墙钟（接近真实执行时间）
# async（patched_step_with_batch_queue，g5 P/D 实际路径）：
if scheduler_output.was_queue_empty_at_submit:
    exec_start_time = scheduler_output.exec_submit_time      # 队列空：从本批提交起算
else:
    exec_start_time = getattr(self, 'last_exec_finish_time', …)  # 队列非空：从上一批完成起算
scheduler_output.actual_batch_exec_time = (t4 - exec_start_time) * 1000
self.last_exec_finish_time = t4
#   = 流水线占位间隔（含排队），不是纯计算时长
```

时序（P 引擎，async 路径）：

```
schedule() → _predict_batch_exec_time（当步预测，进 scheduler_output.predicted_batch_exec_time）
          → execute_model(non_block) 提交，记 exec_submit_time / was_queue_empty_at_submit
          →（队列空时）_emit_batch_event 上报预测值与进度
batch_queue.pop → future.result() 完成时刻 t4 → actual_batch_exec_time（标签）
update_from_output → _update_queue（后台线程）→ predictor.update(actual, predicted, B, L_avg, hit)
```

在途多批复对：按 scheduler_output 对象自身携带（提交时预测、完成时回填），一一配对，无跨批混淆。
**注意**：这是**批执行/占位时间**预测，不能当请求端到端 TTFT 预测使用（_slo_downgrade 里 `predicted_ttft = predicted_batch_exec_time/1000` 仅在 SLO 开启时存在，g5 SLO 关）。

### 5.4 误差样例（现场实采，n49_nmp.log）

```
[fgjsq-batch] batch=0  B=1 Lavg=20.0  residual=0.0  predicted_ms=821.0  actual_ms=6172.5   ← 首批（含引擎预热），欠估 7.5×
[fgjsq-batch] batch=1..4  B=None（空步，无调度 token，不预测）  actual_ms=18.8 / 2.3 / 2.2 / 2.2
```

系统化误差分析【未采集】：prediction_history 有数据结构（deque 1000）但未导出；正式压测后可从 `[slo] predictor update:` 日志行批量提取 actual/predicted/error。

### 5.5 为未来"请求分类"的可用性评估

- **入场前能否调用**：能——`predictor.predict(batch_size, avg_prompt_length, cache_hit_rate)` 是纯函数（numpy 前向），无副作用、无线程限制；`_slo_downgrade` 已示范在 add_request 阶段以 `batch_size=1, avg_prompt_length=request.num_prompt_tokens` 调用。开销：模型版实测 sub-ms 量级（predictor_impl 注释宣称 sub-1ms；日志有 `predict #N: total=…us` 行可复采）。
- **输入可得性**：prompt 长度=Request 构造时即有；cache_hit_rate 只能用 `_last_cache_hit_rate`（上一步批级剩余率——**不是该请求的真实命中**，见 §5.1）。
- **能否预测候选 batch**：接口支持任意 (B, L_avg, hit) 假想输入（_slo_prefilter_waiting 已示范候选批试探），但 g5 该路径关闭且其准确度未在 B>1 长提示场景验证。
- **剩余服务时间估计接口**：**没有**。predictor 只输出批执行毫秒；请求级剩余时间无现成接口，不得自行把批预测改称请求预测。

---

## 6. P 调度链路与最小接入点（本报告重点）

### 6.1 调用链总览（P 引擎，async 路径）

```
HTTP :18080 (Coordinator) → P 引擎 APIServer :10000
  → EngineCore.add_request → SchedulerWithPredictor.add_request（warmup 2 个跳过计数后透传）
  → RecomputeScheduler.add_request（MTP consumer 占位 token 注入 + _enqueue_waiting_request）
      → waiting: FCFSRequestQueue(deque)   [blocked 状态入 skipped_waiting]
  → EngineCore.step_with_batch_queue（patch_core 打点版）
      → SchedulerWithPredictor.schedule()（waiting<=1 直通；SLO 关 → _slo_prefilter_waiting 返回空，等价直通）
        → RecomputeScheduler.schedule()  [= vllm Scheduler.schedule 的 ascend 改造版]
            ① RUNNING 循环（token budget 先耗）
            ② WAITING admission 循环（peek→校验→allocate_slots→入 running）
      → execute_model(non_block) → batch_queue（深度流水）
  → update_from_output（predictor 异步 update + 事件 emit 队列批）
```

### 6.2 原生 waiting admission 循环（vllm 0fc695fc，容器路径 /vllm-workspace/vllm/vllm/v1/core/sched/scheduler.py，行号为该文件实际行号；RecomputeScheduler.schedule 为同构复制+preempt/recompute 扩展，行号见 01_check/recompute_scheduler.rc1.py）

```
# L340  def schedule(self) -> SchedulerOutput:
#   ……（变量初始化，token_budget = max_num_scheduled_tokens = max_num_batched_tokens = 8192）
# L373  # First, schedule the RUNNING requests.（running-first：先耗尽 budget）
        req_index = 0
        while req_index < len(self.running) and token_budget > 0:
            request = self.running[req_index]
            #   ……（async/spec 占位跳过、long_prefill_token_threshold 截断、encoder 预算）
            num_new_tokens = min(num_new_tokens, token_budget)      # 共享 token budget
            with record_function_or_nullcontext("schedule: allocate_slots"):
                while True:
                    new_blocks = self.kv_cache_manager.allocate_slots(request, num_new_tokens, …)
                    if new_blocks is not None:
                        break
                    # KV 不足 → 抢占最低优先级 running（PRIORITY 时按 (priority, arrival_time) max；FCFS 时 pop 尾部）
                    #   ……（_preempt_request：重算式抢占，见 §6.4）
            scheduled_running_reqs.append(request); token_budget -= num_new_tokens; req_index += 1
# L560  # Next, schedule the WAITING requests.
        if not preempted_reqs and self._pause_state == PauseState.UNPAUSED:
            step_skipped_waiting = create_request_queue(self.policy)
            while (self.waiting or self.skipped_waiting) and token_budget > 0:
                if len(self.running) == self.max_num_running_reqs:
                    break
                request_queue = self._select_waiting_queue_for_scheduling()   # FCFS: skipped 优先
                request = request_queue.peek_request()                        # 队首候选
                # blocked 状态（WAITING_FOR_REMOTE_KV 等）且无法提升 → pop → step_skipped 队首，continue（跳过）
                # lora 超限 → 同上跳过
                if request.num_computed_tokens == 0:
                    new_computed_blocks, num_new_local_computed_tokens = (
                        self.kv_cache_manager.get_computed_blocks(request))    # ← 本地 prefix hit 在此查询（有副作用：touch blocks）
                    if self.connector is not None:
                        ext_tokens, load_kv_async = self.connector.get_num_new_matched_tokens(
                            request, num_new_local_computed_tokens)           # ← external KV 查询（P 侧 producer 通常直通）
                        if ext_tokens is None:  # connector 未定 → 跳过该请求
                            request_queue.pop_request(); step_skipped_waiting.prepend_request(request); continue
                    num_computed_tokens = num_new_local_computed_tokens + num_external_computed_tokens
                #   ……
                num_new_tokens = request.num_tokens - num_computed_tokens
                if 0 < threshold < num_new_tokens: num_new_tokens = threshold # long_prefill 截断
                if (not self.scheduler_config.enable_chunked_prefill
                        and num_new_tokens > token_budget):
                    break                                                      # 非分块：预算不足→停止整轮 admission
                num_new_tokens = min(num_new_tokens, token_budget)
                #   ……
                new_blocks = self.kv_cache_manager.allocate_slots(request, num_new_tokens, …)
                if new_blocks is None:
                    break                    # ← KV/预算放不下队首：**停止整个 waiting 循环**（不跳过队首）
                request = request_queue.pop_request()
                if load_kv_async:            # external KV 异步加载
                    request.status = RequestStatus.WAITING_FOR_REMOTE_KVS
                    step_skipped_waiting.prepend_request(request); continue
                self.running.append(request)  # ← 首次 admission 完成
                # token_budget -= num_new_tokens ……
            if step_skipped_waiting:
                self.skipped_waiting.prepend_requests(step_skipped_waiting)    # 被跳过者回 skipped 队列
```

**要点**（对应核查单）：

- FCFS；running-first（running 先耗 token budget）；
- **队首候选放不下时是 `break`（停止 admission），不是跳过**——队首阻塞语义；跳过（pop→step_skipped）只发生在 blocked 状态/lora/connector 未定；
- 部分 prefill 的请求仍回 running（chunked prefill enabled），下轮由 RUNNING 循环按 `long_prefill_token_threshold` 续推；
- 资源限制生效点：token_budget（max_num_batched_tokens=8192）、max_num_running_reqs、allocate_slots（KV 块，watermark）、connector 异步加载预留（_inflight_prefill_reserved_blocks）。
- 原生抢占（preemption）：allocate_slots 失败时对 running 触发（FCFS→pop 尾部=最新入场者；PRIORITY→(priority, arrival_time) 最大者）。g5 P 为 FCFS、prefix_caching=True → 被抢占请求释放块回 waiting（vllm Scheduler._preempt_request）。**本次冒烟/链路验证中未观察到抢占发生**（P 负载低；B16 未跑）【未验证高压行为】。

### 6.3 waiting 队列类型与操作接口（request_queue.py 摘录）

```
class SchedulingPolicy(Enum): FCFS = "fcfs"; PRIORITY = "priority"
# Scheduler.__init__ L157-167: self.policy = SchedulingPolicy(self.scheduler_config.policy)
#                              self.waiting = create_request_queue(self.policy)   → g5 = FCFS
class FCFSRequestQueue(deque[Request], RequestQueue):
    add_request → append        # 尾入
    pop_request → popleft       # 首出
    peek_request → self[0]
    prepend_request → appendleft
    prepend_requests(q) → extendleft(q)
    remove_request / remove_requests / __iter__ / __bool__ / __len__
class PriorityRequestQueue(RequestQueue):   # heap，序 = (priority, arrival_time)，小者先
    add_request → heapq.heappush …（prepend 语义=重新入堆，无真"插队首"）
def create_request_queue(policy) → FCFSRequestQueue() | PriorityRequestQueue()
# 队列选择：_select_waiting_queue_for_scheduling（FCFS: skipped_waiting or waiting）
```

**Request 的比较序**：FCFS 下按入队序（deque）；PRIORITY 下 Request 定义 `(priority, arrival_time)`（priority 默认值待查——g5 未用 PRIORITY，未采集【未验证】）。

### 6.4 finished/abort/cancel 清理路径

- API server 断连/abort → `finish_requests(request_ids, FINISHED_ABORTED)` → 从 running/waiting/skipped 移除 + `_free_request`（KV 块回收 + connector 清理）。
- 抢占：`_preempt_request(request, timestamp)` —— prefix_caching 开启时重算式（释放全部块，请求回 waiting，num_preemptions+1）；RecomputeScheduler 另有 preempted_req_data/recomputed_reqs 扩展（D 侧重算记账）。
- P 侧引擎层 abort 不通知 Coordinator 账本——FG 账本的兜底在 Coordinator 侧（finish_request 兜底 abort，§4.5）。**引擎 abort 与 Mgmt 账本之间无逐事件同步**：若请求在 P 引擎被抢占重排，账本只通过批事件的进度字段感知（remaining 回升）。

### 6.5 异步调度提前推进的状态（async 计数≠计算完成）

async 路径下 `step_with_batch_queue` 在**上一批 future 未完成时**即调度下一批：`scheduled_new_reqs/num_scheduled_tokens` 表示"已提交计算"，模型输出经 batch_queue 流水线后才在 update_from_output 落账（num_computed_tokens 才前进）。因此：

- 日志/事件中的 num_scheduled_tokens（含 fgjsq 事件快照）= **已提交**，不是已完成；
- `actual_batch_exec_time` 在队非空时是占位间隔（§5.3）；
- MTP spec token 的 in-flight 记账由 AsyncScheduler 契约维护（fix-async 注释的崩溃教训：换同步基类会丢记账 → EngineDead——**任何替换 scheduler 基类的插件必须保留该契约**）。

### 6.6 "首次 admission 前可用信息"表

对象视角：P 引擎 Scheduler（请求已 add_request 进 waiting，尚未被 admission 循环 peek）。

| 字段 | 首次可获得的阶段 | 对象/访问接口 | 是否可只读取得 | 成本/限制 | 来源证据 |
| --- | --- | --- | --- | --- | --- |
| prompt 长度（token） | add_request 时 | `request.num_prompt_tokens` | 是 | O(1) | 【源码确认】 |
| 到达时间 | Request 构造 | `request.arrival_time`（time.time 基） | 是 | O(1) | 同 |
| 等待时长 | 入队后任意时刻 | `time.time() - request.arrival_time` | 是 | O(1) | 同 |
| 请求状态 | 入队后 | `request.status`（WAITING 等） | 是 | O(1) | 同 |
| SLO/长度档 | — | **g5 无**（SLO 关，无分级字段；priority 默认未设） | — | — | 【源码确认】scheduler_with_predictor.py:66-68 |
| 已有优先级 | 入队后 | `getattr(request, 'priority', None)` | 是 | g5 FCFS 下不参与排序 | 【源码确认】 |
| **P 本地 prefix hit** | **仅 admission 循环内** | `kv_cache_manager.get_computed_blocks(request)` | **否——有副作用**（touch/占块，阻塞语义），且只对队首执行 | 查真实 hit=进入分配流程；waiting 中段无法免费探得 | scheduler.py waiting 循环【源码确认】 |
| **P→D external KV 状态** | admission 循环内 | `connector.get_num_new_matched_tokens(request, …)` | 否（同上，connector 状态查询） | P 是 producer：该调用主要发生在 D 侧；P 侧语义为"已算完可直接传输" | 同 |
| **predictor legacy cache_hit_rate** | 任意时刻 | `scheduler._last_cache_hit_rate`（上一步批级剩余率） | 是 | 与单请求真实命中无关（§5.1） | 【源码确认】 |
| 剩余计算量 | 批事件后 | request.num_computed_tokens（waiting 阶段=0 或 external 预置） | 是（快照值） | 反映的是"截至上一步" | snapshot.py【源码确认】 |
| 可用 KV | 任意时刻 | `kv_cache_manager`（可用块统计经 watermark） | 部分（聚合统计可读；精确"能否容纳 X token"需 allocate 试探） | — | 【源码确认】 |
| 当前 running/batch 状态 | 任意时刻 | `scheduler.running`（list）、上步 scheduler_output | 是 | async 下"已提交未完成"（§6.5） | 【源码确认】 |
| FG reservation 身份 | 入队后 | `request.kv_transfer_params['fgjsq']`（reservation_id/instance_id/event_url…） | 是（P 请求体携带） | D 请求无此字段（marker 在 Coordinator 剥离） | snapshot.py:21【源码确认】 |
| 三个"命中"严格区分：P 本地 prefix hit（引擎块缓存，需进分配流程）、P→D external KV hit（D 侧收 KV 后的 external prefix cache hit rate 日志，如 94.9%）、predictor legacy cache_hit_rate（批级剩余比例，§5.1）。三者数值互不可比。 |  |  |  |  |  |

### 6.7 可行的最小接入方式评估（不实施）

1. **复用 P general plugin（新 wheel / 扩展 slo_patch）+ scheduler 子类覆写** —— 最干净：
   - 接入位置：`SchedulerWithPredictor.schedule()` 已是稳定覆写点（现成模式：waiting<=1 直通；prefilter+deferred 重排已示范于 `_slo_prefilter_waiting`——**该函数就是"双等待队列"的现成骨架**：pop 全部 → 分类 → batch 重入 waiting / deferred 在 super().schedule() 后回队）。
   - 必须遵守的不变量：deferred 回队必须用 `self.waiting.add_request(r)`（保持 FCFS deque 尾语义或显式重排）；不得破坏 async 契约（§6.5）；不得让 deferred 请求永久饥饿（现版 `_max_deferred_per_step=999` 实际不设限）。
   - 可能冲突的现场 patch：EngineCore.step 打点（patch_core）不冲突；fix1 是 Motor 侧不冲突；**engine_files.json hash** 只锁三个模块（v1.engine.core / async_scheduler / recompute_scheduler）——**新 scheduler 子类不改这三个文件则不触发校验**；若直接改 recompute_scheduler.py 本体则必须 bump 期望值。
   - 可独立关闭：env/flag 门控（如沿用 ENABLE_VLLM_TTFT_SLO_MS 模式新增独立 env），进程重启生效。
   - 未确认：SLO_PATCH_ROLE 硬校验（activate 拒绝非 prefill/env 组合）——新 flag 需过 activate 的 raise 链（不能只加 env 不改 activate——**改 activate 即改交付包**，需走交付包版本流程或独立 entrypoint）。
2. **新增 scheduler 子类（不动 slo_patch）**：以独立 general_plugins wheel 包 `MyScheduler(RecomputeScheduler)` + additional_config flag，在 NPUPlatform wrapper 链上再包一层选择逻辑。与 1 等价但完全独立于交付包——**关闭=去掉 flag 重启**；与 slo_patch 并存时注意 patch_core 打点仍装在 EngineCore 上（打点读 `scheduler.predictor` 属性，缺失时早退——兼容）。
3. **单方法受控 hook（如只包 `Scheduler.add_request` 或 `_enqueue_waiting_request`）**：可做分类标记（给 Request 挂属性），但**无法改变 admission 循环内部的 break/跳过语义**——分类若要影响入场顺序，仍需 1/2 或 4。
4. **修改原生 admission 循环（recompute_scheduler.py）**：能力最全（可改队首阻塞为跳过、加第二队列），代价=改 hash 白名单文件+承担 vllm 升级重基线成本+触碰 fix-async 崩溃敏感区。
   - 结论：**若目标仅是"入场前分类+有限让行"，方式 1/2 足够**（prefilter 骨架已证明能在不改核心的前提下重排 waiting）；若需要"队首放不下时跳过而非停止"或"独立第二队列+预算"，方式 4 不可避免——普通 wrapper 无法改变 break 语义，此为如实评估，不为"即插即用"而美化。
**接入前必须补齐的信息**（缺一项则不能上真实调度）：B16 高压下的 admission 行为基线（waiting 深度、budget 用满率、抢占是否出现）——当前全部未采集（§8）。

---

## 7. 已有冒烟与 AISBench 结果

### 7.1 已完成实验（无性能对照，仅链路/功能）

| run | 配置 | 结果 | 备注 |
| --- | --- | --- | --- |
| d3 单请求 | 非流式+流式各 1，max_tokens=600，temperature=0 | 非流式 200/1871 字符；流式 TTFT 0.51s/192 chunks/finish=stop → D3_SINGLE_PASS | 输出走 delta.reasoning 字段（§2 勘误） |
| smoke（双轮） | concurrency=3，短 prompt，经 :18080 | 3/3 done，output_chars 53-59，首内容 0.51-0.53s；账本归零（open=0） | smoke.json passed=true；原版（单字段）误判留痕 smoke_orig.json |
| d6 abort 探针 | 中断/重复释放探针 | abort=+2/请求定量成立（§4.5）；1 条 "Scheduler request cancelled" 终态已释放 | d6_abort_probe.log |
| d7 长提示 | 8k 真实文档提示 | TTFT 23.6s，输出语义正确；D external hit rate 94.9→99.9% | d7_longprompt.json.log |
| SLO 标准（记录用）：64K P90 TTFT ≤27s / P90 TPOT ≤30ms；128K P90 TTFT ≤30s / P90 TPOT ≤45ms。**g5 尚无任何一档达到/未达到的测量**。 |  |  |  |

### 7.2 进行中 / 未运行

- **B16×128K（RUN_ID=128kB16_g5_p01）**：未成功启动（§1.2）。job.list：`HOST 7.193.130.49:18080；MAX_INPUT 126000；MAX_OUTPUT 1024；BATCH_SIZE 16；PRESSURE_TIME 900；DATASIZE 1000；PREFIX_RATE 0.5；SEED 20261014`。01:27 失败留痕=客户端 pyarrow 缺失（当时未装好），非服务端问题。
- 十档矩阵（66k/128k × B1/2/4/8/16）+ g4 对照：未运行。
- predictor 冷启动（无预训练模型）臂：未运行（两臂统一带预训练模型是 E1/E2 方案 A 签核约束）。

### 7.3 客户端（AISBench）语义（源码确认，版本=现场自持副本 benchmark_0630_release）

- **concurrency 的实际限制对象**：`icl_base_api_inferencer._worker_loop` 中 `num_workers = self.batch_size`；`semaphore = asyncio.Semaphore(num_workers)`（`use_timestamp` 模式下为 None——本实验未用）；`aiohttp.TCPConnector(limit=num_workers + 1)`。→ 限制=**同时在途的 HTTP 请求数**（连接池 B+1）。
- **完成一条是否立即补发 / 整轮 barrier**：压力模式（--pressure）下每 worker 协程完成一条**立即**预取下一条并发送（`next_data_task = create_task(wait_get_data(...))` 提前预取），**无整轮 barrier**；循环直到 `time.perf_counter() - start_time < pressure_time` 不再满足或数据耗尽（sentinel None → stop_event）。
- **request_rate**：经进程间 `BoundedSemaphore` token_bucket 限速；本 job.list 未设 request_rate（现场模型配置 request_rate=1.0 为模板默认值，实际以渲染产物为准【渲染产物未留存，标注】）。
- **pressure_time 结束后在途请求**：worker 停止取新数据；已发请求继续等待完成（aiohttp ClientTimeout total=get_request_time_out()）。
- **TTFT/TPOT 定义**：【部分未核实】耗时字段由 VLLMCustomAPIChatStream 流式路径采集（首 SSE/首内容/逐 token 时间戳），summarizer 汇总 P90 口径未逐行核对源码——正式档产物落盘后以 summarizer 输出列为准，此处不照搬历史解释。
- **失败/重试/未完成统计**：模型配置 retry=2（HTTP 层）；pressure 模式并发未设 batch_size 会显式报错退出（ParameterValueError）——不会静默降并发。失败请求在 status_counter 单列（post/failed/finish 计数），**汇总中成功延迟只覆盖成功请求**，失败数必须同报（本报告承诺口径）。

---

## 8. 对下一阶段研究有用的负载事实

**当前大部分为"未采集"**——链路验证期负载极低（单发/3 并发），B16 未跑；不临时开启高开销 tracing 补齐。已有：

- 验证期 P/D 引擎日志 `Running: 0-1 reqs, Waiting: 0 reqs`（smoke/8k 期，n49_nmd.log:840-855 连续行）→ **低负载下无 waiting 堆积、无抢占**【运行实证】。
- 8k 单请求 D 侧 `GPU KV cache usage: 0.8%` → KV 容量远未构成限制（单请求场景）【运行实证】。
- D external hit rate 94.9%→99.9%（8k 后）→ KV 交接命中在低负载下即高【运行实证】。
- token budget/序列数用满率、waiting/running 分布、批内请求数、scheduled tokens 序列：**未采集**（B16 后从引擎 [slo] 诊断行与 loggers 周期行回溯）。
- 慢请求归因（首入场等待 vs 多轮 chunk vs KV 交接 vs D 等待）：**未采集**。
- reporter/在线训练/CPU 控制面开销：smoke 期 `update consumed <1ms`、predict sub-ms 量级【运行实证，样本少】；高压下未测。
- 64K/128K 档内长度/成本差异：未测。
- 跨节点时差：不可比（未对钟），本文不含任何跨节点耗时计算。

---

## 9. 结论：外部 agent 接下来需要知道什么

**A. 可作为 g5 研究起点的已验证事实**

1. 3P3D Motor 分离链路（含 FGJSQ 账本、三路 P 事件、predictor 预加载、KV 交接）端到端工作：chain_pass=true，账本可归零（§1.3、§4.7）。
2. P scheduler 实际类=MRO 链 SchedulerWithPredictorAsync（§3.1）；SLO/admission 机制**硬关闭**（env 非 0 即拒启）。
3. FGJSQ 公式、事件 schema、两个释放时点（native=HANDOFF 完成、FG=D 首个非空 body bytes）以交付包源码为准且现场零修改（§4）。
4. predictor=批级 LGBM（8 特征、legacy 剩余率、占位间隔标签），预训练模型三 P 加载成功、warm 起步（§5）。
5. AISBench 并发=在途请求信号量 B+预取补发、无 barrier（§7.3）。
**B. 后续插件必须保留的现场修复与接口**
6. fix1 的 Motor node_manager 读法兼容（或上游等价修复）——否则引擎拒启。
7. engine_files.json 的 recompute_scheduler 期望值=23abae3c（rc1 现役）；若插件改此三模块任一，必须同步 bump 期望值，否则 activate 拒启。
8. NM env 契约：P=（SLO_PATCH_ROLE=prefill, ENABLE_BATCH_REPORTER=1, ENABLE_VLLM_TTFT_SLO_MS=0, SLO_PREDICTOR_MODEL_PATH），D=不设（§3.1）。
9. 每节点每角色唯一 JOB_NAME + 串行拉起（fix4/fix8）——重拉栈必守。
10. activate() 的硬校验链：SLO≠0 拒、REPORTER≠1 拒、hash 失配拒——新插件若共存需过同一链路（§6.7-1 的未确认项）。
11. async 契约：换同步 scheduler 基类会 EngineDead（§6.5）。
**C. 双等待队列/入场分类的候选接入位置及证据**
12. `SchedulerWithPredictor.schedule()` 覆写层——`_slo_prefilter_waiting`（源码在档，当前 dead code）即为"pop 全部→分类→batch/deferred 重入"的完整骨架（§6.7-1）。
13. `add_request`/`_enqueue_waiting_request` 钩子——可挂分类标记，不改变 admission 语义（§6.7-3）。
14. 需要改核心才有的能力：队首 break→跳过语义、真第二队列+独立预算（§6.7-4）。
15. 入场前可得信息表（§6.6）——注意 P 本地 prefix hit 只能在分配流程内查（有副作用）。
**D. 仍阻碍安全实现的缺失信息**
16. B16 高压基线：waiting 深度/budget 用满/抢占率/token budget 分布（§8）——没有它，让行预算参数无从标定。
17. predictor 在 B>1、长提示下的误差分布（§5.4 只有一批样例）。
18. Motor attempt 的超时上限（长 waiting 下 Coordinator 侧行为）（§4.8-5）。
19. AISBench summarizer 的 TTFT/TPOT 精确口径（§7.3）。
**E. 下一阶段必须观察的正确性与性能风险**
20. P 侧 mooncake TRANSFER_FAIL 噪声在高压下是否放大（S5 观察项）。
21. 让行→FG 账本不衰减反馈→路由偏置的循环（§4.8-3）。
22. 长等待段的客户端超时→abort 频率上升（计数口径需剔除）。
23. deferred 请求饥饿（现骨架 `_max_deferred_per_step=999` 无实效上限）。
24. 抢占一旦在高压出现：FCFS 抢占=pop 最新入场者，与让行策略的交互未定义。
25. 吞吐回归风险：入场串行化本身（P 侧）是已知正常现象（2026-10-09 裁定），不应误判为策略缺陷。
**哪些信息不阻碍先做 demo**：A/B/C 全部 + D3/D4 的口径问题——足以构建**默认关闭、仅 P 侧、env 门控、可独立回退**的分类+让行 demo（接入位置 §6.7-1/2，回退=去 flag 重启）。
**哪些必须补齐后才能接真实调度**：D1（高压基线）与 D2（预测误差分布）——直接决定让行名额/队列长度/等待上限参数，缺则无法宣称"吞吐不降而 P90 改善"。

---

## 附：关键文件对照（内网路径 → 本文档嵌入位置）

| 内容 | 现场来源 | 本文档 |
| --- | --- | --- |
| 交付包源码（fgjsq/motor_adapter/slo_patch 全部） | EXP_10.20_MOTOR/00_intake/fgjsq-motor-p-0.2.0-20261019/src/ | §3.2/§3.3/§4/§5 关键段落全文嵌入 |
| Motor 七文件 patch | 同上 patches/motor/f203263d-p-fgjsq.patch（269 行） | §3.3 要点（全文随包） |
| 现役 recompute_scheduler | 容器 vllm-ascend（sha 23abae3c） | §2 再锚定 diff + §6 结构（本地副本 01_check/recompute_scheduler.rc1.py） |
| vllm scheduler.py / request_queue.py | 容器 /vllm-workspace/vllm | §6.2/§6.3 摘录（行号为该文件实际行号） |
| P/D 运行时 args | 04_stack_logs/n49_nmp.log:129 / n49_nmd.log:127 | §3.1/§3.4 |
| loads 账本 | GET :18081/fgjsq/v1/loads | §4.7 |
| trace/精度样例 | 04_stack_logs/n49_nmp.log:745-766 / n49_coord.log:1648-1675 | §4.6/§5.4 |
| smoke/d3/d6/d7 结果 | 04_chain/*.json/.log | §7.1 |
| AISBench 并发语义 | 07_bench/deps/benchmark_0630_release（_worker_loop） | §7.3 |