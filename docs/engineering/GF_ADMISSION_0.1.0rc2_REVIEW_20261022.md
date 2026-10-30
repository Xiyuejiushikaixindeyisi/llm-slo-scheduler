# gf_admission 0.1.0rc2 复评与现场放行记录

日期：2026-10-22。评审：Session 2（设计与评审会话）。

## 1. 结论

**本地交付评审通过，可以将下面精确 SHA 的 rc2 代码包、prompt 与本记录交给华为实验机，启动现场验证和既定实验流程。** rc1 的 R1—R4 在 rc2 中已关闭，本轮没有发现新的阻断交付问题。

此次通过覆盖源码与交付一致性、已批准算法的实现、本地可验证的事务/取消/预算/IPC/安装回退行为。实际镜像 Python 3.12、原生 SHM、完整 P/D 与性能由华为验证，不能将本结论写成这些项目已经通过。现场按现有门槛推进；无需为了已经关闭的四项缺陷再次等待本机编码，也不重开流量建模。

允许推进顺序：**off/shadow 兼容验证 → 复用已有证据或必要短探测形成有效 H/L → enforce 短验证（含真实取消、清账、回退）→ 冻结参数并完成通知演练 → 正式 AISBench 配对实验。** 相互独立的兼容验证和压力探测可交错执行；enforce 模板的 null 阈值不能直接启用。

本轮没有修改运行代码、配置、原代码包或原执行 prompt，没有合并/推送 main，没有替华为启动服务或实验。本记录可随包投递。

## 2. 本次批准的版本与实际核验

| 项目 | 核验结果 |
| --- | --- |
| 基准 g5 | `3b63b00546e7a6ffb2526dafc341969cebe22359` |
| 实现提交 | `75c5e519195b55ce314fc00bf81b068f382e9cb1` |
| 交付记录提交/评审时 HEAD | `8171c2da61a6fcfb3007e2fb30be57ce21b37337` |
| 包 | `gf-admission-0.1.0rc2-20261022.tar.gz`，1,575,686 字节 |
| **批准的包 SHA256** | **`b23cee6b81d6f4f8b87b1e6cfd6fc28e7e8ed4bab3512c4ab6a4a7cecd1b0121`** |
| 包内校验 | 685 个 manifest 文件全部匹配；source_head 对应实现提交 |
| 内容一致性 | 包内运行源码/脚本/配置/实验计划与工作区对应文件匹配；wheel 中 gf_admission 文件与包内源码匹配 |
| 桌面随附文档 | rc2 prompt、GUIDE、修复报告与包内对应文件逐字节匹配 |
| 本轮独立解包测试 | 清除外部 PYTHONPATH 和 GF_TEST_MOTOR_ROOT 后，执行随包脚本：**75 passed，退出码 0**；Python 3.13.11 |
| 本轮补充测试 | 对解包源码追加评审用例：**2 passed，退出码 0**；新提交轮次丢 ACK、候选约束与陈旧晋升 |
| 开发会话测试记录 | 项目 96 passed；Motor 309 passed / 8 skipped；本轮未重复运行全部两组，不与 75 累加为独立覆盖数量 |

八项跳过仍包括缺原生库的七项与原 Motor 一项既有 skip。本次 75 项真实 ZMQ/子进程测试使用 **FakeNative**，不改称原生 CAS/NPU 测试。

本机证据入口：

- [交付核验 JSON](../../artifacts/gf-admission-rc2-review-20261022/artifact_audit.json)。
- [独立解包测试日志](../../artifacts/gf-admission-rc2-review-20261022/extracted_tests.log)、[75 项 XML](../../artifacts/gf-admission-rc2-review-20261022/delivered_suite_75.xml)。
- [补充用例源码](../../artifacts/gf-admission-rc2-review-20261022/test_review_rc2.py)、[补充测试日志](../../artifacts/gf-admission-rc2-review-20261022/additional_tests.log)、[XML](../../artifacts/gf-admission-rc2-review-20261022/additional_tests.xml)。

上述文件的完整内容不要求华为读取；关键判定与结果已嵌入下文。代码来源路径/行号针对实现提交，仅用于核查。

## 3. rc1 四项问题的关闭依据

| 原问题 | rc2 源码核对与回归 | 判定 |
| --- | --- | --- |
| R1：同 Motor attempt 无资源后重试卡住 | client 仅收到权威 UNAVAILABLE 才增加 `submission_round`；broker 要求紧邻上一轮仍为 UNAVAILABLE、同 owner 且没有 service reservation。新 round 刷新 payload，但沿用 logical 分类/credit。未知 ACK 继续查同 key；实际 Motor off/enforce 恢复资源后都成功 | **关闭** |
| R2：过期 worker 无法完成清理 | broker 对 query/cancel/finish 允许过期原 owner 操作，不续租；enqueue/claim 仍拒绝。失联 CLAIMED 仅在同记录明确 native/FG 均已释放且非 uncertain 时关闭；没有按心跳超时强减账 | **关闭** |
| R3：100ms 未覆盖 metadata RPC | provider 在入口取得容量、启动总 deadline；metadata 与 executor 共用剩余时间。进入线程后由实际 future 完成回收许可，超时不提前归还；取消传播 | **关闭** |
| R4：残留样本被前部墓碑遮挡 | 先筛 CLAIMED/CLEANUP 再限量，并返回 residual_total / residual_truncated。前部全为终态及超出样本容量的回归通过 | **关闭** |

关键定位：`src/gf_admission/client.py` L54—61、L123—183；`broker.py` L160—174、L274—311、L375—395、L565—575、L636—675、L753—788；`provider.py` L104—169。

迟到取消会覆盖同一 Motor attempt 的后续提交轮次，避免旧轮取消后新轮留下预留；跨 owner 的取消被拒绝。submission round 没有改写引擎的 attempt_seq 或事件 schema，D 路由保持原契约。

本轮补充用例的实际输出：

```text
ROUND_ACK_RECOVERY:
  key=review:1:s1
  native_adds=1
  logical_arrivals=1
  submissions=2

PRESSURE_SCOPE:
  unrestricted=normal
  targeted=pressure tail
  promoted_stale=1
```

第一例是首次无资源、第二轮成功但丢 ACK：通过查询恢复同一份预留，未第三次分配，finish 后 native 余额为零且 client rounds 回收。第二例在一台 P 高压、另一台低压时，无约束请求正常路由；限定到高压 P 的同成本请求可进入 tail，事件陈旧后有保护地晋升，最终清账为零。

## 4. 新增统一高压规则与预算评审

依据已批准的 `docs/admission/GF_PRESSURE_ADMISSION_REVISION_20261022.md`，本轮不是仅审 rc1 补丁，也审新增统一规则：

```text
known_positive_cost AND fresh_pressure
AND (long_cost OR min_eligible_P_score >= H)
AND credit/S/V available AND not protected/draining
```

normal FIFO 优先；tail 只能在实际候选 P 的 `score <= L` 时派发，`0 < L < H`。分类一次，成功预留后更新账本；CAS 切换候选重新检查门限。

核对结论：

- `_minimum_pressure(payload)` 根据请求 target/能力/健康候选列表调用既有 FG rank/recompute，再取最低 score。没有使用全池最大值替代请求候选最低值；一台高压而另一台低压时不会单因高压分支强制让行。
- 长成本和高压力是 OR；同时成立仅一次分类扣额，分别有 cost/pressure/both 原因。unknown、zero、无有效压力不会为了凑 tail 而被伪装成高成本。
- 同一 logical 请求的业务重试不重新赚取/消耗 credit；当前成本、S/V、protected 和压力有效性仍检查。取消和晋升释放存量，不退还分类 credit。
- 默认候选为 quota 1/20、credit cap 2、tail 数量 2、驻留 5s，成本上限 2,097,152；这些是工程/实验起点。H/L 为静态待探测超参数，enforce null 模板会被配置校验拒绝，shadow 的 2/1 不是正式阈值。
- 年龄保护、stale pressure、drain 晋升分别计数；normal/protected/tail 派发来源分开。有界事件环替代持锁文件日志，sequence 缺口与覆盖计数说明观测可能不完整。
- IPC 集成已覆盖：对三台模拟 P 建账、合法匹配事件更新压力、两条同成本 tail、新 tail 先 READY/claim、旧 tail 取消，最后 **native adds=subs=7，open_native=open_fg=0**。通信为真实 Motor DEALER/ROUTER/msgpack，计算与 SHM 仍为替身。

关键定位：`classifier.py` L65—105；`broker.py` L203—226、L291—324、L427—542；`runtime_config.py` L63—72；`tests/integration/test_admission_runtime.py` L182—260。

**需要保留的解释边界：**

1. 全局事件 freshness 仍为保守条件：任一尚未 FG-release 的 P 事件陈旧，可停止新增 tail 并触发晋升。应依据实际 matched 事件间隔选择，不机械使用 1s。
2. FG score 是估计工作量及未释放数的函数，不是设备忙闲、GPU/NPU KV 容量或预测 TTFT；8192 不能直接成为 H/L。阈值间隔也不是全体 P 的硬负载上限，普通请求仍走原 g5。
3. `lifo_overtake_dispatches` 表示派发时存在更旧且路由/压力合格的候选，未对旧请求实际做一次 native CAS；不把它说成旧请求必然能在硬件上执行的证明。
4. GF 限制实际入场并发与 LIFO 越序是两个可研究的效果。没有越序但存在入场调节，可以分析其收益/代价，不再以“没有 LIFO 越序”自动否定实验；仍不能把作用名称混用。
5. 5s 是晋升期限，不是总等待或 E2E 截止；5s→10s 比较只能在短验证阶段注明依据后进行。正式结果出来后不能为每个 B 偷改参数。

这些边界已在交付材料中显式说明，不作为再阻断本地交付的理由。

## 5. 故障、兼容、回退与辅助工具

**兼容范围。** 四个既有文件仍为 adapter bindings/service、Motor scheduler_client/server。rc2 相对 rc1 的 binding 变化为 admission schema 2；新 schema 不更改引擎事件 schema 1。运行 contract/安装器仍拒绝未知文件指纹；NodeManager fix1、engine_files.json 只观察保留。未改变 FG 公式、predictor 特征/训练标签、P FCFS/running-first/共享预算或 D 策略。

**故障边界。** READY 短租约与 CLAIMED 所有权分开；worker 过期不导致执行中资源被盲目释放。CAS 结果未知依然保留 uncertain/CLEANUP 并停止新派发；首版没有自动 Mgmt 崩溃重建，现场遇到此类情况须对账。admission/P 两账收尾不能单独证明 D/E2E 已结束。

**安装回退。** 包内四文件 preimage/journal 和逐文件原子替换方案未扩大为覆盖整棵 Motor。CPU 安装、重复操作、未知 hash 拒绝及回退回归通过；现场仍必须停接入、完整 HTTP/P/D 排空、票据和两账核对后停 Coordinator。不能仅改一个 worker 的 mode 或直接热换参数。

**探测工具。** `gf_pressure_probe.py` 使用与 Motor 一致的管理鉴权 header，从环境读取密钥；标准 TLS 校验。collect 保留样本请求时间，summarize 拒绝缺少指定 P 的行；freeze 要求有完整样本、显式 H/L 并校验配置，记录证据 hash，不自动选最优点。每长度独立文件；人工核对 summary 中 identities、样本来源、健康候选与窗口定义，不能将混合版本/长度汇总当同一阈值证据。工具不是完整流量模型。

**监督工具。** watchdog 只管理自己启动的压测进程，不自动改代码、重启引擎或无限重试；健康失败/终局产生持久事件，再调用现场 notify 适配器。正常轮询不调用模型。现场必须验证真实 agent 消费通知，adapter 返回 0 不等于唤醒成功。未接好通知时不得声称具备无人值守恢复能力。

**非阻断改进项。** 残留接口目前提供样本+total/truncated，尚无遍历所有残留的游标；短验证中如出现 truncated，应停止升阶并由现场保留全部残留关联证据，不能以样本排空替代总量为零。首轮正常排空的验收标准仍是总数为零。压力摘要/freeze 的输入身份审核、原生故障对账和健康/通知适配器依赖执行 prompt 的现场检查，当前工具没有自动代替这些判断。

## 6. 华为执行时必须完成的门槛

本节可直接作为随包审批记录使用，与已有 rc2 prompt/运行指南共同执行。

| 阶段 | 通过条件 | 不通过时 |
| --- | --- | --- |
| 身份/只读 check | 包 SHA 对应本记录；实际镜像 digest/Python/import 路径正确，四文件与 protected 检查通过，保留现场两项修复 | 保存完整 diff/来源，不能改白名单或全目录覆盖 |
| off/shadow | g5 小请求完整响应、P/D 配置保持、真实管理事件鉴权正常；shadow 无新增预留 | 定位修复，不把参考 Motor 覆盖现场 |
| 准备有效配置 | 每长度基于已有证据或必要短探测选择 `0<L<H`，校准 freshness，记录完整配置和依据 | null 不启用；没有等待关联只标压力探索，不伪造最优阈值 |
| enforce 短验证 | 真实 schema-4 SHM；QUEUED 无资源、READY/claim 单次预留；同 attempt 无资源后恢复、丢 ACK、取消竞争、过期 owner 清理、generation 变化和完整 P/D 成功 | 残留/未知 CAS/协议失败先停止升阶、对账和 debug |
| 事件/特征与机制 | 身份匹配的 matched 增长；known/unknown 原因可见；tail/各类晋升/派发有证据；GF 等待计入客户端 TTFT | 全 unknown、无有效事件或无真实作用时先排查，不直接长压测 |
| 回退 | 完整 HTTP/P/D 排空，票据、FG/native 总残留归零；off/rollback 后原 g5 小请求成功 | 不把局部账清空或文件还原称为回退成功 |
| 正式前冻结/监督 | 同长度 B16/18/20 采用同组 H/L、预算及 freshness；冻结数据/输出/缓存/predictor 状态；健康与真实通知演练成功 | 无真实唤醒不得按无人值守流程运行；参数改动形成新 run/版本 |

目标镜像仍为冻结 g5 `vllm-ascend:g5-g4base-motor-20261021-r1` 及已记录的必要现场修复；3P3D/TP4/24×910B2。P 为 async、SLO=0、FCFS/running-first、8192/max24；D 沿用基线，不能将全栈重述成 enforce-eager。

现场修复沿用已有授权范围：最小改动、完整 diff/前后 hash、回归与新 run_id；受影响的 off/enforce 配对重跑，同类失败或未知账本停止扩大实验。未解决的架构/算法变更回传本机讨论，普通环境适配按 prompt 执行，不要求每一步另请本机审批。

## 7. 正式实验与本轮最终边界

矩阵：目标 prefix hit 50% × 实际约 66K（64K 规格）/128K × **整个集群** B16/18/20；先 B16 配对及重复，再扩大。AISBench 版本、request_rate、batch_size/concurrency 和实际发送补发语义以现场小样本验证为准，不只凭参数名称判定开/闭环。

主要评价为全体请求 P90 TTFT、吞吐及 P90 TPOT；64K 27s/30ms，128K 30s/40ms，P95 为补充。GF 等待、最老 tail、失败/取消/超时/未完成及排空成本一并保留。吞吐下降没有默认可接受比例；测到改善或权衡均诚实报告，不能只展示 normal 子集、移除慢请求或把引擎等待下降代替端到端改善。

最终仍只需一份自包含 `GF_ADMISSION_0.1.0rc2_HUAWEI_REPORT.md`：包/镜像/配置身份，短验证，H/L 与 freshness 依据，真实事件/特征、取消/回退，配对指标，所有现场修复、失败运行和通知演练。关键源码/diff、命令、表格、日志直接嵌入正文，不要求完整内网目录外传。

**结论适用范围：rc2 可以进入现场流程；性能收益和 main 合并仍等待现场证据。**
