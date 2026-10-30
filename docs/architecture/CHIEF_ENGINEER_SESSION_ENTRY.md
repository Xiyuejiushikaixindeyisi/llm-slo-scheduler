# llm-slo-scheduler 总工程师会话入口

> 2026-10-30 版本更新：用户批准将 rc2、评审、建模与技术汇报整理为下一轮研发基线 `baseline-20261030`，合入 main 并推送。当前版本身份与复核见[版本说明](../engineering/DEVELOPMENT_BASELINE_20261030.md)。下文按日期保存的分支状态、“未合并”或现场前置限制仅描述当时；现场性能仍未验收，chunk 当前方向仍以 10 月 29 日入口为准。


更新日期：2026-10-28（北京时间）。维护会话：**建立项目进度监控与汇报**。工作根目录：`/home/zhangxiyue/llm-slo-scheduler`。

2026-10-29：Session 3 按用户要求局部同步 chunk 方向、优先级与 fork 入口；其余模块状态仍沿用原证据，未代替总工程师重新核验现场。Chunk 完整交接见[当前研究入口](../modeling/README.md)。

本项目面向 MaaS 的一个 GF＋XPYD 集群，研究如何在满足分档 P90 TTFT、P90 TPOT 的条件下提高服务吞吐与可承载并发。两条主要研究线分别控制 **GF 的请求入场机会**和 **P 引擎的批执行量**。本会话负责贯通业务目标、模块进度、实验证据和方案取舍，形成可核查的分析与汇报材料；各模块的设计、实现和现场执行仍由原负责人承担。

当前最重要的三个状态是：**g5 基线已完成本机对齐；GF admission rc2 已交付并通过本地复评，现场收益尚待回传；chunk 线已有初版数学设计、业界调研及 8 个 B=1 现场结果，当前主线为运行时工程机制、多项式低成本求解与累计 TTFT 时间约束。** 用户计划下一轮 fork 分别开展数学与工程研究，随后由新会话集成审阅并推进 demo；目前还不能宣布两条优化线已共同实现目标。

本文采用本次用户确认、四个相关会话的最近实质交付、当前工作区文件和对应证据。后文的测试数量是已有记录，本轮没有重跑运行测试或 NPU 实验；对新收到的预算 CSV 重新核对了 SHA256、样本数及所列相对变化。

## 1 本会话的职责与阅读入口

总工程师需要回答四个问题：当前实际运行和开发的是什么版本；哪项结论已有证据；下一步由谁完成、依赖什么；某个改动是否同时改善业务尾延迟和吞吐。进度按“设计、实现、本地验证、现场正确性、性能、发布”分别记录，不用一个完成百分比掩盖尚缺的现场环节。

| 阅读顺序 | 入口 | 用途 |
| --- | --- | --- |
| P0 | [项目约定](../../AGENTS.md)、[研究协作与交接](RESEARCH_COLLABORATION_AND_HANDOFF.md) | 工作边界、共享工作区、现场回传契约；时态以较新的明确记录为准 |
| P0 | [g5 本机对齐结果](../engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md)、[对齐审查与勘误](../engineering/G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md)、[首次版本](../engineering/INITIAL_VERSION_20261022.md) | 当前开发底座及继承契约 |
| P0 | [rc2 复评放行](../engineering/GF_ADMISSION_0.1.0rc2_REVIEW_20261022.md)、[交付身份](../engineering/GF_ADMISSION_0.1.0rc2_DELIVERY_20261022.md) | GF 线当前批准状态；覆盖旧“未实现／待复评”表述 |
| P0 | [Chunk 当前入口](../modeling/README.md)、[分工与启动提示](../modeling/CHUNK_RESEARCH_WORKSTREAMS_20261029.md) | 10 月 29 日路线、M/E/I 分工与交接；覆盖旧静态优先排序 |
| P1 | [MaaS token 实践与 g5 静态扫描](../modeling/MAAS_TOKEN_LIMIT_PRACTICES_AND_G5_EXPERIMENT.md) | 10 月 28 日现场数据与来源底稿，作为基线和反例 |
| P1 | [统一高压让行修订](../admission/GF_PRESSURE_ADMISSION_REVISION_20261022.md)、[完整工程设计](../admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md)、[运行指南](../engineering/GF_ADMISSION_RUNTIME_GUIDE.md) | 算法、状态机、安装与回退 |
| P1 | [动态预算初版设计](../modeling/DYNAMIC_BATCH_TOKEN_BUDGET_DESIGN_V0_1.md)、[动态预算数学审查](../modeling/DYNAMIC_BATCH_TOKEN_BUDGET_MODEL.md)、[chunk 业界调研](../modeling/CHUNK_SIZE_INDUSTRY_RESEARCH_SURVEY.md) | 保留的数学路线、反例与迁移边界 |
| P1 | [生产画像核对](../traffic/CLUSTER_FLOW_PROFILE_ANALYSIS_20260924.md)、[等待证据核对](../traffic/FINAL_WAITING_AND_ADMISSION_REVIEW_20261021.md) | 研究动机及不能外推的结论 |
| P2 | [研究指南](../LLM_TAIL_LATENCY_RESEARCH_GUIDE.md)、[super-p95 对比](../references/SUPER_P95_RESEARCH_AND_LLM_COMPARISON.md)、[原始成本函数核查](../modeling/COST_FUNCTION_SOURCE_AUDIT.md)、[KV 数学笔记](../modeling/CHUNK_SIZE_KV_CACHE_MATHEMATICAL_MODEL.md) | 历史推导、算法来源和深入追溯 |

已有研究指南是历史结论入口，不宜仅凭某一旧章节判定当前进度。本入口负责把最新状态连接起来，原始报告和历史评审继续保留。

## 2 业务结构与统一口径

### 2.1 MaaS 的服务链和研究边界

用户请求指定模型服务，例如 Qwen-V3.6-27B。GB 根据原始 JSON 的 tokenization 做上下文分流，不套 chat template，形成 32K／64K／128K 模型规格。规格是路由和 SLO 标签；可以采用相同部署方案，却承接不同流量。研究同规格内部的长短、命中和到达差异，不默认跨规格混排。

```mermaid
flowchart LR
    U[用户指定模型服务] --> A[AI 网关鉴权]
    A --> B[多个 GB 网关]
    B --> C[租户限流与上下文分流]
    C --> Q[每 GB 每规格局部队列]
    Q --> R[基于 Redis 信息的集群路由]
    R --> G
    subgraph S[本项目研究单位 一个 GF 加 XPYD 集群]
      G[GF 协议转换与实例路由] --> F[GF 入场控制与 FGJSQ]
      F --> P[P 节点 prefill 与批 token 预算]
      P --> K[KV 交接]
      K --> D[D 节点 decode]
      P -. 批事件与负载反馈 .-> F
    end
    D --> O[客户端流式响应]
```

- GB：租户超过其并发限额直接返回 403；未超租户限额的请求仍可能因聚合需求超过模型服务能力而进入队列。每个 GB、每个规格有自己的运行与等待队列，采用 VIP 优先的局部 FCFS，不保证全局 FCFS。多个 GB 用于分担网关负载，不能仅因使用 Redis 就假定全局原子限额已实现。
- GF：每个集群一个 GF，负责 OpenAI 格式转换、选择具体 P、采集 KV event／metric 并写入 Redis。本轮采用用户给定的前提：GB 已完成集群级 KV 亲和选择，GF 主要解决集群内部负载均衡。GF 使用缓存信息估计成本仍有意义，但不将任务扩展为重做 GB 路由。
- KV 池化：CPU／Disk／其他层可用 KV 不代表目标 NPU 已驻留。命中减少新计算量，读取长上下文和加载 KV 仍可能有成本；原始命中、加权 affinity 和实际执行成本要分开。

研究单位继续按一个 `instance_uuid` 对应的 GF＋XPYD 集群管理。当前工程底座是 3P3D、每个引擎 TP4、总计 24×910B2。生产九字段样本与 Motor g5 使用不同运行身份，不能因拓扑接近而合并为同一实验总体。

### 2.2 业务 SLO 和服务能力

| 模型规格 | P90 TTFT | P90 TPOT |
| --- | ---: | ---: |
| 32K | <12 s | <32 ms |
| 64K | <27 s | <30 ms |
| 128K | <30 s | <40 ms |

以上采用用户本次业务描述；旧材料中的 128K／45ms 保留为历史。服务准出以 AISBench 在指定输入、输出、缓存和并发条件下满足 SLO 的结果确定可提供并发。用户描述的生产并发低于对应准出压测并发，不等于生产 token 工作量一定更低：同规格流量仍有粗粒度分流、不同输入长度、缓存和输出，聚合 token 存量可能更大。

### 2.3 集群总并发与各 P 的路由分配

**用户于2026年10月28日最终澄清：B=16指整个GF＋3P3D集群合计16个在飞请求，包含prefill和decode；各P分配到多少请求由路由算法决定。** 不存在每P固定16的额度，也不能乘以3得到集群48。此前“每P16、合计48”的表述已撤回。

并发上限、实际在途与引擎批请求数分别记录：

| 量 | 本入口的写法 | 例子及限制 |
| --- | --- | --- |
| 单 GF 集群的业务并发额度 | `B_cluster_cap` | 本例为16，覆盖完整P/D请求生命周期 |
| 一次压测的客户端总并发上限 | `B_client_total` | B=16为向整个集群施加的总并发上限，不按P数倍增 |
| 各 P 关联的实际在途请求数 | 按P分别记录 | 由路由及请求生命周期动态决定，不假设平均分配或固定额度；FG未释放数另按账本语义解释 |
| 引擎某批实际请求数 | `n_batch` | 由运行队列、预算、KV和序列名额决定，不等于集群总并发或max_num_seqs配置值 |

这一口径与历史g5／rc2材料及[rc2六格计划](../../experiments/plans/GF_ADMISSION_RC2_AISBENCH_20261022.json)一致：B16/18/20均指一个3P3D集群的客户端总并发。无需因本次澄清修改既有实验配置或重标结果。业务准出额度与实验探索档位仍需区分，测试B18/20不表示已承诺提供该并发额度。

### 2.4 AISBench 发压与计时

**用户本次已确认修正口述，沿用 g5：完成一条补一条的滚动闭环，无整轮 barrier。** 并发是上限，实际在途通常不超过该上限，启动、限速、数据供给和收尾时可低于上限。用户描述的 1s 发包间隔需与具体 request_rate／发送控制配置关联，不能当作每轮屏障或恒定生产到达率。

这一行为与[g5 冻结报告第8.5节](../engineering/G5_FROZEN_BASELINE_HANDOVER.md)及已引用的 [AISBench 固定提交源码](https://github.com/AISBench/benchmark/blob/1e7cb37e3d5d2101db47fe3fe2272c965375a69c/ais_bench/benchmark/openicl/icl_inferencer/icl_base_api_inferencer.py#L363)一致：pressure worker 在请求完成后继续发送。该公开源码说明机制，现场版本身份仍以对应 run 为准。本地 [Ascend aisbench.py](../../upstream/vllm-ascend-v0.23.0/tools/aisbench.py)是配置／调用封装，不能单靠它证明内网客户端版本的完整行为。

正式 TTFT 从客户端 HTTP POST 前起点到汇总器记录的首个流式时间点；TPOT 使用同一 AISBench 汇总器。不另改为“首个有效 content”。GF 主动等待计入客户端 TTFT；P 的首次 queue_time、批耗时、KV 交接等用于解释，不能代替正式指标，也不能用聚合分位数相减得到阶段分位数。

## 3 g5 基线和模块协作机制

### 3.1 版本身份

| 对象 | 当前可引用身份 |
| --- | --- |
| 已交接的根仓库基线 | `3b63b00546e7a6ffb2526dafc341969cebe22359` |
| 当前开发分支／HEAD | `backup/20261022-init`／`8171c2da61a6fcfb3007e2fb30be57ce21b37337` |
| 本地 main／origin/main 引用 | 均为 `3b63b00`；本轮没有查询远端或推送 |
| GF rc2 实现 | `75c5e519195b55ce314fc00bf81b068f382e9cb1`；未合入 main |
| 冻结现场镜像 | `vllm-ascend:g5-g4base-motor-20261021-r1`；过程 tag 为 `v0.23.0-motor310-g4base-r2` |
| 固定源码 | vLLM `0fc695fc`；Ascend `5cb98caa`；Motor 设计锚 `f203263d`，完整身份见 [sources.lock](../../env/sources.lock.json) |
| 本机 Motor 开发副本 | `artifacts/build/motor-g5/`；包含七文件适配及 NodeManager fix1，不能整目录覆盖现场 |

g5 是完整 g4 正式引擎栈加 Motor、FGJSQ、predictor 的冻结底座。P 是 async `SchedulerWithPredictorAsync`、旧 SLO=0、FCFS／running-first／共享 8192 token、max_num_seqs=24。D 为原生 async，主模型 `enforce_eager=false`＋`FULL_DECODE_ONLY`，MTP3 speculative 为 `enforce_eager=true`；不能描述成全栈 eager。

本机对齐保留了 21 个算法核心文件，33 项冻结指纹匹配；对齐阶段 199 项 CPU 测试，首次版本阶段记录 207 项。NodeManager fix1 是按现场报告作语义对齐，不是远端全文件字节验证；现场 warm predictor 模型没有外传。详见[对齐结果](../engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md)和[首次版本说明](../engineering/INITIAL_VERSION_20261022.md)。

### 3.2 FGJSQ 和 predictor 怎样参与路由

当前负载均衡根据各 P 的未释放请求数 `N_p`、估计已提交负载 `W_p`、最大序列数 `M_p` 计算：

`score_p = W_p × (ceil(N_p / M_p) + 1) / 2`

score 越小越优先。`W_p` 随合法批事件和批时延预测更新；已调度部分随预测时间衰减，未调度剩余量保留，默认 retention=5% 只限制本批已调度部分的估计衰减。它不是最低服务保证，也不是物理剩余 token、KV 容量或预测 TTFT 的直接读数。[算法源码](../../src/fgjsq/policy.py)

生命周期为：GF 选 P 并预留 → P 异步组批／执行／上报带身份的冻结批事件 → GF 更新负载 → g5 HANDOFF 按先 P 后 D 衔接 → 按原生释放点及 D 首非空 body 观察点分别收尾 → abort／finish 幂等兜底。原生与 FG 两本 P 账都清零，不单独证明 D／完整 HTTP 生命周期结束。[服务账本](../../src/motor_adapter/service.py)、[body 观察器](../../src/motor_adapter/body_observer.py)、[事件快照](../../src/fgjsq/snapshot.py)

项目历史上称 predictor 为 batch-level TTFT 预测器，准确的工程含义是**批级主机观察耗时代理**：空流水线时是提交至观察完成，非空时是相邻观察完成间隔，单位 ms。它不直接输出单请求剩余 TTFT，也不是纯设备 kernel 时间。旧八维特征中的 `cache_hit_rate` 是由 prompt／computed 构造的 legacy 比例，不能当真实 APC 命中；computed 在调度时提前推进，不代表设备已经执行。`predict` 还有计数／日志副作用，新成本模型不能把它当严格纯函数反复试调用。[计时实现](../../src/slo_patch/patch_core.py)、[特征实现](../../src/slo_patch/slo/predictor_impl.py)

### 3.3 代码与资料在哪里

| 位置 | 作用 |
| --- | --- |
| [src/gf_admission](../../src/gf_admission/) | 独立入场包，分类、队列、broker、client、特征、压力和兼容检查 |
| [src/motor_adapter](../../src/motor_adapter/)、[src/fgjsq](../../src/fgjsq/) | Motor 桥接、native／FG 账本、事件身份和路由 |
| [src/slo_patch](../../src/slo_patch/) | predictor、P 异步调度适配、EngineCore 和批事件 |
| [docs/modeling](../modeling/) | 数学模型和预算调优研究；动态预算算法尚未形成运行实现 |
| [安装器](../../scripts/deploy/gf_admission_install.py)、[打包器](../../scripts/package/build_gf_runtime_bundle.py) | GF 增量安装、版本保护、回退与交付 |
| [压力工具](../../scripts/experiments/gf_pressure_probe.py)、[watchdog](../../scripts/experiments/gf_watchdog.py) | 已实现的现场辅助工具，真实通知接口需现场接入 |
| [evidence](../../evidence/)、[experiments](../../experiments/)、[artifacts](../../artifacts/) | 原件／来源 hash、实验计划与分析、构建及验证产物 |

## 4 已有实验支持什么

### 4.1 生产画像与历史等待

| 证据 | 可采用的观察 | 对决策的含义与范围 |
| --- | --- | --- |
| 2026-09-24 单 UUID 的 5,549 条生产记录 | <8K 输入占20.33%；零命中45.50%；命中≥90%占12.58%；≥32K且零命中1,268条，占22.85%，约占uncached工作量47.7% | 同一64K规格内成本差异显著，支持研究分类；不能证明同P同时竞争，也不能把整组22.85%都降级 |
| 同一生产画像的处理起点序列 | 0.7712次/s，约17.2K uncached token/s；分钟尺度Fano较大 | 是工作量与节奏描述，不是硬件吞吐、利用率或泊松证明 |
| EXP_10.9，g2生产trace开环重放 | heap／FGJSQ 的客户端TTFT P90为16.859／15.444s；首次P排队P90为8.746／7.811s | 历史路由改善与剩余等待同时存在；不能冒充Motor g5收益 |
| EXP_10.12／10.14 的126K、历史总B16 | 首次排队P50约20–30s；三P waiting合计10s稳态窗均值6.94、最大8 | 长输入有首次入场优化空间线索，尚未证明等待全部由可执行请求排序导致 |
| 同批历史66K、总B16 | 首次queue P50约0.5s、P90约0.8s | 首次入场控制可能覆盖有限；不能从聚合分位差定位剩余时间在running |

原件与核对：[生产原文](../traffic/CLUSTER_FLOW_PROFILE_REPORT_20260924.original.md)、[生产核对](../traffic/CLUSTER_FLOW_PROFILE_ANALYSIS_20260924.md)、[最终等待原文](../traffic/FINAL_WAITING_AND_ADMISSION_EVIDENCE_20261021.original.md)、[等待核对](../traffic/FINAL_WAITING_AND_ADMISSION_REVIEW_20261021.md)。EXP_10.14_TRACE是前两组实验的二次分析，不算独立重复。生产记录的延迟单位与completion语义未解决，因此该九字段报告没有可用的P90／SLO结论；这些边界已接受，集中流量调研已闭合。

### 4.2 g5 的现场工程起点

冻结 E2 128K、历史客户端总 B16 的两轮结果：TTFT mean 38.18／38.49s，P90 43.84／43.76s；TPOT mean 13.2／13.1ms，P90均14.2ms；QPS 0.298／0.2973，零失败。两轮分别通过工程恢复门槛，但 128K P90 TTFT 仍高于业务30s；TPOT相对g4约+7.5%，不能说完全无回归。[冻结报告第8节](../engineering/G5_FROZEN_BASELINE_HANDOVER.md)

这些轮次在连续服务生命周期内运行，predictor状态继承，不能称完全独立重启复现。冻结报告截至2026-10-21 13:09 UTC尚未完成十档验收，B1两项TPOT工程阈值未过。本会话未见后续完整验收报告，也不将10月28日的新预算扫描视为自动补齐该验收。

### 4.3 10 月 28 日接收的 P 预算扫描

用户确认仅改变 **P侧 max_num_batched_tokens**，g5、B=1、输入约66K／128K、目标prefix hit=50%，输出均值1024。CSV含8个run、每档一个r01、各30–43条，合计285条。实际输入均值约67,892／129,241 token。下表保留TTFT原值，单位按算术一致性推定ms，尚无导出schema确认；百分比不依赖该单位推定。

| 输入 | P预算标签 | TTFT P90 原值 | QPS | 相对同输入8K的P90变化 | QPS变化 |
| --- | --- | ---: | ---: | ---: | ---: |
| 66K | 8K | 6431.5 | 0.0541 | — | — |
| 66K | 16K | 6340.0 | 0.0540 | −1.42% | −0.18% |
| 66K | 32K | 6385.0 | 0.0542 | −0.72% | +0.18% |
| 66K | 64K | 9804.3 | 0.0454 | +52.44% | −16.08% |
| 128K | 8K | 13233.7 | 0.0395 | — | — |
| 128K | 16K | 13072.7 | 0.0401 | −1.22% | +1.52% |
| 128K | 32K | 12608.6 | 0.0403 | −4.72% | +2.03% |
| 128K | 64K | 12661.8 | 0.0405 | −4.32% | +2.53% |

这组实测支持按输入档保留不同静态候选：128K重点保留32K，66K保留8K／16K／32K平台区；不支持统一增大到64K。66K／64K的退化是真实观察，具体原因尚未定位。B=1不能证明多P容量或高并发下的最优点；一个r01也不足以给细小差异下稳定结论。目标50%不是实际命中保证，CSV的valid也没有补出失败计数。

原件：[perf_summary.original.csv](../../evidence/huawei/2026-10-28-g5-p-token-budget/perf_summary.original.csv)，SHA256 `73dffb52f08de0d544866a29c29f55a51ff9147354e75adfc39da942ff619be6`。计算记录：[B1分析JSON](../modeling/G5_P_TOKEN_BUDGET_B1_ANALYSIS.json)；完整解释：[静态预算实验第5节](../modeling/MAAS_TOKEN_LIMIT_PRACTICES_AND_G5_EXPERIMENT.md)。in_tps包含命中前缀，是客户端输入token吞吐，不是P新算token/s。

## 5 两条优化线的方案和成熟度

### 5.1 GF 入场与有限让行

目标是将部分请求的额外等待集中在有界的tail集合，为其他请求让出入场机会，改善**包含tail在内的整体请求总体**的P90 TTFT。已派发到P的请求不再受GF排序控制；GF不具备diffusion原型的step暂停能力。

rc2的规则是：

```text
成本可信且为正，压力有效
且（成本偏长 或 该请求合格候选P的最低FG score >= H）
且分类credit、tail数量S、tail成本V有余量
且请求未受保护、系统未排空
    → 可进入tail

normal优先FIFO
normal为空时，tail按LIFO尝试放行
实际候选P必须满足score <= L，且0 < L < H
每次CAS、切换候选P及成功预留后重新检查／记账
到龄、压力陈旧、drain时晋升为受保护normal
```

高压分支使同成本请求也能有限让行，已成为统一算法的一部分，没有benchmark专用分类开关。普通请求仍可按g5派发，因此H/L并不是全体请求的硬并发上限。tail候选只因资源资格不满足而进行有界跳过；压力拒绝不能变成另一个隐含的短作业搜索策略。[classifier](../../src/gf_admission/classifier.py)、[queue](../../src/gf_admission/queue.py)、[broker](../../src/gf_admission/broker.py)

分类成本与FG预留账本分开。当前特征路径使用Motor tokenizer及Conductor的NPU／CPU／Disk互斥覆盖，估计“未缓存量＋CPU加载权重×CPU覆盖＋Disk加载权重×Disk覆盖”，取合格候选的最低估计；缺失、过时或身份不匹配为unknown，不视作零命中。beta为可配置代理权重，尚未标定成真实服务时间。[features](../../src/gf_admission/features.py)、[provider](../../src/gf_admission/provider.py)

每20次逻辑到达补1个分类credit；候选credit cap=2、tail最多2条、驻留5s，并有成本上限。分类一次，不因传输重试重复扣额；credit不是滑窗比例、出队令牌或最低服务保证。5s只触发晋升，不是E2E期限。H/L与freshness需要现场证据选择并冻结；[enforce模板](../../configs/gf_admission/enforce.example.json)中的null不能直接启用。

**关于“低负载休眠、队列深度动态变化”：** 这是希望达到的运行表现，不能写成已实现的动态容量寻优。rc2的占用量随到达／派发变化，但数量上限S是静态配置；低压时同成本高压分支不触发，长成本分支仍可能分类为tail，随后在normal为空且资源可用时及时出队。是否基本无额外等待，要由运行证据确认。

工程上采用独立包＋Mgmt统一broker＋worker等待／HTTP保留的结构，在P预留前排队。QUEUED不占资源；后台READY_RESERVED（代码状态READY）有交付租约并需claim；CLAIMED不因租约过期盲目释放。off／shadow／enforce分开，未知预留结果不重复fallback，现场NodeManager fix1与engine_files.json保持受保护。rc1的同attempt重试、过期owner清理、特征总deadline、残留样本过滤四项问题已在rc2关闭。

成熟度：实现与本地复评通过；项目96、Motor309通过／8跳过，独立解包75通过，复评补充2项通过；这些集合不能相加为独立覆盖数量。真实ZMQ测试使用FakeNative，Python3.12／原生SHM／完整P-D／真实故障回退仍需现场验证。批准归档SHA为 `b23cee6b81d6f4f8b87b1e6cfd6fc28e7e8ed4bab3512c4ab6a4a7cecd1b0121`。[rc2复评](../engineering/GF_ADMISSION_0.1.0rc2_REVIEW_20261022.md)

### 5.2 P 侧执行预算与 chunk 寻优

本线要解决“给当前批多少执行量”。必须区分 API输出max_tokens、服务输入／总上下文上限、批总预算C、单请求每轮上限U、批请求数上限和KV容量。8192是g5每轮共享预算，不是单请求输出上限或整条prompt上限。

数学路线已从原始带到达率／等待项的效用函数，发展为冻结状态、模拟原生组批、计算实际新算量Q和历史交互、预测批成本、比较有限候选。两种模型为：

`T_S = α0 + αB·n_batch + αU·Q + αA·[Σ(u_i h_i) + (Σu_i² + Q)/2]`

`T_F = β0 + β1·n_batch + β2·Q + β3·Σu_i² + β4·Σ(u_i h_i)`

其中u_i是本批新算token，h_i是执行前所依赖的历史，Q≤C。结构模型S与自由模型F是可解释的候选成本模型，原初版以Q/T作局部评分，并保留固定预算、时间约束内最大进展作为比较。已有代数及合成反例验证，不是910B2拟合与性能验证。[初版设计](../modeling/DYNAMIC_BATCH_TOKEN_BUDGET_DESIGN_V0_1.md)

原始公式的`d_1,…,d_k`与`d_1,…,d_2`是两个有意保留的时间函数参数集合，不能当笔误合并；其含等待库存和未来到达量的分子也不能直接称完成吞吐。宏观KV微分模型仍是研究方向。旧LightGBM特征无法还原新模型所需的全部逐请求二次／历史交互项，不能直接换算成α／β；计时标签也要单独版本化。

已识别的核心风险：局部Q/T最优可能增加chunk次数、固定开销与KV重读，反而延迟完整prompt完成；更小预算也不自动改变running-first；候选模拟／预测增加的主机开销必须按关键路径和重叠关系测量。批平均成本不直接给出请求P90保证。

**10 月 29 日已纠正推进顺序：DeepInfer／Ascend 运行时工程机制与数学建模并行 → 独立集成审阅 → 第一版设计及可关闭 demo → 华为机验证。** 数学重点是根据候选后剩余完成时间、请求 TTFT 余量和可得实例压力形成时间约束，再用多项式低成本求解；不预设必须昂贵搜索，也不把大规模静态扫描作为前置条件。已有静态结果继续作为基线和反例。当前控制量仍为批总预算 c，不借此引入单请求优先级、waiting 重排或抢占；运行实现尚未完成，也不能凭现场扫描在任意现有进程中突破配置的能力上限。[当前路线与分工](../modeling/CHUNK_RESEARCH_WORKSTREAMS_20261029.md)

### 5.3 业界调研的作用

| 已有材料 | 借鉴内容 | 迁移边界 |
| --- | --- | --- |
| super-p95固定源码dd9c0895与[迁移研究](../references/SUPER_P95_RESEARCH_AND_LLM_COMPARISON.md) | 普通FIFO、让行LIFO、分类credit、普通优先 | 原型还含step暂停、路由折扣及可选batch2；历史Qwen P95约降21.3%伴吞吐约降8.5%，不能当本项目纯LIFO收益 |
| DeepInfer官方生产机制披露，见[方向纠正](../modeling/RUNTIME_CHUNK_TIME_CONSTRAINT_CORRECTION.md)与[来源定位](../modeling/CHUNK_RESEARCH_WORKSTREAMS_20261029.md) | FIFO、step时间预算、二次成本模型反求chunk | 生产披露与公开通用scheduler分开；完整内部quota实现及单项收益尚不能从公开代码补齐 |
| [NVIDIA预算扫描指南](https://nvidia.github.io/TensorRT-LLM/1.3.0rc23.post1/legacy/performance/performance-tuning-guide/tuning-max-batch-size-and-max-num-tokens.html) | 按工作负载扫描token预算与请求数上限，兼顾延迟及内存 | 提供选型方法，不提供910B2最佳数值 |
| [TGI参数定义](https://huggingface.co/docs/text-generation-inference/en/reference/launcher)、[vLLM优化说明](https://docs.vllm.ai/en/v0.23.0/configuration/optimization/) | 分离服务输入／输出／容量与每轮计算预算，理解延迟吞吐权衡 | 混部decode优先的通用描述不能覆盖当前固定P调度源码 |
| Ascend Dynamic Batch／Dynamic CPP，见[业界调研](../modeling/CHUNK_SIZE_INDUSTRY_RESEARCH_SURVEY.md) | 查表时间约束、历史上下文成本、低维拟合与反求 | Dynamic Batch依赖decode状态；CPP要求PP>1；不能当TP4、P-only g5即插即用开关 |
| Sarathi、QoServe、SGLang及其他研究，见同一[调研](../modeling/CHUNK_SIZE_INDUSTRY_RESEARCH_SURVEY.md) | 静态基线、分块累计开销、成本预测与优化目标分离 | 混部decode deadline不直接等于P-only的每批30／40ms上限，论文总收益不能归因于chunk单项 |

现有调研还覆盖AWS／BentoML、DJL、Anyscale和相关PR／issue，详细来源在[MaaS实践材料](../modeling/MAAS_TOKEN_LIMIT_PRACTICES_AND_G5_EXPERIMENT.md)。本会话不因汇总职责重新开启全行业或全链路调研；优先使用已沉淀的固定源码、成熟实践与现场数据。

## 6 会话分工和交接方式

以下名称与当前应用中的会话标题一致。应用是否idle／notLoaded只表示会话运行状态，不表示任务完成。

| 会话 | 职责与维护范围 | 当前实质进度 | 下一项交接 |
| --- | --- | --- | --- |
| **fgjsq+motor适配**，Session 1 | g5底座、Motor适配、配置／补丁／安装核验 | 10月22日完成对齐和首次main交接；207项CPU测试记录 | 按需核对现场基线差异，保护现有修复；不能将旧“尚待实现GF”当当前状态 |
| **super_P90设计文档**，Session 2 | GF机制、分类预算、设计变更、完整交付复评、实验解释 | rc2复评通过，R1–R4关闭，无新交付阻断项 | 接收现场证据，分析参数及机制；不是编码日常决策的前置审批人 |
| **super_P90代码编写**，编码会话 | gf_admission、窄钩子、测试、版本包、现场修复吸收 | rc2代码和桌面交付完成，尚无已接收现场性能结果 | 现场短验证／探测冻结／六格配对回传，吸收diff；满足条件后再处理main |
| **chunksize寻优建模与设计**，Session 3 | docs/modeling、成本模型、预算策略与业界研究 | 初版设计、调研、8点B1分析已完成；10月29日确认运行时机制＋累计TTFT约束，并整理fork交接 | M数学／E工程分别交接，后续I独立集成审阅与demo；新专题及运行实现尚未完成 |
| **建立项目进度监控与汇报**，本会话 | 总目标、状态账、证据分析、方案协同及汇报入口 | 完成当前上下文核对，建立本文 | 跟随新交付／回传更新进度，给出跨模块取舍建议 |
| 华为内网执行方 | 真实镜像、NPU、SHM、P/D、部署debug与压测 | 本机通过用户回传材料了解状态 | 返回一份关键源码／diff／结果直接嵌入正文的自包含Markdown |

只读定位用会话ID：Session 1 `01a157da-32c3-75d1-aee8-24e542bb5441`；Session 2 `01a13dd7-18a6-7003-a1c5-2177f76ac5bf`；编码 `01a161bd-bbb9-7412-91f6-cca1ba9dd95c`；Session 3 `01a15255-06c7-7763-a8f9-342aed189cb6`；本会话 `01a18169-ba9a-7e62-ae05-965b3d3ff807`。

所有本地会话共享同一worktree。读取其他会话和材料用于进度核对；本轮没有创建／fork会话、发送任务或接管模块实现。修改`src/motor_adapter`、slo_patch、补丁、版本锁及公共文档之前，要先核对最新文件与未提交变更。本轮工作区已有其他会话的共享文档修改、评审证据及未跟踪数学文档，均需保留，不能reset或顺带打包提交。

交接闭环沿用：[本机设计／代码／CPU验证 → WSL版本包校验 → Windows桌面交付 → 华为debug／真实栈验证／实验 → 自包含Markdown回传 → 本机核对与吸收](RESEARCH_COLLABORATION_AND_HANDOFF.md)。内网路径只是来源索引，关键证据必须进入正文。研究文档留在项目；本轮不生成交付压缩包。后续合并使用个人直接merge流程，但本轮没有commit／merge／push授权，也没有执行这些操作。

## 7 总工程师怎样评估联合优化

### 7.1 共同目标与验收维度

在同一规格、硬件、输入／输出、缓存流程和计时口径下，先用P90 TTFT、P90 TPOT筛选可接受配置，再比较完成吞吐与可承载并发。当前任务要求吞吐提升或不下降；若只有尾延迟改善而吞吐下降，应报告为权衡，不能自行设一个容忍百分比宣布达标。提高可承载并发也不自动等于提高QPS。

| 维度 | 每次汇报至少说明 |
| --- | --- |
| 业务结果 | 全体normal＋tail的成功延迟总体P90 TTFT、P90 TPOT，P95补充；对照值与绝对／相对变化 |
| 完整请求总体 | 到达、成功、失败、取消、超时、未完成；成功延迟的统计范围明确，失败不能被静默排除来声称“全体达标” |
| 吞吐 | QPS、输入／输出token/s及实际分母；客户端逻辑token与P实际新算token区分 |
| 单卡 | 明确分母是全服务24卡、P侧12卡还是其他范围；E2E服务吞吐／24不等于纯P硬件吞吐 |
| 并发 | B_cluster_cap、B_client_total、集群及各P实际在途；各P分配由路由决定，GF pending与引擎在途分开 |
| GF机制 | known／unknown、cost／pressure分类、tail直接派发、age／stale／drain晋升、越序证据、最老tail代价 |
| P预算机制 | 配置C、可选U、实际Q／批形状、标签类型、预测误差、搜索／提交关键路径开销 |
| 可比性 | 版本hash、run_id、重复轮、服务重启、缓存预热、predictor训练／权重状态是否继承 |

GF扣留请求导致引擎实际并发下降，是已批准研究的机制效果；要与真正的LIFO越序分开归因。`lifo_overtake_dispatches`中的older_eligible只说明旧候选满足路由／压力条件，没有对它实际执行一次native CAS，不能升级为硬件必然可执行证明。只报告tail分类次数不够。

闭环结果用于准出和对照，不能直接保证生产开环效果。生产的低请求数并发可能同时具有较大的未命中token、长上下文访存或短时积压；已有画像帮助解释场景，不要求先完成完整负载分布拟合或KV微分方程才能推进实验。

### 7.2 两条线需要分别归因再组合

以下是后续分析框架，不是本轮新增实验任务：

| 实验臂 | GF | P预算 | 回答的问题 |
| --- | --- | --- | --- |
| A | g5原路由／admission off | 固定8192 | 共同冻结对照 |
| B | rc2 enforce | 与A相同 | GF入场策略本身的收益和代价 |
| C | 与A相同 | 版本固定的P预算候选，与原生及必要静态参考比较 | P预算本身的收益和代价；候选可为运行时策略 |
| D | 已确认的GF策略 | 已确认的P候选 | 两者组合是否仍有净收益、是否出现交互 |

不能把B、C的百分比相加预测D。GF改变进入P的节奏、缓存和批构成；P预算改变服务速率、批事件间隔及FG压力演化，因此换C后可能需要重新审查H/L、freshness和成本模型的适用范围，并在正式配对前冻结。D的算法保持基线，但TPOT结果仍须测量。在线预算版本以后应对比最佳稳定静态点，而不只对比历史默认8192。

## 8 下一步安排与汇报维护

### 8.1 当前优先事项

| 优先级 | 应推进的工作 | 负责人／交付物 | 状态边界 |
| --- | --- | --- | --- |
| P0 | 持续统一集群总并发口径，并保留各P路由分配与实际在途 | 本会话维护口径；实验负责人记录实际配置 | B16/18/20均为整个集群总并发，既有六格计划无需因此改版 |
| P0 | 推进已放行rc2现场流程并回传结果 | 编码会话＋华为，Session 2兜底解释与评审 | 不再被旧rc1拒绝／rc2待评审措辞阻塞；尚不能报现场已通过 |
| P0 | 运行时工程机制与时间约束数学建模并行，先统一字段与时序契约 | M／E按[分工计划](../modeling/CHUNK_RESEARCH_WORKSTREAMS_20261029.md)交接 | 下一轮用户fork；已有B1结果作基线，不以静态扫描为前置 |
| P1 | 独立审阅两份交接，收敛第一版设计，再按启动任务开发可关闭demo | 后续I会话；总工程师协调跨模块边界 | 现场权重、剩余TTFT估计及P本地FG状态可得性不能猜补 |
| P1 | 分别评价入场和P预算，在共同指标下验证收益与代价 | 本会话汇总，模块负责人和华为机提供证据 | 不把B1或本机逻辑结果外推为高压收益；不引入重排或抢占 |

rc2既定现场顺序为：off／shadow兼容 → 复用已有压力证据或必要短探测选有效H/L → enforce真实SHM／P-D、取消清账／回退短验证 → 冻结参数并演练真实通知 → 正式配对压测。步骤可按依赖合理交错。当前六格为目标cache50%×实际约66K／128K×整个集群客户端总16／18／20；同长度使用同组冻结参数，优先B16配对重复。各P获得的请求由路由决定，不将总并发乘以P数。[华为prompt](../engineering/HUAWEI_AGENT_PROMPT_GF_RUNTIME.md)、[放行条件](../engineering/GF_ADMISSION_0.1.0rc2_REVIEW_20261022.md)

已有watchdog负责后台常规监测，正常轮询不调用模型；故障通知需要现场真实可用的agent接口及消费验证，脚本返回0不等于已唤醒。失败运行、修复diff、新版本和受影响配对重跑必须留痕。本会话本轮只建立上下文入口，没有创建周期自动化或启动监控服务。

### 8.2 每轮状态与证据记录

今后收到交付或现场回传时，按下面六项更新总览，不以聊天“完成”替代证据：

1. **身份**：模块、版本／hash、run_id、材料日期、配置变化及负责人。
2. **进度**：设计／实现／本地／现场／性能／发布分别完成到哪里。
3. **结果**：配对TTFT／TPOT／吞吐／失败及适用负载，注明来源。
4. **归因**：观察到哪些机制；哪些只是解释候选；有无控制变量混入。
5. **决定**：继续、修复、复评、冻结或回退，以及决定依据。
6. **下一步**：最小可执行动作、负责人和交付物，不自动扩展为环境／GB／全流量补采。

关键源码、diff、配置、计算和表格必须可在单份回传Markdown中核查；原件保持字节不变并记SHA，分析另存。低样本、无重复或单位推定等限制跟随对应结论，不生成没有依据的置信区间或“已显著提升”表述。

### 8.3 已识别的文档时态差异

| 旧表述 | 本会话采用的当前结论 |
| --- | --- |
| README／协作正文称新增编码会话待创建、GF尚未实现 | 编码会话已存在，rc2实现和交付完成 |
| 实施／交付说明仍称rc2待Session 2复评 | 以rc2独立复评记录为准：已通过，可进入现场流程 |
| 数学线先完成KV联合微分方程，或先静态扫描才考虑动态 | 10月29日路线：运行时工程机制＋多项式＋累计TTFT约束；完整KV模型与大规模静态扫描均非前置条件 |
| 此前误记为每P16、集群总48 | 用户最终澄清：整个GF＋3P3D集群总16，各P分配由路由决定；与既有六格计划一致 |
| AISBench整轮最慢请求完成才发下一轮 | 用户已修正：滚动闭环，完成一条补一条 |
| 原型／基线／CPU通过可说明目标已实现 | 分别保留证据身份；GF现场收益、联合优化和生产收益尚未确认 |

后续维护公共入口时采用局部增补，保留其他会话的未提交修改和历史原文。新的结论只有在明确对应版本、指标和负载之后，才进入共同决策记录与汇报。
