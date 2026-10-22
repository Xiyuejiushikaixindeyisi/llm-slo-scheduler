# gf_admission 实施与验收记录

更新：2026-10-22；backup/20261022-init；g5 起点 3b63b00546e7a6ffb2526dafc341969cebe22359。

**当前是 0.1.0rc1 完整本地 runtime 候选交付，不再是 0.1.0.dev1 纯核心。现场验收和性能验收仍未完成。**
旧 dev1 已有的 core 包/说明保留历史，不可用来启动 admission。新版本实现范围、参数、依据和运行命令见 [RUNTIME_GUIDE](GF_ADMISSION_RUNTIME_GUIDE.md)，现场执行入口见 [HUAWEI prompt](HUAWEI_AGENT_PROMPT_GF_RUNTIME.md)。

## 已完成与证据

- 独立 core + Mgmt broker + worker RPC/WaitHub + Motor tokenizer/Conductor provider；global credit、normal FIFO/tail LIFO、预算/年龄、canonical reserve、READY claim、释放/取消/失败闭环。
- 默认 off 可在无法导入 gf_admission 时走 g5；shadow 仅观察；enforce 源码兼容契约和 capability/digest 拒绝混版。
- 少量显式 g5/Motor 钩子、精确四文件增量补丁/指纹、安装前整组校验、备份journal、幂等安装及逆向回退。
- 原 FGJSQ、predictor、引擎源码与 NodeManager fix1/engine_files.json 不变；旧基线 manifest 不改成新 hash。shared docs 启动时的未提交内容保留且不混入开发提交。
- 固定 super-p95 原片段 oracle：3,044 次分类对照；seeded 5,000 次队列访问轨迹。核心格式化未修改 oracle 夹具。
- 本地项目测试 **79 passed**（Python 3.13.11）；Motor 配置/客户端/服务端/UnifiedPD 回归 **309 passed, 8 skipped**。合计 388 passed；不把 skip 算通过。
- 真 Motor DEALER/ROUTER + msgpack、两个本进程客户端及一个独立 Python 子进程共享 broker：丢 enqueue ACK、typed cancellation、重复 query、全局到达计数、最终两账归零。SHM 为 FakeNative。
- provider 的线程超时不提前释放 permit；空闲超过 worker lease 后可继续分配；partial FG commit / uncertain native CAS 保留失败记录；claim/cancel 竞争及墓碑满拒绝测试通过。
- WSL 候选归档解包后随包 58 项测试通过；隔离安装路径导入 wheel 与完整 runtime contract 通过；Python 3.10.12 的 standalone broker/config 导入通过（不是完整 Motor 测试）。
- 新代码 Ruff 检查/格式化通过。Motor 原 pre-commit 已执行：pylint/bandit/头/typing/log 等通过；Ruff 要求格式化既有 g5 段、gitleaks 缺本地二进制，**整个 pre-commit 未全绿**。自动格式变更已按原 before/after SHA 还原，避免无关重排原 g5；差异和日志随包保存。这不是算法或 NPU 通过结论。

测试明细、命令来源、skip 与 hash 在 evidence/manifests/gf_admission_runtime_20261022.json；原始日志/XML 在 artifacts/gf-admission，随包复制至 evidence/local。
8 个 skip：7 个因本地没有 libmindie_workload_shm.so（也无 cargo）；1 个是原 Motor endpoint model_validate 的已存在 skip。没有构建或交付本机 .so；现场必须使用实际镜像自身库。Python 3.12 尚未验证。

## 需求—用例—结果—未覆盖项

表中“通过”仅指所列本地测试。设计编号来自 G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN §15。

| 编号 | 本地用例/证据 | 结果与边界 |
| --- | --- | --- |
| U01 | test_admission_core 分类 oracle | 通过；固定原型片段 |
| U02 | core credit + broker fast_ack_loss / attempt_budget | 通过；重传与新 attempt 不补两次、取消不退款 |
| U03 | core queue seeded replay | 通过；FIFO/LIFO/取消/S-V |
| U04 | core budget/finite validation | 通过；动态降限未提供，配置不热更新 |
| U05 | core pressure + broker guard_rechecks | 通过；score 不当 ms；guard=None 原回归通过 |
| U06 | core fake clock promotion | 通过；晋升而非完成截止承诺 |
| U07 | broker duplicate/owner/epoch/cancel-before/attempt | 通过；同 attempt resubmit 不支持，实际 router 返回 None 终止当前 attempt |
| U08 | broker guard_rechecks / fg_commit_failure / uncertain_cas | 通过；CAS fallback 每候选重过 guard；失败保留 |
| U09 | ready_claim_expiry / claim_cancel_race | 通过；CLAIMED 不随 READY timer 释放 |
| U10 | claim_cancel_race_and_record_backpressure + queue capacity | 通过；没有 heap/独立通知缓存，故无 heap compaction/resync 接口 |
| U11 | core feature + provider_capacity + provider_reuses_token_ids | 通过；timeout 保持 permit，缺层 unknown、generation 变更回普通；真实模板/现场 Conductor 待短验证 |
| U12 | client_cancellation + real_zmq typed result | 通过；取消传播、bounded cleanup、强引用收集异常 |
| I01 | 原 test_motor_adapter 全部11项、Motor309项 | off 通过；7 native 测试未运行 |
| I02 | real_zmq 多 client/子进程；broker global credit | 通过；同一 Mgmt，全局分类计数 |
| I03 | real_zmq_two_workers... 内含独立子进程、真 IPC/transport | 通过；并非完整真实 daemon+P/D HTTP进程部署；自动重连故意 fail closed，需新client与对账 |
| I04 | broker ack duplicate/claim + IPC lost ACK | 通过；CAS替身计数唯一；真实引擎是否重复执行待短验证 |
| I05 | real_handoff_create_attempt_waits_for_p_before_d + 原 router bookkeeping rollback | 本地顺序通过；完整真实 RequestManager+native SHM+admission端到端取消窗口仍须现场 |
| I06 | 原 http boundary stream/nonstream/buffered/role chunk | g5 回归通过；真实 P/D socket 组合与NPU未验证 |
| I07 | 原 authenticated events + broker notify/guard | g5认证/matched与guard分别通过；真实引擎事件→新broker→P一体链待现场 |
| I08 | worker lost CLAIMED / READY expiry / old generation + epoch | 模拟通过；真实进程kill/Daemon重建SHM须现场；没有自动恢复未知native提交 |
| I09 | test_admission_install 4项 + runtime digest/epoch | apply/rollback幂等、未知拒绝、现场两处observe-only保留；平台ABI未验证 |
| I10 | provider_capacity / max_records / bounded batches | 本地容量通过；高压控制面公平性、超大真实prompt tokenization内存/线程耗时需短验证 |

没有把 I03/I05/I07/I08 的模拟或分段测试标成现场闭环全部通过。完整本地代码包可供 Session 2 审阅、之后进入短验证；不能跳过这些明确未覆盖项直接做十小时性能归因。

## 实现偏差与下一步

设计曾提出 async provider、heap、通知缓存及 submission_round：现按实际接口取有界同步协议复用、单调 deadline 队首、ticket revision 查询，以及同 attempt 终局。理由/限制详见 GUIDE，均未引入 P running/waiting 重排、抢占、动态 chunk。

Session 2 接收完整候选后审策略/工程风险与参数起点，不承担本 session 日常编码裁决。无需用户另收 GB/全量trace/完整环境来继续本地工作。当前下一关是对这一具体包评审，再用实际镜像短验证补足上述边界；不是立即 AISBench。尚无华为报告可吸收，也没有收益建议可以伪装成已验证结果。

main 合并：需要现场正确性、off回退、成对重复 AISBench 的全体 P90 TTFT/吞吐/分档 P90 TPOT 条件。只有工程价值或收益不稳定时由用户裁决。当前不合并、不推 main。
