# 原始效用函数与 FGJSQ / predictor 源码核对

日期：2026-10-19。数学分支。本轮只分析与记录，不修改代码。原始投递 11 个文件的 SHA256 均与 evidence/manifests/g4_source_intake_20261019.json 相符。核对的是本地投递和固定上游源码，不代表已验证现场运行轨迹。

关联：[数学笔记](CHUNK_SIZE_KV_CACHE_MATHEMATICAL_MODEL.md)、[工程侧核对](../engineering/FGJSQ_MOTOR_ADAPTATION_REVIEW.md)。本文对原始投递独立读取核查；工程实现与修复由主会话负责。下列源码链接均指原始投递，不指后来适配的 src 副本。

## 1. 结论

用户的公式是有解释空间的队列状态效用函数，但目前不是严格的吞吐公式、总 TTFT 公式或 P90 最优目标。值得保留的是“chunk 推进收益 / 请求时间代价”的结构；需要补齐的是工作量记账、两个时间窗口的含义、异步可入场边界和尾部风险。

predictor 确实可以提供成本信息，但当前实现的特征名与物理含义不一致，标签也不是纯计算时间。不能把模型的 cache_hit_rate 当作宏观 APC 命中率，不能把预测值直接叫作请求 TTFT。

## 2. 原函数逐项解释

保持用户明确要求的两个不同时间函数，不认为 d_1,...,d_2 是笔误：

$$
T(C)=T_{mix}(d_1,\ldots,d_k;C,p_1,\ldots,p_m),\quad
U(C)=T_{mix}(d_1,\ldots,d_2;C,p_1,\ldots,p_m).
$$

设 P=Σp_i，W=Σw_j，N=1+m+n，ℓ=E[L]，则

$$
F(C)=\frac{A(C)}{D(C)}
=\frac{C+P+W+\lambda T(C)\ell}{NT(C)+\lambda U(C)^2/2},\qquad C^*=\arg\max_{C\in\mathcal C}F(C).
$$

这是最大化 utility；如称 cost，则通常取其倒数并最小化（须 A,D>0）。目标请求不得再次算入 p_i 或 w_j。

| 项 | 可以成立的解释 | 必要限制 |
| --- | --- | --- |
| C+P | 本轮目标与其他 prefill 的计划推进量 | p_i 必须是本轮分配，而非完整 prompt |
| W | 当前等待工作量，用于反映积压 | 本轮未处理，不能当作完成收益 |
| λTℓ | T 窗口内预期到达工作量 | 局部常强度/相应条件独立假设；不是本轮完成量 |
| NT | N 个计入请求在 T 窗口内累计驻留时间 | 是 request·time，不是批墙钟；也不是反事实的纯额外损害 |
| λU²/2 | 新到达请求在 U 窗口内累计等待 | 需要明确其阻塞确实在 U 解除 |

统一时间单位：若 λ 是 request/s，predictor 的 ms 必须除以 1000。分母的两项均为 request·s；整体为 token/(request·s)，不是完成 token/s 或 QPS。

### 2.1 平方项成立的条件

若新请求在 s∈[0,U] 到达且只能在 U 进入服务，本次等待是 U−s：

$$
\int_0^U\lambda(U-s)ds=\lambda U^2/2.
$$

若所有在 [0,T] 到达的请求都等到 T，则是 λT²/2；若仅统计 [0,U] 到达但仍等到 T（U≤T），则是 λ(TU−U²/2)。因此原式的 U² 可以保留，但必须解释为什么现存请求按 T 计费，而新到达按另一个 U 解除阻塞。现有 Chunker 描述和所查代码均未提供这一解释。

连续批处理中，完成一个 chunk 只是重新调度的机会；running-first、共享预算、KV/序列名额及已提交的异步批都可能阻止 waiting 入场。不能据此认为所有新请求至多等待一个 chunk。

### 2.2 分子混入库存的后果

固定候选和其他状态，∂F/∂W=1/D>0：多出尚未服务的工作会提高效用分数。它可以作为积压紧迫性启发式，但不能称作完成收益。

更直接的例子：λ=0、P=0、W>0，且 T(C)=τ+aC，τ,a>0：

$$
F(C)=\frac{C+W}{N(\tau+aC)},\quad
F'(C)=\frac{\tau-aW}{N(\tau+aC)^2}.
$$

若 W>τ/a，函数严格偏好最小 C；C=0 可行时，甚至偏好零推进。在混合批中 C=0 可能仍能服务 decode；在纯 P 且无其他工作时则会产生空转。这个反例不是否定所有使用场景，而是说明需要推进约束以及解释 W 为什么放在收益侧。

同样，λTℓ 随 T 增长；它表示服务期间新增积压，不能因为执行更慢、到达更多而计作新增产出。

### 2.3 最优点与解释边界

冻结 N,P,W,λ,ℓ，假定 T,U 可微且 D>0：

$$
F'(C)=\frac{(1+\lambda\ell T')D-A(NT'+\lambda UU')}{D^2}.
$$

内点满足

$$
\frac{1+\lambda\ell T'}{A}=\frac{NT'+\lambda UU'}{D}.
$$

即边际相对收益与边际相对代价相等。仍需比较边界和所有离散候选；没有自动成立的凹性或唯一最优性。改变 C 若也改变请求集合，则 N、P 等也要变化，不能使用此固定候选导数。

函数没有请求年龄、SLO 剩余时间或完成分布；相同 n,W 的队列可以具有完全不同的 P90 风险。因此优化 F 不自动保证 P90 TTFT，也不保证吞吐不降。decode 的 k 未进入 N：若要同时保护 decode，必须明确是否由额外约束表达。3P3D 的 P-only 模型还需去掉虚构的本地 decode 工作，D 的 TPOT 上限不能直接等同于 P 批时长上限。

λ 应为单 P 的有效到达强度。FGJSQ 路由和闭环发压会使它随系统状态变化；不能把 request_rate=1 直接代入稳态 λ，也不能默认 λ系统/3。短时冻结 λ 是分析近似，而非已验证事实。

## 3. FGJSQ 负载、更新与释放

源码：[proxy](../../evidence/source_drops/proxy/g4-20261015/load_balance_proxy_finegrained_p3d_pdhybrid.py)，重点行 332–523、883–969、1446–1566、1602–1631、1744–1759。

### 3.1 路由分数

实例 i 的未释放请求数 n_i，已提交估计负载 W_i，配置最大序列数 b_i：

$$
S_i=W_i\frac{\lceil n_i/b_i\rceil+1}{2}.
$$

派发前重新估算有事件的请求，按分数升序选最小，然后登记新请求。外层锁覆盖选择与登记。同分按稳定排序的实例插入顺序，不是随机。b_i 是配置上限，不是本批 B，也不是 token budget。

初始 original_load=max(1,HTTP body 字节数//4)。首次有效事件按 num_prompt_tokens 修正 original 与 committed。此分数是 token 负载启发式，不是毫秒。

### 3.2 请求负载

O=original，L=prompt，Q=本批 scheduled，R=remaining，ρ默认0.05，t_recv=proxy 接收本地时间：

$$
g(t)=\min((t-t_{recv})/\hat T,1-\rho),\quad
w(t)=\operatorname{round}\left[O\frac R L+O\frac Q L(1-g(t))\right].
$$

仅在预测时间与 elapsed 正数时使用上式 g，否则 g=0。无有效事件时使用 O。首次校正后 O=L，等价于估计剩余 token 加上本批尚未消耗部分。

同批请求共享一个预测时间尺度，不是把每条请求的预测时间相加。5% 保留仅作用于本批 Q；整数取整后不保证严格正值。

事件按请求 ID、实例和源 timestamp 检查；只接受更新 timestamp。接受事件保存 batch_info 并重置接收时钟，除首次校正外，负载差量在后续 dispatch/report_loads 时提交。源 timestamp 用于拒旧，衰减时钟用本地接收时间。事件未直接释放请求，也未把 request_count 减少。

### 3.3 释放及证据边界

reduce_load 以 ID pop，减去最近 committed_load，减少请求数并移除 active 登记；重复释放不再减账，迟到事件不能复活记录。

g4 正常释放 P 负载发生在 D 返回首个非空 HTTP bytes chunk，且在 SSE 内容解析前；不是 P 计算完成时，也不严格等于首个内容 token，更不是执行物理 KV 释放。流结束/异常 finally 兜底；重新派发前释放旧 P/D 负载。D 池保持 heap active_tokens。

需区分 P 账本幂等与全局 request_num：重派发生成新 ID、initial 集合仍持有旧 ID，存在计数登记残留风险；P 派发后但 InstanceInfo 尚未返回时的取消清理也需工程侧单独覆盖。不把静态风险说成历史现场故障。

### 3.4 事件链限制

[reporter](../../evidence/source_drops/slo_patch/g4-20261015/slo_patch/slo/batch_event_reporter.py) 行 38–95：后台线程读取 live requests，而不是冻结快照；同一旧 SchedulerOutput 可能读到后续批更新的 computed，或请求已消失。timestamp 也在后台生成。

[patch_core](../../evidence/source_drops/slo_patch/g4-20261015/slo_patch/patch_core.py) 行 220 附近：流水线中下一批事件可能在等待上一批 future 前发出。因此事件时钟不等同于实际设备开始执行。

reporter 使用 req_id[:-9]，proxy 仅精确匹配/前缀匹配。固定上游标准 chat 路径为 chatcmpl-uuid-xxxxxxxx，截尾后仍是 chatcmpl-uuid，不能匹配 proxy uuid。证据：上游 chat_completion/serving.py:256、input_processor.py:240、proxy:458、1313。只能判定这些代码在标准路径组合下不相容；现场可能有未披露差异，不能断言历史全部事件丢失。event_count/HTTP200 也不能证明关联成功。

这些限制使 FGJSQ 账本不宜直接作为精确队列等待时间或宏观 KV 状态。

## 4. predictor 特征与标签的真实口径

### 4.1 特征

[patch_core](../../evidence/source_drops/slo_patch/g4-20261015/slo_patch/patch_core.py) 行 22–54；[特征实现](../../evidence/source_drops/slo_patch/g4-20261015/slo_patch/slo/predictor_impl.py) 行 141–176、258–306。

设 L=本批请求完整 prompt 总长，K=调用 predict 时这些 Request 的 num_computed_tokens 之和，B=参与请求数：

$$
\bar L=L/B,\quad h_{legacy}=(L-K)/L,\quad
N_c=\operatorname{int}(B\bar L\,clip(h_{legacy})),\quad
N_u=\operatorname{int}(B\bar L-N_c).
$$

| 列名 | 实际数值 |
| --- | --- |
| N_uncached | N_u，prefill 正常范围下约等于 K |
| B | 当前 scheduled 请求数 |
| L_avg | 完整 prompt 平均长度 |
| cache_hit_rate | 剩余比例 h_legacy，不是真实 APC 命中率 |
| prefill_intensity | N_u/(B+1e-6) |
| N_cached | N_c，约等于 L−K |
| Cross_Attention_Proxy | N_u N_c/max(B,1) |
| Self_Attention_Proxy | N_u²/max(B,1) |

上游 Scheduler:997–1010 在 schedule 返回前已累加本批 scheduled tokens；Ascend RecomputeScheduler:823 调用它。因此 K 可包含刚计划甚至在途计算，不代表已完成或缓存命中。当前 predict/update 调用只传 B、L_avg、h，没有把本批真实 scheduled token 总数传给 compute_features 的可选参数。

例：L=1000、schedule 后 K=400、本批 Q=200，则 h=0.6、N_u≈400、N_c≈600。另一个状态本批 Q=400、此前 K=0，schedule 后也为400，得到同样的八维特征。两者本批 token 与上下文构成不同，却无法由现有特征区分。这是候选成本可辨识性的限制，不只是预测精度未知。

旧笔记中宏观 h 的定义仍可作为数学变量，但不能从本实现同名字段直接读取。八列多数是三个输入的派生变换；没有独立的每请求 chunk/context 分布、真实 APC hit、decode 组成或 pipeline 状态。

### 4.2 标签和对齐

[patch_core](../../evidence/source_drops/slo_patch/g4-20261015/slo_patch/patch_core.py) 行 118–143、170–242；[训练入口](../../evidence/source_drops/slo_patch/g4-20261015/slo_patch/slo/scheduler_with_predictor.py) 行126–153、402–429。

- 同步：execute_model 提交前至 future.result 返回的主机时长；后续另行 sample_tokens 不计在先前采样时间中。
- 异步、提交时队列为空：本批主机观察完成时刻减提交时刻。
- 异步、提交时队列非空：本批主机观察完成时刻减上一批主机观察完成时刻。
- 单位 ms，保存为 actual_batch_exec_time，经参数 actual_ttft 写入 execute_time_ms。

特征与标签附着于同一 SchedulerOutput，训练队列再复制标量；没有发现正常路径下直接把另一批特征混入当前批标签的证据。但“标量对齐”不意味着测量等同设备耗时：流水线重叠、主机处理/观察延迟、采样等都会影响标签含义，空队列与非空队列标签也不是同一计时窗口。

### 4.3 训练与模型结构

实际为 StandardScaler + LGBMRegressor，尽管注释称 GBR。默认300棵、深度5、学习率0.05、单训练线程。按 prompt 均长1000和上述 h 的0.2间隔分桶，每桶最多100样本，最低50样本；warmup_batches=2 只是触发尝试，仍受50样本门槛约束。之后按100批间隔尝试后台重训；已有训练未结束可跳过，预训练加载可跳过冷启动。

单调约束顺序是 [+, +, +, −, +, −, +, +]。这些约束作用于当前列，不能按名称解释成真实 KV 物理定律。特别是 N_cached 实际接近剩余量；相关派生特征同时变化时，也不能把逐列约束当成沿 C 的全局单调保证。

训练后 MAE/R²/误差分位数在同一训练集上计算，是拟合指标，不是独立验证的未来误差分布。模型输出点估计，没有直接训练 P90 分位数。加载的外部模型具体参数需另验，本文仅确认源码新训路径。

常数叶 LightGBM 对输入分段常数；当前新训代码未启用 linear_tree。网格搜索可以直接调用；微分建模需另外给出可微代理及其成立范围，不能把树模型当光滑成本函数。[LightGBM 官方说明](https://lightgbm.readthedocs.io/en/stable/Parameters.html#linear_tree)

## 5. 下一轮的建模接口，不在本轮替换公式

1. 明确 T/U 分别预测执行时长、完成间隔还是可入场阻塞时间，保留二者差异直到有业务定义。
2. 定义候选 C 对应的完整批状态与独立特征，分离 scheduled tokens、历史 context、APC 命中和异步在途。
3. 明确收益是实际推进量还是积压紧迫性；如保留 W，给出选择它的效用解释和零推进边界。
4. 区分局部预测均值、方差/分位数与请求剩余 TTFT。即便时间窗成立，随机 U 也有 E[U²]=E[U]²+Var(U)，仅代入均值平方会漏掉波动代价。
5. 结合请求年龄与分档 SLO，讨论如何把局部代价连接到尾部约束；不把对均值求导当作 P90 保证。

以上是数学问题与接口需求；代码修正、模型 schema 迁移和现场验证由主会话处理。
