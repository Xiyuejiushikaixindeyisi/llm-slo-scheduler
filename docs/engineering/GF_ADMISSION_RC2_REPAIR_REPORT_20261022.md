# gf_admission 0.1.0rc2 修复报告与复评入口

2026-10-22。原rc1对应546bc7d/0bb3e40，已按用户要求删除旧WSL/桌面交付包和prompt副本。原评审与复现证据保留。本报告随新包给Session2兜底复评；没有向其他会话自动发送消息，没有启动华为压测或合并main。

## 已关闭的本地缺陷与证据

| 评审项 | 修改 | 行为回归 |
| --- | --- | --- |
| R1 P1 | 同Motor attempt的确认无预留业务重试使用新submission_round；前轮必须UNAVAILABLE且无service key；旧轮仍可查询；新轮重新准备特征，逻辑额度不重扣 | test_motor_retry_same_attempt_recovers_in_off_and_enforce；test_confirmed_unavailable_resubmits_without_reclassification（含迟到取消/跨owner拒绝） |
| R2 P1 | query/cancel/finish允许过期owner清理，不续租；dead owner的CLAIMED仅依对应record两释放标志收敛 | test_expired_owner_cleanup_without_reviving_lease四路径；worker_lost仍保留执行中CLAIMED |
| R3 P2 | 总deadline在metadata前开始，入口permit覆盖RPC/线程；timeout不提前释放后台线程permit | test_metadata_rpc_obeys_total_feature_deadline_and_capacity；原provider_capacity及取消测试 |
| R4 P2 | residual过滤先于limit，total/truncated明确 | test_residual_sample_filters_before_limit_and_reports_truncation |

原评审5个观察用例是“缺陷存在即通过”，不修改原件迎合修复；新回归用例要求修复后成功，旧测试含义不能混淆。编写中额外审查了新round迟到取消的owner约束、预留成功与诊断的顺序：观测候选查询置于CAS之前，成功ACK立即写ticket，避免观测异常打断已获得资源的记账。

## 用户批准的算法变化

成本异质性不再是让行必要条件；known positive cost/fresh pressure/共同预算下，long_cost OR min_eligible_P_score>=H。保留long_request_ratio>1用于原成本分支，不放宽成1，不新增同成本或benchmark模式。每次tail预留需实际P score<=L，0<L<H。原g5 FG公式、predictor、P/D调度不改。

同成本高低压、候选低压旁路、双原因一次扣额、未知/陈旧不牺牲、年龄保护及LIFO越序有CPU测试；真IPC测试覆盖3P载荷事件、两个tail、较新先claim和较旧取消。native CAS为替身，现场必须复核。

机制观测包含decision_tail/pressure/cost_and_pressure，dispatch_normal/protected/tail，promoted_age/stale/drain，lifo_overtake_dispatches，logical_arrivals/submissions，残留及每P压力。越序候选需路由/压力资格，未对旧候选试做native CAS，不能等同引擎可执行证明。累计计数与有界事件环分开。

## 阈值及实验决定

用户授权华为先利用B16×66K/128K AISBench或生产重放已有长等待结果，必要时补5–10分钟短探测，观察每P FG W/N/score与已有waiting证据；按完整候选最小score定静态H/L。不能用最忙P的W、TTFT残差或8192直接冒充阈值。探测工具不自动拟合、freeze要求显式H/L与证据hash；正式同长度三个并发保持同组阈值。下一版才研究TTFT动态预测。

正式矩阵为50%目标prefix hit × 实际66K(64K规格)/128K × B16/18/20，对照g5 off/enforce。B是集群并发；保留GF等待、全体失败和tail，GF减少引擎在途是可接受机制，吞吐代价诚实报告；无LIFO越序只归因入场调节。详细样本、重复、warmup、输出、缓存和停止规则见运行指南及JSON计划。

## 本地验证与现场门槛

项目96通过；Motor309通过/8跳过。7跳过为native库缺失、1原Motor已知skip。Python3.13.11运行，3.12/NPU/AISBench未运行。Ruff新范围通过；runtime contract25个保护文件匹配。install/rollback等由项目测试覆盖；真实ZMQ包含独立子进程，但不是完整现场daemon/P/D/NPU。

最终包解包自检/独立wheel导入结果记录在交付清单。复评关注：round迁移与迟到消息、过期owner清理证据、准备deadline与线程许可、压力H/L和全局freshness、有限观察不干扰资源生命周期。不存在“CPU都过所以已具备性能收益”的结论。

Session2只需复评这个完整候选；普通编码决策本session已完成，无需先恢复设计会话。华为短验证、参数探测、agent通知演练后才能正式压测。现场agent接health/notify适配器，后台脚本不轮询模型；异常保留证据、最小修复、回归、新run_id重跑受影响配对，最多两次修复重试。没有真实唤醒接口不能声称已无人值守。

原始证据入口：evidence/local（随包），项目目录artifacts/gf-admission-rc2及evidence/manifests/gf_admission_rc2_20261022.json。现场结果未回传，不合并main。


## 交付候选独立验证补充

独立解包目录随包75项通过；wheel全部gf_admission源码及runtime contract逐字节一致，pip --target隔离导入与兼容验证通过。第一次解包发现子进程测试脚本误引入本地测试helper（开发PYTHONPATH掩盖），已删除无用导入并在仅包内src的环境重验；失败原日志保留在evidence/local/extracted-initial-failure.log，未把失败隐藏。最终归档校验及桌面移动hash在交付清单。

CPU控制面微基准1000次enqueue+finish对，包含逐渐增长的墓碑：P50 426.244us、P95 993.930us、P99 1502.238us、最大2852.969us；native模拟账最终零。方法/原始JSON随包。仅进程内broker＋FakeLedger，不含IPC/NPU、不代表真实并发吞吐或锁时长上限；没有根据该结果宣称硬2ms预算。
