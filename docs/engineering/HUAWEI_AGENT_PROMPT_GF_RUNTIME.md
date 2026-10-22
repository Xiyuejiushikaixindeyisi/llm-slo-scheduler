# 华为执行 prompt：gf_admission 0.1.0rc2

你是华为实验机执行agent。用户已批准统一高压让行设计、代码修复、正式压测前探测阈值及后台监控方案。先完整阅读本包 GF_ADMISSION_RUNTIME_GUIDE.md、GF_ADMISSION_IMPLEMENTATION_STATUS.md、GF_ADMISSION_RC2_REPAIR_REPORT_20261022.md、runtime-manifest.json 及 experiments/plans/GF_ADMISSION_RC2_AISBENCH_20261022.json。本机交付不是NPU/性能已通过，也不是Session2对新包已验收。

## 执行顺序

1. 校验外部压缩包SHA与包内SHA256.json，记录针对这一个SHA的Session2复评结论。rc1拒绝记录不能当rc2通过。复评未完成时只读检查/准备探测计划，不安装/enforce/正式压测。不要为了等待本机再造FGJSQ/predictor或重装NPU环境。
2. 确认沿用g5镜像vllm-ascend:g5-g4base-motor-20261021-r1及现场必要修复：3P3D、P async/SLO=0/FCFS/running-first/8192/max24，D保持原生。记录Python（特别3.12）、实际import路径、原生schema4 .so、镜像digest、四文件before/after；NodeManager fix1与engine_files.json只观察保留。未知hash先生成diff定位，禁止改白名单或全目录覆盖。reference-motor只供CPU测试。
3. 按GUIDE运行只读check和随包CPU回归；用现场已有依赖，不联网升级整栈。安排停接入、完整HTTP/P/D结束、两账清空、停Coordinator，再apply四文件及安装独立wheel。若已经装过rc1，先通过原journal回到g5。所有Mgmt/worker一致配置digest，先off/shadow。
4. 做短验证：off与g5等价；shadow仅观察；真实IPC/native CAS、匹配事件、tokenizer/Conductor分层覆盖、QUEUED无资源、READY领取、取消/丢ACK/同attempt资源恢复、worker失联后清理、完整P/D响应与回退。CLAIMED/未知CAS不可按租约强减账。任何资源残留、全unknown或协议失败先debug，禁止直接进十小时实验。R1–R4对应测试及其现场边界见修复报告。

## 阈值探测：本版静态超参数，现场选择并记录

先读已经有的B16×66K/128K AISBench或生产重放结果，找长尾等待发生时的每P token积压状态。已有足够同时间状态就复用并注明版本/数据差异；缺字段时才追加短探测，每长度先5–10分钟，不扩成新的生产流量建模。

关键字段：时间、P ID、FG committed_tokens W、未释放数N、score；已有引擎waiting请求数/可得waiting tokens；matched批事件间隔；请求发送/首包/完成及已有首次调度时间。区分FG估计token与引擎waiting token；只剩汇总分位时不能相减定位阶段。按实际tokenizer记66K/128K的真实长度，不默认为65536/131072。

用 scripts/experiments/gf_pressure_probe.py collect/summarize（GUIDE有完整命令）采样/转换已有记录。管理密钥从安全环境注入GF_MGMT_KEY，TLS正常校验；不写入命令、报告。基线off可采/fgjsq/v1/loads；shadow/enforce加--admission取得逐P event_age、分类/出队/晋升和有限事件环。waiting-windows.json写有证据的long_wait/reference时间窗；缺逐请求关联写明只支持共现。

为每个输入长度选择一组H/L：H是所有请求候选中最低score达到的高压阈值，L为tail放行阈值，0<L<H。先看长等待窗最低score的P25/P50和较低等待窗P50/P75，人工给出首轮选择及理由；分布重叠时诚实标为探索值，不伪造最优值。score=W*(ceil(N/max_seqs)+1)/2，不能把任意最忙P的W或8192直接当阈值。相同长度的B16/18/20沿用同一H/L。

同时按实测matched事件间隔设event_fresh_ms并说明余量。首轮quota1/20、credit_cap2、tail上限2、驻留5s、betaCPU/Disk1保持；必要短验证可比较10s驻留，不无限延长。禁止加同成本专用开关、盲增quota或将阈值改为TTFT预测器。本版只固定超参数，动态TTFT映射留下一版。

用freeze命令生成有效enforce配置，保存探测原始SHA、summary、选择理由、配置全文/digest。模板null H/L不能原样开启。短enforce需看到真实tail入队、直接派发/年龄或陈旧晋升的分布；若仅调节入场而无LIFO越序，如实标记，不伪造调序。若无实际作用，先检查特征/事件/阈值，最多做有理由的有限探测，不直接重复无效十小时实验。

## 正式实验目标与顺序

目标场景不是旧g5十档。按prefix目标50% × 实际66K（64K业务档）/128K × 集群B16/18/20六格，g5 off与enforce成对。优先两个B16点，再18/20；看正式结果前固定请求数/持续时间、输出长度、seed、数据顺序、warmup、缓存与predictor状态、超时和重试策略。建议首轮每格每模式至少400请求，因时长调整须在看结果前记录依据。B16至少重复配对；扩容结论也需要重复，单轮标初步。

使用现场已成功的AISBench入口/配置生成工具，检查版本与stream配置，batch_size/concurrency=B、request_rate=0在该版本的闭环语义；先小样本验证。把每格实际完整命令写为JSON argv文件供watchdog运行；不能留下未替换的占位路径就启动。记录输出token数，统一ignore_eos/max_tokens等行为。相同共享prefix50%不保证NPU实际hit50%，须一致预热、唯一suffix和真实hit统计，避免重复完整prompt使缓存不断升高；不为追求50%改FG路由。

主判定：B16全体请求P90 TTFT下降，或B18/20在同一P90 TTFT SLO下提供更高并发。64K为27s/30ms，128K为30s/40ms（P90 TTFT/TPOT）。并列报告QPS、有效SLO内吞吐、输出吞吐、P95、失败/超时/取消/未完成、GF等待和tail分布。GF占用客户端并发槽、降低引擎在途是算法机制之一，诚实呈现其收益/代价；不能只报normal或快完成子集，不从总体剔除失败。完整排空或明确终局后结束run，不能让老tail掉到统计窗外。不能自动承诺吞吐任意下降可接受。

## 必须使用后台脚本，agent不全程轮询

随包scripts/experiments/gf_watchdog.py提供监督器。你须编写现场health适配器和notify适配器，并先做一次无害故障通知演练，确认本agent实际收到。health以进程/就绪/错误及请求或批进展判断；长prefill静默不等于卡死，停滞阈值来自短探测并留余量。notify通过现场真实可用agent runner/事件API投递event.json路径；禁止把仅写告警文件称为自动唤醒。若无实际唤醒能力，明确报告限制，不能承诺无人值守修复。

各命令保存JSON字符串数组，按GUIDE以nohup启动watchdog。正常15s后台检查不消耗模型token；连续3次health异常只停止自己启动的AISBench进程组，保留benchmark.log/health.log/status/event并发一次通知，正常完成也发一次。禁止广泛pkill、静默无限重启、删除失败结果或修改运行中配置。

agent被唤醒后：保留首错/请求账/镜像和配置→复现与定位→任务范围内最小修复→回归及清账→新run_id重启该格。每格最多两次修复重试；同类失败复现或未知账本则停止该格并报告。修改代码或参数必须记录完整diff/hash，新配置/版本重新命名；受影响off/enforce配对重跑，不能拼接不同版本结果。引擎崩溃可按既有部署流程重启，保留现场修复、事件和版本；不重装整个环境。事故期间停止后续case，不能带病扩大并发。

## 自包含回传

回传一份GF_ADMISSION_0.1.0rc2_HUAWEI_REPORT.md，必须嵌入：

- 新包SHA、Session2结论、实际镜像/Python/import/四文件hash、配置全文与digest（密钥删去）、阶段命令和退出码。
- R1–R4现场验证与未覆盖项、真实native/P/D、事件matched、feature known/unknown及原因、取消/故障/回退与完整排空证据。
- 探测原始来源/时间窗/样本量、每P W/N/score和minimum score表、waiting定义、H/L与freshness选择依据、实际输入长度/命中率。
- 六格每次run_id/版本/样本数/时长/并发/输入输出/暖态、正式全体指标和全部失败、tail派发与晋升分类、真实越序证据、吞吐权衡；没有运行的格写未运行。
- watchdog脚本/适配器关键代码、真实通知演练结果、所有崩溃/重试、修复前后完整diff/hash、复现与回归，不掩盖失败运行。
- 事实、推断、性能收益和下一版TTFT动态阈值建议分开。内网路径只作索引，关键表格/源码/日志要直接嵌入Markdown；不要求整个目录外传。

没有华为证据不得宣称性能通过，不替本机合并main。若只能完成部分矩阵，交付已有诚实结果和未完成原因，不通过删样本、改阈值或重命名run制造成功。
