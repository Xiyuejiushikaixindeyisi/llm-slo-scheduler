# Chunk size 与动态批 token 预算：业界调研和研究优先级

> 2026-10-29纠正：上一轮将“成熟实践”误收窄为静态离线扫描。当前以有工程依据的运行时chunk决策、多项式低成本求解和时间约束为主线；见 [方向纠正与时间约束](RUNTIME_CHUNK_TIME_CONSTRAINT_CORRECTION.md)。旧文实验与来源保留，静态优先的研究排序已被覆盖。

> 2026-10-28 历史更新（研究排序已撤回）：当时将“成熟工程实践”理解为先做分规格静态 C/U，再决定是否动态。这一收窄并非用户当前方向；[g5 现场实验](MAAS_TOKEN_LIMIT_PRACTICES_AND_G5_EXPERIMENT.md)的事实保留。本稿继续作为来源底稿，当前优先级与 fork 交接见[研究入口](README.md)。

版本：v1.0；核查日期：2026-10-28；会话：Session 3（数学建模）。

本稿承接[初版算法设计](DYNAMIC_BATCH_TOKEN_BUDGET_DESIGN_V0_1.md)及[动态预算数学审查](DYNAMIC_BATCH_TOKEN_BUDGET_MODEL.md)。本轮完成公开资料与固定源码调研，没有运行算法实验、拟合现场参数或修改调度代码。下文“建议”是本项目的研究判断，不是来源作者的结论或新增实施授权。

## 1. 结论与适用范围

**保留初版“原生顺序模拟组批＋预测批时延＋实际执行量/时间评分”，但应优先比较三种决策目标：固定 token 预算、固定时间预算、局部吞吐最大化。** 业界证据支持使用 batch/context-aware 成本模型；没有证据证明逐批吞吐贪心能保证本项目的 P90 TTFT 或整体吞吐。

三个最重要的发现：

1. **Ascend 的 Dynamic Batch 和 Dynamic CPP 是不同机制。** 前者根据 decode 状态查表选 token 预算，无 decode 时不调整；后者依据历史上下文反求 chunk，使 PP 各块执行时间接近。两者都不是当前 g5 P 调度器的直接替换件。
2. **混部中的 decode deadline 不能照搬为 P-only 的 batch 上限。** QoServe 明确在 P/D 分离实验中使用较大 8K chunk，且未取得混部情况下相同的动态 chunk 收益。当前 D 的 TPOT SLO 仍须满足，但不能直接设为 P 的每批 30/40ms 上限。[S6]
3. **计算量、访存量和服务完成时间必须分开。** chunk 划分可能保持因果 attention 算术总量，却增加 KV 重读、调度与启动次数。只预测一批或只计算 FLOPs，会遗漏完整 prompt 的累计成本。

研究对象是一个实例 UUID 对应的 3P3D 集群，当前关注单 P 引擎的预算决策，D 和 GF 策略固定以分开归因。硬件为 910B2、P TP4，不能把 TP4 当作 PP4；当前资料未给出需要启用 PP 的依据。不假设当前平均吞吐接近容量。

正式收益口径沿用 AISBench：全体请求 P90 TTFT、业务吞吐及分档 P90 TPOT，P95 补充；局部 token/s 是解释量。64K TTFT/TPOT 为 27s/30ms，128K 为 30s/40ms。闭环 B 是集群总并发，不能将 request_rate=1 直接当作稳定到达率。

## 2. 先统一“chunk size”究竟指什么

| 控制量 | 定义 | 本项目关系 |
| --- | --- | --- |
| 单请求 chunk 上限 | 每个 prefill 本轮最多计算多少 token | 与批总预算不同，不作为首版控制量 |
| 批总 token 预算 c | 全批实际新增计算量 Q(c)=Σu_i ≤ c | 用户已选定的控制量 |
| 批时间预算 τ | 预测执行时间不得超过 τ，再反求 token | 值得作为独立算法对照 |
| batch size B | 批中请求数 | 由原生顺序、token/KV/seq 限制共同决定，不等于 c |
| PP microbatch/chunk | 流水线阶段处理的工作块 | 目标包含阶段均衡，不能直接等价于单 P 的吞吐寻优 |
| 请求排序/抢占 | 哪个请求先执行、是否中断 | 属于另一条研究线，本轮不引入 |

原生 FCFS＋running-first＋共享 token 预算仍是首版基础。不能把文档中的“decode-first”泛化为所有版本调度器的逐行语义。固定 vLLM 源码先遍历 running，再处理 waiting；`long_prefill_token_threshold` 为正时另加请求上限，其为 0 不等于关闭由总预算触发的 chunked prefill。[S1]

## 3. 证据分级与机制对照

固定源码用于判定“实现怎样做”；论文用于判定“在什么假设下为什么有效”；行业博客用于识别已披露工程方向。PR 的提案和作者测试不等于合入，更不等于当前现场运行。

| 来源 | 真正优化的量/约束 | 成本信息 | 对本项目的用途 |
| --- | --- | --- | --- |
| vLLM v0.23.0 | 固定共享预算、资源可行性 | token、seq、KV 状态 | 必须保留的基线语义 |
| Ascend Dynamic Batch | 时延门限内最大查表 chunk | decode 数与平均上下文 | 借鉴预算接口与查表对照；P-only 不能原样使用 |
| Ascend Dynamic CPP | PP chunk 时间均衡 | 新 token、历史长度、批请求数、profile 时延 | 高优先级成本映射参考；低优先级直接部署 |
| SGLang CPP | 缩小 PP 流水线气泡 | 累积二次时间曲线 | 检查反求、对齐和异步边界 |
| Sarathi-Serve | 吞吐与 TBT 的静态预算折中 | profile 与 chunk 开销 | 固定预算基线及分块累计成本依据 |
| QoServe | deadline slack 内扩大 prefill | batch 随机森林时延预测 | 高价值方法参考；混部目标需重新定义 |
| NVIDIA TensorRT-LLM | IFB 的利用率、时延及激活内存 | 公开文档未披露完整寻优器 | 工程约束依据，不虚构公式 |
| SLOWeave（预印本） | decode deadline 内最大 prefill 进展 | 单调时延函数＋误差裕量 | 数学对照，非 P-only 直接方案 |
| Huawei/Tsinghua Dynamic Batching | 内存/SLA 下 decode batch 请求数 | decode 时延与请求数关系 | 参考约束结构，不是本项目 c 的公式来源 |
| FlowPrefill（预印本） | 用算子边界抢占减小阻塞 | 执行/抢占开销 | 边界参考，当前不实现 |

## 4. 最直接的工程依据：Ascend 两条路径

### 4.1 Dynamic Batch：实际是 decode 状态驱动的查表预算

核对固定 commit `5cb98caaadeff42b5b62b996e34bb2aaa29d20fd` 的 `scheduler_dynamic_batch.py`，而非只看特性名。[S2]

`BudgetRefiner` 的逻辑可写成：

\[
 c_{table}(h_d,B_d;\tau)=\max\{x:(h_d,B_d,x,t)\in\mathcal D,\ t\le\tau\}.
\]

这里数据表列为 `ctx_len,d_num,chunk_size,cost`。在线取 running 中已完成 prompt 计算的请求，以其 `num_tokens_with_spec` 均值和数量查表。**如果 decode 数为 0，直接返回原预算**。表缺失时关闭 refiner；越界或缺项回默认预算。这是“满足时延的最大工作量”，并没有枚举 Q/T。

必须保留的实现限制：

- `SchedulerDynamicBatch` 还将 running 分成 decode/prefill 两段再拼接。因此完整替换会改变调度顺序，不是只改预算；其类直接继承核心 Scheduler，也不是 g5 的 AsyncRecomputeScheduler/predictor 链。
- 文档为 Atlas A2、TP8 的若干 dense 模型经验；代码注释具体写 910B3，表名为 A2-B3-BLK128。不能将其成本数值迁移到 910B2 TP4、64K/128K。
- `_align_key` 遍历的是 `set`；尽管初始化曾调用 sorted，转换回 set 后不能从代码保证取到最小向上邻点。因此不要照搬为严格保守插值。
- 返回的表 budget 没有在 refiner 这里显式 `min(default_budget, table_budget)`。本项目初版仍须独立遵守批准的硬预算上限，不能把表值理解为天然受原上限保护。

**判断：优先借鉴“成本表→可行预算”的结构；不建议直接打开开关作为 P-only 对照。** P 可能存在首 token 等特殊状态，但不能因此把它当成有稳定 decode 混批的实例。

### 4.2 Dynamic CPP：二次曲线、历史项与时间预算

固定实现启动 profile 拟合 `g(l)=al²+bl+d`，再用

\[
 \widehat T(u,h)=g(h+u)-g(h)=au^2+(2ah+b)u
\]

反求给定时间内的下一块；固定项 d 在差分中消失。历史反馈阶段则按代码形成

\[
 X_1=\sum_i u_i(u_i+h_i),\quad X_2=\sum_i(u_i+h_i),\quad X_3=B,
\]

并拟合 `T=aX1+bX2+dB`。这是两个不同的模型，不能把启动曲线的系数或理论解释直接套给历史阶段。[S3]

其调度器维护时间预算并保留 token 资源约束；配置要求 PP>1。worker 的同步计时与 g5 主机提交/取结果标签口径不同。代码还做 smoothing、最小 chunk 和向上取整：**反求前满足目标时间，不保证取整后仍满足严格时间上限**。本项目若采用硬时间约束，应对合法化后的完整计划重新预测，不能仅信解析根。

借鉴顺序：实际执行形状→对齐标签→拟合→候选合法化→再次判定。成本公式可以迁移研究；PP 消气泡目标不能未经论证转成 P90 TTFT 最优。详细函数与行号见初版设计第13节。

## 5. 其他框架与工业论文

### 5.1 SGLang：等时间 chunk 的工程实现

官方 CPP 文档以历史长度增长导致同大小 chunk 变慢为出发点，用累积二次曲线的差分反求下一块，并向下对齐到 `max(page_size,64)`。官方博客同时包含 PP、异步 P2P 和动态 chunk；整套系统的加速比不能归给 chunk 单项。[S4]

对本项目的判断：历史长度必须进入成本模型；对齐方向和 smoothing 会改变实际约束。没有 PP 时仍可以研究“固定时间预算”，但不再以流水线气泡作为收益依据。不能把“上下文越长，chunk 越小”当作所有优化目标共有的规律。

### 5.2 Sarathi-Serve：静态预算是必须击败的基线

Sarathi-Serve 按 decode、未完成 prefill、新请求的顺序填充 token 预算。预算选择兼顾 TBT 和分块开销；论文明确指出更小 chunk 会损害利用率，并导致已有 KV 被重复读取，即使 attention 算术计算量不变。[S5]

对本项目的判断：动态算法应与合理的静态预算比较，不能仅与一个未调好的静态点比较。8192 冻结基线必须保留；其他静态点属于后续批准的对照研究。当前不因调研扩大可用硬预算。

### 5.3 QoServe：最贴近 predictor＋chunk 的工业研究

Microsoft Research 的 ASPLOS’26 论文使用轻量随机森林，根据 batch、chunk、context profile 预测执行时间，再利用在执行请求的 deadline slack 扩大 prefill。它也包含优先级与 relegation，必须分项归因。P/D 分离实验使用 8K 基线，作者明确称该场景未利用到同样的动态 chunk 优势。[S6]

对本项目的判断：优先学习“成本预测与目标函数分离”，不照搬 decode slack。我们的 P-only 约束需要来自完整 TTFT 的剩余工作和等待外部性。论文的整体 goodput 增益不是纯预算控制的保证。

### 5.4 NVIDIA TensorRT-LLM：硬约束和性能曲线更值得借鉴

官方文档区分 `max_num_tokens` 和请求数，说明预算增大会改善利用率、但超过合适范围可能损害延迟；非末块要求 KV block 对齐。官方博客提到动态 sizing 与利用率、激活缓冲区配置，但未给出可完整复现的在线成本函数或搜索算法。[S7]

对本项目的判断：用其说明“预算需要 profile、合法对齐、兼顾激活内存”是有依据的；不能据博客声称 NVIDIA 使用了本项目的 Q/T 或同一个二次公式。chunk 限制中间激活峰值，也不意味着完整 prompt 的持久 KV 不再增长。

### 5.5 新论文 SLOWeave：可用于明确证明边界

2026-09 预印本用单调成本函数，二分寻找不超过最早 decode deadline 的最大 prefill chunk；证明依赖准确预测、decode-only 可行等条件。论文包含事件模拟和 GPU runtime 实验描述，未在本地核验其 artifact。实现描述以每轮一个 pending prefill 为主，无 decode 时可用最大块。[S8]

对本项目的判断：适合作为数学参照，不属于已核实的工业部署。其“当轮最大安全进展”不证明 Q/T 最大、更不证明整请求 P90 最优。多个 prefill 的原生组批会改变 batch 组成，不能不检查单调性就将我们的网格搜索换成二分。

### 5.6 原始 Dynamic Batching 论文与抢占研究

Huawei Noah’s Ark Lab/Tsinghua 的 `Optimizing LLM Inference Throughput via Memory-aware and SLA-constrained Dynamic Batching` 主要优化 decode batch 的请求数，给出内存和 decode SLA 约束。其满批条件下的 `b/step_time(b)` 不是本项目多 prefill 的总预算问题，也不是用户最初含 λ、等待项分式的出处。[S9]

FlowPrefill 将抢占粒度细化至算子边界，说明“计算块大小”和“响应新请求的中断粒度”可以分离。它需要改变执行/调度交互，当前不在批准范围内；仅用于防止把极小 chunk 当成改善阻塞的唯一可能机制。[S10]

### 5.7 DeepSeek 与火山/AIBrix：明确本轮披露边界

DeepSeek 官方资料披露 P/D 分离、EP、双 microbatch 通信计算重叠以及 prefill 负载均衡；这些说明执行时间取决于并行和重叠，但该材料没有给出本项目所需的在线 chunk 寻优公式。dual-batch overlap 也不是 GF 双等待队列。[S11]

本轮对火山官方资料的检索未获得可复核的 chunk 成本公式；检索到的 AIBrix PD 材料主要讨论路由与 token 负载。这里记录“本轮未找到直接依据”，不推断厂商没有该技术，不用路由方案冒充 batch 寻优方案。

## 6. vLLM PR / RFC：提案状态必须单独核实

以下状态于2026-10-28经 GitHub API 核对；三项 PR 的 `state=closed, merged_at=null`。

| 链接 | 内容定位 | 此次核验状态 | 能支持什么 |
| --- | --- | --- | --- |
| [PR #20359](https://github.com/vllm-project/vllm/pull/20359) | PP/V1 Token Throttling | 关闭、未合入 | 存在 PP 调度/节流探索；不是当前固定基线能力 |
| [PR #23545](https://github.com/vllm-project/vllm/pull/23545) | DCCP supported | 关闭、未合入 | 动态 CPP 的提案轨迹；不采用作者数字作为本项目收益 |
| [PR #31561](https://github.com/vllm-project/vllm/pull/31561) | PP async send | 关闭、未合入 | 异步通信是独立改动，不能算作 chunk 单项 |
| [RFC #33914](https://github.com/vllm-project/vllm/issues/33914) | CPP dynamic chunk size | 页面显示 Closed as not planned | token budget / compute-load budget 抽象可参考 |

这里只判定这些具体 PR 未合入，**不推断等价功能从未通过其他 PR 合入**。本项目实际能力仍以 sources.lock 固定 commit 的代码为准。RFC 中计算预算抽象可启发接口设计，但本轮不引入其代码。

## 7. 对我们的数学模型应怎样修正或验证

以下均为本项目推导，来源仅提供问题动机；不冒充论文原式。

### 7.1 保留实际计划作为共同输入

对同一冻结状态 s、同一原生请求顺序，令

\[
 \mathcal P(s,c)=\{(i,u_i,h_i)\},\quad Q(s,c)=\sum_i u_i,\quad Q\le c.
\]

两种候选模型仍按初版比较：

\[
 T_S=\alpha_0+\alpha_B B+\alpha_U Q+
 \alpha_A\left[\sum_i u_i h_i+\frac{\sum_i u_i^2+Q}{2}\right],
\]

\[
 T_F=\beta_0+\beta_1B+\beta_2Q+\beta_3\sum_i u_i^2+\beta_4\sum_i u_i h_i.
\]

`Q/T` 是新增计算 token 吞吐，不是客户端 output token/s，也不直接等于 prompt 请求完成速率。已有 KV 命中不能算进 Q，但它会改变 remaining、历史长度及可能的加载代价。

### 7.2 三个应公平比较的决策器

| 决策器 | 数学形式 | 解释 |
| --- | --- | --- |
| 固定预算 | c=C_base | 现有8192基线 |
| 时间预算内最大进展 | argmax Q(s,c)，约束 T⁺(s,c)≤τ | 在可接受阻塞窗口中尽量多做事 |
| 局部吞吐最大 | argmax Q(s,c)/T̂(s,c) | 单位预测时间完成最多新计算 |

其中 `T⁺=T̂+δ(s,c)` 是可选的单侧保守估计；δ须基于匹配条件的残差校准，不能任意加一个百分比就声称保障 SLO。τ在 P-only 场景是尚待定义的控制参数，不是照抄 D TPOT。

对局部固定 batch 构成、Q=c、`T=a+bc+dc²`：

\[
 \frac{d(c/T)}{dc}=\frac{a-dc^2}{(a+bc+dc^2)^2}.
\]

因此 a,d>0 时效率峰值为 `sqrt(a/d)`；而时间预算算法往往选择满足 `a+bc+dc²≤τ` 的最大 c。只有效率在可行区间内不下降等条件成立，两者才可能选同一点。

这也解释了：历史项若只进入 b，会改变同时间预算下的 c，却不改变这个局部模型的无约束效率峰值。因此“历史越长就缩 chunk”是时间预算方法的结论，不能直接当成 Q/T 方法的必然结论。真实组批跨越 B/完成边界、tile/kernel 区间后，此局部解析式不再适用，应回到候选模拟。

### 7.3 第一优先修正：检查 KV 重读与固定开销

对长度 L、初始前缀 h0、分块 u_j，h_j=h0+Σ_{k<j}u_k，有恒等式

\[
 \sum_j\left(u_jh_j+\frac{u_j(u_j+1)}2\right)
 =h_0L+\frac{L(L+1)}2.
\]

这仅说明稠密因果 attention 的算术配对计数不随划分改变，**不说明 wall time 不变**。若等块 c 且 L=nc，一个粗粒度历史读取代理为

\[
 \sum_{j=0}^{n-1}(h_0+jc)=nh_0+\frac{c n(n-1)}2.
\]

它随分块方案变化，但不是实际 HBM bytes 的精确公式：kernel tiling、缓存和重复访问都会影响真实流量。研究上可先检查残差是否随 `Σh_i`、chunk 数和区间系统变化，再决定是否加入 `α_H Σh_i` 或分段模型。不能直接把所有读写成本与计算成本线性相加后称为硬件定律，因为二者可能重叠。

当前结构模型是近似基线。若现场模型含 hybrid linear/full attention，则完整二次项只描述其中一部分；需要按实际架构解释系数，不能将所有层视为标准稠密 attention。该问题优先于拟合更复杂的全局 KV 微分方程。

### 7.4 第二优先修正：从单批评分走向 prompt 完成

对请求 i 的候选剩余时间，可先写记账分解：

\[
 \widehat{TTFT}_i(c)=a_i+T_{next}(s,c)
 +\widehat R_i(s'_c)+\widehat E_i(s'_c).
\]

`a_i` 为已消耗时间；R 为未来仍需的 P 服务与调度等待；E 为后续交接、D首结果及客户端可见阶段。未在下一批执行的请求也要更新等待。这里只定义组成，不声称当前 predictor 能提供 R/E。

P 异步时 `T_next` 必须区分设备服务时间、等待已提交批次及结果可见时间；不能把所有阶段当成串行相加，也不能忽略 inflight 已承诺的 token。g5 主机观察标签不是天然的单批纯设备时间。

后续可在相同吞吐约束下比较有限前瞻的完成时间/超期风险代理。P90 是总体分位，不应被替换成“每请求均不违约”的未经说明强约束；平均剩余时间最小也不自动等于 P90 最优。旧分式中的 d_k 与 d_2 仍保留为不同量，本轮不合并或宣称已经求解。

## 8. 研究优先级与预期产物

优先级按当前 P-only TP4 适用性、可解释性、归因清晰度排序，不按论文总加速比排序。此表是下一阶段计划，不是已启动实验。

| 优先级 | 研究问题/参考 | 应产出的结果 | 进入下一步的判据 |
| --- | --- | --- | --- |
| **P0-1** | 成本模型与计时契约；Ascend两路径 | 明确u/h/B、inflight、真实KV与标签；S/F及可选历史读取项的数学对比 | 能区分服务时间与主机观察间隔，解释分块累计开销；不能则先保留代理模型边界 |
| **P0-2** | 固定预算、时间约束最大进展、Q/T最大；Sarathi/Ascend/QoServe | 同候选集下的目标等价条件、反例及可复现比较规格 | 区分局部效率、全prompt完成、全局SLO；不要求先复刻整套框架 |
| **P1-1** | predictor误差和搜索；SGLang/SLOWeave | 合法对齐后重判、误差裕量、非单调回退、搜索开销上界 | 不依赖未经证实的单调性，不重复调用有副作用schedule/predict |
| **P1-2** | 完整prompt尾延迟；QoServe方法启发 | 有限前瞻或剩余成本项，阐明P90代理的边界 | 在确定性反例中能识别“单批更好、请求更晚” |
| **P2** | 宏观KV状态与微观成本耦合 | 命中、驻留、加载、占用的状态定义及闭合假设 | 先避免将后验命中当在线已知；不强行由宏观命中率推出逐批成本 |
| **P3/暂缓** | PP重构、算子抢占、向D转移prefill | 仅保留备选与文献索引 | 当前拓扑/运行边界未变，不进入首版实现 |

**推荐实际阅读顺序：** 本地 Ascend `BudgetRefiner` → `profiling_chunk_predictor` → Sarathi §4.3 → QoServe §3.6.1与§4.1.3 → SGLang CPP → SLOWeave §3。NVIDIA 文档用于补齐硬约束；vLLM PR用于追溯设计，不作为成熟功能安装清单。

## 9. 后续比较如何避免得出伪结论

后续获批时，先进行数学/确定性模型比较，再在华为机做匹配条件实验；本轮不要求新增采集或重开环境调研。

1. 目标函数比较使用同一成本模型、候选集、原生请求顺序、硬上限及KV规则；模型比较则固定决策器。不能同时换排序、预测器、上限和目标函数。
2. 保留8192基线，并在批准范围内选择静态对照；如果扩大硬预算，所有可比策略都获得同样上限，单独归因扩容效果。
3. 先固定GF版本与D配置；之后才研究与双队列的组合。所有失败/取消和等待中的请求按统一统计契约处理，不能只统计完成的快请求。
4. 同时报实际Q、批时间、整prompt完成/客户端TTFT、吞吐、P90TPOT和预测误差。选择候选的排序错误比平均拟合误差更直接影响算法；低平均误差不代表尾部或候选排序可靠。
5. 不能平均各批Q/T当系统吞吐；即使没有重叠，聚合也应为ΣQ/ΣT。异步重叠下要用明确的墙钟观测窗口，不能将重叠批耗时简单相加。
6. 同时保留单请求、同长度高并发、长度/命中异质三类机制场景；它们是后续对照维度，不暗示当前生产分布或容量已知。闭环结果不直接保证MaaS开环收益。
7. 来源中的A100/H100/H20、910B3/A3、TP8/PP配置与当前910B2 TP4不同，不迁移其默认chunk、系数或百分比收益。

## 10. 来源索引与复核入口

下列是直接来源。论文注明版本；网页按本轮访问日期解释，滚动网页不视为v0.23.0的冻结文档。固定源码版本依据[env/sources.lock.json](../../env/sources.lock.json)，现场身份与公开版本分开。

- **S1 vLLM固定代码：** [scheduler.py @0fc695fc](https://github.com/vllm-project/vllm/blob/0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665/vllm/v1/core/sched/scheduler.py)，本地同路径 `upstream/vllm-v0.23.0/vllm/v1/core/sched/scheduler.py`，重点360、378、408、685附近。
- **S2 Ascend Dynamic Batch：** [实现 @5cb98caa](https://github.com/vllm-project/vllm-ascend/blob/5cb98caaadeff42b5b62b996e34bb2aaa29d20fd/vllm_ascend/core/scheduler_dynamic_batch.py)，`BudgetRefiner`与`SchedulerDynamicBatch.schedule`；[特性文档](https://github.com/vllm-project/vllm-ascend/blob/5cb98caaadeff42b5b62b996e34bb2aaa29d20fd/docs/source/user_guide/feature_guide/dynamic_batch.md)。本轮未下载或复用外部profile表。
- **S3 Ascend Dynamic CPP：** [predictor](https://github.com/vllm-project/vllm-ascend/blob/5cb98caaadeff42b5b62b996e34bb2aaa29d20fd/vllm_ascend/core/profiling_chunk_predictor.py)、[设计文档](https://github.com/vllm-project/vllm-ascend/blob/5cb98caaadeff42b5b62b996e34bb2aaa29d20fd/docs/source/developer_guide/Design_Documents/dynamic_chunked_pipeline_parallel.md)；本地 `ascend_config.py:69` PP校验、`platform.py:712–725`调度器选择、predictor的fit/get_time/record_batch_execution_time。
- **S4 SGLang官方：** [Pipeline Parallelism for Long Context](https://docs.sglang.ai/advanced_features/pipeline_parallelism.html)，Guidance about Dynamic Chunking；[2026-01-15技术博客](https://lmsys.org/blog/2026-01-15-chunked-pipeline/)。Ascend设计文档明确引用该博客；不将二者当成完全独立的两份效果证明。
- **S5 Sarathi-Serve：** [OSDI’24论文入口](https://www.usenix.org/conference/osdi24/presentation/agrawal)；本轮细读[arXiv v1 §4.2–4.3](https://arxiv.org/html/2403.02310v1)，Taming Throughput-Latency Tradeoff in LLM Inference with Sarathi-Serve。
- **S6 QoServe：** [Microsoft Research提供的ASPLOS’26论文](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/10/QoServe_CC_final_v2.pdf)，§3.3、§3.6.1、§4.1.3、§4.1.4。标题 QoServe: Breaking the Silos of LLM Inference Serving。
- **S7 NVIDIA：** [TensorRT-LLM调度与chunk官方文档](https://nvidia.github.io/TensorRT-LLM/features/paged-attention-ifb-scheduler.html)；[2024-11-15技术博客](https://developer.nvidia.com/blog/streamlining-ai-inference-performance-and-deployment-with-nvidia-tensorrt-llm-chunked-prefill/)。区分规范性约束和高层性能描述。
- **S8 SLOWeave：** [Deadline-Aware Adaptive Prefill Chunking for Efficient Large Language Model Serving, arXiv:2609.07883v1](https://arxiv.org/html/2609.07883v1)，§3及§5；预印本，实验为作者报告，未独立复现。
- **S9 Dynamic Batching：** [arXiv:2503.05248v1](https://arxiv.org/html/2503.05248v1)，§II–III，Huawei/Tsinghua作者；满批假设和decode目标不移植为本项目事实。
- **S10 FlowPrefill：** [arXiv:2602.16603v1](https://arxiv.org/html/2602.16603v1)，§5.1–5.2，算子边界抢占；仅边界参考。
- **S11 DeepSeek：** [官方V3/R1推理系统披露](https://github.com/deepseek-ai/open-infra-index/blob/main/202502OpenSourceWeek/day_6_one_more_thing_deepseekV3R1_inference_system_overview.md)，Computation-Communication Overlapping、Prefill Load Balancer；不从该文推断未披露的chunk算法。

PR核验API：`https://api.github.com/repos/vllm-project/vllm/pulls/{20359,23545,31561}`；逐个读取title/state/merged_at/html_url。具体链接及状态见第6节。

本稿与初版设计并存：保留已批准的局部吞吐基线，新增行业对照、适用边界与研究优先级；未宣称动态预算已经取得现场收益。

本轮PR状态摘录见[核验记录](CHUNK_SIZE_INDUSTRY_RESEARCH_PR_STATUS.json)；它是工具结果摘录，不是完整API响应归档。
