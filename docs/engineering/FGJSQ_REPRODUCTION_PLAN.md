# FGJSQ 与 predictor 基线复现

当前目标是在 MindIE-Motor 中接入 P 池 FGJSQ，并保留 P 引擎 predictor、reporter 和在线训练链路。D 引擎及其路由保持现场基线。先核对原实现与迁移实现的行为，再研究入场分类与让行预算。

## 已有材料与版本

用户提供的 DOC1 描述 10.13 g2：P/D 都注入 slo_patch，FGJSQ 使用 P/D 双池。这是组件增量说明，不能作为本次仅 P 侧交付的完整启动配置。新的 [g4 取证报告](../../evidence/huawei/2026-10-19-g4-forensics/FGJSQ_P_ONLY_REPRO_FORENSICS.txt) 对应历史栈 TAG=20261015_134536，已 teardown。该报告明确 P 启用 predictor/reporter，D 保留原生调度与已有 Hook3 chat_utils 兼容包装。

2026-10-19 取证报告给出的 vLLM/vLLM-Ascend 完整提交与本地固定 checkout 一致，并报告源码树 clean、插件通过 vllm.general_plugins 挂载。镜像为 quay.io/ascend/vllm-ascend:v0.23.0，arm64，Image ID 已记录；由于 docker load 导入，RepoDigests 为空。依据与运行时未决项见 [现场环境记录](../../env/onsite-g4-reported.json)，本地源码见 [版本清单](../../env/sources.lock.json)。报告明确原 proxy 栈未部署 Motor；仍按用户指定 f203263d9742dd6fa76eaef658e0ff3a0f380301 设计，不能将其标为现场已匹配版本。

## 必须对齐的行为

1. FGJSQ 的负载公式、时间衰减、波次除数、同分规则、预留与释放；不能依据摘要猜写。
2. P 请求和批事件的身份、事件顺序与进度含义；整批预测不能未经核对当作每请求独立成本累加。
3. 实际异步调度的提交批与完成批对应关系，predictor 特征与训练标签的计时边界。
4. 原 proxy 在首个 D chunk 释放 P 路由账本的语义；由 Motor 观察响应接线，无须修改 D 引擎。
5. Motor 多 worker 的共同负载视图、原子预留及取消/重试清理。
6. SLO=0 时保持原生调度路径；确认各 Hook 的 P 侧启用范围和必要性。

## 当前审查结果与待提供材料

2026-10-19 已收到 g4 proxy、slo_patch 包内 9 个文件和聊天粘贴的 setup.py，已归档并记录 SHA256。已完成 FGJSQ 公式、事件与释放、predictor 特征/标签及 Motor 接线点核查，具体文件级设计见 [适配审批稿](FGJSQ_MOTOR_ADAPTATION_REVIEW.md)。用户已批准推荐组合，P 侧适配代码已实现并通过本地逻辑与接口测试；交付包及现场执行入口见 [工程交付说明](FGJSQ_MOTOR_DELIVERY.md)。目标改为用户指定 rc1＋Motor 镜像，本机未读取该镜像，兼容性仍需现场核对。

待提供：原始 model.pkl、启动脚本、实际依赖版本、Motor 现场配置，以及一条能够关联派发 ID、引擎 ID、batch payload、updated 计数和释放的脱敏 trace。完整投递路径见 [投递清单](G4_SOURCE_INTAKE.md)。模型缺失不阻塞代码审查，但不能声称预测数值已复现。

## 推进顺序与验收

先核对版本、源码和事件协议；再用原实现与迁移实现重放相同事件，比较路由决策、账本状态、预测特征与调用顺序；随后接入固定版本 Motor 和 P 异步插件，进行必要的接口验证。最后由实验机验证安装、回退、功能和性能。

源码已确认 cache_hit_rate 是剩余比例，h=0 不被当前样本过滤拒绝；标准 chat ID 截尾关联不相容，异步标签是主机观察间隔。详细证据、修正范围与待现场补证项见适配审批稿。

本地逻辑对照与 NPU 性能结论分开记录。未来基线通过后再讨论双等待队列的入队条件与预算；动态 chunk 的数学研究在 docs/modeling 独立推进。

## 2026-10-20：g5 现场上下文与下一阶段研究记忆

来源为用户提供的 [G5_BASELINE_HANDOVER.md](G5_BASELINE_HANDOVER.md)，报告截止 2026-10-20 02:3x UTC。本节记录现场报告及本机有限源码核对，不代表本机访问过实验机。此前各节保留为交付历史；不再将“取得完整模型/脚本/代码包并复刻环境”作为下一阶段前提。仅凭单份 Markdown 补足接口上下文，后续优先交付默认关闭、P-only、便于接入与回退的独立 demo/插件或小补丁。

### 已接收的基线事实

- 报告 §1、§7：3P3D 链路和短请求冒烟通过，三路 P 有事件与 predictor 更新，结束后两个账本归零；8k 请求输出正常。报告截止时 B16×128K AISBench 尚因客户端依赖问题未成功启动，不能作为高压基线或性能收益证明。后续用户提供新结果时再更新。
- 报告 §2：`fgjsq`、`motor_adapter`、`slo_patch` 的 Python 算法实现沿用 0.2.0；FG 公式/身份关联/释放时点、predictor 特征/标签没有现场改写。安装后的兼容性清单和实验 smoke 副本确有修改，不能笼统称“交付内容完全未变”。
- 报告 §3：P 为 `SchedulerWithPredictorAsync → SchedulerWithPredictor → AsyncRecomputeScheduler → AsyncScheduler → RecomputeScheduler → Scheduler`，async=true、FCFS、running-first、共享 max_num_batched_tokens=8192、max_num_seqs=24、max_model_len=131072。chunked prefill 开启；long_prefill_token_threshold=0 仍是未获运行时显式值的推断。P prefix caching=true、enforce_eager=true；D prefix caching=false、使用 decode graph；报告记载 P/D 均配置 MTP3。不要将旧报告中的 eager 模式泛化到 g5 的 D。
- P 的旧 SLO admission 硬关闭：`ENABLE_VLLM_TTFT_SLO_MS=0`；非零会被 activate 拒绝。D 未启用 P predictor/reporter hooks，D 参数以 g5 现场配置为基线。
- 报告 §5：三 P 加载预训练 predictor，各有独立实例并接收更新样本；没有充分证据表明已完成新一轮模型训练。legacy `cache_hit_rate` 是批级剩余比例，标签是异步主机观察间隔；均不是实际 APC 命中率或请求级剩余 TTFT。首批样例预测 821ms、观察标签 6172.5ms，不据此概括所有负载的误差。
- 报告 §7.3：AISBench 压力模式为 worker 完成后补发，无整轮 barrier；推翻此前“等 B 条全部完成才发下一轮”的假设。实际渲染的 request_rate 和 TTFT/TPOT 精确口径仍未完整核对。

### 现场修改及后续必须保留的内容

| 变化 | 对下一阶段的影响 |
| --- | --- |
| Motor `config/node_manager.py`：lookup_rpc_port 顶层键缺失时回退读取 kv_connector_extra_config | 启动兼容修复，保持现场状态；不需要在双队列算法中重新实现 |
| 安装后 engine_files.json：Ascend recompute_scheduler 期望 hash 改为现场 `23abae3c…`，原生引擎文件未改 | 镜像与本机固定 Ascend 源码不同。仅收到缩写 hash 和局部 diff，不据此生成新白名单或覆盖现场清单 |
| 每节点每角色唯一 JOB_NAME，串行启动 NM，自持 Mooncake master，清理遗留实验资源 | 属于部署规程；新调度实验复用 g5，不重复搭建环境 |
| D 采用合法 bool CLI `--no-enable-prefix-caching`；P 补 api_server_host/port 兼容占位 | D 维持 g5；真实 reporter URL 来自 reservation，勿将占位身份当网络地址 |
| 实验副本 smoke 支持 content/reasoning/reasoning_content | 后续首输出与正确性检查须识别 reasoning；首 HTTP bytes、首有效输出与 AISBench TTFT 不能混用 |

现场已固化 `vllm-ascend:g5-motor-fgjsq-20261019` 基线镜像（报告 §3.2）。后续只回退新增双队列机制时，应恢复 g5 的 FGJSQ＋predictor，不应通过关闭整个 slo_patch 来充当算法对照。

### 对 super-p95 研究的直接影响（尚未选算法）

1. 当前基线没有启用双队列。后续主线是**首次入场前的请求分类与有限让行预算**，以全体请求 P90 TTFT 和吞吐为目标，P95 补充、P90 TPOT 为约束；不先引入 running/KV 抢占或动态 chunk。
2. running-first 下，仅调整未入场候选，不能使已经 running 的长 prefill 主动让出预算；能改善多少尾等待取决于真实积压、到达时序和成本异质性。高压数据缺失不妨碍机制讨论或默认关闭的 demo，但不支持声称有效或标定参数。
3. FGJSQ 在首次批事件前保持初始负载，不因等待自动衰减；延后 admission 会延长记账并反馈到后续选路（报告 §4，本机 `src/fgjsq/policy.py`、`src/fgjsq/snapshot.py`）。这是需要观察的路由与引擎交互，不预设其利弊。
4. 插件需保留现有 async MRO、predictor、冻结快照、两类释放点及取消/异常清理；单独继承同步 RecomputeScheduler 且丢失 predictor，不能视为兼容方案。加载顺序、scheduler 选择覆盖和独立关闭方式留到下一轮讨论。
5. 旧 `_slo_prefilter_waiting` 只能参考其调用位置；其 EDF/deadline、用批耗时近似 TTFT、回队和异常处理不等于 super-p95 双队列，也没有经过 g5 启用验证。不直接打开旧 SLO 开关来实施新实验。
6. 延后请求仍属于总体样本；必须观察公平性、最长等待和超时/失败，不能从性能统计中剔除被让行或超时请求来制造改善。Mooncake TRANSFER_FAIL、64K/128K 档内成本差异、P waiting 分布和预测误差仍待现场数据。

### 报告中不直接写成既定事实的判断

本机只做了以下与下一阶段相关的有限核对；保留原报告原文，不就地改写。

- **异步 computed 计数**：报告 §6.5 写“update_from_output 才前进”，与本机 vLLM `_update_after_schedule` 不符：schedule 后已经增加 num_computed_tokens，Ascend schedule 调用该方法；它可能包含尚未执行完成的计划 token。依据 [scheduler.py](../../upstream/vllm-v0.23.0/vllm/v1/core/sched/scheduler.py) `_update_after_schedule`、[recompute_scheduler.py](../../upstream/vllm-ascend-v0.23.0/vllm_ascend/core/recompute_scheduler.py) 的调用。不能拿它当真实已完成量。
- **缓存查询与分配**：报告 §6.6 把 get_computed_blocks 等同 touch/占块，证据不足。本机 [kv_cache_manager.py](../../upstream/vllm-v0.23.0/vllm/v1/core/kv_cache_manager.py) 的该方法做命中查询并可能更新统计；touch 位于 [single_type_kv_cache_manager.py](../../upstream/vllm-v0.23.0/vllm/v1/core/single_type_kv_cache_manager.py) 的分配路径。不能因此认定 waiting 命中不可观察，也不能直接认定现场查询免费、无副作用；需核对现场对应方法、统计污染和查询后失效风险。
- **事件计数**：报告 §1 的“五计数均15”与 §4.7 原快照不一致，后者为 reserved/release_native/release_fg=15，received/matched=17。依据 [service.py](../../src/motor_adapter/service.py) `events`，matched 按接受的请求批事件计数，同一请求可多次上报；不能将多出的2条解释为被丢弃事件，也不能从单个空闲快照证明所有异常路径均无泄漏。
- **未入场事件**：依据 [snapshot.py](../../src/fgjsq/snapshot.py) `freeze_snapshot`，仅遍历 output.num_scheduled_tokens；尚未首次调度的 deferred 请求通常没有事件，不应照搬报告 §4.8“waiting 会收到 scheduled=0 事件”的描述。
- **必须改核心的断言**：报告 §6.7“独立第二队列＋预算必然修改原生 admission 循环”尚无证明。候选过滤/队列适配与修改原生资源失败 break 是不同能力，应分别评估。暂不承诺独立插件一定足够，也不把核心修改定为前提。
- **predict 纯函数与新开关**：本机 [predictor_impl.py](../../src/slo_patch/slo/predictor_impl.py) `predict` 修改计数且周期日志，线程能力不能由“无锁”推出；[activate.py](../../src/slo_patch/activate.py) 也不拒绝所有未知新环境变量。独立开关本身不必然要求修改 activate，但插件组合顺序仍需设计。
- **Ascend 差异**：报告只嵌入了 num_in_flight_tokens 扣减/failed-KV 顺序的局部 diff；不足以推出“现役更保守”或完整失败路径安全性。后续尽量不改该路径，不能只换 hash 代替语义核对。

下一轮范围：讨论 super-p95 与 g5 的兼容点、适用负载和有效机制；本轮没有修改运行代码、启用新策略或要求重建现场环境。

