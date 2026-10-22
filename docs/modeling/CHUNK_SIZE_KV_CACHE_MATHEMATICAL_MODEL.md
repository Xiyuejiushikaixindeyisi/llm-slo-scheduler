# Chunk size、预测器与 KV 缓存的数学建模笔记

版本：v0.1，2026-10-19。供研究讨论；本文给出条件化推导，不报告性能实验，也不声称已证明本部署上的 P90 最优性。

关联：[研究指导文档](../LLM_TAIL_LATENCY_RESEARCH_GUIDE.md)。当前部署是 3P3D、P 侧异步连续组批，研究主指标是 P90 TTFT，吞吐不下降，P90 TPOT 按业务档约束。

**本轮结论：可以把批耗时预测、缓存状态和 chunk 寻优连起来，但必须分清三个对象：当前批的成本函数、缓存状态的演化、请求首 token 时间的分布。仅对平均批耗时求导，不能得到 P90 保证。**

以下区分三类来源：

- 用户模型：原始 C* 分式及 Optimal Prefill Chunker 的功能说明。
- 已有依据：vLLM 缓存机制、LightGBM 模型形式、TTL/LRU 缓存近似文献。
- 本文推导：商法则、条件最优点、缓存闭合方程及两者的耦合；假设均在使用处列出，不归因于厂商已部署算法。

## 1. 固定问题与记号，保留两个不同的时间函数

用户补充的 Chunker 是一个在线决策模块：先有 decode 候选批，再枚举一个长 prefill 请求的 chunk，调用成本模型，选择效用最大的候选。这里固定其他请求集合和其 token 分配，只研究一个标量 C。联合选择请求集合、各请求 chunk，是更大的优化问题。

| 记号 | 本文定义 |
| --- | --- |
| C | 目标长请求本轮新增计算 token；连续推导时暂作实数，落地时离散/对齐 |
| p_i、P_b | 其他已选 prefill 请求本轮 token，P_b=Σp_i |
| w_j、W_q | 等待 prefill 的 token，W_q=Σw_j；是总长还是未缓存剩余量仍需统一 |
| m、n、N | 其他已选 prefill 数、等待 prefill 数，N=1+m+n |
| d_1,…,d_k 与 d_1,…,d_2 | 用户有意保留的两种 decode 参数集合；二者的业务对应关系待补充 |
| λ | 到达当前被建模 P 实例的有效请求强度，单位 request/s |
| ℓ | 原式 E[L]；总输入长度或未缓存长度必须与分子其他量口径一致 |
| h | 本 P 的 token 加权有效前缀命中比例；不是 P→D external KV 命中率 |
| z | 其他状态：候选构成、上下文、KV 可用量、异步在途、模型模式等 |

定义两个独立函数：

$$
T=T_k(C,h,z)=T_{\rm mix}(d_1,\ldots,d_k;C,p_1,\ldots,p_m),
\qquad
U=T_2(C,h,z)=T_{\rm mix}(d_1,\ldots,d_2;C,p_1,\ldots,p_m).
\tag{1}
$$

这里 U 仅作时间函数简写，不表示总 token；指导文档第 8 节的总 token 另记为 $U_{\rm hard}$ 等。

用户已明确两处参数差异不是笔误。本文不令 T=U，也不假设第二个函数一定更小、更快。补充说明解释了混合批 Chunker 的整体流程，但尚未给出为什么第二项只含两个 decode 请求的等待机制。

按原式定义：

$$
A=C+P_b+W_q+\lambda T\ell,\quad
D=NT+\frac{\lambda}{2}U^2,\quad
F(C,h,z)=\frac{A}{D},\quad C^*\in\arg\max_{C\in\mathcal C}F.
\tag{2}
$$

分子单位是 token；分母是 request·s 的累计时间量（请求数作为计数单位），并非单段执行墙钟。F 是“工作量/累计时间”的效用。W_q 和未来到达 token 本轮没有被处理，所以 F 不能直接命名为完成 QPS 或本轮 token/s。

目标长请求不得再次计入其他 p_i 或 w_j。每项采用逻辑 token 还是未缓存 token，也不能混用；否则缓存变化本身会改变效用定义。

## 2. 从等待积分检查平方项，而不是改写它

设决策发生于时刻 0，新请求在 s 到达，本次动作对它产生的附加等待为 w_C(s)，条件到达强度为 λ(s)。一般形式是：

$$
W_{\rm arrival}(C)=\mathbb E\!\left[\sum_{\text{arrivals }j}w_C(s_j)\right]
=\int_0^\infty \lambda(s)w_C(s)\,ds.
\tag{3}
$$

上述等式要求强度与等待核的处理匹配；若等待核依赖随机系统状态，应保留相应条件期望。常强度、确定性时间窗口是以下简化的条件。

| 简化等待机制 | 新到达请求的累计附加等待 |
| --- | --- |
| 所有 0≤s≤T 的新请求都等到 T | λT²/2 |
| 只有 0≤s≤U 的到达计入，但都等到 T，且 U≤T | λ(TU−U²/2) |
| 被计入的新请求在 U 时刻解除本次阻塞，等待核为 (U−s)_+ | λU²/2 |

因此 **λU²/2 可以成立，但需要第三类等待窗口或其他等价推导**。如果实际描述是“在完整混合批 T 内到达的请求全部等到 T”，则应由该机制推得 T²，而不能仅靠代数保留 U² 就宣称解释完成。这是语义待定义项，不是认定用户写错。

NT 也有假设：N 个被计入的 prefill 请求都被本次时间窗口占用/延迟 T，且未在窗口内提前退出该计数。它不是所有请求真实 TTFT 的直接和；decode 请求的延迟若只通过 T、U 隐式进入，仍需说明是否足够表达目标中的 decode 代价。

AISBench pressure 的公开实现是滚动闭环。request_rate=1 不能直接代入稳态 λ；FGJSQ 后单 P 的 λ 也不等于全系统到达强度。数学分析可先冻结短时 λ，但研究长期均衡时，λ 会与完成速率、D 状态和路由反馈联动。[发压源码](https://github.com/AISBench/benchmark/blob/1e7cb37e3d5d2101db47fe3fe2272c965375a69c/ais_bench/benchmark/openicl/icl_inferencer/icl_base_api_inferencer.py#L427)

## 3. 原始分式的正确导数与最优条件

先固定 h、z、λ、ℓ、P_b、W_q、m、n；设 T、U 对 C 可微，D>0。由商法则：

$$
A_C=1+\lambda\ell T_C,\qquad
D_C=NT_C+\lambda U U_C,
$$

$$
F_C=
\frac{(1+\lambda\ell T_C)D-A(NT_C+\lambda U U_C)}{D^2}.
\tag{4}
$$

内点驻点满足：

$$
\boxed{
(1+\lambda\ell T_C)\left(NT+\frac{\lambda}{2}U^2\right)
=
(C+P_b+W_q+\lambda T\ell)(NT_C+\lambda U U_C)
}.
\tag{5}
$$

当 A>0 时，这等价于 $A_C/A=D_C/D$：增加一个 token 带来的相对效用增量，等于累计时间代价的相对增量。两处 T 的不同导数均保留。

二阶导数为：

$$
F_{CC}
=
\frac{A_{CC}D-AD_{CC}}{D^2}
-\frac{2D_C(A_CD-AD_C)}{D^3},
$$

$$
A_{CC}=\lambda\ell T_{CC},\qquad
D_{CC}=NT_{CC}+\lambda(U_C^2+UU_{CC}).
\tag{6}
$$

在驻点处，式 (6) 的第二项为零。$F_{CC}<0$ 给出严格局部极大；全局最大仍需比较可行区间端点及全部候选驻点。没有凹性/单峰性证明时，不能假设只有一个根，更不能直接用二分搜索。

若搜索 C 时其他 p_i、W_q 或候选数也变动，式 (4) 只对每个固定构成区间有效。若 λ=λ(C)、ℓ=ℓ(C)，则要补入：

$$
A_C=1+(P_b)_C+(W_q)_C+\lambda_C T\ell
+\lambda T_C\ell+\lambda T\ell_C,
$$

$$
D_C=N_C T+NT_C+\frac{\lambda_C}{2}U^2+\lambda UU_C.
\tag{7}
$$

闭环到达下把 λ 冻结是一种局部近似，不是普遍事实；候选成员突变处应按分段/离散问题处理。

## 4. 一个可解析的例子：什么条件下会出现内部最优 chunk

为理解式 (5)，暂取 λ=0；此时 U 项自然消失，不表示一般情况下 T=U。令 V=P_b+W_q 固定，取一个说明性平滑成本：

$$
T(C,h)=\tau(h)+a(h)C+b(h)C^2,\qquad
\tau>0,\ a\ge0,\ b>0.
$$

它只是成本形状假设，不是 910B2 拟合结果。则

$$
F_C\ \text{的符号}=
\operatorname{sign}\{\tau-aV-bC^2-2bVC\}.
$$

当 $\tau>aV$ 时，非负区域内唯一内点最大值为：

$$
C_{\rm int}^*
=-V+\sqrt{V^2+\frac{\tau-aV}{b}}.
\tag{8}
$$

在固定闭区间 $[C_{\min},C_{\max}]$ 上，把该值截到区间即可；若 $\tau\le aV$，F 在 C>0 上递减，最优位于 C_min。可行域若因块对齐、KV 或候选成员形成不连续集合，则需逐个可行候选比较。

这个例子解释两个机制：固定开销 τ 鼓励较大的 chunk；累计等待工作 V 和二次成本 b 会偏向较小 chunk。它也揭示原分式可能总选最小 chunk 的条件，不能在没有分析前认定网格搜索一定产生有意义的内部最优值。

固定 V，在内部最大分支上求 h 的敏感度：

$$
\frac{dC^*}{dh}
=
\frac{\tau_h-a_h V-b_h((C^*)^2+2VC^*)}
{2b(C^*+V)}.
\tag{9}
$$

若 τ 不变且 a_h、b_h 都非正，式 (9) 非负。但更高缓存命中还会改变上下文和候选组成，不能一般地假设这些符号。因此“命中率高就增大 chunk”需要条件，而不是通用规则。

## 5. 把 batch predictor 放到成本函数的位置

### 5.1 先确定预测对象

按内网报告，现有 predictor 预测的是 prefill batch 的执行毫秒数。称它为 batch-level TTFT predictor 容易混淆：单批执行时间不是某条请求从到达到首 token 的完整时间。收到 patch 后仍需复核真实标签、异步 batch 对齐和计时边界。

数学上设候选特征为 φ(C,h,z)，预测均值为：

$$
\mu_k(C,h,z)=f_k(\phi_k(C,h,z)),\qquad
\mu_2(C,h,z)=f_2(\phi_2(C,h,z)).
\tag{10}
$$

两种函数可以复用同一个模型，通过不同候选特征求值；不要求训练两个独立预测器。若模型只支持 P-only batch，不能直接声称它能预测混合 decode/prefill 的 T_k、T_2。

将 μ_k、μ_2 代入式 (2) 是 plug-in 近似，继而使用式 (4)。请求级剩余首 token 时间还需要未来多批计划、轮间等待、异步在途及 KV/D/网络状态；不能把当前 μ_k 直接当成这些量。

### 5.2 为什么不能直接对普通 LightGBM 的输出做解析求导

LightGBM 的普通树是常值叶；官方 linear_tree 选项默认为 false，开启后才使用分段线性叶。[官方参数说明](https://lightgbm.readthedocs.io/en/stable/Parameters.html#linear_tree)

因此，在普通树配置下，连续输入 C 的预测是分段常数，导数几乎处处为零、分裂边界不连续。它可以支持离散候选比较，却不适合直接提供式 (5) 所需的平滑边际时间。实际 patch 的配置仍待核对；linear_tree=true 也不自动意味着跨叶连续可微。

当前数学研究采用以下接口：

> 用具有明确平滑性和适用区域的成本代理 $\widetilde T(C,h,z)$ 表达结构；现有 predictor 为它提供数值约束、校准点或残差修正。对 $\widetilde T$ 求导，清楚标注代理误差。

可选择有形状约束的样条、局部光滑响应面或解析性能模型。单调/凸约束应按适用区间证明或论证；内核切换和批量效率可能使全局简单凸模型失效。本轮优先讨论数学形式，不以先做 profiling 作为继续推导的前提。

### 5.3 KV hit 应进入特征和剩余工作，而不是乘掉整个执行时间

对一个标准全注意力层的说明性模型，已有上下文 s_i、新计算 c_i 的 query-key 对数量为：

$$
Q_i=c_i s_i+\frac{c_i(c_i+1)}2.
$$

可以用它组成成本代理：

$$
\widetilde T=
\tau(z)+a(z)\sum_i c_i+
b(z)\sum_i Q_i+
g_{\rm decode}(\mathbf d,z)+g_{\rm memory}(\mathbf c,\mathbf s,z).
\tag{11}
$$

式 (11) 仅解释特征为何有用；并不假定所有内核耗时可加，也不覆盖模型可能采用的混合 attention/state cache。异步重叠、TP 通信、W8A8 和实际模型结构必须另有适用说明。

缓存命中减少待计算前缀，但新 token 仍可能关注命中的历史上下文。因此 $\widetilde T(C,h)=(1-h)\widetilde T(C,0)$ 通常没有依据。对当前候选，优先使用已知的命中长度与上下文；宏观 h 用于未来流量或未观测候选的分布，不覆盖已经知道的个体状态。

### 5.4 保留平方项时，预测不确定性应进入二阶矩

如果 T_k、T_2 是随机执行时间，式 (2) 的等待窗口解释成立，并且到达强度/长度按所用条件模型处理，令 $\mu_k=E[T_k]$、$\mu_2=E[T_2]$、$v_2=\operatorname{Var}(T_2)$。则“期望工作量/期望累计时间”形式为：

$$
\bar F=
\frac{C+P_b+W_q+\lambda\mu_k\ell}
{N\mu_k+\frac{\lambda}{2}(\mu_2^2+v_2)}.
\tag{12}
$$

这里使用 $E[T_2^2]=\mu_2^2+v_2$，不是用平均时间的平方代替二阶矩。分子分母的比值不等于随机比值的期望；式 (12) 是另一个明确命名的代理目标。若到达率和耗时相关，需要联合条件期望，不能直接拆乘积。

分母的 C 导数变为：

$$
\bar D_C=N(\mu_k)_C+
\lambda\mu_2(\mu_2)_C+\frac{\lambda}{2}(v_2)_C.
\tag{13}
$$

这给出了比简单加入任意“风险惩罚权重”更直接的一项改进：平方等待机制本身要求估计波动。模型的认知不确定性与运行噪声需区分；若用预测分布合并，必须说明其含义。该修正仍不等于 P90 风险模型。

## 6. 宏观缓存：状态方程必须有驻留与淘汰机制

### 6.1 定义 token 加权命中率

在同一个流量总体内，令 L 为输入 token，H 为实际可复用前缀 token：

$$
h(t)=\frac{E[H(t)]}{E[L(t)]},\qquad
\ell_u(t)=E[L-H]=(1-h(t))E[L(t)].
\tag{14}
$$

这不是“每请求命中比例的算术平均”，两者在请求长度不同时不同。式 (14) 是同一总体下的恒等关系；不需要假设 L 与命中率独立。

若要把原分式改为未缓存工作量效用，须同时统一 C、p_i、w_j、ℓ 的计数；不能只把 ℓ 改成 ℓ_u。实际已知 waiting 命中用个体状态，宏观 h 用于未观测/未来总体。

vLLM 按 block hash 查询可复用前缀，并维护引用计数和空闲块队列。空闲缓存块可按分配需求淘汰；已被请求引用的块不是任意可回收空间。[v0.23.0 设计](https://docs.vllm.ai/en/v0.23.0/design/prefix_caching/)，[版本源码](https://github.com/vllm-project/vllm/blob/v0.23.0/vllm/v1/core/kv_cache_manager.py#L196)

因此一个 h 数值无法独立确定它下一时刻的变化：同样 h，可能对应不同热点、重用距离、共享关系、容量、占用与在途 KV ready 状态。

### 6.2 一个可分析的多类近似

为构造闭合模型，先作简化：请求被分成 J 类，每类有一个可复用前缀；不同类前缀暂不重叠。类概率 q_j，前缀长度 ℓ_j，类前缀“驻留且可用”的概率 x_j∈[0,1]。令 $\bar L=E[L]$：

$$
h=\sum_j\frac{q_j\ell_j}{\bar L}x_j,\qquad
\kappa=\sum_j\frac{q_j\ell_j}{\bar L}\le1.
$$

κ 是该分类假设下可复用的最大输入份额。定义条件转移强度 a_j、e_j，单位 s⁻¹：

$$
\boxed{
\dot x_j=a_j(C,z,t)(1-x_j)-e_j(C,z,t)x_j.
}
\tag{15}
$$

a_j 表示从不可用到可用的写入/完成强度；e_j 表示从可用到不可用的正常缓存淘汰/失效强度。**这里的缓存淘汰是既有缓存生命周期，不是在 A 线引入“抢占运行请求并释放 KV”。**

对真实多块前缀，a_j 不能直接等同该类到达率：需要计算/传输完成才可用；共享、pin/refcount、容量依赖进入 z。实际块有引用时，淘汰必须受限。为避免重复计数，可用各类驻留物理空间 b_j 与未建模空间 K_other 表示必要的平均容量条件：

$$
K_{\rm other}+\sum_j b_jx_j\le K_{\rm total}.
$$

上述计数把同一物理块只计一次；请求共享前缀时必须改成块/前缀树状态。平均容量约束也不能替代逐批分配可行性检查。

固定 q_j、ℓ_j、$\bar L$ 后，式 (15) 推得：

$$
\dot h=
\sum_j\frac{q_j\ell_j}{\bar L}
[a_j(1-x_j)-e_jx_j].
\tag{16}
$$

若 FGJSQ 改变流量组成，q_j 或 $\bar L$ 随时间变化，还须加上权重变化项。即使缓存完全没变，路由到本 P 的前缀分布变化也会改变 h。

### 6.3 用一个标量方程连接后续 chunk 推导

再加同质强度假设 a_j=a、e_j=e，κ 固定，可从式 (16) 得到：

$$
\boxed{\dot h=a(C,z)(\kappa-h)-e(C,z)h.}
\tag{17}
$$

只要 a,e≥0，边界 h=0 时导数非负，h=κ 时非正，故区间 [0,κ] 保持不变。固定 C、z 且 a+e>0 时：

$$
h_\infty=\frac{\kappa a}{a+e},\qquad
h(t)=h_\infty+(h(0)-h_\infty)e^{-(a+e)t}.
\tag{18}
$$

a=e=0 时 h 保持不变。式 (17) 是本文的同质两状态闭合近似，**不是从 vLLM LRU 源码直接推出的精确方程**。它适合先研究方向、平衡点和敏感性；状态异质性重要时应回到式 (15)。

若没有机制使 chunk 改变缓存写入、ready 时刻或驻留压力，a、e 就不应被强行写成依赖 C 的函数。这样模型允许“缓存影响 chunk，而 chunk 对缓存影响很弱”的情况。

## 7. 如果“宏观面”指容量：给出另一种静态关系

用户尚未指定宏观面主要指时间演化还是容量曲线，本文分别给出两者，后续选择。

TTL/characteristic-time 对 LRU 的近似有明确文献基础，其有效性依赖独立请求过程及相应渐近条件；不直接覆盖闭环、共享多块前缀、计算后才写入的 KV 缓存。[Jiang、Nain、Towsley 原论文](https://arxiv.org/html/1707.06204)

在独立 Poisson 类请求、固定特征驻留时间 θ 的简化中：

$$
x_j(\theta)=1-e^{-r_j\theta}.
$$

把前节互不重叠的类对象大小 b_j 引入，作一个容量近似：

$$
K(\theta)=\sum_j b_j(1-e^{-r_j\theta}),\qquad
h(\theta)=\frac{\sum_j q_j\ell_j(1-e^{-r_j\theta})}{\bar L}.
$$

固定 r_j、q_j、ℓ_j、$\bar L$，且分母非零：

$$
\boxed{
\frac{dh}{dK}
=
\frac{\sum_j q_j\ell_j r_j e^{-r_j\theta}/\bar L}
{\sum_j b_j r_j e^{-r_j\theta}}.
}
\tag{19}
$$

式 (19) 是上述简化函数的求导结果。文献中的单位对象 LRU 近似不等于已经证明了这个可变大小、KV 前缀版本；它是容量敏感度的研究起点。K 表示供这些对象使用的有效驻留容量，不是直接把 64GB 显存全算成 prefix cache。

本关系不含缓存写入延迟；式 (15) 则关注状态演化。二者不能未经论证混合成一个“真实 KV 命中率定律”。

## 8. 微观成本与宏观缓存的耦合微分方程

### 8.1 从最优性条件推导，而不是凭空指定控制律

选定 F 或式 (12) 的 $\bar F$ 为研究效用，并用光滑成本代理。在某邻域假设：

1. 当前候选构成固定，状态可微；
2. 存在一个持续可跟踪的严格内点局部极大分支 C*(h,z,λ)；
3. $F_C=0$ 且 $F_{CC}<0$；可行边界在此邻域未激活。

对 $F_C(C^*(t),h(t),z(t),\lambda(t))=0$ 求时间导数：

$$
F_{CC}\dot C^*+F_{Ch}\dot h+
F_{Cz}\cdot\dot z+F_{C\lambda}\dot\lambda=0.
$$

所以：

$$
\boxed{
\dot C^*=
-\frac{F_{Ch}\dot h+F_{Cz}\cdot\dot z+F_{C\lambda}\dot\lambda}{F_{CC}}.
}
\tag{20}
$$

把其他状态冻结，并采用式 (17)，得到本轮可以继续讨论的最小耦合系统：

$$
\boxed{
\begin{aligned}
\dot h&=a(C^*)(\kappa-h)-e(C^*)h,\\
\dot C^*&=-\frac{F_{Ch}}{F_{CC}}
\left[a(C^*)(\kappa-h)-e(C^*)h\right].
\end{aligned}
}
\tag{21}
$$

式 (21) 将“缓存写入/失效改变命中率”与“成本函数的边际变化改变最优 chunk”连接起来。它跟踪既定局部最优分支，不是可从任意初值自动收敛到全局最优的算法；初始 C* 必须满足相应驻点条件。

缓存状态对 chunk 的影响由 $-F_{Ch}/F_{CC}$ 决定，不能只看 $T_h$。分子工作量、不同时间窗口和可行域都可能随缓存状态变化。

### 8.2 稳定性与失效边界

记 $g(C,h)=a(C)(\kappa-h)-e(C)h$。沿 C*(h) 的平衡点，局部渐近稳定的充分一维条件是：

$$
g_h+g_C\frac{dC^*}{dh}
=g_h-g_C\frac{F_{Ch}}{F_{CC}}<0.
\tag{22}
$$

固定 C 时式 (17) 的稳定，不自动推出联动 C 后稳定；反馈的符号和增益也重要。

下列情形需要改用其他分析：

- 最优点在 token/KV/剩余长度边界：使用约束最优/KKT 的敏感度，不能直接用式 (20)。
- 有多个极大点、$F_{CC}=0$、成员集合变化：分支可切换或导数不存在。
- C 取块对齐离散值：ODE 表达连续近似趋势，执行仍是离散候选。
- h 无法代表热点/容量状态：用向量 x 代替 h，令 $F_{Cx}\cdot\dot x$ 进入式 (20)。
- 异步在途批较深：z 必须包含已提交的承诺；当前动作不能改写已提交 batch。
- online predictor 更新产生跳变：分段分析模型版本，不能把跳变硬套为光滑时间导数。

## 9. 对当前 P-only 部署与 P90 目标的限定

### 9.1 P-only 特化不能靠填假 decode 请求完成

用户补充的原型是混合 decode/prefill 场景。当前 P 节点是否有首 token 计算、实际输出占位或其他 decode 工作，要以 runtime trace 和 patch 确定；不能把 D 节点的常驻 decode 集合直接填进 P 的 T_mix。

P-only 分支应写为 $T_P(C,\mathbf p,h,z)$，并重新定义第二种等待时间 $U_P$。若两者不同来自两个时间窗口，而不是 decode 数量，需明确窗口事件；不能因为 P 上 k=0 就自动令 $U_P=T_P$。这一步是把原模型迁移到本部署所必需的语义定义。

64k/128k 的 30ms/45ms 是 P90 TPOT 承诺，不能直接当成每个 P batch 的时间上限。P chunk 通过完成节奏影响 D，端到端影响由联合模型表达。

### 9.2 均值模型无法识别尾部分位数

一个反例即可说明：X 恒为 10；Y 以 0.8 概率为 0、以 0.2 概率为 50。二者均值都是 10，而 P90 分别为 10 和 50。因此仅凭平均批时间、平均缓存命中率及均值队列方程，不能识别 P90 TTFT。

数学目标需要保留按业务档的请求时间随机变量：

$$
\Pr(TTFT_b\le S_{F,b})\ge0.9,\qquad
\Pr(TPOT_b\le S_{P,b})\ge0.9,\quad b\in\{64k,128k\}.
\tag{23}
$$

要把式 (23) 变成可计算约束，后续必须选择请求年龄/剩余工作分布、批预测误差及阶段依赖模型。各阶段 P90 不能相加；批均值预测器也不能直接提供式 (23) 的概率。

本轮保留 F 为局部效用，并以业务尾延迟与吞吐为外部目标。下一阶段数学工作是论证二者的联系，或在明确随机模型下构造尾部风险约束；不以“网格搜索能求最大 F”替代该证明。

### 9.3 在线复杂度与数学解释是不同问题

G 个候选的时间成本为：

$$
O\!\left(G(K_{\rm feature}+K_{\rm predict}+K_{\rm feasible})\right).
$$

若每个候选评估为常数，才是 O(G)；若 lookup 为 O(log M)，则是 O(G log M)。从大 O 不能推出满足毫秒预算，也不能推出全局连续最优。离散网格穷举只保证在给定候选集及成本模型下取得最大值。

C=0 需要说明动作含义：已有 decode 可继续时，它表示本轮不加目标 prefill；纯 P 且没有其他工作时，它意味着空转，不能在目标函数中把无推进动作当成可长期重复的最优服务策略。

## 10. 接下来优先完成的数学定义

| 顺序 | 待明确内容 | 对后续推导的作用 |
| --- | --- | --- |
| M1 | T_k、T_2 分别对应哪些请求和解除等待事件；P-only 中的对应物 | 判断平方项、N 的计数及两个窗口的含义 |
| M2 | L、p、w 是逻辑输入还是未缓存工作；h 的总体及权重 | 保证单位、缓存效用与去重一致 |
| M3 | 选择可微成本族，说明哪个区间可微/凸，如何承接 predictor | 推导内点/边界最优与敏感度 |
| M4 | 选择宏观状态：时间演化 x/h，或容量曲线 K→h | 决定使用式 (15)/(17) 还是式 (19) |
| M5 | 选择请求级随机模型与 P90 风险表达 | 将单批局部效用连到真正业务目标 |
| M6 | 分析闭环 λ、FGJSQ 流量组成与缓存的反馈 | 避免把 request_rate 或本 P 到达过程当固定常数 |

本轮已完成代数和模型框架，尚未给这些未定义对象填入虚构的 910B2 参数。硬件校准属于后续实现阶段；继续讨论以上数学问题不需要等待内网实验环境恢复。

## 11. 一手依据与推导边界

- 用户提供：C* 分式及 Optimal Prefill Chunker 说明。未提供该说明的公开出处；按用户研究材料处理。
- [LightGBM 官方 Parameters / linear_tree](https://lightgbm.readthedocs.io/en/stable/Parameters.html#linear_tree)：支持常值叶/线性叶的区别，不证明本文光滑代理的精度。
- [vLLM v0.23.0 Prefix Caching 设计](https://docs.vllm.ai/en/v0.23.0/design/prefix_caching/)和 [KVCacheManager](https://github.com/vllm-project/vllm/blob/v0.23.0/vllm/v1/core/kv_cache_manager.py)：支持版本缓存机制；不直接给出命中率 ODE。
- [Jiang、Nain、Towsley，On the Convergence of the TTL Approximation for an LRU Cache under Independent Stationary Request Processes](https://arxiv.org/html/1707.06204)：支持 TTL/LRU 近似在特定假设下的分析依据；本文 KV 扩展另有简化假设。
- [微软 QoServe](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/10/QoServe_CC_final_v2.pdf)、[SLOs-Serve](https://arxiv.org/html/2504.08784v1)：支持批成本预测、动态分配与 SLO 联合研究方向；均不是式 (2)、(17)、(21) 的来源。
- [Queueing, Predictions, and LLMs](https://arxiv.org/html/2503.07545v1)：讨论预测、排队、批处理和内存约束的组合困难；不提供本自建效用的 P90 最优证明。

新增资料核查日期：2026-10-19。式 (3)–(23) 中的具体推导及模型选择由本文给出，不能引用本文链接声称已有工业部署收益。

