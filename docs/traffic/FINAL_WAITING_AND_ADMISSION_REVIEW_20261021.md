# 最终等待与入场证据报告：接收、核对和采用范围

日期：2026-10-21。**集中调研到此结束。** 本文只核对回传材料与已有本地实现，不新增环境调查、采集或实验。下一阶段入口为[双等待队列讨论底稿](../admission/DUAL_WAITING_QUEUE_DISCUSSION_BRIEF.md)。

## 1. 原件及证据边界

- [本次原始报告R2](FINAL_WAITING_AND_ADMISSION_EVIDENCE_20261021.original.md)，SHA256：`29a964d3342d94a72e8c9f73cfa2783a67610e82e10e4128d91b6729a28b301a`。用户附件按字节保存，不就地修改其结论。
- [上一份流量原始报告R1](CLUSTER_FLOW_PROFILE_REPORT_20260924.original.md)及[核对](CLUSTER_FLOW_PROFILE_ANALYSIS_20260924.md)。两份报告均作为流量建模原始资料留存于docs/traffic，分析意见与原件分开。
- [接收清单](../../evidence/manifests/final_waiting_admission_report_20261021.json)记录完整hash和本机核对的源码hash。
- R2正文包含汇总表、部分源码片段和gauge复算描述；多数直方图原始bucket、计算脚本和逐请求记录仍未嵌入，来源hash大多只有前缀。它可作为实验机调研报告引用，不能把全部E编号等同于本机可独立重算的原始数据。
- 本机已有源码的hash前缀与R2的policy、service、snapshot及vLLM scheduler/stats/loggers相符；前缀吻合不等同完整远端hash验证，更不证明历史run实际加载了相同文件。没有为补齐这些缺项发起新的调研。

## 2. 本次新增、可采用的事实

### 2.1 实验总体得到更清楚的区分

| 材料 | 本次采用的身份 | 使用范围 |
| --- | --- | --- |
| R1九字段生产CSV | 同规格多UUID导出，选定UUID的5,549条生产记录；max_num_seqs=16是用户背景 | 输入/缓存异质性，延迟单位与输出语义仍未决 |
| EXP_10.9 | 报告记载为同源生产trace的5,549条原速开环重放，g2 proxy，N=heap、F=FGJSQ | 历史路由对照和聚合等待现象；不能代表当前Motor性能 |
| EXP_10.12 | g2栈的AISBench闭环；66,158/126,000输入、B扫描、PT=1200 | 历史压力场景；不是当前生产流量分布 |
| EXP_10.14_TRACE | 上两项的二次分析，不是独立新增采集 | 口径整理、已有数值复核；不能计作一次独立重复实验 |
| g5/EXP_10.20_MOTOR | FGJSQ＋predictor＋Motor链路与smoke；报告截止时无成功性能压测，max_num_seqs=24 | 现有接入与生命周期契约；不接受跨世代性能外推 |

R2把S4写成“原生proxy、非FGJSQ”比此前证据更强。本轮仍采用`native_proxy_unspecified_policy`：原生proxy字样本身不决定路由算法。R1的事后cached也不能改称“入场前流量特征”。

### 2.2 历史FGJSQ改善与剩余等待可以同时存在

以下均为R2 §3.1回传值，本机未重算原始样本：

| 指标 | heap N | FGJSQ F | 采用结论 |
| --- | --- | --- | --- |
| 客户端TTFT P90 | 16.859s | 15.444s | 此历史对照F低1.415s，约8.39%；不外推为稳定收益或g5收益 |
| P池首次排队直方图P90 | 8.746s | 7.811s | 此历史对照F低0.935s，约10.69%，同时仍有明显等待尾部 |
| P池首次排队P50/P95/P99 | 0.904/10.887/14.936s | 0.285/9.721/14.752s | 低中位数与较高尾部并存，不能由此识别具体哪类请求受阻 |
| P池waiting>0快照 | 144/240=60.0% | 126/240=52.5% | 三P池化快照比例，不能换成等待请求占比或真实时间占比 |

报告的池化方法是各P最近样本容差≤2.75s、任一缺样则丢弃。保留该抽样口径；不能说三P严格同时观测，也不能从平均分位相近证明路由已最优。没有完成吞吐和重复运行误差，不能宣称吞吐保持或统计显著。

### 2.3 两个闭环场景应区分采用

- **126k_B16**：报告引擎首次排队P50约20—30s，三P waiting合计的10s稳态窗均值6.94、最大8、这些窗口非零100%。较长的首次调度前等待值得研究；它是否由可执行请求的顺序而非资源/远端KV等因素主导，仍不能从汇总值独立确定。
- 原报告5.87的waiting均值未复现；本轮引用6.94时必须带“10s稳态窗、三P合计”的口径。6.79/6.86/6.99属于其他窗口/抽样，不混成同一估计。
- **66k_B16**：报告引擎首次排队P50≈0.5s、P90≈0.8s，而模型化wait_est P50=4.673s、TTFT P50=11.17s。只支持“首次入场队列指标较小，而客户端仍有更大延迟/模型残差”的对照，**不采用‘已定位约4.2s在running’**。

这使得“首次入场等待明显的场景”和“首次入场指标较小、其他延迟来源未决的场景”成为有用对照。两者不需要再拟合流量模型才能开始机制讨论。

## 3. 原报告中不能直接采用的推断

| 原报告位置/说法 | 核对意见与替代表述 |
| --- | --- |
| §2.1：waitproxy是下包络，真实等待≥它 | 不成立。TTFT减桶内P10是残差代理，不是数学下界。即便真实等待为0，服务/缓存/批组成差异也可使残差为正；之后不再引用“下界” |
| §3.3/§6：66k_B16约4.2s位于running | 与§5承认不可逐请求分解矛盾。不同分位数不能相减作分段，prefill_est来自同一个模型也不是独立验证；只保留阶段定位未决 |
| §3.3/§6：开环ρ≈1可作工作假设 | 不采用为默认场景。非零waiting、无局部突发和17.2K群体token/s没有给服务容量；把它改名“假设”也不会补充证据，更非算法必须依赖的前提 |
| §6：queue P50和P99差异证明长短请求同时竞争 | 不成立。边际分布没有时间、请求类型和P实例关联，不能还原同一轮候选集合；异质性与竞争机会必须分开 |
| §6：waiting长则入场重排必然覆盖、D queue小则D无关 | 首次SCHEDULED前可包含blocked/KV/资源等待；不全是可通过排序消除的等待。D首次排队小不能说明D计算/传输/首流式响应无贡献 |
| §6：GF无队列，所以等待只在P | 所见代码未实现目标双等待队列，不等于GF不存在RPC、HTTP、连接池、原生配额或流式转发等待。只能描述已核对的主动排队结构 |
| §6：P端已有全部waiting候选的精确cache与成本 | 只证明被检查候选有查询路径；不等于整条waiting队列已拥有可靠、无开销的命中快照，也不等于未来执行时的命中不变 |
| §6：5% retention与首chunk释放是最低进展保障 | 错误。前者限制账本预测衰减，后者终止相应负载记录；两者都不为任何请求分配token、调度次数或等待期限 |
| §6：FG账本waiting项就是让行队列存量 | 仅是未调度剩余工作量项，包含已经running请求的后续未调度部分；不能直接对应一个新建的低优先级队列 |
| §6：历史waitproxy最大约30s可作为最长额外等待尺度 | 只能作历史残差量级，不能导出安全让行额度。27s TTFT SLO更不是27s纯等待预算 |
| §6：batch预测毫秒可直接累计成让行预算 | 需要另行定义决策层映射和不确定性；现有标签含主机/异步流水线影响，不是可相加的逐请求剩余服务时间 |
| §3.2/§5：Erlang-B对照差异证明某种闭环机制 | Erlang-B损失概率与“等待>1s比例”不是同一事件；模型和测量对象均不同，差异不能单独定位原因。此处不再继续排队论拟合 |

报告中“多UUID矛盾待外网裁定”“completion≥8192与预算语义冲突待裁定”两句也不保留：原SQL没筛UUID，8192明确是每轮预算，这两点无须继续调查。仍未解决的是completion本身含义，不是它与8192的大小关系。

## 4. 与双队列直接相关的代码核对

以下为本机既有文件有限核对；运行世代仍按第1节区分。

### 4.1 首次排队口径与连续调度边界

[stats.py](../../upstream/vllm-v0.23.0/vllm/v1/metrics/stats.py)第420—444行保存首次SCHEDULED并计算`scheduled_ts - queued_ts`；[loggers.py](../../upstream/vllm-v0.23.0/vllm/v1/metrics/loggers.py)第1179—1187行在finished_requests中observe。定义也可核对[固定commit源码](https://github.com/vllm-project/vllm/blob/0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665/vllm/v1/metrics/stats.py#L436)。

它不包含GF持有请求到引擎入队之前的等待，也不测量首次SCHEDULED之后的所有停顿。结束时才观测意味着窗口增量的总体是本窗口被记录结束的请求，不能自动视为窗口内到达的全部请求。

已有调度骨架为running-first、waiting使用剩余token/序列/KV资源；chunked prefill允许队头按剩余预算分块入场，但仍有资源失败、blocked和异步已提交工作的边界。不是“所有长请求都必须整条算完才准下一条进”，也不是“每个chunk结束都会重新公平选择所有请求”。

### 4.2 retention保护的是估计负载，不是请求进展

本机[policy.py](../../src/fgjsq/policy.py)第39—47行与R2片段一致：

```python
if p is None or p.prompt <= 0:
    return request.original
waiting = request.original * p.remaining / p.prompt
running = request.original * p.scheduled / p.prompt
# retention只限制scheduled部分的预测衰减；没有调度/唤醒操作。
```

[snapshot.py](../../src/fgjsq/snapshot.py)第17—31行只遍历本轮scheduled请求；remaining取计划更新后的`num_tokens - num_computed_tokens`。尚未首次入场的请求通常无批事件，维持原始预留负载；已经running的请求也可能有remaining>0。因此双队列改变入场时机后，会反馈FG路由排序，但不能把FG原有账本当作新让行队列的完整统计。

“延后→原始负载保留更久→后续路由可能更少选该P”是有条件的反馈路径，不是绝对排序保证，也不是可随意打折隐藏负担的理由。snapshot里的计划computed也不能直接当作设备已执行token。

### 4.3 释放与预测器契约仍需保留

- [service.py](../../src/motor_adapter/service.py)第76—87行分别处理native与FG释放并保留幂等状态。
- [body_observer.py](../../src/motor_adapter/body_observer.py)的FirstBodyObserver响应D首个非空body bytes；这与P首次入场、客户端首有效内容均不是同一事件。不得为了让行而提前把存量从账本释放。
- [scheduler_with_predictor.py](../../src/slo_patch/slo/scheduler_with_predictor.py)第66行拒绝非零旧SLO开关。未来双队列不能以“打开旧SLO”冒充实现，需要明确独立接口/开关后再审批。
- predictor保持batch级主机观察耗时定位。legacy cache_hit_rate不是单请求APC命中；R2的“纯函数/sub-ms”未附独立性能测量，只采用已有可调用接口事实，不保证新增大量查询的开销。
- 实际P继承/异步链以[g5研究上下文](../engineering/FGJSQ_REPRODUCTION_PLAN.md)为约束。仅摘vLLM核心schedule不能覆盖Ascend重写的全部分支。

## 5. 调研闭合后的使用决定

保留两份报告提供的三类材料：成本异质性、历史首次调度前等待现象、FGJSQ/predictor接入契约。保留未知：具体请求在哪段受阻、实际在线命中可见性、候选并发竞争、容量及g5性能。**不再要求用户补数据，也不把这些未知变成下一轮流量调研任务。**

这些证据足以提出可检验的算法假设，但不证明双队列收益。下一轮围绕[合并讨论底稿](../admission/DUAL_WAITING_QUEUE_DISCUSSION_BRIEF.md)讨论机制、分类、预算和位置；不实现waiting重排、running/KV抢占或动态chunk，不启动实验。
