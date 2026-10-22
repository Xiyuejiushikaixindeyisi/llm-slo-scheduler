# g5 冻结基线与本机对齐审查（A–D 已批准）

> 2026-10-22 审批后更新：用户批准 A–D，并明确算法核心优先、配置与启动环境只同步，无需一比一复刻现场。实施已完成，见 [对齐结果](G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md)。下文保留审批时的核查与计划；“本轮仅审查”“待实施”等指当时状态。M08/M09 中完整启动/进程环境审计按最新范围收敛为参考配置与只读源码/可选导入检查，未新造集群编排器。

日期：2026-10-22。负责会话：Motor 适配与 g5 基线对齐。**本轮仅审查、记忆更新和文档落盘，没有修改运行代码、配置、补丁或依赖，没有执行部署。**

## 1. 审批结论与推荐组合

**推荐批准“保留算法核心，补齐现场修复、冻结配置及交付校验”的组合。无需重做 FGJSQ＋predictor，也无需在本机复刻整套 NPU 镜像。**

本机 `src/fgjsq`、`src/motor_adapter`、`src/slo_patch` 共 **21 个 Python/JSON 文件**与 2026-10-19 交付目录及其 wheel 对应内容全部一致。最终交接报告 §5.2 声明这三个包沿用交付代码；报告嵌入的 `policy.py`、`body_observer.py` 全文也与本机一致。本机固定 vLLM / vLLM-Ascend 已是最终 g5 使用的正式版提交，三个引擎文件实测 SHA256 与本机 `engine_files.json` 全部匹配。

**真正尚未对齐的是部署层和一处 Motor 修复。** 当前本机 Motor 开发副本只有原七文件 FGJSQ 补丁，缺少现场 NodeManager `lookup_rpc_port` 兼容修复；部署元数据仍指向旧 rc1 镜像；启动模板没有承载现场对称 HCCL 环境、唯一 JOB_NAME、完整 Motor 配置和启动顺序；冒烟脚本漏读 `delta.reasoning`。

建议本次审批以下范围，实施顺序见第 7 节：

| 编号 | 审批项 | 建议 |
| --- | --- | --- |
| A | 补齐 NodeManager fix1，形成可重建的本地 Motor g5 开发副本，保留原七文件补丁 | **批准** |
| B | 新增 g5 冻结配置档、更新环境身份记录、启动与只读预检/采集能力 | **批准** |
| C | 补回 smoke 的 `reasoning` 兼容；增加有针对性的回归测试；形成新版本交付与校验入口 | **批准** |
| D | 保持 FGJSQ、predictor、reporter、EngineCore overlay、原生引擎源码和 D 算法不变 | **批准保留** |
| E | 修改 predictor 特征/标签、真实 KV 感知、双队列、动态 chunk、抢占、继续深挖 TPOT 残差 | **不纳入本次基线同步**；由对应会话另行设计/审批 |

批准本节 A–D 只授权本机对齐实现、必要测试及交付准备，不代表十档压测最终验收，也不授权改变现场服务配置或直接重启实验集群。

## 2. 资料身份、证据范围与当前性能状态

### 2.1 原件和本次检查记录

- 原件：[G5_FROZEN_BASELINE_HANDOVER.md](G5_FROZEN_BASELINE_HANDOVER.md)，145,299 字节；保持字节不变。
- 原件 SHA256：`0995514a020978159fa49803e956380da435f2279cf9431f0920cbc5dbcc7aae`。
- 报告数据截止：**2026-10-21 13:09 UTC**。不能用本机阅读日期推断之后实验已经完成。
- 本次可复核记录：[g5_local_alignment_audit_20261022.json](../../evidence/manifests/g5_local_alignment_audit_20261022.json)：原件身份、本机 commit/clean 状态、21 文件逐项 SHA256、wheel 对比、Motor 七文件前后 hash、引擎三文件比对及报告代码块校验。
- 本轮直接检查的是**本地源码、原交付快照和报告正文**，未直接访问华为机器。报告称“零修改”与本机证明“逐字节相同”是不同证据，不能合并成“本机逐文件远程校验完毕”。

### 2.2 唯一采用的 g5 身份

| 项目 | 冻结报告中的 g5 | 本机情况与采用方式 |
| --- | --- | --- |
| 镜像 | `vllm-ascend:g5-g4base-motor-20261021-r1`，等同过程 tag `v0.23.0-motor310-g4base-r2` | 替换当前 rc1“目标”记录；旧记录转为历史 |
| 完整底座 | g4 实际 `quay.io/ascend/vllm-ascend:v0.23.0`，短 ID `660ce23a8357` | 作为现场事实记录；不在 WSL 模拟相同硬件运行栈 |
| vLLM | `0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665` | `upstream/vllm-v0.23.0` 已匹配、clean，**不换源码** |
| vLLM-Ascend | `5cb98caaadeff42b5b62b996e34bb2aaa29d20fd` | `upstream/vllm-ascend-v0.23.0` 已匹配、clean，**不换源码** |
| Motor | 现场 `3.1.0-main-0917`＋原交付七文件 patch＋NodeManager fix1 | 本地公开设计锚 `f203263d9742dd6fa76eaef658e0ff3a0f380301`；报告未给现场全树 commit/完整逐文件 SHA 清单，不把构建串视为全树一致证明 |
| 三个自有包 | `slo_patch 0.2.0` wheel 中的 `fgjsq` / `motor_adapter` / `slo_patch` | 本机与原交付一致；按报告继承为算法基线 |
| 现场依赖 | Python 3.12.13、torch 2.10.0+cpu、torch_npu 2.10.0.post4、CANN 9.0.1、mooncake 0.3.11.post1 | 记录组件及实际加载路径；WSL CPU 环境不承担 aarch64/NPU ABI 验证 |
| 拓扑 | 3 节点×8 张 910B2；每节点 P TP4 卡 0–3，D TP4 卡 4–7 | B 为整个 3P3D 集群并发 |
| P 调度 | `SchedulerWithPredictorAsync`，async=true，SLO=0，reporter/在线训练启用 | 保持；FCFS＋running-first＋共享 8192 token，max_num_seqs=24 |
| D 执行 | 原生 `AsyncRecomputeScheduler`；async=true；**enforce_eager=false、FULL_DECODE_ONLY**；MTP3 的 speculative enforce_eager=true | **不是“P/D 全部 eager”**。按最终报告区分 D 主模型图模式与 MTP 设置，不为了字面对称而改 D |
| 缓存 | P prefix=true、D prefix=false；MultiConnector；独立 Mooncake master | 保持，新增策略不改 D 路由/KV 算法 |
| 三节点镜像 | `.49=9ff2237f0ebe` / `.151=c590300504b9` / `.175=fb149ce8f7d2` | 原样记录为短 ID。相同上下文构建不等于所有镜像字节已验证相同；不把短 ID 当 registry digest |

报告已给出完整 Motor 配置、NM 脚本和构建 Dockerfile，可用于恢复**配置语义**。`g5_export`、完整 native 依赖、模型权重仍在内网，本文没有把它们假定为本机已持有。

### 2.3 性能状态可用，但尚非最终十档验收

| E2 128K×B16×PT900 | r01 | r02 |
| --- | --- | --- |
| 成功/总数 | 284/284 | 283/283 |
| TTFT mean / P90 | 38.18 / 43.84 s | 38.49 / 43.76 s |
| TPOT mean / P90 | 13.2 / 14.2 ms | 13.1 / 14.2 ms |
| QPS | 0.298 | 0.2973 |
| 失败、503、引擎退出 | 0 | 0 |

E2 每轮均通过原定 +10% 延迟 / −10% QPS 工程门槛，足以作为**已固化、可继续开发的现场起点**。TPOT 相对 g4 仍约 +7.5%，不能写成“完全无回归”。两轮连续生命周期、有共同缓存及 predictor 状态，不是独立随机试验；历史 g4 比较也不单独证明 Motor 的因果收益。

报告截止时十档只完成 128K B16、B1、B2，B4 在跑；B1 的 TPOT **mean 与 P90 两项**均未过，不只 mean 差 0.01 ms。完整十档与人工验收仍等待后续报告。最新业务 128K SLO 为 P90 TTFT 30 s / TPOT **40 ms**，报告 §8.6 的 45 ms 属旧值；E2 的 P90 TTFT 仍未达业务阈值。

## 3. 文件级差异与是否修改

表内“新增/修改”均为**审批后计划**，并非本轮已执行。

| ID | 本机文件/目录 | 差异或缺口 | 是否修改、具体建议 |
| --- | --- | --- | --- |
| M01 | `upstream/vllm-v0.23.0/`、`upstream/vllm-ascend-v0.23.0/` | 提交与新 g5 一致；三个锚文件也匹配本机允许值 | **不修改**；继续作固定、干净源码参考 |
| M02 | `src/fgjsq/`、`src/motor_adapter/`、`src/slo_patch/` | 21 文件与原交付及 wheel 一致，报告声明沿用 | **不修改算法核心**；不按报告摘录重新生成这些文件 |
| M03 | `src/slo_patch/engine_files.json` | 本机 recompute 已是正式版 `38111806…`；报告 async hash 有字符矛盾 | **保留本机现值**，不抄报告 hash；第 4.1 节给完整证据 |
| M04 | `patches/motor/f203263d-p-fgjsq.patch`、`f203263d-files.json` | 七文件前后 hash 与 `upstream/motor` / `artifacts/build/motor` 全部吻合 | **保留原件**；它们是可追溯的原适配补丁，不混入新算法 |
| M05 | `upstream/motor/motor/config/node_manager.py:280`；开发副本同路径 | 两处仍直接读 store 顶层 lookup port，缺现场 fix1 | **必须补齐**：新增独立 fix1 patch 与清单，应用到可重建开发副本；不污染 `upstream`，见第 4.2 节 |
| M06 | `env/delivery-target.json`、`env/sources.lock.json` | 仍指旧 rc1 目标/旧 g4 取证状态，缺冻结身份和数据截止 | **必须更新**：历史与当前分开；新增 `env/onsite-g5-frozen-reported.json` 保存现场报告值、证据等级、缺失字段；公开 commit 不改 |
| M07 | `configs/baseline/` | 只有抽象 argv 模板与 FG 配置，缺冻结 Motor/NM/基准负载配置 | **必须新增** `configs/baseline/g5-frozen/`：Motor 运行档、角色环境、FG 配置、负载说明和现场路径映射；原模板保留通用用途 |
| M08 | `scripts/deploy/launch_local.py` | 可按角色执行单命令，但不是集群编排器；不校验 HCCL 对称、唯一 job、Mooncake 启动序 | **补充**独立 g5 启动计划渲染/检查入口；优先复用现场已验收启动链，不造第二套重启/杀进程系统。默认只渲染/校验，明确执行才启动 |
| M09 | `scripts/validate/preflight.py`、`scripts/collect/collect_runtime.py` | 浅层 find_spec 和七文件清单不足；采集脚本默认 rc1；缺 NodeManager fix、真实 import 路径、底座依赖及角色配置核验 | **必须增强**：深层 import battery、模块 origin/hash、fix 状态、实际进程参数/选定 env、对称性检查和 warm model 身份；不得输出密钥 |
| M10 | `scripts/deploy/install_motor_patch.py` | 当前 check/apply 只认 before，已打七文件的冻结 g5 会被当 mismatch；未管理 fix1 | **必须增强状态识别**：pristine / 原七文件已装 / g5 已对齐 / unknown 分开。已安装不重复 apply；未知失败关闭；回退仅撤销本次新增内容，不撤掉现场基线 fix1 |
| M11 | `scripts/validate/smoke.py:48` | 只读 content 或 reasoning_content，漏 Qwen3.6 的 reasoning | **必须修改**为三字段兼容；只改功能冒烟解析，不改 AISBench 正式 TTFT/TPOT 口径、Motor 字节观察器或业务输出 |
| M12 | `scripts/package/build_release.py`、`scripts/validate/verify_delivery.py` | 固定旧包名和旧 rc1 README/状态；只带七文件清单/旧文档；缺 g5 目标与新校验资料 | **应更新交付工具**：新工具包版本、带冻结身份/新增 fix/校验说明，校验已装基线再叠加策略；旧 0.2.0 工件不可覆盖。算法 wheel 不因部署工具变化就强制重装 |
| M13 | `models/predictor/` | 只有占位文件；报告仅给 `model.pkl` SHA 前缀 `142f3364…`，无完整模型 | **记录外部依赖，不伪造模型**；本机可测接口/确定性样本，现场继续原模型。新策略测试要约定模型版本及是否重启/继承在线训练状态 |
| M14 | 根 README、AGENTS、docs 索引及各设计入口 | “两会话”“rc1”“仅冒烟成功”等历史时态已过期 | **更新共同入口和记忆**；本轮已更新最小入口。入场/数学设计的技术正文由对应会话维护，不在共享目录抢写 |
| M15 | `src/admission/`、`src/chunking/`、D 调度、predictor v2 | 尚未实现的新研究方向 | **本轮不修改**。基线对齐后由两个研究会话分别推进；不要用“对齐”名义引入新策略 |

M07 的关键配置应明确列出：P/D max_num_seqs=24、token budget=8192、model_len=131072；P additional_config 的 predictor 开关与 reporter host/port；D 否定式 `no_enable_prefix_caching=true`；P runtime async=true；D FULL_DECODE_ONLY；HANDOFF、单 P endpoint、单 Mgmt；当前 fault_tolerance / engine_relaunch 均为 false（记录实验值，不当成生产推荐）；节点角色唯一 JOB_NAME；P-only 插件环境；P/D 共同 HCCL/ASCEND/OMP 环境。

现场 HCCL 段实际含 **16 个 export**，不以报告“15项”的文字计数为准。IP、NIC、端口、模型路径要参数化，但参数化后的有效值必须与冻结档一致。`config_sample.json.image_name` 仍有历史 rc1 字符串，报告称裸 Docker 路径不消费它；归档原值，当前有效镜像另作显式字段，不能让新部署路径误消费旧值。

## 4. 需要精确处理的两处差异

### 4.1 引擎 hash：这次不需要重新适配

本机 `src/slo_patch/engine_files.json`、原交付 wheel 与固定上游实测结果一致：

```text
vllm.v1.engine.core
cf9cbde601afb80925254aae814033abeab3817f9c4fe7bf01ca92edc9d10c2d

vllm.v1.core.sched.async_scheduler
0022e12f356fd46406f6e6d3c82755daf7287ca2d86e2000c27b05bb8d9621cc

vllm_ascend.core.recompute_scheduler
38111806d9434e4267482a63a453f6f4328a5d0bf9ae931fa17ad38208d79202
```

报告 §4.6 把第二项写成：

```text
0022e12f356fd46406f6a6d3c82755daf7287ca2d86e2000c27b05bb8d9621cc
                  ^ 此处与本机及原交付不一致
```

差异为 `06f6e6` vs `06f6a6`。这与报告“包零修改、三锚实测匹配、服务启动通过”的组合叙述矛盾，**疑似转录错误，不能据此改允许值**。需内网后续在单份 MD 中补贴实际 `sha256sum` 与安装后 JSON 的这两行；不需要重跑压测。

同理，报告 §6.E 的“完整 activate.py”出现 `from slo_patch.compatibility import verify_engine()`，AST 校验是语法错误，本机原文件为合法的 `from ... import verify_engine`。说明报告部分代码块是整理后的摘录，不能当可直接覆盖文件的原始源码。

`engine_files.json` 不是“发现不匹配就回填”的绕过开关。未来引擎变更仍须先做调用契约/控制流审查和验证，再生成新版本允许清单。三文件 hash 也不等于整个运行环境兼容性证明。

### 4.2 NodeManager fix1：有明确语义，缺完整现场字节证据

本地公开源码和 `artifacts/build/motor` 中的 NodeManager 文件均为：

```text
SHA256 = 9d1121d46ac707d2168f5bb1606797029595c3dbb2b565d8fea0996299adac35
```

实际局部原代码见 [node_manager.py](../../upstream/motor/motor/config/node_manager.py:273)：

```python
store = connectors[1]
if store.get(KV_CONNECTOR_KEY) != UCM_CONNECTOR:
    config.lookup_rpc_port = int(store[LOOPUP_RPC_PORT_KEY]) + lookup_rpc_port_offset
```

现场报告 §3.2 给出修复原则：**先读 store 顶层，缺失则读 `kv_connector_extra_config`，再缺失默认字符串 `"0"`。** 报告摘录没有完整展示 `config.lookup_rpc_port` 赋值、`int()`、offset 和 UCM 外层条件，因此本地补丁必须保留这些原有语义，而非复制一段孤立赋值。

拟实现局部逻辑如下（审批提案，尚未写入代码）：

```python
if store.get(KV_CONNECTOR_KEY) != UCM_CONNECTOR:
    if LOOPUP_RPC_PORT_KEY in store:
        lookup_rpc_port = store[LOOPUP_RPC_PORT_KEY]
    else:
        extra = store.get(KV_CONNECTOR_EXTRA_CONFIG_KEY) or {}
        lookup_rpc_port = extra.get(LOOPUP_RPC_PORT_KEY, "0")
    config.lookup_rpc_port = int(lookup_rpc_port) + lookup_rpc_port_offset
```

建议新增 `patches/motor/f203263d-g5-node-manager-lookup.patch` 及对应 before/after 清单，不把它并进原七文件 patch。应用顺序：固定公开 Motor → 七文件 FGJSQ patch → fix1 → 校验 → 本地 g5 开发副本。

测试必须覆盖顶层优先、extra 回落、默认 0、P/D offset、UCM 跳过和不合法值。报告给出的现场 after SHA 仅有 `c098842c…`，不能声称本地生成补丁与现场字节一致。后续仅需完整 fix1 hunk＋完整 SHA 即可闭合；此前可标为“按现场语义重建”，不能用不明哈希放行任意文件。

## 5. 原报告的采用范围与关键勘误

这份报告是**珍贵的现场实验与部署事实来源**；以下勘误保护后续设计，不否定 E2 已通过的现场结果。原件保持不变，本节作为旁注。依据优先级：用户最新明确约定 → 对应版本实际源码 → 有运行证据的现场事实；报告中的推断/代码摘录不覆盖前两者。

| # | 报告位置/表述 | 本机核查与应采用的解释 | 影响 |
| --- | --- | --- | --- |
| C01 | §4.6 async hash；§6.E activate 全文 | 存在第 4.1 节的 hash 字符矛盾和 import 语法错误 | 不从 Markdown 重建整包；优先原交付文件 |
| C02 | §6.B.5 “computed 在 update_from_output 才前进” | [Scheduler._update_after_schedule](../../upstream/vllm-v0.23.0/vllm/v1/core/sched/scheduler.py:997) 在 schedule 后立即 `+= num_scheduled_token`；[RecomputeScheduler](../../upstream/vllm-ascend-v0.23.0/vllm_ascend/core/recompute_scheduler.py:822) 调用该链。完成后再做拒绝 token 等修正 | computed 可能包含未完成工作，不能当真实完成量 |
| C03 | §6.C 标签“vllm-ascend 产生的占位间隔” | 标签实际由 [patch_core.py](../../src/slo_patch/patch_core.py:251) 写入：提交时队列空取 `t4-submit`，否则取 `t4-last_exec_finish`，再传给 update。是 **主机观察的提交至取结果/相邻取结果间隔**，不是任意占位值或设备 kernel 时间 | chunk 数学模型要针对这个观测量，不直接称请求 TTFT；低 R² 的因果未证明 |
| C04 | §6.C predict“纯函数、无副作用、sub-ms” | [predictor_impl.py](../../src/slo_patch/slo/predictor_impl.py:258) 会累加 `_predict_count`、周期日志；后台训练会替换 snapshot。报告未嵌入足以保证所有候选 sub-ms 的统计 | 不改排队/KV，但不是严格纯函数；同轮候选可比较性和预测预算须单独设计 |
| C05 | §6.C.6 “接口能区分任意 chunk” | 现接口只有 B/Lavg/legacy rate；同样三个输入必定不能表达不同 chunk 分配。伪造 Lavg/rate 来编码 C 会改变训练特征语义 | 保留 g5 v1；新 cost model 另行版本化，不默默改 v1 |
| C06 | §6.B/6.D get_computed_blocks“touch/占块、只能队首查询” | [kv_cache_manager.py](../../upstream/vllm-v0.23.0/vllm/v1/core/kv_cache_manager.py:196) 是命中查找并可能更新统计；touch 在 [single_type_kv_cache_manager.py](../../upstream/vllm-v0.23.0/vllm/v1/core/single_type_kv_cache_manager.py:231) 的分配链。查询也非免费/无副作用，结果可能失效 | 不据此断言 waiting 的 KV 无法观察；不等于授权现在增加查询 |
| C07 | §6.D “P producer 的 external 查询=已算完可传输”；§4.9 P→master→D | [pool_scheduler.py](../../upstream/vllm-ascend-v0.23.0/vllm_ascend/distributed/kv_transfer/kv_pool/ascend_store/pool_scheduler.py:491) 查询可加载的外部 KV，producer 未被一概排除；V1 另有 [直接 transfer 路径](../../upstream/vllm-ascend-v0.23.0/vllm_ascend/distributed/kv_transfer/kv_p2p/mooncake_connector.py:962)。控制/寻址与 KV 数据传输不是同一条箭头 | 外部命中不能自动归因某一个 connector；不能把 master 画成所有 KV payload 的中转节点 |
| C08 | §6.A.1 score“翻倍、指数级”“load 持续压低 score” | [policy.py](../../src/fgjsq/policy.py:59) 为 `load*(ceil(count/limit)+1)/2`，系数阶梯增长，count 从 limit 到 limit+1 是 1→1.5，非指数；load 大使 score **升高**，rank 升序更不易选中 | GF 压力阈值方向不能读反；retention=5% 不是最低服务保证 |
| C09 | §4.4 reserve_window_s=30 是衰减参考 | [bindings.py](../../src/motor_adapter/bindings.py:112) 和 [service.py](../../src/motor_adapter/service.py:90) 用它限制**首次预留命令有效期**；已有 key 先幂等返回。衰减分母是 predicted_ms；active reservation 没有 30s 自动到期释放 | 不拿 30s 当让行预算/自动回收 TTL；GF 应在真正放行时创建 reserve 命令 |
| C10 | §4.1 在 P 执行前 allocate(D)；§5.2 “CONCURRENT_ENGINE”；把 finish_attempt 当 native-only 释放 | 实际仅允许 [HANDOFF](../../src/motor_adapter/bindings.py:201)。[Motor HANDOFF](../../artifacts/build/motor/motor/coordinator/router/strategies/unified_pd.py:1584) 先等待 P 结果，再后台 release P native，随后确保 D 资源；[finish_attempt](../../src/motor_adapter/bindings.py:222) 发的是 **abort 双账兜底** | 不因为该时序图更改当前正确代码。native 与 FG flag 独立；D 首非空 bytes 触发 FG 释放，不等于首有效 token |
| C11 | §6.A.5 示例 computed=8192、scheduled=8192、remaining=117808、prompt=126000 | [snapshot.py](../../src/fgjsq/snapshot.py:27) 的 computed 字段为 schedule 后 computed 减本批 count；若首块无缓存应为 0，remaining 才是 117808。示例不能视为真实逐请求日志 | 保留真实 freeze 时序与字段定义；不要用示例校正算法 |
| C12 | §5.4/8.3 FG 开关四轮指标 <1%→“零行为变更” | 性能接近不能证明 FG 与 RR 路由语义相同；SLO=0 只说明该 prefilter 不改变原生调度决策，predictor/reporter/打点仍有执行与开销 | 保留“未观察到该轮性能差异”，不能拿它替代协议/控制流回归测试 |
| C13 | §7 “独立 entrypoint 无冲突”；§6.E 去 P env 即关闭 | [patch_runtime.py](../../src/slo_patch/patch_runtime.py:220) 会覆盖 scheduler_cls，且替换 EngineCore 两方法；独立插件仍有顺序/覆盖冲突。停用必须协调 GF、P 插件与服务重启，不能留下 FG 开但 P 事件链已关 | 新 chunk 插件须显式组合契约；入场 off 必须回到完整 g5，不卸载其基线插件 |
| C14 | §9 残差继续归因 rc1→final 的 435 文件；TRANSFER_FAIL 非零必为 env 漏配；缓存不影响 TPOT | 新 g5 与 g4 已同正式版，旧 rc1 差异不能直接解释两者剩余 +7.5%；这些均缺单变量证据。错误有多种原因；缓存可间接改变系统负载 | 不引出不必要的新引擎改造，不做绝对因果结论 |
| C15 | §8 128K TPOT 45ms；§0 对 B1 只强调 mean 边缘 | 最新用户约定为 **40ms**；§8.4 同时记录 B1 TPOT P90 未过 | 工程容差、业务 SLO、全十档最终验收分开记录 |

另：`coordinator_epoch` 在 [service.py](../../src/motor_adapter/service.py:33) 是重启重新生成的 UUID，不是数值递增。事件 `stale` 指 batch_seq 过旧，释放后事件归 `unknown_or_released`，不能把两种丢弃原因混成“乱序释放被 stale 拒绝”。

Motor 固定源码存在 KV Conductor/tokenization 能力；当前 g5 的 FG 预估路径仍是 `req_len//4`。报告没有证明 Conductor 的候选 KV 命中信号已接入该 FG 路径，保持“源码有能力、现场接入未确认”的区分，不重开大规模流量调查。

## 6. 给两个研究会话的基线契约

### 6.1 入场策略会话

继续以 [G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md](../admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md) 的 **normal pending FIFO / sacrificial pending LIFO** 为设计起点。该文第 2 节仍有 rc1/仅冒烟成功的历史身份，实施前应引用本审查和最终交接更新身份；本轮不替该会话改写算法设计。

- GF 等待应在创建 FG reserve 命令、占 P native/FG 账之前；真正放行后沿用 g5 的 rank→native CAS→FG reserve。否则长期等待既影响路由账本，又可能消耗命令 deadline。
- 维持 nonce/attempt/epoch/generation、重试幂等、CAS fallback 候选检查、取消与双释放契约。`finish_attempt` 不是“只释放 native”的可替代通知。
- D 路由与引擎保持 g5；P 原生 FCFS/running-first/8192 预算保持。GF 无法暂停已派发请求。
- off 模式必须回到完整冻结 g5；不重装原 `slo_patch`，不覆盖 fix1、预训练权重和 engine hash。
- 压力 score 是账本估计，不是准确 running 数；5% retention 与 30s reserve 窗均不是让行保护预算。

### 6.2 数学建模 / chunk 会话

用户自建目标函数、batch cost 与 KV 宏观微分模型继续由数学会话研究，本审查不把它们当已验证算法。

- g5 的 predictor v1 是既有 FGJSQ 反馈组件，应保留它的特征/标签/模型接口；新 chunk 成本模型可以旁路、新版本实现，不能为了“修正命名”直接改变 FG 衰减输入。
- legacy `cache_hit_rate=(prompt-computed)/prompt` 为 schedule 后批级剩余比例。它既非真实 prefix hit，也非简单“当前 chunk token 数”；特征里的 `N_uncached` 名称也不能直接按实际本批工作量理解。
- 当前真实标签是主机观测批间隔；新模型需要明确 C 如何映射到特征、预测对象、异步流水关系以及同轮候选使用的模型 snapshot。对同一三元组试探不同 C 并不会获得可辨识成本曲线。
- P/D 分离下，本轮算法只作用 P；不能直接把共享实例中大量 decode 与 prefill 混批的假设套进 P 池，需说明 P 上实际包含的执行阶段/MTP 工作。
- 本机没有现场模型字节，不宣称数值复现；现场可继续使用同一个 warm-start 文件。未来模型变更的比较要记录启动权重和在线训练状态，不能把重启清状态当作无关动作。

## 7. 审批后的实施与验收顺序

### 阶段 L1：建立本地可复核的 g5 源码与配置档

1. 保留原交付目录、wheel、原始报告和固定 upstream；从固定 Motor＋七文件 patch＋fix1 生成开发副本，例如 `artifacts/build/motor-g5/`。该副本是构建产物，维护源仍是 `upstream`＋`patches`。
2. 写入现场身份、配置和角色环境档；完整记录报告中已知值与未知值，不填造完整镜像 digest、模型 SHA 或未提供的配置。
3. 校验业务包 21 文件与 g5 v1 基准一致、引擎三锚一致、七文件 hooks 一致；fix1 单独列明是现场字节确认还是本地语义重建。

**L1 通过后两个会话可基于明确的本地逻辑基线开始开发。** 不必等本地具备 NPU，也不必先获取完整内网目录。涉及实际安装的文件仍须在现场检查 hash/接口后再应用。

### 阶段 L2：工具与针对性测试

| 验证面 | 验收内容 |
| --- | --- |
| fix1 | 顶层/嵌套/缺省、P/D offset、UCM、非法值的边界；只改变目标兼容行为 |
| 安装器 | pristine 安装、已装七文件、已对齐 g5、未知文件、失败恢复；重复运行不二次 patch；回退不删除原现场修复 |
| 启动/预检 | 只渲染无执行；P/D 环境隔离与共同通信变量；unique JOB_NAME；有效镜像非 rc1；无 rc1 editable finder；深层依赖实际可导入 |
| 冒烟 | content / reasoning / reasoning_content、空 delta、DONE；正式 AISBench 指标口径不变 |
| 既有协议 | 原 FG 事件重放、未知 reserve 结果、取消/重复/迟到事件、双释放、D body 保真 |
| 引擎 | 现有同步/异步控制流与 feature-label 批次配对检查；不靠 CPU fake 宣称 NPU 正确 |
| 打包 | 新版本 manifest、原件 hash、支持的基线与 apply/revert 说明；无宿主编译 native 库混入；包在 WSL 准备后按约定移至 Windows 桌面并复核 SHA |

Motor 测试遵守其仓库入口，使用 `bash tests/run_tests.sh`；先单文件再模块。现有 2026-10-19 测试记录仅作为历史，不能改日期冒充本轮验证。本轮做了读文件、Git 状态、SHA256、wheel 对比及 AST 核查，**没有重跑测试，也没有改环境**。

### 阶段 L3：形成对其它会话稳定的交付入口

输出一份 `G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md`，记录实际修改、测试、仍未闭合的证据和基线指纹。入场/数学会话从该指纹继续，不各自重做 Motor 适配。

后续给华为的优化包以**已有冻结 g5**为安装目标，只包含新策略及窄 hook；不是要求现场再次构建整套镜像。任何修改 `motor_adapter` 的策略包也要列出所替换文件的 before/after 与关闭回归，不能把冻结基线文件静默改成新版本。

本机完成设计/编码/CPU 测试 → 华为执行 debug/NPU 正确性与完整压测 → 华为回传单份自包含 MD → 本机核对、迭代。回传文档始终要求**关键源码、diff、配置、原始结果与判定证据直接嵌入正文**，内网路径只作来源索引。

## 8. 还缺哪些证据，哪些不应阻塞开发

无需完整代码包或完整日志。后续内网文档追加下列小块即可：

1. **优先**：实际安装 `engine_files.json` 与 `async_scheduler.py` 的 SHA256，澄清转录矛盾。
2. **优先**：NodeManager fix1 完整 hunk（含 int/offset/UCM 上下文）与文件完整 SHA256；最好附七个 Motor hook 文件逐个 SHA256。当前聚合 MD5 未附生成规则，不能用来逐文件安装校验。
3. **记录项**：warm-start model.pkl 完整 SHA256、加载版本及在线产物关系。模型字节无法外传时接受限制，不要求替换现场模型。
4. **后续验收项**：十档完整结果与用户裁定，尤其 B1 两个 TPOT 项。它决定性能验收状态，不改变本文已确认的源码差异。

无需为这些证据新增压测。现有源码/文件只读摘录即可。完整 `g5_export`、模型权重、NPU native `.so` 不要求同步到 WSL。缺少它们意味着本机未复刻现场运行环境，**不意味着无法建立可开发、可传递的 g5 逻辑基线**。

## 9. 三会话协作与本轮变更记录

- **本会话**：维护 Motor 适配和 g5 基线对齐、安装/核验/交付契约。
- **入场会话**：维护双队列设计与后续实现；当前普通 FIFO / 让行 LIFO，基线对齐后推进第一版。
- **数学会话**：维护目标函数、predictor 成本映射与 KV 宏观模型；工程接口需求明确后协调实现。
- 三者共享同一工作树。修改共享文件先读最新内容；不覆盖其它会话的未提交改动，不自动向其它会话发消息。

本轮仅新增本审批稿、审查证据 JSON，并更新 AGENTS/项目与文档入口的最新状态。最终交接原件未改；`src`、`patches`、`configs`、`env`、`scripts`、`tests`、upstream 和历史交付包均未修改。**当前状态：已完成对齐审查，等待本节所列代码与工具改动的人工审批，尚未宣称本机实现已对齐。**
