# 华为执行 prompt：gf_admission 0.1.0rc1

你是华为实验机执行 session。完整阅读包内 docs/engineering/GF_ADMISSION_RUNTIME_GUIDE.md、GF_ADMISSION_IMPLEMENTATION_STATUS.md、runtime-manifest.json。用户要求完整代码包先经 Session 2 评审，再开展 AISBench；当前本机交付时 Session 2 未评审，华为/NPU 未验证。此 prompt 不是立即开始十小时压测的授权。

先记录 Session 2 对这一个包 SHA 的结论与未解决 blocker。没有评审记录，停在只读解包/源码审阅，不安装、不重启、不压测。用户明确启动现场阶段且 blocker 关闭后，按以下顺序执行。

1. 校验压缩包 SHA 和解包 SHA256.json；记录实际主机/容器镜像 digest、Python、import 路径、gf_admission 版本与配置 digest、Motor/FG hook before/after hash、NodeManager fix1 与 engine_files.json 现场 hash。不要修改后两者。不把本地 reference-motor 当现场源码覆盖。
2. 确认单 UUID、同规格、3P3D 基线；P async SchedulerWithPredictorAsync/SLO=0/FCFS/running-first/8192/max24；D 保持现场。保留原 warm model、FG 配置与 predictor。依赖漂移/未知四文件 hash 要嵌入 diff 回传，不跳过兼容检查。现场 Python 3.12 是独立验证点。
3. 运行 GUIDE 中 --action check。CPU 测试可在新解包目录运行 `bash scripts/validate/run_gf_runtime_tests.sh`，使用已存在 CPU 依赖的 Python PATH，不联网拉依赖。它调用随包固定 Motor tests/run_tests.sh；是 mock/IPC 验证，不代表现场 native SHM。所有命令退出码必须记录，禁止因为日志末尾有 passed 就忽略失败。
4. 经评审且用户启动现场验证后，安排停接入/清账/停 Coordinator，按 GUIDE 安装 wheel+四文件增量，备份目录保持持久化；初始 off 或 shadow。只改本包拥有文件和 GF_ADMISSION_CONFIG，不重装引擎/NPU、不改变 D、不强覆盖现场修复。
5. 小样本验证：off 功能等价；shadow 不延迟真实 g5 reserve；enforce 请求确实入票据、等待中 P/D 没预留、claim 后 P-first/D-deferred；流式字节/首非空body语义不变。认证 events 检查 matched 而不只 HTTP200；Conductor 明确三层覆盖且 tokenizer/template 与实际请求相符；记录 known/unknown 原因、tail/promoted/pressure_deferred。模拟丢确认、queued/READY取消、worker退出、generation更替；CLAIMED失联只报残留，不按READY租约强减账。验证双账回零、无遗留task、provider shutdown_residual=0、管理接口响应以及 off/rollback。native .so 必须使用现场镜像自身兼容版本。
6. 如果有失败/残留/错误重放/全unknown/无实际tail，停止升阶，回传诊断。不要直接转十档 AISBench。若只有同质请求，没有调序机会，明确报告，不调高额度伪造收益。
7. 上述通过后才执行经用户启动的 AISBench：先一个已知规格点的 off/enforce 配对及重复，再决定扩展。冻结数据、输出长度、warmup、并发、seed与参数；B16是整个集群16。保留全体请求和全部失败/取消，正式TTFT/TPOT遵循AISBench。报P90 TTFT、P95补充、QPS/throughput、分档P90 TPOT及SLO。不能只报未让行组或降低负载制造改善。
8. 发生现场修复，先在副本定位和测试；仅本任务范围的必要修复可进入现场候选，记录 before/after 完整SHA、完整diff、复现/回归结果；未知设计变更先报告。不得修改指纹白名单使坏版本变成合格。运行中不悄悄混用两个包/配置。

最终只回传一份自包含 `GF_ADMISSION_0.1.0rc1_HUAWEI_REPORT.md`：

- 包SHA、评审结论、实际运行身份、配置全文（密钥脱敏）、各阶段命令/退出码。
- 本地已知未覆盖项在现场的结果或明确未执行；真实原生SHM/进程生命周期与P/D验证证据。
- 所有改动的关键源码/完整diff与完整SHA，不能仅引用内网路径。
- matched/duplicate/stale/wrong_identity、tail/promoted/unknown/pressure_deferred、票据和双账清理证据。
- 如做AISBench：每轮样本量、全体指标、失败数、分组辅助表、重复波动、与同身份off基线的配对；不以aggregate分位相减当阶段等待。
- 是否可进入下一阶段、是否满足收益条件、回退是否验证。原始日志片段与表格嵌入正文；路径只作来源索引。没有执行的内容明确写“未执行”，不要推断性能已达标。
