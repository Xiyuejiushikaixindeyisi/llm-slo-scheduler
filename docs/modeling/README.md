# Chunk 预算研究入口与 fork 交接

更新：2026-10-29，Session 3。本页是数学与工程机制研究的当前入口；下一轮由用户 fork，本轮仅整理文档和项目记忆。已完成初版数学设计、来源核查、现场 B1 结果分析与研究分工，**尚未完成专题交接、最终集成设计、demo 或动态算法的 NPU 验证**。

## 1. 当前决定

研究主线是：**从 DeepInfer、Ascend 等有工程支撑的运行时机制出发，用低成本多项式选择批预算，并以剩余 TTFT 余量和实例压力约束累计完成时间。** “先静态扫参，只有静态不足才研究动态”的 10 月 28 日排序已撤回。静态现场结果继续作为对照与反例，不是开展运行时设计的前置条件。

- 控制量 `c` 是 **P 整个 batch 的总 token 预算**；实际执行量 `Q=Σu_i≤c`，局部效率使用 `Q/预测时间`。它不是 API 输出 `max_tokens`、整条输入上限或每请求统一 chunk 上限。
- 沿用原生 FCFS、running-first 和资源分配顺序；首版不引入 waiting 重排、running/KV 抢占、D 侧调度或 FG 公式变更。动态算法目前仍处于研究/设计阶段。
- 保留结构约束模型与自由拟合模型；已有 LightGBM 与新多项式模型分版本，不默认旧训练表已含全部新特征。
- 单批吞吐最优可能使完整 prompt 更晚完成。先明确 step 时间约束，再估计候选执行后的剩余 P 服务/等待及后续链路成本，不能只用一批时长保证 TTFT。
- 目标是全体请求 P90 TTFT 改善、吞吐提升或不下降、分档 P90 TPOT 达标；P95 为补充。P90 目标不等于每条请求硬 deadline，也不对应固定牺牲 10% 请求。

## 2. 最短阅读路径

| 顺序 | 文件 | 用途与状态 |
| --- | --- | --- |
| 1 | [项目工作约定](../../AGENTS.md) | 最新基线、共享目录与会话权限；末尾 10 月 29 日记录覆盖旧 chunk 排序 |
| 2 | [方向纠正与时间约束](RUNTIME_CHUNK_TIME_CONSTRAINT_CORRECTION.md) | 当前路线、低成本分段求解、step 与累计 TTFT 的区别 |
| 3 | [研究分工与启动提示](CHUNK_RESEARCH_WORKSTREAMS_20261029.md) | M/E/I 职责、共同接口、相似研究、完成条件；第 8 节可直接用于下一轮 |
| 4 | [数学审查](DYNAMIC_BATCH_TOKEN_BUDGET_MODEL.md) → [初版设计 v0.1](DYNAMIC_BATCH_TOKEN_BUDGET_DESIGN_V0_1.md) | 已批准的工作量定义、两类模型、原生模拟与验证边界；后续时间约束扩展尚待收敛 |
| 5 | [g5 本机对齐结果](../engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md)及[审批稿与源码勘误](../engineering/G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md) | 预测标签、异步进度、FG 账本与实际接入语义；不能仅沿用早期摘要 |

工程研究另读下表来源底稿；不要求新会话先通读所有历史报告。

## 3. 文档与证据分层

| 类别 | 文档/材料 | 如何使用 |
| --- | --- | --- |
| 当前路线 | [方向纠正](RUNTIME_CHUNK_TIME_CONSTRAINT_CORRECTION.md)、[分工计划](CHUNK_RESEARCH_WORKSTREAMS_20261029.md) | 研究取舍与下一步以此为准；不是运行实现或收益报告 |
| 初版模型 | [动态预算审查](DYNAMIC_BATCH_TOKEN_BUDGET_MODEL.md)、[v0.1 设计](DYNAMIC_BATCH_TOKEN_BUDGET_DESIGN_V0_1.md)、[合成检查](DYNAMIC_BATCH_TOKEN_BUDGET_DESIGN_V0_1_CHECKS.json) | 保留定义、推导和反例；合成验证不等于 910B2 性能验证 |
| 业界来源底稿 | [技术调研](CHUNK_SIZE_INDUSTRY_RESEARCH_SURVEY.md)、[PR 状态快照](CHUNK_SIZE_INDUSTRY_RESEARCH_PR_STATUS.json) | 来源核验截至对应日期；后续引用固定 commit，必要时重核 PR 状态 |
| 现场预算证据 | [MaaS 参数与 g5 实验分析](MAAS_TOKEN_LIMIT_PRACTICES_AND_G5_EXPERIMENT.md)、[计算结果](G5_P_TOKEN_BUDGET_B1_ANALYSIS.json) | 保留 B1 实测结论，旧“静态优先”建议已被覆盖 |
| 原始现场数据 | [CSV 原件](../../evidence/huawei/2026-10-28-g5-p-token-budget/perf_summary.original.csv)、[来源清单](../../evidence/huawei/2026-10-28-g5-p-token-budget/manifest.json) | 保持字节不变；P-only 8K/16K/32K/64K，66K/128K，目标 cache 50%，8 个 run 共 285 条 |
| 历史数学与代码核查 | [自建分式与源码审查](COST_FUNCTION_SOURCE_AUDIT.md)、[KV 数学笔记](CHUNK_SIZE_KV_CACHE_MATHEMATICAL_MODEL.md) | 原公式 `d_k` 与 `d_2` 的区别保留；宏观 KV 微分方程仍为研究方向，不是首版前置条件 |

现场 B1 中，128K 的 32K 相对 8K：P90 TTFT −4.72%、QPS +2.03%；66K 的 64K 相对 8K：P90 TTFT +52.44%、QPS −16.08%。每档仅 r01，单位由一致性检查推定，重启/热身/实际命中过程未完整确认。不能将其写成高并发最优预算、动态算法收益或容量上限。

10 月 28 日的[项目技术汇报](../reports/LLM_SLO_SCHEDULER_TECHNICAL_BRIEF_20261028.html)保留为当日快照；其中 chunk 研究排序不覆盖本页。

## 4. 下一轮分工与文件所有权

| 工作线 | 下一步 | 负责产物（尚未创建） |
| --- | --- | --- |
| M：数学建模，建议当前会话继续 | 多项式成本 → 候选后剩余完成时间 → TTFT/压力时间约束 → 解析或分段求解、反例与不可行处理 | `CHUNK_TIME_BUDGET_MODEL_V1.md`、`CHUNK_MODEL_HANDOFF.md` |
| E：工程机制，由用户 fork | DeepInfer 生产披露与公开实现分别核查；Ascend Dynamic Batch 与 Dynamic CPP 分开；输出类图、时序图、活动图、组件与效果证据 | `engineering/DEEPINFER_RUNTIME_CHUNK_MECHANISM.md`、`engineering/ASCEND_DYNAMIC_BUDGET_MECHANISMS.md`、`engineering/CHUNK_ENGINEERING_HANDOFF.md` |
| I：集成审阅，用户后续新建 | 两份交接完成后独立审查、收敛最终设计，再按启动任务开发可关闭 demo 与交付 | `integration/CHUNK_OPTIMIZER_V1_DESIGN.md`及后续实现/验证记录 |

文件均相对 `docs/modeling/`。本轮不创建空壳产物，不提前编写 demo。三份可复制提示在[分工计划第 8 节](CHUNK_RESEARCH_WORKSTREAMS_20261029.md#8-会话启动提示可复制)；下轮选用相应提示即可。M/E/I 是 chunk 工作标签，不替代原 Session 1/2/3、GF 编码会话或总工程师职责。

先对齐[分工计划第 3 节](CHUNK_RESEARCH_WORKSTREAMS_20261029.md#3-两条研究线共用的最小约定)的数据契约，再各自研究。M/E 分别维护自己的产物，共享入口只作局部更新；不切换共享分支、不覆盖其他会话修改，不自动向其他会话发消息。未来 I 接入运行代码前核对当时版本与已有现场修复。

## 5. fork 后必须带走的事实与未决项

1. **g5 预测语义。** 当前是 LightGBM，标签为主机提交/相邻取结果间隔的 batch 观察耗时；不是请求剩余 TTFT，也不是已证实的纯设备时间。`predict()`有计数/日志副作用；候选求解不能反复调用真实调度或产生 KV/账本副作用。
2. **异步时序。** computed 在调度后提前推进，不代表设备已完成；候选后状态必须区分已提交与已完成，并定义从决策时刻到下一批完成的墙钟增量。当前模型缺少的量不能通过重复加算隐藏。
3. **FG 压力。** score/committed 不是秒或精确剩余服务量；事件主要是 P→GF，不能假设 P 本地已有新鲜 GF 状态。先核查可得性、更新成本、单位映射和去重，再讨论压力反馈；不默认增加每批同步 RPC。
4. **预测与开销。** 已观测批上的准确度不等于反事实预算准确度；未拿到现场完整权重。多项式运算量低，但“完整决策几十纳秒”和“优于 DeepInfer”均未验证。
5. **累计 TTFT。** 尚需定义剩余 P 成本、后续阶段估计、保护集合、误差裕量与不可行处理。请求已过期不能导致全局停摆；D 的 TPOT 约束不能直接作为 P-only 批时限。
6. **评价口径。** SLO：32K 12s/32ms、64K 27s/30ms、128K 30s/40ms（TTFT/TPOT）。AISBench B 是整个集群总并发，滚动闭环、完成一条补一条，无整轮 barrier；正式计时沿用 AISBench。
7. **边界。** 不假设平均吞吐接近容量；不重开 GB/全链路流量采集；利用现有报告设计最小必要验证。GF admission 和 P 动态预算分别归因，NPU 与性能结论由华为机实证。

建议对照链为固定原生预算 → 固定 step 时间约束＋多项式 → 累计 TTFT 约束 → 可得 FG 压力反馈，详见分工计划第 7 节。它用于区分机制贡献，不要求先做大规模扫参，也不是本轮新增实验任务。
