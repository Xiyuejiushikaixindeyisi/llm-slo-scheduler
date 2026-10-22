# gf_admission 0.1.0rc1：实现、评审与实验方案

2026-10-22；基线 3b63b00546e7a6ffb2526dafc341969cebe22359；开发分支 backup/20261022-init。
这是接通 Motor 的实验候选包，默认 off。用户要求的顺序是：完整本地交付 → Session 2 兜底评审 → 华为短验证 → AISBench。没有执行华为实验，没有性能收益结论，不满足合入 main 条件。

## 本轮为什么继续，以及上轮为什么停止

上轮交付 0.1.0.dev1 纯核心，是本 session 把阶段成果当作交付终点，停止过早；没有证据证明必须等待华为或 Session 2。此前不具备完整 runtime，不应拿旧包开展 admission 性能实验。现已继续完成 broker、客户端协议、Motor 接口、兼容校验、测试及增量交付工具。新包与旧 core 包名称、版本不同，不替换历史证据。

开始 broker/协议/IPC 的门槛是：确认 Mgmt 全局所有权、锁/预留/释放语义、真实 transport 取消行为、HANDOFF 先 P 后 D、默认 off 边界，以及可运行的本地 mock/IPC 测试。上述信息来自固定源码，已具备。参数最优值、真实吞吐和完整 NPU 环境不属于编码门槛。

## 实现与边界

- 独立 wheel 只包含 gf_admission，没有 vLLM entrypoint。没有重写 FGJSQ 公式、predictor 特征/训练/标签。
- Mgmt 一份 broker，共用原 FG lock；logical_nonce 去重后补 credit、冻结分类。normal FIFO、tail LIFO、数量/工作量/驻留预算；正常新请求仍服从 normal 队首。
- enqueue 不持有 engine 请求体；在线 feature 在 worker 的专用单线程提取，IPC 只传成本、候选 generation 与原 g5 预留字段。GF queue residence 不预留 P/D。
- normal 快路径可原子预留并返回 CLAIMED；等待路径为 QUEUED → READY_RESERVED → claim → CLAIMED。READY 持 P native/FG 两账且有租约；只有 claim 成功才能转发 P。
- canonical reserve_deadline 在 Mgmt 真正预留时创建，排队不消耗原 30s reserve 命令窗口。每一次 CAS fallback 重新检查候选 FG score；压力不足停止本轮，而非跳过高压 P 去追逐最低成本。
- unknown feature 不当零命中；zero cost 不污染正值 min/max；候选 generation 不一致回 unknown。事件新鲜度仅由经过 g5 身份与序号校验的 matched 事件更新。
- 一条 worker WaitHub 同时承担长轮询和租约心跳，包括空闲与推理期间。wait < server 5s dispatch timeout，超时不是出队/取消。typed transport CANCELLED 重新抛出；未知 enqueue/claim 查同 key，禁止另起预留。
- cancel-before-enqueue 有墓碑；取消不返还 credit。取消/领取在共享锁串行化；CLAIMED 不因 READY 租约或 worker 心跳丢失而自行释放。释放未确认保留 CLEANUP_PENDING；native CAS 抛出且结果不明时保留 uncertain record 并阻断新派发，不猜测减账。
- finish_attempt、finish_request 沿用 g5 abort 兜底；shutdown 在销毁 SHM 前检查残留，拒绝把 CLAIMED/CLEANUP_PENDING 当成已清空。
- drain 是停止新的让行并晋升已有 tail，继续普通 FIFO；不是停流量开关。运维须先停接入，再 drain、等双账归零，再停进程/切 off。
- 配置每进程固定；不支持热切 mode/参数。所有 Mgmt/worker 必须同 digest。D 路由与引擎、P FCFS/running-first/8192/max24/async/SLO=0 不变。

实际 runtime 变更仅四个既有文件：motor_adapter/{bindings,service}.py 与 Motor scheduler runtime/{scheduler_client,scheduler_server}.py。完整 before/after SHA 在 runtime-manifest.json；增量 diff 在 patches。开发笔记 patch 单独保存，不由部署器写入现场。

## 与设计候选的有据取舍

| 项目 | 实施及依据 | 风险/后续门槛 |
| --- | --- | --- |
| submission_round | 当前 UnifiedPD _prepare_attempt_resource 收到 None 即结束本 attempt，不对同一 attempt 再 allocate；UNAVAILABLE 保留终局，真正新 attempt 才再排队 | 如现场出现同 attempt 的正常 resubmit，先扩协议，禁止删除旧墓碑绕过 |
| 年龄 heap | 固定驻留且 FIFO 插入，tail 最老项就是下一到龄项；使用 OrderedDict 队首，有界晋升 | 动态 deadline/热更新未实现，不宣称支持 |
| 通知缓存 | 不设独立无界消息队列；按 worker 的有界 ticket 集合取 revision > cursor 的最新状态，分批返回 | 可跳过中间状态但不会重复执行；票据 TTL 需覆盖请求+worker lease；不宣称重放完整事件日志 |
| FeatureProvider | 复用固定 Motor _ensure_token_ids、query_conductor 的模板/租户/编码/超时/熔断；单线程且最多 2 个在途 future | 不是新增 async HTTP 协议；超时后底层工作未完成不能返还 permit。Python 无法强杀阻塞 tokenizer 线程；close 有残留计数，现场必须为零 |
| 成本与压力 | 成本为 uncached + beta_cpu*CPU + beta_disk*Disk 的候选最小值；压力直接 g5 score | 不做毫秒拟合、不改 FG 预留成本；权重/score 阈值无性能标定 |
| 账本部分失败 | guarded 分支保存 native/FG 记录，统一 abort 清理，未知 CAS 停新派发 | 无自动 crash recovery/分布式共识；Mgmt 重启和 CLAIMED worker 丢失必须现场对账 |

取消/线程方案也核对了 [Python asyncio 文档](https://docs.python.org/3.12/library/asyncio-task.html#shielding-from-cancellation)：shield 不免除外层取消，任务必须有强引用。实现与 timeout 后仍持 permit 的测试据此设计。super-p95 固定 dd9c0895 原始片段及 SHA 在 tests/fixtures/admission；oracle 测试不是按新实现重写的期望。

## 参数：显式实验起点，不是生产默认值

configs/gf_admission/{shadow,enforce}.example.json 需先填 cluster_uuid、model_spec 与参数来源。每次实验固定一份配置，记录 SHA/digest。

| 参数 | 候选值 | 依据 |
| --- | --- | --- |
| quota_every / quota_amount | 20 / 1 | 原型频率起点；累计让行比例受额度控制，不保证 P90 |
| threshold_ratio / long_request_ratio | 0.8 / 1.5 | 固定原型双阈值，边界有 oracle |
| credit_cap | 2 | 限制闲期累计额度后的突发让行；工程起点 |
| max_pending / max_tail_requests | 256 / 16 | 有界背压，超限明确拒绝，不旁路重复 reserve |
| max_tail_cost | 2097152 cost-token | 16×128K 的显式工作量预算；不是 NPU KV 容量 |
| max_tail_wait_ms / scan_limit | 1000 / 4 | 保守限制让行驻留和一次资源不可用扫描；到龄只保证晋升，非完成截止 |
| release_threshold | 0 g5 score | 仅空/零分候选释放 tail 的保守起点；可能过于保守 |
| beta_cpu / beta_disk | 1 / 1 | 未标定时不给 CPU/Disk 省计算奖励；仅显式 NPU 覆盖降成本 |
| wait / worker lease / READY lease | 1000 / 10000 / 5000 ms | 5s server headroom、worker liveness 和确认窗口分离 |
| request wait / tombstone | 120000 / 180000 ms | 去重记录覆盖最大等待与 lease；不是 E2E SLO |
| tick / pump items / pump time | 20ms / 16 / 2ms | 有界周期与批次；管理/取消共享锁仍需现场观察 |
| feature timeout / in-flight | 100ms / 2 | 限制 GF 新增前处理延迟与线程积压；底层 Motor HTTP 仍为 3s |
| event freshness / cleanup retries | 1000ms / 3 | 陈旧压力停止新增让行；释放失败保留可见残留 |

没有要求用户继续收集 GB 数据、完整 trace、权重模型或额外参数意见。现场开始前才需确认实际 Python/安装路径、同一集群规格身份、可用 Conductor 分层协议和原生 .so；这些属于兼容/短验证，不是再开十小时实验。

## 包、安装和回退

包内有独立 wheel、四文件 payload、增量 patch、manifest、配置、测试、参考 Motor Python 源码和本说明。reference-motor 仅用于 CPU 测试/审阅，**不可覆盖现场整棵 Motor，也不是可安装的 Motor wheel**。不包含本机编译 .so，不打包现场 warm model，不重装 slo-patch/引擎。

先解压到新目录，校验 SHA256.json。用现场原 Python 找到真正 import 路径，motor-root 指向包含 motor/ 的目录，adapter-root 指向包含 motor_adapter/、fgjsq/、slo_patch/ 的目录：

```sh
python scripts/validate/verify_gf_runtime_bundle.py .
python scripts/deploy/gf_admission_install.py --bundle . --motor-root /actual/motor-parent --adapter-root /actual/site-packages --state-dir /persistent/gf-0.1.0rc1-backup --action check
```

check 完全只读。unknown target hash 或 protected g5 Python 依赖漂移直接拒绝；不要 --force 或改 manifest 让它通过。NodeManager fix1 和 engine_files.json 是 observe-only，记录现场 hash，不替换，不冒充现场逐字节核对成功。

Session 2 评审通过并完成停流/清账后，原路径同参 `--action apply`，再在 Coordinator 运行环境执行 `python -m pip install --no-deps --no-index wheels/gf_admission-0.1.0rc1-py3-none-any.whl`。确认已有 anyio 4；不安装/升级 NPU 栈。不要在 P/D engine 环境全量重装。所有 worker 与 Mgmt 设置相同 GF_ADMISSION_CONFIG，先 shadow。空环境变量或 off.json 走 g5 原路径，off 不导入可选 gf_admission。

安装器先校验全体，再保存全部 preimage/journal，再原子替换每个文件；不是跨文件原子事务，进程必须停止。中途失败保留 journal，可同参 apply 或 rollback；install.lock 如果因进程被 kill 留下，只能确认旧安装器已结束后由运维删除。重复 apply/rollback 已测试。rollback 仅恢复本安装器已备份且 after/before 匹配的四文件，未知现场后续修改拒绝回退，要求先审阅。

回退顺序：停接入 → POST /admission/v1/drain → 确认 QUEUED/READY/CLAIMED/CLEANUP 与 g5 open_native/open_fg 全归零 → 停 Coordinator → GF_ADMISSION_CONFIG 改 off 或移除 → 原安装参数 `--action rollback` → 重启 g5 → 小请求核对。wheel 可保留而不激活；无需为回退删除任何现场文件。

状态接口 GET /admission/v1/state、POST /admission/v1/drain 复用 Mgmt 鉴权；同时保留 /fgjsq/v1/loads、/fgjsq/v1/events。日志 gf_admission key/state/revision/elapsed_ms 是阶段诊断，不是正式 TTFT。CLEANUP_PENDING、fault、claimed_worker_lost、provider shutdown_residual 非零都应停止升阶，保留 reservation/key/epoch/generation 和现场账本核对；禁止猜测减账。

## 实验升阶门槛

1. **本地交付**：源码/包校验、核心 oracle、事务故障、真 transport/跨进程、off 回归、安装回退测试通过；未覆盖项明确列出。完整测试报告见 IMPLEMENTATION_STATUS。
2. **Session 2**：审完整包，重点核对 guard 的取分点、让行与晋升规则、参数是否适合观测、生命周期与待覆盖项；输出 blocker/非阻断建议及理由。该评审不回溯阻塞本 session 已授权编码。
3. **华为短验证**：实际 Python 3.12/镜像 import、原生 schema-4 CAS、真 worker/P/D、鉴权事件 matched、取消/故障清账、off 回退；先小样本，不开全矩阵。unknown=100%、无有效 matched、零实际 tail、残留账本或 ABI 失败均不得进入收益压测。
4. **AISBench**：前三项通过才冻结镜像/配置/模型/输入输出/并发/seed/warmup。先选一个已知 g5 规格点做 off/enforce 配对，不先跑十档；数据支持再扩展。记录全体成功/失败/取消，不能删最慢让行组。正式 TTFT/TPOT 使用 AISBench 原汇总器。B=16 是整个 3P3D 集群并发。
5. **收益/合并**：全体 P90 TTFT 改善、吞吐提升或不下降、分档 P90 TPOT 满足 32K 32ms/64K 30ms/128K 40ms；业务 TTFT 目标 12/27/30s 同时报距离。至少重复配对，给原始数值与波动，当前没有授权用任意百分比伪造收益门槛。P95 只补充。若仅工程正确/基础设施价值或收益不稳定，交用户裁决，不自动 merge main。

## 给 Session 2 的有证据建议

优先审四项：score=0 与 1s 晋升是否令 tail 几乎无调序；beta=1 的成本排序是否已足够区分 NPU 命中；历史全程 min/max 对离群长请求是否敏感；CLAIMED 失联/未知 CAS 的停止与人工对账契约是否可接受。前两项需要短 shadow/enforce 的命中率、tail 比例、晋升/pressure_deferred 数据，不能凭 CPU 测试选最优值。若同质大请求均进 normal 或到龄前没有竞争，建议停止扩十档并报告策略无可利用机会，而不是盲目提高牺牲额度。只有看到实际候选与收益证据，才讨论滑动阈值、压力曲线；waiting 重排、抢占、chunk 动态化仍不在本版本。
