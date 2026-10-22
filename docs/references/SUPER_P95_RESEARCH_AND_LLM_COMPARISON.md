# Super P95 调研与 LLM 连续批处理对比

日期：2026-10-16

研究目标：以 diffusion 双队列调度为起点，理解如何在高并发、密集请求的 aisbench 场景中，提升吞吐并优化 LLM 的 P90 TTFT；P95 TTFT 与 P90 TPOT 作为补充观察。本轮沉淀已有实现和比较基础，优先级规则、让行预算、动态 chunk 的 cost 函数与实验设计留待下一轮。

核心认识：super_p95 通过有限预算标记高成本请求，使普通请求在 diffusion step 边界取得执行机会。LLM 场景还需要决定每轮哪些请求入场、每个请求推进多少 token，以及让行时如何保留 KV。两者可借鉴调度语义，不能直接照搬抢占和恢复实现。

## 1 版本与证据范围

| 对象 | 版本或证据 | 使用边界 |
| --- | --- | --- |
| 本地 vllm-omni | 分支 v0.18.0-super-p95-rewrite-dev；提交 dd9c0895d98a73c760e9ca930d87e03198713ff7 | 本文 diffusion 实现的主依据 |
| vLLM | 本地 Git 对象中的 v0.23.0；rev-parse 返回 0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665 | 读取标签内容，不使用本地其他版本工作区代替 |
| vLLM-Ascend | 官方仓库 v0.23.0，重点核对 core/recompute_scheduler.py | 用于理解原生继承与调度机制，不冒充内网 fork 的完整实现 |
| 内网部署 | 用户提供的 3P3D FGJSQ 总结，生成日期 2026-10-15，覆盖 10.9—10.14 | 部署、负载与历史结果依据；内网原始日志和补丁未在本地复验 |
| 内网异步链路 | 用户随后提供的三节点运行日志结论、MRO 和 SLO=0 调用路径 | 对报告中“P 为同步实例”的旧注释作纠正 |

2026-10-19 起，本地参考源码位于 /home/zhangxiyue/llm-slo-scheduler/upstream/vllm-omni-super-p95，本文在本项目 docs/references 中继续维护。本文未执行 NPU 性能实验。历史结果与当前源码事实分开表述。

必须保留的研究前提：**当前吞吐是否接近容量尚未证实。** 高等待、持续积压或某一并发档 QPS 变化不大，都不能单独证明硬件利用充分、引擎吞吐已达上限，或调度没有改进空间。

## 2 Super P95 实际优化和测量什么

名称中的 P95 指向尾延迟目标，但现有 diffusion benchmark 统计的是请求完成延迟，并未独立测量首 token 或首帧时间：

| 路径 | 计时范围 |
| --- | --- |
| chat completions 与 image generations | 请求函数开始至完整响应读取和处理完成 |
| v1/videos | 创建任务、每 2 秒轮询状态、任务完成后下载视频内容 |
| latency_p95 | 对所有成功请求的 latency 使用 np.percentile(latencies, 95) |
| 客户端并发限制 | semaphore 等待发生在请求函数计时开始前，未计入单请求 latency |

因此，已有结果应称为“P95 端到端完成延迟”，不能直接称为严格定义的“P95 TTFT”，也不是仅对 normal 子集计算的 P95。视频轮询和内容下载同样进入结果。[D8][D9]

这与后续 LLM 的目标不同：LLM TTFT 终点是客户端收到首个有效生成输出，不是完整生成结束；批执行时间预测也不等于请求 TTFT 预测。

## 3 设计依据与服务时间估计

Diffusion 请求的分辨率、去噪步数和视频帧数差异较大。昂贵请求占据执行资源时，后续请求等待其剩余工作，产生队首阻塞。super_p95 将一小部分昂贵请求标记为 sacrificial，下文称“让行请求”：仍需完成，但可延后执行，以降低更多普通请求的延迟。[D1]

估计器采用固定硬件锚点，并非在线学习模型。[D5]

| 模型和规格 | 910B2 锚点秒 | 910B3 锚点秒 |
| --- | ---: | ---: |
| Qwen 512×512，20 steps | 8.60 | 8.64 |
| Qwen 768×768，20 steps | 8.94 | 8.64 |
| Qwen 1024×1024，25 steps | 14.22 | 14.22 |
| Qwen 1536×1536，35 steps | 43.22 | 49.34 |
| Wan 854×480，3 steps，80 frames | 38.07 | 38.07 |
| Wan 854×480，4 steps，120 frames | 71.34 | 71.34 |
| Wan 1280×720，6 steps，80 frames | 119.71 | 119.71 |

图片在已知分辨率上按 steps 缩放；未知分辨率用 1024×1024 锚点按像素数和 steps 外推。视频优先匹配完整规格，否则基于 1280×720、6 steps、80 frames 锚点按像素数、steps 和归一化帧数外推。帧数归一化遵循 VAE 时间压缩因子 4，调整到 4k+1。

估计器没有自动针对 USP4、USP8 分别校准。锚点是策略输入，不能当作任意拓扑下的实测服务时间。

默认每 20 个到达请求提供 1 个让行名额，与 P95 目标存在直观联系：把延迟代价集中到少数请求。但名额比例与最终最慢请求比例不等价，不能保证 P95 必然改善，更不能保证吞吐不下降。

## 4 算法结构

### 4.1 组件和调用关系

~~~mermaid
flowchart TD
    A["请求：尺寸、steps、frames"] --> B["Dispatcher：估计服务时间"]
    B --> C["累计预算与长请求判定"]
    C --> D["选择 backend 并记入负载"]
    D --> E["HTTP 请求头传递分类与估计值"]
    E --> F["Backend API 写入 sampling.extra_args"]
    subgraph BE["单个 backend：单卡或多卡组"]
        F --> G["SuperP95StepScheduler"]
        G --> N["normal pending：FIFO"]
        G --> S["sacrificial pending：LIFO"]
        N --> H["step 边界选择请求"]
        S --> H
        H --> I["Engine → Executor → ModelRunner"]
        I --> J["state_cache 与 pipeline step 执行"]
        J --> H
    end
    G -. "支持反馈的响应路径：剩余负载快照" .-> D
~~~

两个层次各自负责：

- Dispatcher：服务时间估计、让行分类、backend 选择、全局估计负载。
- Backend Scheduler：本地排队、step 边界让行、进度更新和剩余负载快照。

“跨卡调度”更准确地说是跨 backend 调度。Wan 的一个 backend 可以占用一个四卡或八卡组。[D3][D4]

### 4.2 到达分类与累计预算

设 A 为累计到达数，Q 为尚未使用的名额，K=20，M=1。每次到达：

~~~text
A += 1
若 A % K == 0：Q += M
对每个 backend 分别估计 E[r,b]
分类用 E[r] = min_b E[r,b]
更新历史最小值 Gmin、最大值 Gmax

sacrificial =
    Q > 0
    且 Gmax > 0、Gmin > 0
    且 E[r] >= 0.8 * Gmax
    且 E[r] >= 1.5 * Gmin

若判为 sacrificial：Q -= 1
~~~

最后一条对应 long_request_ratio，防止等长工作负载也消耗让行名额。该条件已存在于 dd9c0895，较早的技术方案只描述了相对最大值的阈值。[D3]

需要区分预算和队列长度：

- Q 初始为 0；没有明显长请求时预算可以积累。
- 默认累计让行次数不超过 floor(A/20)，但不是每个滑动窗口都限制为 5%。
- 一段时间积累的名额可在后续连续长请求上使用。
- 预算约束的是分类次数，不直接约束当前让行队列长度、已等待时间或占用内存。
- 完成、失败不会自动返还已花掉的分类名额；历史最值也不是滑动窗口统计。
- 当前没有显式 aging 或最大等待时间保证；持续普通负载下可能出现让行请求饥饿。

### 4.3 Backend 选择与记账

每个 backend 维护普通负载 N、让行负载 S、两类 inflight 数量和响应耗时 EMA。默认 alpha=0.1，按字典序取最小值：

~~~text
score = (
    N + alpha*S,
    inflight_normal + alpha*inflight_sacrificial,
    latency_ema,
    N,
    backend_name
)
~~~

分类采用所有 backend 估计值的最小值；实际记账和请求头采用选中 backend 的估计服务时间。路由主评分没有显式把“新请求在该 backend 上的执行时间”加到 score 中。[D3]

alpha 表示让行负载在路由中的折扣，并不意味着这类请求只消耗 10% 算力。

同步响应回来时，若存在合法的 Normal-Load-S / Sacrificial-Load-S 响应头，则用快照替换估计；否则减去完成请求的原始估计。快照是按步数估算的剩余工作，不是实测剩余秒数。

异步视频路径不同：创建成功后保存 video_id 对应的 backend 与 decision；轮询发现 completed/failed/cancelled 等终态，或删除成功时释放记账。因此不能笼统描述为“每个 HTTP 响应都意味着计算完成”，也不是所有路径都持续使用 scheduler 快照闭环。[D3]

### 4.4 本地双队列与让行规则

| 对象或条件 | 规则 |
| --- | --- |
| 普通等待请求 | arrival_seq 升序，FIFO |
| 让行等待请求 | -arrival_seq 升序，较新的先执行，LIFO |
| 两个队列同时非空 | 先普通队列 |
| 当前运行让行请求，普通请求到达 | 下一次调度时让行，标记 PREEMPTED 并重新入队 |
| 当前运行普通请求 | 其他普通或让行请求不将其抢占 |
| 当前运行让行请求，新让行请求到达 | 不抢占；LIFO 仅决定再次选取等待请求时的次序 |

判定函数 request_outranks(candidate, incumbent) 只检查“candidate 普通且 incumbent 让行”。这不是全体请求按服务时间最短优先，也不是按剩余时间排序。[D4]

已完成 C 步、总共 P 步、估计总耗时 E 的请求，剩余负载近似为：

~~~text
remaining_service = E * max(P-C, 0) / max(P, 1)
~~~

该估计把成本均摊到 step，没有单独建模 encode、decode 和不同 step 的差异。

### 4.5 状态保留与恢复

选择 super_p95_step 时，DiffusionEngine 强制 step_execution=True；step_baseline 同样使用 stepwise，但采用 RequestScheduler。[D6]

ModelRunner 的机制是：

1. 新请求创建并缓存 DiffusionRequestState。
2. 首次调用执行 prepare_encode，再执行一个 denoise_step 和 step_scheduler。
3. 非首次调用通过 cached request ID 取得原状态，继续下一个 step。
4. 最后一个 step 完成后执行 post_decode，并释放缓存状态。

调度器将 S 标记 PREEMPTED，不会因此从 runner 的 state_cache 删除 S。恢复时发送 cached ID，已完成的 step 不需要从零重复。[D7]

这是执行调用之间的协作式切换；不能在当前 denoise 算子中途切走。首轮 encode 和末轮 decode 也包含在执行调用中，实际可响应让行的延迟不一定只有纯 denoise step 的时间。

## 5 Diffusion 时序图

下图以单请求执行路径为例，省略传输和错误处理；batch2 是额外分支。

~~~mermaid
sequenceDiagram
    participant C as 客户端
    participant D as Dispatcher
    participant S as Backend Scheduler
    participant E as Engine 与 Executor
    participant R as ModelRunner 与 state_cache

    C->>D: 长请求 L
    D->>S: 让行标记与估计服务时间
    S->>E: new request L
    E->>R: execute_stepwise
    R->>R: 缓存状态，prepare_encode，执行 step
    R-->>E: step_index，未完成
    E->>S: 更新 L 进度

    C->>D: 普通请求 N
    D->>S: normal N 入队
    Note over S,R: 当前 L 的执行调用结束后到达调度边界
    S->>S: L 重新入让行队列，N 获得执行机会
    Note over R: L 的状态仍保留
    S->>E: new request N
    E->>R: 初始化 N 并执行首个 step
    loop N 的后续 step
        S->>E: cached request N
        E->>R: 继续 N
        R-->>E: 进度
        E->>S: 更新进度
    end
    R->>R: post_decode N
    R-->>C: 经引擎与 API 返回 N

    Note over S: 普通队列为空，再选择让行队列
    S->>E: cached request L
    E->>R: 从保留状态继续 L
    Note over R: 不重复 prepare_encode，不重跑已完成 step
    R-->>C: 最终完成 L
~~~

## 6 实验方法与证据强度

### 6.1 Qwen Image 混合请求实验

eval_qwen_image.sh 默认：500 个请求、0.8 req/s、固定 seed / random-request-seed / arrival-seed，指数分布到达间隔，先 warmup。请求混合为：

| 尺寸 | steps | 权重 |
| --- | ---: | ---: |
| 512×512 | 20 | 0.15 |
| 768×768 | 20 | 0.25 |
| 1024×1024 | 25 | 0.45 |
| 1536×1536 | 35 | 0.15 |

服务端示例采用 8 个 backend，对比 step_baseline 与 super_p95_step。脚本 positional 参数 baseline/super_p95 只是输出标签，不会替用户切换服务器调度器。当前脚本实际使用 backend=vllm-omni，即 chat completions；旧笔记推荐 backend=openai，不能混为同一压测路径。[D10]

### 6.2 历史结果

| 来源与条件 | Baseline | Super | 可以支持的结论 |
| --- | --- | --- | --- |
| 重写笔记，Qwen 8 卡、500 请求 | P95 407.83s；0.4525 qps | P95 321.00s；0.4139 qps | 笔记记录 P95 约降 21.3%，吞吐约降 8.5%；属于先前移植阶段证据 |
| 第三方文档，Wan 50 请求、0.05 req/s | 1×USP8；50/50；P95 2750.93s；0.0135 qps | 2×USP4；50/50；P95 2191.56s；0.0157 qps | 组合方案 P95 约降 20.3%；吞吐按表中舍入值约增 16.3%，混有拓扑变化 |

不能据此声称当前 dd9c0895 的“纯双队列算法”独立获得相同增益：

- Qwen 数字来自历史重写笔记，不是当前最新分类条件与 batch2 的独立复验。
- Wan 同时修改了每副本卡数和副本数。
- THIRD_PARTY_TEST_COMMANDS.md 中 Qwen baseline 请求率为 0.8，super 为 0.5，直接照两条命令对比会混入负载变化。
- 历史笔记记录残留 NPU 状态下吞吐从约 0.415 变为约 0.27 qps，环境状态会显著干扰比较。
- 历史笔记写“没有采用原生 stepwise 恢复”，是旧尝试的经验，不能覆盖当前代码已走 execute_stepwise 的事实。[D2][D11]

### 6.3 小图 batch2 是另一项优化

SUPER_P95_QWEN_SMALL_BATCH2 开启后，未开始执行的普通 Qwen 请求可以配对。像素数不超过 768×768，并且尺寸、steps、guidance、seed 等键兼容；多模态输入等情况被排除。

Dispatcher 优先寻找同 batch key 计数为奇数的 backend；本地 scheduler 从普通队列搜索窗口找一个配对请求。默认搜索窗口 32，第三方启动示例设为 64。runner 支持一次推进最多两个请求。[D3][D4][D7]

因此，开启 batch2 后普通请求可能因配对提前执行，“普通 FIFO”需限定为基础出队次序；也不能把 batch2 带来的吞吐变化全部归为双队列收益。

### 6.4 已有测试范围

test_super_p95_step_scheduler.py 检查普通 FIFO 和 tail LIFO；test_diffusion_scheduler.py 还检查普通优先、估计等行为；dispatcher 测试包含等长请求保留预算和后续长请求消耗预算；API 测试检查元数据和负载头。

这些单元测试不能替代真实硬件上的抢占恢复正确性、输出质量和性能对照。本轮未运行这些测试，代码未作修改。

## 7 LLM 现有实验基线

以下部署事实来自用户提供的内网报告和后续校正。

| 项目 | 当前基线 |
| --- | --- |
| 部署 | 3 节点，每节点 8×910B2-64G；每节点 1P TP4 + 1D TP4，共 3P3D |
| 模型 | 报告记载 Qwen3.6-27B W8A8 |
| P | FCFS；chunked prefill；max_num_batched_tokens=8192；max_num_seqs=24；long_prefill_token_threshold 未启用；APC 开启 |
| P 异步 | CLI 没有传 async-scheduling；fork 配置自动解析为 True，三节点日志确认开启 |
| P 实际类 | SchedulerWithPredictorAsync |
| D | AsyncRecomputeScheduler 路径，显式异步、MTP3；g4 无 predictor/reporter 注入 |
| 执行 | 报告记录 enforce-eager |
| KV | Mooncake；报告记录外部迁移命中率 100%，该批实验无迁移重算 |
| 路由 | g4 P 为 FGJSQ，D 为 heap active_tokens |
| 预测器 | P 侧批执行耗时预测，继续参与事件上报与路由；SLO 组批开关为 0 |

注意三个不同的 B：aisbench B 是客户端在途并发上限；max_num_seqs 是引擎序列上限；predictor 特征 B 是实际批大小。三者不等价。

### 7.1 继承链和 SLO 为零的路径

用户提供的实际 MRO：

~~~text
SchedulerWithPredictorAsync
→ SchedulerWithPredictor
→ AsyncRecomputeScheduler
→ AsyncScheduler
→ RecomputeScheduler
→ Scheduler
~~~

用户确认 SLO=0 时：

~~~text
waiting <= 1：直接 super().schedule()
否则：_slo_prefilter_waiting() 因 SLO 关闭立即返回
随后仍调用 super().schedule()
每 100 步诊断日志；predictor/reporter 保持工作
~~~

官方 Ascend v0.23.0 中，AsyncRecomputeScheduler 继承 AsyncScheduler、RecomputeScheduler，没有独立重写 schedule；AsyncScheduler 主要扩展异步进度与输出处理，实际 schedule 方法沿 MRO 落到 RecomputeScheduler 的实现。[L3][L4]

因此，“原生 FCFS 语义”不等于没有 wrapper 和观测开销，也不等于 schedule 直接调用核心 Scheduler 的方法体。内网 fork 的精确 commit 仍需后续锁定；官方标签用于解释机制，不能替代插件源码核验。

### 7.2 Predictor 的当前含义

按报告，predictor 输出一个 prefill 批的执行时间 predicted_exec_ms。特征包括未缓存 token 数、批大小、平均 prompt 长度、命中率、cached token，以及交叉/自注意力成本代理项。当前输出服务于 proxy 负载随时间衰减，在线样本由实际批耗时更新。

本研究可以继续利用这个批级预测器，但不能把其输出直接当成“任意请求剩余 TTFT”：后者还包括排队、后续多个 chunk、KV 交接和 D 首次输出。调度策略改变后，新批形状上的预测误差也属于待验证事项。

## 8 FCFS 与 running first 及共享 token 预算

### 8.1 统一进度模型

V1 用 token 进度统一处理 prefill、decode 和推测执行。简化形式为：

~~~text
demand[r] =
    num_tokens_with_spec[r]
    + num_output_placeholders[r]
    - num_computed_tokens[r]

allocation[r] = min(demand[r], remaining_token_budget, 其他限制)
~~~

普通 decode 通常推进一个 token；MTP/异步有额外 token 和占位。partial prefill 在首 chunk 获得调度后进入 running，所以 running 不等于 decode。[L1][L3]

调度器中的 computed 进度可能在发出调度后先推进，用于异步继续排程；它不能在所有时刻直接解读为“设备已经完成计算的 token 数”。

### 8.2 每轮分配过程

RecomputeScheduler 同样采用以下主顺序：[L4]

1. 初始化共享 token 预算，通常为 max_num_batched_tokens；若配置 max_num_scheduled_tokens 则使用后者。
2. 遍历 running，为已有请求分配本轮 token 并申请 KV block。
3. 若发生抢占/重算等条件，可能跳过本轮 waiting 接纳。
4. 否则利用剩余预算接纳 waiting，检查 max_num_seqs、前缀命中、远端 KV 和可用内存。
5. 生成 SchedulerOutput，执行后更新状态；完成请求退出。

FCFS 描述等待次序；running-first 描述在途请求优先参与分配；共享 token 预算描述所有请求共同竞争本轮额度。它不是轮转均分，也不自动实现短请求优先。

基础循环不会每轮都重排成严格 decode-first。对本实验更重要的是 P 侧多个 prefill 之间的预算竞争，不应套用 P/D 混部下“decode 消耗 P 预算”的解释。

### 8.3 没有单请求上限的示例

假设同一 P 上 A 尚需 20,000 token，B 尚需 1,000 token，顺序 A 在前；总预算 8192；无 KV 限制、无缓存及其他干扰：

| 轮次 | A 分配 | B 分配 |
| --- | ---: | ---: |
| 1 | 8192 | 0 |
| 2 | 8192 | 0 |
| 3 | 3616 | 1000 |

A 第一次入场后留在 running，后续轮次仍可吃满预算。chunked prefill 提供了调度边界，却没有自动把边界变为其他请求的执行机会。

这是逻辑调度轮次示意，不是同步时间轴；异步场景可能已有多个在途 batch，不能假定每个边界都能立即改变设备接下来的全部工作。

### 8.4 KV 与资源抢占

核心 Scheduler._preempt_request 会释放请求 KV/encoder 资源、置 num_computed_tokens=0、标记 PREEMPTED 并放回等待队列。恢复时可能重用仍可命中的 prefix cache，否则需要重算。[L1]

Ascend RecomputeScheduler 还包含 KV consumer、远端 KV、暂停恢复/重算输出等分支，需结合角色和开关判断。[L4] 报告中的“外部 KV 命中 100%”不意味着未来主动抢占必然无重算。

需要明确区分：

| 动作 | 资源与成本 |
| --- | --- |
| 等待请求延后入场 | 尚未获得该次执行机会，不等于抢占在途工作 |
| 已入场请求本轮暂缓，保留 KV | 可以继续利用进度，但仍占 KV；保留 running 时还可能占序列槽位 |
| 资源抢占并释放 KV | 腾出内存，可能导致缓存丢失、重算和额外传输 |
| 取消已提交设备计算 | 不属于简单队列重排；异步依赖和正确性要求另行处理 |

## 9 LLM 执行与指标时序

~~~mermaid
sequenceDiagram
    participant C as 客户端
    participant X as Proxy
    participant P as P EngineCore 与 Scheduler
    participant W as P Worker
    participant D as D 引擎与 KV Connector
    C->>X: 请求
    X->>P: 路由到 P，进入 waiting
    Note over P: 首次准入之前：引擎 queue time
    P->>P: running 优先，再从 waiting 分配剩余预算
    P->>W: 第一个 chunk
    Note over P,W: 异步调度可与在途执行重叠
    loop 尚未完成 prefill
        P->>P: 为 partial prefill 再分配 token
        P->>W: 后续 chunk
        W-->>P: 批输出与进度
    end
    P-->>X: P 响应与 KV 交接信息
    X->>D: 发送 D 请求
    Note over W,D: KV 获取或传输，具体完成点由 Connector 决定
    D-->>X: 首个有效输出
    X-->>C: 首个有效输出，客户端 TTFT 终点
~~~

引擎指标区间：[L5]

~~~text
queue_time = first_scheduled_ts - queued_ts
prefill_interval = first_token_ts - first_scheduled_ts
~~~

prefill_interval 包含首次调度后到首输出的等待与可能的抢占，不是纯设备计算时间。在 PD 系统中，P 引擎自己的首输出也不直接等于客户端经 D 收到的首输出。

客户端 TTFT 可按逐请求时间点理解为：前端和传输 + P 入场等待 + P 首次调度后耗时 + P/D 交接与 D 首次执行 + 输出返回。各段 P90 不能相加得到总 TTFT P90，也不能用两个不同分布的 P50 相减确定某段时间。

## 10 对现有 P 侧负载的理解

报告给出了两类工作负载：

- 闭环 aisbench：66k/128k 长输入、共享前缀、输出 1024，客户端 B=1/2/4/8/16。B 约束 P、交接、D 全链路在途请求；稳态近似 lambda = 平均在途数 / 平均 E2E，不总是精确 B/E2E。D 变慢也会降低请求补充速度。
- 开环 trace：按计划到点发送，长度和间隔有变化，不随本次实验完成速度自动背压。大约 20% 的请求小于 8k，但实际可拼批条件还取决于缓存命中和剩余 token。

P 侧工作量由实际未缓存 token、已有上下文、批构成和执行效率共同决定。50% 共享前缀不保证每条请求实际命中 50%；原始输入 token/s 也不等于实际 prefill 计算吞吐。

报告观察到：128k 高并发和开环长尾有明显入场等待；66k B16 的客户端残差估计高于引擎 queue time。这些支持把“入场前”和“入场后”分开研究，但不能仅靠残差认定全部来自 running 内 chunk 交织。

特别保留以下证据边界：

- TTFT - uncached/24576 是工程残差估计，不是纯排队真值；其误差方向不能不经校准就固定为低估。
- 首次调度后的残差可能包括实际计算差异、chunk 间隔、KV 交接和 D 首次执行。
- proxy P 账本在首个 D chunk 才释放，不等于 P 算力在此之前一直忙，也不等于 P KV 在此刻才释放。
- 队列非空、持续等待、均值负载平稳，都不能证明当前吞吐接近容量。
- 同一到达率下开环完成 QPS 相近，不代表最大可持续吞吐相同。
- 报告中的“容量顶死”“无算法空间”不作为本研究前提；吞吐提升空间需要实验查证。

## 11 Diffusion 与 LLM 的迁移边界

| 维度 | Diffusion super_p95 | LLM 当前基线及研究问题 |
| --- | --- | --- |
| 目标终点 | 完整图片/视频完成延迟 P95 | 首输出 P90 TTFT 为主，并要求吞吐提升或至少不降 |
| 执行单位 | 一个 diffusion step 调用 | 每请求本轮分配的一段 token |
| 批组成 | 基础单请求，可选小图 batch2 | 多请求连续批处理，受 token、序列、KV、异步依赖约束 |
| 分类依据 | 固定锚点估计总耗时，历史 min/max 与累计预算 | 尚未确定；不能直接把总 prompt 长度等同于剩余成本 |
| 等待队列 | normal FIFO、sacrificial LIFO | 当前 FCFS；未来双队列规则待研究 |
| 对 running 的处理 | 普通请求使运行中的让行请求在 step 边界暂停 | 不仅入场顺序，还涉及 partial prefill 后续预算 |
| 状态保留 | runner state_cache 保留 diffusion 状态 | KV、序列槽位、在途 batch 与占位进度共同约束 |
| 原生资源抢占 | 此双队列路径不靠释放状态恢复 | 可能释放 KV 并产生重算，不能等同于无损让行 |
| 成本模型 | 固定硬件规格锚点 | 已有批执行时间 predictor，可作为未来输入 |
| 已有收益证据 | 历史有尾延迟下降，也有吞吐损失或拓扑混杂 | 不能据此推断 LLM 收益 |
| 执行时长比较 | step 成本依模型与规格变化 | chunk 比 step 短是待实测的研究假设，不是所有场景的定律 |

Diffusion 的 5% 累计让行预算不能机械改成 10% 来“对应 P90”。入场比例、队列长度、资源占用、最终延迟分位与公平性是不同量。

## 12 下一轮研究方向记录

本节仅记录用户提出的方向和待回答问题，不形成已选定的算法或实验计划。

### 12.1 双等待队列与执行机会

目标是为到达引擎的请求排优先级，控制让行请求对多数请求尾延迟的影响，同时尽量避免吞吐损失。待讨论：

- 什么请求适合低优先级：原始长度、未缓存工作、预测成本，还是其他条件？
- 如何区分累计让行预算、当前队列长度和长期等待约束？
- 仅重排 waiting 是否足够，何时需要调整 running 中 partial prefill 的机会？
- chunk 边界已提供选择机会时，是否需要释放资源的抢占？
- 异步已提交 batch 下，可生效的调度边界在哪里？

不预设沿用 diffusion LIFO、不预设固定让行比例，也不预设必须抢占。

### 12.2 基于预测成本的动态 chunk 与组批

用户希望从固定共享 8192-token 的顺序消耗，探索由 predictor 与 cost 函数决定批构成和各请求 chunk size，以提升吞吐并控制尾延迟。

“不再共享 token”在研究层面理解为：不再只依赖固定公共预算按顺序贪心分配；具体资源预算如何表达留待设计。无论采用何种模型，物理内存、总工作量、序列数及执行接口的容量约束仍存在，不能从表述直接推导为取消全部总量约束。

用户提及 Optimizing LLM Inference Throughput via Memory-aware and SLA-constrained Dynamic Batching 作为参考方向。本文未评述该论文算法，后续需取得准确论文版本再比较。

### 12.3 现有闭环的利用与目标

可利用 FGJSQ 路由与 P 侧批执行时间 predictor，使“请求进入哪个 P”和“该 P 如何组成下一批”具有一致的负载信息。更精准和更高效是待验证目标，不是现有结果。

首要场景是高并发 aisbench 的密集请求与高负载。优化目标按用户当前要求记录为：

1. 提升吞吐，至少保证吞吐不下降。
2. 优先改善全体请求 P90 TTFT，同时观察 P95 TTFT。
3. P90 TPOT 可纳入，注意闭环中 D 延迟会反馈到 P 到达节奏。
4. 不通过排除慢请求、忽略失败或只报告 normal 子集来替代全体指标。
5. 当前平均吞吐是否接近容量仍待查证，不作为建模前提。

下一轮由用户提供可行方向、场景和负载原因后，再讨论分类条件、预算、让行边界及 cost 函数。

## 13 源码与文档索引

Diffusion 文件均在 dd9c0895。可在本仓库直接阅读；永久链接便于区分历史版本。

- [D1 技术方案](../../upstream/vllm-omni-super-p95/benchmarks/diffusion/super_p95_technical_plan.md)：目标、两级调度、公式和验证建议，部分细节早于当前代码。
- [D2 重写笔记](../../upstream/vllm-omni-super-p95/benchmarks/diffusion/super_p95_v018_rewrite_notes.md)：历史移植结果、环境干扰和旧恢复机制经验。
- [D3 Dispatcher](https://github.com/Lijunzhang0829/vllm-omni/blob/dd9c0895d98a73c760e9ca930d87e03198713ff7/benchmarks/diffusion/super_p95_dispatcher.py)：BackendState.score_tuple；_choose_backend；_is_sacrificial_candidate；_select_backend_index；_apply_response_feedback；_release_video_load。
- [D4 Step Scheduler](https://github.com/Lijunzhang0829/vllm-omni/blob/dd9c0895d98a73c760e9ca930d87e03198713ff7/vllm_omni/diffusion/sched/super_p95_step_scheduler.py)：_QueuedRequest；schedule；update_from_runner_output；request_outranks；_pop_batch_partner。
- [D5 估计器和协议](../../upstream/vllm-omni-super-p95/vllm_omni/diffusion/super_p95.py)：硬件锚点、HTTP 头、采样参数元数据、load snapshot。
- [D6 DiffusionEngine](../../upstream/vllm-omni-super-p95/vllm_omni/diffusion/diffusion_engine.py)：_make_default_scheduler；add_req_and_wait_for_response。
- [D7 ModelRunner](../../upstream/vllm-omni-super-p95/vllm_omni/diffusion/worker/diffusion_model_runner.py)：_update_states；_update_states_after；execute_stepwise。
- [D8 压测请求函数](../../upstream/vllm-omni-super-p95/benchmarks/diffusion/backends.py)：三类请求计时、视频轮询。
- [D9 压测聚合](../../upstream/vllm-omni-super-p95/benchmarks/diffusion/diffusion_benchmark_serving.py)：iter_requests、latency_p95、客户端 semaphore。
- [D10 Qwen 压测脚本](../../upstream/vllm-omni-super-p95/eval_qwen_image.sh)：混合规格、随机种子、到达率、实际 backend。
- [D11 第三方命令与结果](../../upstream/vllm-omni-super-p95/THIRD_PARTY_TEST_COMMANDS.md)：batch2 开关、不同请求率、Wan 1×8 对 2×4。
- [D12 API 接线](../../upstream/vllm-omni-super-p95/vllm_omni/entrypoints/openai/api_server.py) 与 [chat 接线](../../upstream/vllm-omni-super-p95/vllm_omni/entrypoints/openai/serving_chat.py)：请求头传入与响应负载。
- [L1 vLLM v0.23.0 Scheduler](https://github.com/vllm-project/vllm/blob/v0.23.0/vllm/v1/core/sched/scheduler.py)：schedule、_preempt_request、_update_after_schedule。
- [L2 vLLM v0.23.0 EngineCore](https://github.com/vllm-project/vllm/blob/v0.23.0/vllm/v1/engine/core.py)：step、step_with_batch_queue。
- [L3 vLLM v0.23.0 AsyncScheduler](https://github.com/vllm-project/vllm/blob/v0.23.0/vllm/v1/core/sched/async_scheduler.py)：输出占位、异步进度更新。
- [L4 Ascend v0.23.0 RecomputeScheduler](https://github.com/vllm-project/vllm-ascend/blob/v0.23.0/vllm_ascend/core/recompute_scheduler.py)：原生 schedule、KV 和重算分支、AsyncRecomputeScheduler 继承。
- [L5 vLLM v0.23.0 指标](https://github.com/vllm-project/vllm/blob/v0.23.0/vllm/v1/metrics/stats.py)：queue、prefill、首 token 的区间定义。
- [L6 Ascend v0.23.0 ModelRunner](https://github.com/vllm-project/vllm-ascend/blob/v0.23.0/vllm_ascend/worker/model_runner_v1.py)：NPU 输入准备、attention metadata 与异步执行。
- 内网依据：用户粘贴的 SUMMARY_REPORT 3P3D FGJSQ 实验全景总结，2026-10-15；用户补充的 P 自动异步、SchedulerWithPredictorAsync MRO 与 SLO=0 路径。未在本仓库复制内网脚本或原始日志。

