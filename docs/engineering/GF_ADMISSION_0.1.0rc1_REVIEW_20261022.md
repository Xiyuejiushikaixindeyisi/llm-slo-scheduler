# gf_admission 0.1.0rc1 完整交付评审（Session 2，2026-10-22）

## 1. 结论与本次范围

**当前包不通过交付安装/enforce 实验审批。** 独立包＋四个显式宿主改动的架构、FIFO/LIFO 基本规则和保留 g5 的方向成立；但本机已复现重试身份和过期 worker 清账两个 P1 问题，另有特征准备预算和残留诊断两个 P2 问题。先由编码 session 修复并形成新候选，再复评。原 rc1 包保留为历史证据，不覆盖同名包或只改 SHA 白名单。

本结论针对下述精确源码与包，不撤销已经批准的工程设计。真实镜像、原生 SHM、P/D 和 AISBench 仍须华为验证；不能以本机没有 NPU 为由阻止完成可在本机修复的事项，也不能把 mock 通过当作现场通过。

本次仅评审、复现和写文档；未修改运行代码/配置/安装器，未合并或推送 main，未修改桌面交付物，未触发华为实验。原有共享文档改动保留。

## 2. 交付身份、核验与实际测试

| 对象 | 本次核对结果 |
| --- | --- |
| g5 基准 | `3b63b00546e7a6ffb2526dafc341969cebe22359` |
| 开发提交 | `546bc7d349c1ed24fdb4acd868ad28e409eb0c11` |
| 评审时 HEAD | `0bb3e40adbecb0ddbadfe1f7400f3b44c47ec54b`，比开发提交多交付记录文档；分支仍为 `backup/20261022-init` |
| 桌面代码包 | `C:/Users/ALIENWARE/Desktop/gf-admission-0.1.0rc1-20261022.tar.gz`，1,448,273 字节 |
| 包 SHA256 | `3e97e3ebdbd930f9ec0c5892870d07f04e415a1cf96865ff309c67588d3b14e3` |
| manifest | 642 个已列文件全部通过哈希核验；source_head 为上述开发提交 |
| 工作区/包/wheel | 包内 src/scripts/configs/deploy 与对应工作区文件匹配；wheel 中 gf_admission Python 与包内源码匹配 |
| 两份桌面文档 | 运行 prompt、GUIDE 均与归档内相应文档逐字节一致；完整 hash 见核验 JSON |
| 本轮重跑 | `run_gf_runtime_tests.sh` 指向 `artifacts/build/motor-g5`：**58 passed**，退出码 0；Python 3.13.11 |
| 本轮定向复现 | **5 个观察用例**确认 R1—R4，包括 g5 off 对照；退出码 0。用例断言的是“当前缺陷确实存在”，不能计为修复后的 5 项正确性测试 |
| 开发会话记录 | 项目 79 passed、Motor 309 passed / 8 skipped、解包 58 passed。前两组本轮未全量重跑；与本轮 58 不累加成独立覆盖数量 |

评审证据：

- [交付核验 JSON](../../artifacts/gf-admission-review-20261022/artifact_audit.json)。
- [本轮 58 项结果](../../artifacts/gf-admission-review-20261022/delivered_suite_58.xml)。
- [最小复现源码](../../artifacts/gf-admission-review-20261022/test_review_rc1.py)、[完整输出](../../artifacts/gf-admission-review-20261022/reproductions.log)、[复现 JUnit](../../artifacts/gf-admission-review-20261022/reproductions.xml)。

复现使用仓库既有 FakeNative/测试夹具及真实 Motor Python 方法，没有运行真实原生 SHM 或模型。执行器会生成测试用 protobuf；没有更改所审运行源码。复现命令如下（仅在当前项目已有 CPU 测试环境运行）：

```sh
cd /home/zhangxiyue/llm-slo-scheduler/artifacts/build/motor-g5
PATH=/home/zhangxiyue/llm-slo-scheduler/.venv/bin:$PATH \
PIP_NO_INDEX=1 \
PYTHONPATH=/home/zhangxiyue/llm-slo-scheduler/src:/home/zhangxiyue/llm-slo-scheduler/tests/unit:/home/zhangxiyue/llm-slo-scheduler/tests/integration \
bash tests/run_tests.sh --serial \
  /home/zhangxiyue/llm-slo-scheduler/artifacts/gf-admission-review-20261022/test_review_rc1.py -s --color=no
```

## 3. 已确认的问题与修复验收

### R1 · P1：暂时无可用 P 后，正常 Motor 重试被旧 UNAVAILABLE 票据锁住

**触发：** 首次 P allocate 无候选/CAS 全失败；之后 P 恢复可用，Motor 按原有重试流程再次创建 attempt。

**原因与定位：**

1. [UnifiedPD](../../artifacts/build/motor-g5/motor/coordinator/router/strategies/unified_pd.py) L682—695 在分配前计算 `session._attempt_seq + 1`；只有 P 分配成功才执行 `session.new_attempt(...)`。[dispatch_session.py](../../artifacts/build/motor-g5/motor/coordinator/router/dispatch_session.py) L210—224 才递增计数。
2. `_prepare_attempt_resource` L2125—2133 收到 None 抛 RuntimeError；`_process_response_error` L637—661 允许这种错误重试，外层 L492—502/L576—579 仍使用同一 session。因此失败的首次分配和下一次正常分配，**可能使用同一个 attempt_seq**。
3. [broker.py](../../src/gf_admission/broker.py) L413—417 将无资源的普通请求终结为 UNAVAILABLE；L230—237 对相同 key 永远返回原票据。[client.py](../../src/gf_admission/client.py) L156—157 将其转成 None。恢复后的重试没有新的 native CAS。

当前 GUIDE L32 的“收到 None 即结束本 attempt，真正新 attempt 才再排队”解释不成立：这里还没有成功创建/递增 Motor attempt。不是等待现场才会发现的未知协议。

**实际对照输出：** 同样调用真实 `_create_attempt` / `_prepare_attempt_resource` / Motor client+binding，第一次资源不可用，第二次恢复：

```text
off:     second_attempt=success; session_sequence=1; native_adds=1
enforce: second_attempt=UNAVAILABLE despite available P;
         session_sequence=0; native_adds=0; broker_states={UNAVAILABLE:1}
```

**要求：** 明确区分“同一次提交的 RPC 重发”与“确定无预留后的业务再次提交”，可以使用受控 submission round 或其他等价协议。保留 logical_nonce 的一次分类/credit，不能通过删墓碑或随机换 key 来绕开结果不明的预留。相应更新 GUIDE、manifest/契约和测试。修复不应为了方便直接改 D 调度或给所有失败盲目递增 Motor attempt。

**验收：** P 不可用→恢复后，正常重试成功且只产生一次有效预留；lost enqueue/claim ACK 仍查同提交、不双 reserve；取消墓碑不能被迟到重发复活；成本/候选发生变化的再次提交不能误撞 immutable payload；重试不重新赚 credit。

### R2 · P1：worker 租约过期同时封死 query/cancel/finish，产生无法排空的 admission 残留

**触发：** 请求已 CLAIMED，worker 心跳超过租约（默认 10s）；之后原 Motor 清理路径已完成释放，或者 worker 恢复后尝试提交完成清理。

[broker.py](../../src/gf_admission/broker.py) L141—153 对过期 worker 永久拒绝；L444—455 对 query、cancel、finish 也先执行 `_worker()`。维护逻辑 L328—358 不把已确认清理的 CLAIMED 收尾；`drain` 只停止新的让行，`close` L653—660 保留 CLAIMED。新 worker 也不能接管旧 owner 的票据。

**实际复现：** CLAIMED→心跳过期→调用既有 g5 abort 成功→原生/FG 账都为零→同 owner 的 query/cancel/finish 全部被拒绝→drain 后 CLAIMED 仍为 1。

```text
rejected_ops=[query,cancel,finish]
open_fg=0, open_native=0
states={CLAIMED:1}, claimed_worker_lost=1
```

这不是已经证明 native 泄漏，而是**已清账后 admission 无法完成收尾**，会卡住“状态归零后 shutdown/rollback”的运行规程。现有文档只写人工对账，未给能安全关闭这类票据的路径。

**要求：** 将“禁止失效 worker 获得新资源”与“允许原 owner 查询、幂等完成清理”分开；或提供有明确所有权与证据校验的管理侧 reconcile。旧 epoch/owner 校验必须保留，清理操作不得让 worker 恢复 enqueue/claim 权限。不能因为超时就释放仍可能执行的 CLAIMED，也不能只见 score=0 就宣告请求结束。

**验收：** 已失活 worker 不可恢复分配；原 owner 确认完成后的清理可达、幂等；READY 到期只减一次；确认原生释放的票据能终结；真实结果未知的 CAS/CLAIMED 仍保留可见残留和人工核对步骤。正常退出、10s 控制面中断后恢复、原 owner 已退出这三类应分开测试。

### R3 · P2：特征准备时限没有覆盖候选 RPC，额外延迟可远大于 100ms

[provider.py](../../src/gf_admission/provider.py) L120—122 先 await `admission_features` RPC；到 L138—140 才对 executor future 设置 `feature_timeout_ms`。`feature_max_inflight` 检查只统计线程 future，未约束等待候选 RPC 的协程。[client.py](../../src/gf_admission/client.py) L129—142 的 request_wait 也只包住后面的排队等待。

**实际复现：** 特征预算 20ms、in-flight=2；8 个并发查询的候选 RPC 各延迟 250ms，返回空候选，完全不进入线程：

```text
elapsed_ms=250.76; metadata_rpc_peak=8; thread_futures=0
```

这不是在推测 NPU 慢：前置元数据 RPC 本身就绕过新增准备预算。真实 transport 每次超时默认 5s、可重试 3 次；连续返回 None 时此阶段可能用掉约 15s，之后才 unknown 回退。故障或 Mgmt 拥塞时会直接增加我们要优化的 TTFT。

**要求：** 从准备入口计算总 deadline，容量许可覆盖前置候选获取和线程阶段；剩余时间不足直接 unknown。仍须维持“线程实际结束才还线程许可”，不能因外层超时放开无界后台工作。取消继续传播，不把取消吞成普通 unknown。前置查询限流与线程限流可分层，但应明确预算各管什么。

**验收：** 慢/丢候选 RPC、慢 tokenizer、慢 Conductor、突发并发四种情况均在配置总准备期限附近返回 unknown（允许调度误差）；无超额后台任务；请求本身取消时不继续正常入队。文档中的 100ms 应与真实执行边界一致。

### R4 · P2：残留样本先截断后过滤，可能返回空列表而实际存在 CLAIMED/CLEANUP

[broker.py](../../src/gf_admission/broker.py) L614—623 先取最早 `changes_batch` 个 ticket，再过滤残留状态。默认最早 32 个若已终结，后面的真实残留将不出现在样本中，可能持续到这些墓碑过期。

**实际复现：** 测试 `changes_batch=10`，先完成 10 条，再保留一条 CLAIMED：

```text
states={CLOSED:10, CLAIMED:1}; residual_sample=[]
```

聚合 `states` 并未被误报成零，但华为仅回传单份 Markdown 时会缺失定位/清理所需 key、reservation_id。

**要求与验收：** 先筛残留，再限量；给 total/truncated 或游标，不能把“空样本”当已排空。覆盖前部全墓碑、超过一页残留以及 CLEANUP_PENDING；避免改成无界返回所有请求。

## 4. 压力阈值、分类预算与晋升规则评审

这些参数是显式实验起点，不能通过逻辑测试确定最优值。下表的风险用于解释机制与设计短验证，不要求重开流量建模。

| 项目 | 源码实际语义 | 结论与适用边界 |
| --- | --- | --- |
| `release_threshold=0` | 仅 tail 使用 guard；FG rank/recompute 后、native CAS 前、同锁检查选中 P 的 score；每次预留后重算，fallback 也过 guard | 取分点和原子性正确。0 是极保守门限，**不等于物理 P 空闲**；不能命名为准确 empty-P 判定，也不是 8192 batch token 门限 |
| normal FIFO | 普通请求不加压力阈值；按 normal 队首走 g5 资源选择 | 首版只控制少量让行请求，仍可把大量普通请求发进 P waiting；无法重排已经进入引擎的工作 |
| quota `20/1`、credit cap=2 | 每个 logical nonce 一次到达补额，首次分类扣额；取消/派发/晋升不退款；cap 限制闲期积累 | 保留原型主要规则并限制突发积额；不是每 20 条必须牺牲一条，也不是运行中的让行个数上限；P90 不推出应牺牲 10% |
| 分类 `0.8*历史max`、`1.5*历史min` | 正成本全程 min/max，两个阈值都满足且其他条件通过才 tail；unknown/zero 有单独路径 | 规则有原型来源。同质请求常没有候选；历史离群值可能长期影响分类，先记录影响，不在首轮擅改滑窗算法 |
| S=16、V=2,097,152 | tail 即时条数及冻结成本和；离队/取消/晋升释放 S/V；不退款 credit | 是固定上限，不是已经实现的自适应预算控制器；V 不等于 NPU KV 容量，也不保证最终派发 P 的实际计算量 |
| `max_tail_wait_ms=1000` | 最老 tail 到龄后 append 普通 FIFO 尾部，protected 防止再降级；scan 有界 | 固定年龄下 OrderedDict 足够，省去 heap 合理；到龄是晋升，**不是请求完成或总等待硬上限** |
| `event_fresh_ms=1000` | 对所有尚未 FG-release 的 reservation 所在 P 检查最近有效事件；任一过期即可让全局压力无效 | 只认可 g5 matched 事件是正确方向；但这是全局保守条件，不只是选中 P 的条件。长 batch、事件间隔或新 P 未出首事件可让 tail 提前晋升 |
| 压力失效 / drain | 停止新让行、已有 tail 有界晋升普通；drain 继续普通派发 | 依照设计降级；不是停接入开关，也不等于引擎工作排空 |
| scan=4 | 最新最多 K 个 tail，仅因 native 候选资格不可用而跳过；压力不满足停止 pump | 保持“可执行资格内 LIFO”，没有暗中改成短作业优先 |
| `beta_cpu=beta_disk=1` | 三层为互斥覆盖时，`uncached + CPU + Disk = L - NPU_hit`，再取候选最小成本 | 是分类 proxy，不是精确计算量/加载时间或逐请求 TTFT；缺字段不能当零命中，不改原 FG body/4 初值 |

压力源见 [policy.py](../../src/fgjsq/policy.py) L39—66、[broker.py](../../src/gf_admission/broker.py) L178—195；成本见 [features.py](../../src/gf_admission/features.py) 与 provider。原 g5 score 为 `committed_tokens * (ceil(unreleased_count / max_seqs) + 1) / 2`。committed 由事件和预测衰减估计，整数取整等情况下 score=0 仍不证明设备上没有请求。

**这套默认值的关键交互：** P 持续有正 score 时 tail 不走 LIFO 释放；到 1s 或全局事件陈旧时它会转普通。可能出现“确实进入过 tail，但主要效果只是等了约 1s 后走 FIFO”，并未发挥 LIFO 将等待集中于少数老请求的机制。队列里始终只有一条 tail 时，也没有 LIFO 与 FIFO 的相对顺序差异。上述是代码可推导的条件，不是已测得现场一定无效。

因此：默认值可用于**修复后的工程短验证**，暂不背书为有效性实验参数。短验证要能区分正常低压出 LIFO、到龄晋升、事件陈旧晋升以及无可分类请求。看不到可利用的竞争时，不盲目调高 quota 或延长等待以制造收益；先说明当前场景的能力边界。

## 5. 故障清账、接入与兼容性判断

| 检查项 | 当前证据与判定 |
| --- | --- |
| 独立包/宿主改动 | wheel 仅 gf_admission，无 vLLM entrypoint；4 个既有文件为 adapter bindings/service、Motor scheduler_client/server；范围符合批准方案 |
| P/D 边界 | P allocate 前接入；真实 Motor `_create_attempt` 的 HANDOFF 先 P、后 D 控制流已有测试；P scheduler、predictor/reporter、D 引擎与 D 路由未改。测试不是完整 P/D 推理证据 |
| 预留所有权 | QUEUED 不 reserve；READY 同时持 P native/FG 两账且有租约；claim 后才交给 worker；CLAIMED 不因 READY 到期释放，方向正确 |
| 异步协议 | 每 worker 一个 WaitHub；同锁 revision+event；wait 在锁外；真实 ZMQ/msgpack 和独立子进程已有覆盖。现有集成请求主要 cost=None，并不能证明真实 tail→READY→claim 全链已验证 |
| 有效事件 | service L169—205 校验 reservation、coordinator/engine epoch、instance/endpoint/generation、attempt、seq 与数值；只有 matched 调 notify。HTTP200、received 增长均不能替代 matched |
| 双账释放 | FG/native 各自幂等释放；取消复用 g5 abort；CAS 结果不明保存 uncertain 并停止新派发，而不是猜测减账。此保守边界应保留 |
| CLEANUP_PENDING | 有界重试，失败保留可见残留；不是无限自动恢复。必须提供具体现场对账/停机恢复步骤，R2/R4 修复后再验证 |
| 源码兼容 | runtime contract、before/after hash、protected 文件校验有价值；NodeManager fix1、engine_files.json observe-only，不覆盖现场修复。未知 hash 不可绕过 |
| 真实镜像/ABI | **未确认**。目标仍是冻结 g5 镜像 `vllm-ascend:g5-g4base-motor-20261021-r1`，不是早期 rc1 镜像。本地 Python 3.13.11 测试不替代镜像 Python 3.12、原生 schema-4 .so、vLLM/Ascend 集成验证 |
| 安装回退 | 原子替换单文件＋全量预检/备份/journal，要求进程停止；非跨文件原子事务。未知后续修改拒绝覆盖是正确的；本机安装回退测试通过，不等同真实容器回退已过 |
| 关停顺序 | 先停接入、排空仍运行的完整 HTTP/P/D 请求，再 drain/核对票据与两账、停 Coordinator、切 off/rollback。两本 **P** 账为零不能单独证明 D/E2E 已结束 |

保留的故障边界：worker 真退出后的 CLAIMED、Mgmt 崩溃、native CAS 结果未知，不要求首版实现分布式 HA；要求的是**明确哪些结果可自动收尾、哪些必须核对、如何有证据地恢复**。不得把清零内存计数当作执行完成或回退验证。

性能实现也应准确描述：OrderedDict 增删是平均 O(1)，但 broker maintenance、查同 logical 活动票据、revision 取变化、FG recompute/prune 会扫描记录。`pump_ms=2` 只在派发循环边界检查，不含所有维护/晋升成本，也不能中断单次 CAS/同步日志；目前不具有“共享锁最多占 2ms”的保证。暂不为此重写结构，短验证记录控制面时延/事件滞后，证据需要时再优化。

## 6. 观测与交付材料需要补齐的最小内容

现有累计 `tail_enqueued/promoted/pressure_deferred/reserved` 无法可靠区分**真的 LIFO 派发**与到龄/陈旧事件后走普通队列；`_change` 日志只有 key/state/revision/elapsed，晋升时也没有逐请求原因日志。这会妨碍本轮最重要的机制归因。

建议下一候选加入小而有界的结构化观测，至少：

- 派发来源 `normal / protected / tail`，晋升原因 `age / stale_pressure / drain`，各自累计计数；不能混用“进入过 tail”和“以 tail 身份出队”。
- 能通过少量逐请求状态日志关联分类、晋升和派发；记录候选 P、取分点的 score/门限及压力有效性原因，避免输出请求正文/token 数组。
- 判断是否确实存在至少两条可比较的 tail、是否发生 LIFO 越过；少量有界轨迹即可，不建立全量新采集系统。
- feature unknown 分原因、总准备耗时/timeout；每 P 有效 matched 的新鲜度；排空后的 states/open_native/open_fg 及残留样本完整性。

`decision_*` 当前在每次新 ticket 增加，`logical_arrivals` 按 nonce 增加；有业务重试时不能直接把前者当唯一请求分类比例。修复 R1 时顺便明确指标分母。

更新 GUIDE 中 R1 的错误说明、feature timeout 的边界，以及“score=0 等于 empty P”的措辞。华为 prompt 继续保留单份 Markdown 回传、内嵌关键源码/diff/证据的要求；不要扩大为重做环境/流量调研。短验证场景应给可执行步骤、观察字段和通过条件，而不只是“检查取消”。

## 7. 新候选的交付与华为升阶条件

### 7.1 编码 session 先完成

1. 关闭 R1/R2；修复 R3/R4；将本报告复现改成断言正确行为的回归测试，并覆盖对应丢 ACK/取消/过期重试边界。保持原有 58 项与相关 Motor 回归通过。
2. 补充第 6 节的最小机制观测；增加**确实入 tail** 的 broker→真实 IPC→worker claim→取消/释放集成场景，SHM 仍可本机 mock，明确界限。
3. 更新 guide/prompt/状态矩阵；生成新版本/新 SHA 的包。原 rc1 不改写；在 WSL 校验完后按项目约定移动到 Windows 桌面。
4. 提供修复提交、变更文件、测试结果、包 SHA 和未覆盖项，Session 2 核查关闭问题后，才批准发往现场安装和短验证。本轮不合入 main。

### 7.2 华为短验证通过条件（不是本机声称已经通过）

| 顺序 | 最小场景 | 必须嵌入回传正文的证据 |
| --- | --- | --- |
| A 镜像/安装 | 原镜像 Python 环境只读 check；停接入/清账后装新候选，先 off | image digest、Python/实际 import 路径、四文件 before/after、受保护文件指纹、observe-only 两项、命令与退出码；不升级 NPU 栈 |
| B off/shadow | 原 g5 小请求流式完成；shadow 只观察 | P/D 配置未变、stream/E2E 成功、原 FG/native 正常闭合；不能以 shadow 快慢替代 enforce 测试 |
| C 真实 SHM/P/D | 现场自身 schema-4 原生 .so；短的确定性排队场景 | QUEUED 无 P/D 预留；READY 有且仅有一份 P 双账；claim 后 P 发出，HANDOFF 后才分配 D；完整 HTTP/P/D 收尾 |
| D 分类/有效事件 | tokenizer/template、Conductor 三层已知与缺失；合法及 stale/错误身份事件 | known/unknown 原因；合法 matched 更新压力；重复/错 epoch/错 generation 不更新新鲜度；真实 tail 和各晋升/释放原因 |
| E 取消/重试 | queued 取消、READY 取消、claim 与取消竞争、lost ACK、P 暂时无资源后恢复 | 单份预留、单次释放、无迟到复活；R1 对应实际重试能成功；失败和取消也计入报告 |
| F 故障/恢复 | worker 心跳中断后恢复、worker 退出、generation 变化；状态未知则停升阶 | R2 对应清理可达；旧代不扣新代；不按租约强减执行中请求；已确认清理的账和票据归零；未知残留有具体安全处置 |
| G 回退 | 停接入并等完整 E2E/P/D 结束→drain→票据/双账核对→停 Coordinator→off/rollback→重启 | 回退前后文件 hash、无原生/票据/task/provider 残留、原 g5 小请求成功；失败时不可声称可回退 |

短验证可以使用明确标注的合成状态/样本触发协议边界；这些结果仅用于工程验收，不能冒充生产流量收益。未知 KV=100%、无有效事件、原生/取消/回退不通过时停止升阶。只有过年龄保护的请求而无真实 LIFO 顺序竞争时，不把一次 TTFT 变化归因为 LIFO。

### 7.3 进入收益实验后

先单个已知规格点 off/enforce 配对、重复，固定 g5/数据/输出长度/warmup/并发与完整配置；B16 始终是整个 3P3D。正式口径为 AISBench 客户端计时、全体请求 P90 TTFT、P95 辅助、吞吐和 P90 TPOT，同时报告失败/取消、排空成本与让行组最老等待。不能删尾部样本或只展示普通组改善。

安全性和机制能被观测不等于收益成立；收益不稳定时回到分类、出队门限、驻留预算逐项讨论，不同时改 FG 公式、引擎 chunk 或 D。本轮没有提出新的流量采集前置条件。

## 8. 阅读入口与下轮衔接

- 本报告优先于 rc1 GUIDE 中关于“已足以交付”的推断；原 GUIDE/状态报告保留为被审版本证据。
- [实现状态](GF_ADMISSION_IMPLEMENTATION_STATUS.md)、[运行指南](GF_ADMISSION_RUNTIME_GUIDE.md)、[桌面交付记录](GF_ADMISSION_RUNTIME_DELIVERY_20261022.md)、[华为 prompt](HUAWEI_AGENT_PROMPT_GF_RUNTIME.md)。
- [批准的设计](../admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md)、[g5 冻结交接](G5_FROZEN_BASELINE_HANDOVER.md)。

本次给编码 session 的核心结论：保留架构与算法基线，先修复交易身份、清账可达性与准备预算，补齐可归因的观测；不需要重写引擎或重新建模流量。
