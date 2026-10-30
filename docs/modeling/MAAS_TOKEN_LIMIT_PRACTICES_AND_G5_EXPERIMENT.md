# MaaS token 上限的成熟实践与 g5 静态预算实验

> 2026-10-29纠正：上一轮将“成熟实践”误收窄为静态离线扫描。当前以有工程依据的运行时chunk决策、多项式低成本求解和时间约束为主线；见 [方向纠正与时间约束](RUNTIME_CHUNK_TIME_CONSTRAINT_CORRECTION.md)。旧文实验与来源保留，静态优先的研究排序已被覆盖。

2026-10-28，Session 3，v1.0。承接[业界 chunk 调研](CHUNK_SIZE_INDUSTRY_RESEARCH_SURVEY.md)。本稿当时提出静态配置、场景分档和现场扫描优先；**这一研究排序已于 10 月 29 日撤回**，不能继续作为用户当前任务。参数定义、来源和现场分析保留，当前路线与 fork 交接见[研究入口](README.md)。

本轮只有文献/源码核查、用户CSV分析及归档，没有启动新实验、改变配置、实现动态算法或修改GF/D代码。已由用户明确确认：本次8K/16K/32K/64K仅改变P侧 `max_num_batched_tokens`。

## 1. 本轮回答的问题与证据等级

我们关心的不是“最新论文提出了什么”，而是：在TOB在线服务、长上下文、混合长度、不同并发下，已有系统如何选择批预算、单请求分块上限与服务输入上限，以及怎样用低运行开销达到吞吐/尾延迟目标。

证据按用途分开：

- **本项目现场结果：** 用户提供的g5、910B2压测，是本项目相关性最高的观察证据。CSV是8个run的原始交付汇总，不是285条逐请求明细；数值可信不等于所有机理已被证明。
- **成熟工程实践：** NVIDIA、AWS、Hugging Face、Anyscale及SGLang的官方文档、官方调参实验。它们支持方法和参数语义，不直接给出910B2的最佳数值。
- **源码：** 用固定v0.23.0核查参数是否真正被消费，避免把文档选项当成有效功能。
- **issue/PR：** 用于识别真实问题与实验设计线索；发帖人的生产描述和未复现结果不提升为厂商保证。
- **论文：** Sarathi、QoServe等继续解释权衡，但本轮不以复杂在线寻优作为默认落点。

## 2. “max token”和“单条最长prefill”必须拆成不同控制量

| 层面 | 含义 | 典型参数 | 对性能的作用 |
| --- | --- | --- | --- |
| API输出上限 | 单请求最多生成多少token | `max_tokens` / `max_new_tokens` | 改变D耗时与KV增长，不是本次扫描对象 |
| 服务输入上限 | 单请求总prompt最多多长 | TGI `max_input_tokens`；入口校验 | 产品规格、内存保护、超长请求处理契约 |
| 请求总上下文上限 | 输入＋输出允许的总长度 | vLLM `max_model_len`；TGI `max_total_tokens` | 不能简单把它等同输入上限 |
| 单轮批预算 C | 一批最多新增计算多少token | vLLM `max_num_batched_tokens` | 本次P侧8K/16K/32K/64K变量 |
| 单请求本轮上限 U | 一个请求本轮最多算多少token | 当前固定引擎的 `long_prefill_token_threshold` 正值截断 | 允许大批预算与较小单请求块同时存在 |
| 批请求数上限 | 一批最多多少条请求 | `max_num_seqs` / `max_batch_size` | 与C、KV共同约束batch形状 |
| KV/潜在总token容量 | 活跃序列累计存量，而非本轮新增量 | TGI `max_batch_total_tokens` 等 | 不能与C做同名等价替换 |

如果“单条最长prefill”指**整个输入**，应研究产品规格与输入限制；如果指**一轮计算块**，则研究U。长文档允许128K输入，不要求一次prefill计算128K，也不意味着将输出上限设128K。

当前项目已按32K/64K/128K规格分流，本稿不建议跨规格混排，不建议未经业务约定按输入长度P99截断客户请求。TOB输入规格应与超限拒绝、专用长上下文服务或客户端显式切分的契约一致；后两种处理属于业务选择，不是本轮执行操作。

## 3. 官方实践：哪些内容可直接作为起点

### 3.1 NVIDIA TensorRT-LLM：离线扫描，联合看batch数与token预算

官方调参指南建议以2的幂扫描 `max_num_tokens`，并与 `max_batch_size` 组合比较。其Llama-3.3-70B、4×H100案例，在batch上限512时，2048/8192/16384预算的token吞吐分别为2474.26/2466.79/2461.02，差异很小，最大预算并非最佳。该页明确讨论大预算的激活内存与KV空间权衡。[N1]

**迁移判断：** 采用“固定场景→离线扫描→选折中点→部署固定配置”的过程。其案例数字仅说明非单调与平台区现象，不是我们的推荐值；页面属于legacy build-flow，不能把其构建期内存行为逐字套给vLLM eager。

### 3.2 AWS＋BentoML：按负载挑Pareto点，而非唯一全局参数

AWS公开Qwen3-4B的SageMaker实验，扫描TP={1,2,4}、预算={4096,8192,16384}、并发={32,64,128}。文章报告高吞吐点与低延迟点使用不同预算/并发，并输出配置及Pareto结果。[A1]

**迁移判断：** 这是当前最值得借鉴的工程流程。先对现有部署做预算×并发扫描，按业务SLO筛选，再选吞吐较高且稳定的配置。不能将多变量联合提升归因于预算一项。该文叙述部署L4而estimate示例使用L40，且演示输入长度与ShareGPT实测不同，故不使用其理论估计或百分比作为跨系统定量标杆。

### 3.3 AWS JumpStart＋Hugging Face TGI：服务保护与计算预算分开

AWS的TOB端点说明分别配置输入上限、输入输出总上限、并发保护、prefill预算与批总token容量；早期TGI路径中prefill会暂停decode。当前HF launcher仍明确区分 `max_input_tokens`、`max_total_tokens`、`max_batch_prefill_tokens` 和 `max_batch_total_tokens`。[A2][H1]

**迁移判断：** 先定义服务接收哪些请求，再调执行预算。TGI文档中的 `max_input_tokens+50` 默认关系有其版本/后端语境，不能复制为支持chunked prefill的vLLM规则；TGI批总token容量也不是vLLM单轮预算。

### 3.4 DJL/LMI：先找可运行内存边界，再保留KV余量

DJL的历史TRTLLM教程提供离线查找预算的流程：试算、失败后缩小、二分查找不导致engine cache OOM的边界，并建议为paged KV保留空间。示例基于LMI 0.29.0/TRTLLM 0.11.0。[D1]

**迁移判断：** “容量可行”和“延迟/吞吐最优”是两次不同筛选。这个查找在部署前做，不是每个batch寻优；教程的比例和减半经验不能直接当910B2的安全系数。当前不要求在生产服务中主动触发OOM。

### 3.5 vLLM：官方建议是扫描起点，不是单调定律

固定v0.23.0优化文档给出小预算改善混部ITL、大预算改善prefill效率的指导，尤其建议小模型/大GPU探索超过8192的吞吐点。[V1]

**迁移判断：** 这为你的8K/16K/32K/64K扫描提供合理起点，但不证明“越大TTFT越低”。你的66K结果正说明实际部署需要测量。当前P-only也没有相同的批内decode竞争，不能用混部ITL经验直接决定P预算。

### 3.6 SGLang：先判断内存压力发生在哪个阶段

官方调参文档区分prefill OOM和decode OOM：前者可减小chunk（给出4096/2048例子），后者考虑降低running请求数；静态KV池与activation/graph buffer也需协调。[S1]

**迁移判断：** 不把“token预算变大”只理解为计算变化。预留内存、可用KV块、缓存行为都可能随配置变化。但这些只是解释候选，尚不能据此断言本次66K/64K点的慢来自显存。

### 3.7 Anyscale、NIM：TOB服务应按场景和负载定配置

Anyscale分别讨论高并发、长上下文、大模型部署；长上下文不能任意压缩服务规格时，需要在并发和硬件容量之间权衡。NVIDIA NIM基准指南要求依据实际输入/输出分布选择场景并扫描负载，明确固定并发为完成一条再补一条。[Y1][N2]

**迁移判断：** 64K/128K规格、低并发/高并发、冷/热前缀应分别保留测试身份。离线批处理的“容忍高延迟以换吞吐”与在线TOB的承诺SLO不能共用一个最优配置。

## 4. 单请求本轮上限U：有价值，但先核对版本语义

本机固定 `vllm-ascend` commit `5cb98caa` 的 `core/recompute_scheduler.py`：

- running路径233–235附近：若 `0 < long_prefill_token_threshold < num_new_tokens`，先截断到阈值，再与剩余token预算取min。
- waiting路径565附近：计算未完成量后做同样截断，再受预算/资源约束。
- 因而可以研究 **C较大＋U较小**，让多个请求各贡献一块；不需要先引入逐批预测搜索。
- 这只给单请求的本轮分配设上限，不保证所有waiting都入场，不等于公平轮转，也不消除running-first或KV阻塞。
- 对固定核心V1及Ascend core检索，未找到 `max_num_partial_prefills` / `max_long_partial_prefills` 的调度消费点，虽然配置仍有字段。不能据字段说明就把这些开关当作当前有效的并发prefill控制。[C1]

**B=1无法判断U能否缓解请求间竞争。** 而且当U比C小很多时，只剩单条请求可能无法填满C。应先测C，再在确有多个候选竞争的场景比较U；不要同时改变两者后混合归因。

### 社区实际问题与版本陷阱

[vLLM issue #57413](https://github.com/vllm-project/vllm/issues/57413) 的作者报告长RAG、约100K–180K输入及短输出的生产问题，讨论并发partial prefill控制。它是有用的TOB形态参考，但作者对阻塞原因的解释不是本项目的既定结论。

[issue #60476](https://github.com/vllm-project/vllm/issues/60476) 报告v0.31.0对单请求放宽阈值后，短请求到达可能碰上已提交的大块，并讨论异步batch queue。关联[#57951](https://github.com/vllm-project/vllm/pull/57951)、[#58459](https://github.com/vllm-project/vllm/pull/58459)仅作该讨论的变更索引；本轮未审计这些PR diff或合入状态，不提出回移植。

这些较新版本讨论说明：**即使参数名不变，单请求豁免、异步预提交也能改变效果。** 当前0.23.0按固定源码判断，不能把新版故障直接归给g5，也不以issue中的实验值作为高置信度标杆。

## 5. g5现场实验：材料身份与口径

### 5.1 归档与已知条件

原始文件来自用户 `C:/Users/ALIENWARE/Downloads/perf_summary.csv`，已原字节归档：

[evidence/huawei/2026-10-28-g5-p-token-budget/perf_summary.original.csv](../../evidence/huawei/2026-10-28-g5-p-token-budget/perf_summary.original.csv)

SHA256：`73dffb52f08de0d544866a29c29f55a51ff9147354e75adfc39da942ff619be6`。

[机器可读计算记录](G5_P_TOKEN_BUDGET_B1_ANALYSIS.json)保留全部8行及相对变化、算术核对。源文件未修改。

| 条件 | 来源与确认程度 |
| --- | --- |
| g5、3P3D/TP4、910B2、模型与P/D执行模式 | 用户指定g5；背景依据冻结交接及对齐文档，CSV本身不含镜像指纹 |
| 改动范围 | 用户本轮明确：仅P侧max_num_batched_tokens |
| 预算 | 用户/round标签：8K、16K、32K、64K；CSV未记录精确CLI整数，不擅自把标签当逐批实际执行量 |
| 负载 | 用户：AISBench B=1，输入66K/128K，prefix cache目标50% |
| 实际输入 | 66K组均值约67892；128K组约129241 token |
| 输出 | 每行out_mean=1024 |
| 样本 | 8个run、均r01，各30–43条，n合计285；status全为valid |
| 时间窗 | span=759.6–793.0；不能用历史pressure_time=900覆盖本文件实际分母 |
| 缓存/重启 | 目标50%已知；实际逐请求命中、各档重启/warmup/seed未给出，保持未确认 |
| 单位 | CSV表头无单位。延迟按ms、span按s与全部算术守恒高度一致，但用户本轮只明确回答P侧范围，单位暂记“推定” |

g5历史文档§8.5明确：AISBench压力模式为在途信号量，完成一条补一条，**没有整轮barrier**；不能沿用早期“等整轮完成”的口述。正式TTFT/TPOT沿用客户端口径，不改成P内部计算时间。

冻结文档中对 `computed` 更新时间、cache查询副作用等存在已知勘误，本稿不复用这些旧推断；以对齐审查/AGENTS的纠正为准。

### 5.2 内部一致性核对

全部8行均与以下关系在显示精度内一致：

- `qps ≈ n/span`。
- `in_tps ≈ qps × in_mean`；`out_tps ≈ qps × out_mean`。
- `tot_tps ≈ in_tps+out_tps`，允许各字段舍入误差。
- 若延迟单位ms，`qps × [ttft_mean + 1023×tpot_mean]/1000` 为0.99917–1.00097，符合B=1串行完成闭环；这强烈支持单位解释，但不替代导出schema。

所以这里的in_tps是**客户端输入token吞吐**，包含命中前缀；不是P新增计算token/s。tot_tps与QPS在固定长度组中高度绑定，不应当成多个独立的收益证明。`tpot_verify`与`tpot_mean`相同是文件事实，但缺少生成过程，不能称独立设备计时验证。

### 5.3 原始关键指标与相对8K变化

TTFT列保持CSV原数值（推定ms），比例变化不依赖单位。每个输入组分别对其8K行归一化。

| 输入 | P预算 | n | TTFT mean | TTFT P90 | QPS | total token/s | mean变化 | P90变化 | QPS变化 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 66K | 8K | 42 | 6383.2 | 6431.5 | 0.0541 | 3730.1 | — | — | — |
| 66K | 16K | 42 | 6294.7 | 6340.0 | 0.0540 | 3720.9 | -1.39% | -1.42% | -0.18% |
| 66K | 32K | 43 | 6320.8 | 6385.0 | 0.0542 | 3736.8 | -0.98% | -0.72% | +0.18% |
| 66K | 64K | 35 | 9716.6 | 9804.3 | 0.0454 | 3125.7 | +52.22% | +52.44% | -16.08% |
| 128K | 8K | 30 | 13151.5 | 13233.7 | 0.0395 | 5145.1 | — | — | — |
| 128K | 16K | 31 | 12959.2 | 13072.7 | 0.0401 | 5221.5 | -1.46% | -1.22% | +1.52% |
| 128K | 32K | 31 | 12491.9 | 12608.6 | 0.0403 | 5248.2 | -5.02% | -4.72% | +2.03% |
| 128K | 64K | 31 | 12456.3 | 12661.8 | 0.0405 | 5279.9 | -5.29% | -4.32% | +2.53% |

D配置保持不变不等于测量的TPOT必然不变：128K各预算的TPOT P90依次12.966/12.530/13.600/12.560；66K依次12.292/12.495/12.452/12.629（推定ms）。正式选配置应保留TPOT指标，不能只看TTFT。

### 5.4 可以明确得到的结论

1. **128K：32K/64K值得作为后续静态候选。** 32K相对8K的mean/P90都有约5%改善，QPS约+2%；64K相比32K的mean略好，但P90反而高0.42%左右。不能宣称64K在尾延迟上最佳。
2. **66K：8K/16K/32K接近，64K出现明显回退。** 16K是本轮mean/P90最小值，但QPS略低于8K；32K QPS略高。这些小差异没有重复run，不据此宣布精确赢家。64K的大幅退化是必须保留的真实观察，不删为离群点。
3. **同一g5部署，不同输入档的响应不同。** 此证据支持按规格保留静态配置候选，而不支持“统一上64K”或“越大越好”。
4. **B=1测的是低负载串行服务能力。** 集群内同时在途一条，无法据此评价3P容量、同P请求竞争或高并发P90尾部；QPS受整个P→D生命周期影响。P侧TTFT节约会被后续约12秒decode时间稀释，因而TTFT百分比改善大于QPS改善是合理的。
5. **不把可信现场观察扩大为因果/显著性证明。** 每档仅一个r01、无逐请求样本和重复波动估计；不计算虚假的置信区间，不用30余条样本的P99判长期尾部稳定性。status=valid也不能补出未提供的失败计数。

### 5.5 66K/64K反转：解释候选，而非结论

如果真实命中恰好50%、预算标签分别对应8192/16384/32768/65536，那么66K组剩余约33946 token，对应理想分块数约5/3/2/1；128K剩余约64620，对应8/4/2/1。**这只是条件演算，不是已观察的调度轨迹。** 实际命中和每批执行token未给出，不能据此声称64K时就是单块。

值得在后续已有日志或定向复核中区分：

- 实际前缀命中/冷热态或选中P不同；目标50%不保证每条实测50%。
- 配置预算改变启动profile/缓冲区/KV可用空间，即使实际工作量相同也可能改变执行条件。
- batch形状跨越算子/tiling等性能区间；目前没有kernel计时支持这个归因。
- 长块减少启动次数但增加单块耗时；其净效果取决于当前模型和执行后端。

以上不构成本轮新采集任务。优先利用用户已有实验材料；如后续复测，只围绕该反转与候选稳定性，不重新开展全链路环境调查。

## 6. 面向不同TOB场景的设置方法

下面是结合官方实践与本项目结果的建议，不声称厂商披露了完全相同的生产参数。

| 场景 | 首先设置什么 | 批预算/单请求块如何研究 | 不应做的推断 |
| --- | --- | --- | --- |
| 低并发长文档、P/D分离 | 保留业务输入规格与输出契约 | B=1扫描C，选稳定平台区；当前128K保留32K候选，66K保留8–32K | B=1最优就是高并发最优 |
| 高并发同规格长文档 | 以目标SLO下可承载并发选点 | 候选C×并发对照；资源/seq固定后再研究U | 更多batch token自动代表更多请求完成 |
| 同规格内长短prompt混合 | 保留FCFS基线和真实长度差异 | 比较C固定、U=关闭/较小上限，观察短请求和全体P90 | U能保证公平或消除已提交批阻塞 |
| 混部交互聊天/RAG | 同时满足TTFT和ITL/TPOT | 小C/U保护decode；借鉴vLLM/TGI/NVIDIA权衡 | 将该时间限制直接移植为P-only批时限 |
| 高前缀复用的企业知识库/多轮 | 先区分输入长度、命中量、驻留/加载 | 使用实际运行缓存条件扫描，避免仅按原始prompt长度选预算 | 输入token/s就是实际P算力吞吐 |
| 离线文档批处理 | 完整任务吞吐、成本、成功率 | 放宽时延后扫描较大C与seq，但保留内存界限 | 离线最大吞吐配置适合在线SLO |

目前公开资料更充分披露的是框架参数、扫描过程与端点案例；对大型MaaS生产中逐规格的完整内部配置表披露有限。本稿不以匿名帖子或博客默认值填补这一空白。

## 7. 如何控制优化本身的开销

用户指出的担忧成立为工程风险：每批多次模拟和预测增加CPU工作。但**尚未测量，不能直接认定额外时间一定很大或一定成为瓶颈**；长P批与异步重叠可能掩盖部分开销，关键是它是否落在提交关键路径上。

建议按复杂度逐级推进：

1. **静态分规格配置**：离线选C，运行时无搜索。这是新的第一基线。
2. **静态双上限(C,U)**：共享批预算＋单请求每轮上限；沿用原生消费顺序，只有已有截断操作，不进行模型推断。先验证该组合是否已有收益。
3. **少量离线标定档位**：只有当静态配置在不同已知场景下明显冲突，才研究按可得状态查表选档。分档边界须由实验依据决定；不凭空堆积阈值。
4. **受限在线调整**：只比较少量候选，特征提取一次、共享候选计算；模型稳定/状态未显著变时不重复全搜索。缓存键必须覆盖有效状态，不能误复用不再可行的计划。
5. **完整逐batch寻优**：仅当它相对强静态基线的额外收益覆盖决策成本和维护复杂度，才进入工程实现。

后续若研究在线版本，比较的应是“净收益”：新增决策耗时与提交间隙、预测次数和候选数分别记录；不能从O(n)就宣称开销很小，也不能把主机运行时间全部加到设备批耗时而忽略重叠。首版分析复杂度应写成候选数×模拟组批成本，而不是把每次模拟默认当O(1)。

## 8. 后续研究优先级：覆盖上一版数学优先顺序

| 优先级 | 本阶段工作 | 具体产物/依据 |
| --- | --- | --- |
| **P0** | 建立成熟静态预算基线 | 本轮8点现场结果、官方扫描方法；明确C/U/输入上限；保留66K64K反转 |
| **P0** | 选出少量有依据的候选 | 66K保留8K/16K/32K，128K重点8K对32K，64K作为增量收益/风险对照；尚不批准上线替换 |
| **P1** | 在目标并发下比较静态C，再研究U | 分开预算效果和入场顺序；不把B=1结论当高压收益；既有GF/D版本固定 |
| **P1** | 以实测形状解释模型 | 判断非单调、固定开销、KV与标签差异；模型帮助缩小范围，不要求先解完整微分方程 |
| **P2** | 比较低成本查表/少档控制与静态配置 | 只有已证实场景冲突时增加自适应，测净收益 |
| **P3** | 完整在线cost函数寻优、宏观KV联合模型 | 作为可选增量，不再阻塞工程基线与现场比较 |

建议下一轮首先讨论：**是否以“分规格静态C＋原生单请求U”作为新的最小工程候选**。这是待讨论方案，不是本轮修改调度策略的授权。

## 9. 最小实验设计建议（未执行）

- 保留现有g5固定8K基线；P预算变化是唯一首轮自变量，D和GF保持同版本。C候选来自本轮现场扫描，不盲目扩大全网格。
- 优先核对/重复66K64K反转，以及128K8K与32K差异；记录是否重启、warmup和seed策略。按一致流程做配对重复、交替顺序，避免把缓存和时间漂移当预算收益。
- 从已有B=1进入实际目标B时，保持同长度/输出/缓存流程。正式目标是全体P90 TTFT、吞吐不下降、P90 TPOT；完成率和错误单列。
- 如果研究U，在固定C下做对照，再与U关闭比较；用同规格内长短混合及长请求执行中插入短请求的定向场景检验阻塞边界。该场景是机制实验，不冒充生产分布。
- 在线动态算法若以后加入，必须对比最佳稳定静态点，而不仅是8K历史默认；调参和评估用不同重复轮，保留挑选偏差。
- 无需复刻其他厂商完整服务栈；现有华为机g5优先级最高。本地继续研究设计、核对结果，不把模型预测或CPU模拟称为NPU性能。

## 10. 直接来源

所有网页核查日期2026-10-28。滚动文档不当成现场版本，博客数字仅在原场景成立。

- **N1** [NVIDIA：Tuning Max Batch Size and Max Num Tokens](https://nvidia.github.io/TensorRT-LLM/1.3.0rc23.post1/legacy/performance/performance-tuning-guide/tuning-max-batch-size-and-max-num-tokens.html)，legacy性能指南，Tuning Case Study、Tuning Max Num Tokens。
- **A1** [AWS/BentoML：Optimizing LLM inference on Amazon SageMaker AI with BentoML’s LLM-Optimizer](https://aws.amazon.com/blogs/machine-learning/optimizing-llm-inference-on-amazon-sagemaker-ai-with-bentomls-llm-optimizer/)，Run the benchmark。重点是离线扫描与Pareto选型，不照抄理论输出。
- **A2** [AWS：Benchmark and optimize endpoint deployment in Amazon SageMaker JumpStart](https://aws.amazon.com/blogs/machine-learning/benchmark-and-optimize-endpoint-deployment-in-amazon-sagemaker-jumpstart/)，Select an endpoint deployment configuration。历史TGI端点模式。
- **H1** [Hugging Face TGI launcher reference](https://huggingface.co/docs/text-generation-inference/en/reference/launcher)，MAX_INPUT_TOKENS、MAX_TOTAL_TOKENS、MAX_BATCH_PREFILL_TOKENS、MAX_BATCH_TOTAL_TOKENS。
- **D1** [DJL：TensorRT-LLM finding max_num_tokens tutorial](https://docs.djl.ai/master/docs/serving/serving/docs/lmi/tutorials/trtllm_finding_max_num_tokens_tutorial.html)，历史LMI/TRTLLM版本示例。AWS实例名g5不是本项目g5软件基线。
- **V1** [vLLM v0.23.0优化文档](https://docs.vllm.ai/en/v0.23.0/configuration/optimization/)，同时核对本地 `upstream/vllm-v0.23.0/docs/configuration/optimization.md`，避免只信网页路由版本。
- **S1** [SGLang Hyperparameter Tuning](https://docs.sglang.ai/advanced_features/hyperparameter_tuning.html)，prefill/decode OOM与内存分配。
- **Y1** [Anyscale：Tune parameters for LLMs on Anyscale services](https://docs.anyscale.com/llm/serving/parameter-tuning)，Optimization scenarios。本文不采用该页所有通用建议作为本部署规则。
- **N2** [NVIDIA NIM：Parameters and Best Practices](https://docs.nvidia.com/nim/benchmarking/llm/parameters)，Use Cases、Load Control。
- **C1** [Ascend固定recompute_scheduler.py](https://github.com/vllm-project/vllm-ascend/blob/5cb98caaadeff42b5b62b996e34bb2aaa29d20fd/vllm_ascend/core/recompute_scheduler.py)；[vLLM固定scheduler config](https://github.com/vllm-project/vllm/blob/0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665/vllm/config/scheduler.py)。语义判断以本地固定源码为准。
- 项目背景：[g5冻结交接](../engineering/G5_FROZEN_BASELINE_HANDOVER.md) §4、§8.5；[本机对齐审查及勘误](../engineering/G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md)。背景不能替代这8个run缺失的配置指纹/缓存实测。

研究取向已经调整为：**成熟静态实践＋现场数据先行，低成本增量其次，数学与预测模型服务于工程选择。**
