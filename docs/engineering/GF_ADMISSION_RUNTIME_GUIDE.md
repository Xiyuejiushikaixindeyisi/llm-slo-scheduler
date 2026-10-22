# gf_admission 0.1.0rc2：修复、阈值探测与正式实验

2026-10-22；基线 3b63b00546e7a6ffb2526dafc341969cebe22359；开发分支 backup/20261022-init。rc1 已撤回，本文替代旧运行指南；历史错误由原评审保留。当前仅本地候选，Session 2 复评、华为真实栈验证及性能结论未完成，不能据此合并 main。

## 已批准的统一规则

可信正成本、有效压力下，成本偏长 OR 请求可路由 P 中最低 FG score >= H，且有共同 credit/S/V 预算、未受年龄保护，才进入 tail。无同成本或 benchmark 专用开关。normal FIFO 优先，tail 在实际候选 score <= L 时按 LIFO 放行，0 < L < H；每次 CAS fallback 重验、成功预留后重算。GF 队列不持 P/D 资源，不撤回已派发请求；P/D、FG 公式和 predictor 均保持 g5。

高压时允许同成本新请求让行；GF 扣留闭环并发槽、减少引擎实际在途量是有效研究方向。入场调节和真实 LIFO 越序分别报告。实际未发生越序不能归因于 LIFO；只有入场调节也可比较端到端效果，不把降低实际引擎在途量自动判为造假。GF 等待包含在 AISBench TTFT 内。

## 修复与边界

| 项目 | rc2 行为 | 回归证据 |
| --- | --- | --- |
| R1 | Motor attempt 编号不改，增加 submission_round；仅上一轮确认 UNAVAILABLE 且无预留才允许下一轮，传输重试沿用原 key；重新获取 feature/候选信息，逻辑分类/credit 不重扣；迟到取消覆盖同 attempt 后续轮次 | 真 UnifiedPD off/enforce 无资源后恢复；轮次/丢 ACK/取消/owner 测试 |
| R2 | 同 owner、同 epoch 的 query/cancel/finish 可在 worker lease 过期后清理，不恢复新分配权限；失联 CLAIMED 仅在对应 FG record 的 native/FG 两个释放标志都确认时收敛 | 过期清理/被动对账/活跃未知保留；真实双账收尾 |
| R3 | 总 feature deadline 覆盖候选 RPC＋executor；入口并发许可覆盖两阶段，后台 future 实际结束才归还许可；真实取消传播 | 8 请求/2 许可的慢 RPC、总超时、线程超时不提前归还、取消 |
| R4 | 先筛残留再截断，返回 residual_total/residual_truncated | 多 CLOSED 在前、CLAIMED 在后及分页截断 |
| 观测 | cost/pressure/both 分类原因；逻辑到达与提交次数分开；normal/protected/tail 派发、age/stale/drain 晋升、LIFO 越序计数；有界事件环、每 P W/N/score/event_age | 核心测试及真 Motor IPC tail→READY→claim→取消/释放 |

schema_version 与 admission capability 均为 2，混用 rc1 配置/worker 会拒绝。g5 event schema 保持 1，SHM 保持 schema 4。首轮 key=nonce:attempt；后续为 nonce:attempt:sN；attempt_seq 单独保存并沿用引擎事件身份。取消/finish 不需要存活租约，但仍验证 worker 与 coordinator epoch。结果未知不换 key、不 fallback。

unknown native CAS 仍停派发并保留 CLEANUP_PENDING；不猜测减账、不根据 score=0 或租约超时回收执行中的请求。对应释放证据若已被 g5 TTL 清除，不能推断丢失记录已经安全，需现场对账。CLAIMED/admission 关闭只说明这层资源责任处理完毕，不证明 D 或完整 HTTP 已结束。

每条请求生命周期诊断写入有界内存环，管理采样导出；共享锁内不新增日志文件 I/O。events 的 sequence 跳跃表示中间事件未采到，event_ring_overwritten 是环覆盖计数，不是客户端失败数。LIFO older_eligible 表示当时存在更旧且路由/压力合格的候选，未对旧候选试做 native CAS，不能称为硬件可执行性的完整证明。计数不保证所有事件正文永久保留。

pump_ms 是派发循环的软时间预算，维护、一次 CAS、采样和晋升可能超过它；不是 2ms 锁时长硬上限。provider Python 线程不能强杀，关闭残留必须记录；元数据 RPC 总 deadline 受事件循环调度延迟影响。

## 配置与探测

独立包默认 off。configs/gf_admission/enforce.example.json 的 H/L 为 null，不能原样开启。shadow 模板 H=2/L=1 仅用于引导观测，不是标定结论；shadow 不预留/延迟业务，也不能拿 shadow 的队列预算统计当 enforce 的仿真。

首轮固定候选：quota=1/20、credit_cap=2、tail数量上限2、tail驻留5s、scan=4；成本权重CPU/Disk=1、成本上限2097152（估计 token，不是 KV 容量）；成本双阈值0.8/1.5保留。若5s没有合适作用空间，可在短验证阶段比较10s，但不能无限拉长驻留；正式运行前冻结。未知成本和零成本不进入tail，不把未知缓存当零命中。

用户授权华为在正式实验前优先读取已有 B16×66K/128K AISBench 或生产重放结果；已有时间对齐的压力/等待证据足够时不要重跑。缺少对应状态时，在原 g5 或 shadow 下对 B16×实际66K/128K、目标缓存50%做必要短探测，建议每长度先5–10分钟，明确运行时长与未稳定的限制。探测不算正式对照结果，也不扩成流量建模项目。

同时收集：实际P实例ID；FG committed_tokens W、未释放数 N、score；时间戳和采样间隔；已有引擎 waiting请求数/可得waiting tokens及其定义；有身份匹配的批事件间隔；AISBench请求发送/首包/完成及已有逐请求首次调度时间。没有逐请求关联就只报告时间窗共现，不相减分位数、不把TTFT残差当排队下界。FG W包含未完成估计工作，不等于引擎waiting token。

初版压力严格沿用 score=W*(ceil(N/max_seqs)+1)/2；当0<N<=max_seqs时score=W，不能将此条件外推到所有时刻。以所有可路由P最低score达到H表示没有低压去处；报告长尾发生时每P及该最低值的分布，避免用最忙P的token数直接代入H。

建议选择流程：比较“长等待窗口”与“较低等待窗口”的最低score分布，先考虑长等待窗口P25/P50附近为H、较低等待窗口P50/P75附近为L，要求0<L<H。这些只是首轮候选依据。分布重叠/无低压窗口时明确写探索性选择和理由，不伪造分离点；在短enforce观察tail入队、直接放行、晋升与GF等待后固定一组。每个长度一组H/L，B16/18/20沿用该组，不在正式结果出来后偷偷按并发优化。event_fresh_ms 根据匹配事件间隔探测并留明确余量，不能默认1s有效；很久没事件且无法确认状态时仍保守晋升。基于预测TTFT的动态阈值留下一版。

提供三个可执行子命令：

```sh
# 在现有现场Python环境；管理密钥通过环境安全注入，不写进argv/报告。
python scripts/experiments/gf_pressure_probe.py collect --url "$MGMT_URL" --instances "$P_IDS" --run-id probe-66k-b16 --input-tokens "$ACTUAL_TOKENS" --concurrency 16 --duration 600 --interval 0.5 --output probe-66k.jsonl
# shadow/enforce时可加 --admission；TLS使用 --ca-file，不关闭证书校验。
python scripts/experiments/gf_pressure_probe.py summarize --input probe-66k.jsonl --windows waiting-windows.json --output probe-66k-summary.json
PYTHONPATH=src python scripts/experiments/gf_pressure_probe.py freeze --template configs/gf_admission/enforce.example.json --evidence probe-66k-summary.json --cluster-uuid "$CLUSTER_UUID" --model-spec "$MODEL_SPEC" --high "$H" --low "$L" --event-fresh-ms "$FRESH_MS" --rationale "$RATIONALE" --output enforce-66k.json > enforce-66k-freeze.json
```

waiting-windows.json 为数组，每项含 start_s/end_s/label（例如long_wait/reference）及可另加source说明；时间为Unix秒，对齐实际记录。无等待定位证据可不传 --windows，但须标记阈值只是压力探索。工具输出 per-P W/N/score分位与集群最低score分位，缺任何指定P的样本拒收。已有记录可转换为同一JSONL结构并保留转换脚本/原始字段。每长度独立文件，不混合规格/不同基线。

## 安装、自检与回退

包含独立 wheel、四文件增量 payload、精确manifest/patch、测试、参考Motor Python源码、探测/监控工具。reference-motor只供CPU测试/代码审阅，不安装为Motor、不覆盖现场目录；没有本机.so、权重或引擎wheel。保留NodeManager fix1、engine_files.json、warm predictor、D/引擎配置。

```sh
python scripts/validate/verify_gf_runtime_bundle.py .
python scripts/deploy/gf_admission_install.py --bundle . --motor-root "$MOTOR_PARENT" --adapter-root "$ADAPTER_PARENT" --state-dir "$BACKUP_RC2" --action check
# 在实际解释器且已有CPU依赖时运行；不联网补依赖。
bash scripts/validate/run_gf_runtime_tests.sh
# 完成针对新包的复评、停接入、完整请求结束、清账及停止Coordinator后：
python scripts/deploy/gf_admission_install.py --bundle . --motor-root "$MOTOR_PARENT" --adapter-root "$ADAPTER_PARENT" --state-dir "$BACKUP_RC2" --action apply
python -m pip install --no-deps --no-index wheels/gf_admission-0.1.0rc2-py3-none-any.whl
```

路径来自现场import，不能照抄本机路径；必须已有anyio4。apply/rollback为整组校验、全部preimage备份后逐文件原子替换，不是跨文件原子事务。要求进程停止；未知hash不强制覆盖，先保留diff定位。若现场已装rc1，先用其真实journal回退至g5；不要直接让rc2接受rc1 hash。安装器故障保留journal，同参恢复；不能覆盖未知现场修复。

所有worker/Mgmt使用同一配置digest，改变mode/阈值需停流排空后重启Coordinator。off.json或不设置GF_ADMISSION_CONFIG恢复原g5路径。schema2只属于admission，不能修改原引擎event schema。

回退：停止新请求→/admission/v1/drain→等QUEUED/READY/CLAIMED/CLEANUP、open_native/open_fg、完整HTTP/P/D在途全部结束→停Coordinator→改off→同参 --action rollback→重启g5→小请求验证。drain只停止新增让行并晋升，不是停流开关；两账为零不单独证明D/E2E结束。

## 正式矩阵与比较

见 experiments/plans/GF_ADMISSION_RC2_AISBENCH_20261022.json。64K业务规格使用现场实际约66K输入，128K记录实际token数（旧126000不能无声改名131072）。每组同输入tokenization/template、输出长度、数据/顺序、seed、缓存预热、模型、predictor状态及超时/重试策略；共享prefix50%不等于实测NPU命中50%。避免循环相同完整prompt造成后续接近100%命中。

B是集群并发16/18/20，不乘3。使用现场AISBench流式模型、闭环配置，核对其版本下batch_size/concurrency及request_rate语义。先用一个短case确认发送并发与完成补发，再固定正式case。六格各做g5 off/enforce配对；优先B16，两次配对确认核心结论，再推进18/20。其余格首次结果可以先报告，声称扩容收益前需重复；不把六格一次运行写成稳定结论。建议每格每模式至少400请求作为第一轮量级，实际样本/持续时间由现场根据成本在看正式结果前确定并固定，不能因结果不好提前截断；记录尾部样本量和不确定性。

主要目标为B16全体请求P90 TTFT改善，或B18/20达到同一SLO；64K TTFT27s/TPOT30ms，128K30s/40ms。同步报告QPS、有效SLO内吞吐、输出吞吐、失败/超时/取消/未完成及tail分布；P95补充。不得只统计normal、只选快的完成请求，不能将失败从总体消失；AISBench成功请求分位与总请求失败账并列。尾部请求需完成/明确终局后结束run，稳态窗口与全程结果均保存。吞吐下降需如实披露，不默认任意容忍度；是否接受仅入场调节或性能权衡由结果与用户目标裁决。

## 后台监控

scripts/experiments/gf_watchdog.py 后台持有一条AISBench子进程，正常15s检查不调用模型；连续3次health失败停止自己启动的benchmark进程组，保留日志和event.json并调用通知适配器。它不杀整个Python环境、不自动改代码、不重启引擎、不自动重跑。成功完成也发送一次事件，便于agent启动下一格。

华为agent须创建/验证两个现场适配器：health返回0表示健康，非0表示有证据的异常；notify接收event.json绝对路径，通过实际可用agent runner/事件API唤醒当前agent。JSON文件保存argv数组，禁止shell字符串。health检查引擎进程、就绪、错误及请求/批次进展；不能单凭日志静默判长prefill卡死。进展超时根据短探测实测上界并留余量，OOM/进程退出/持续服务错误单独判定。需要先人工注入无害故障，验证agent实际收到；通知命令返回0本身不等于agent消费。没有真实唤醒接口时必须报告，不能声称无人值守恢复已实现。

```sh
nohup python scripts/experiments/gf_watchdog.py --command case-command.json --health health-command.json --notify notify-command.json --output "$NEW_RUN_DIR" > "$WATCHDOG_LOG" 2>&1 &
```

必须在新run目录运行，不复用覆盖。异常时agent保留首错、配置/digest、镜像、NPU/engine/Motor日志及请求账；先定位复现再修复，测试后恢复。每格最多两次自动流程中的修复重试，连续同类失败或账本未知则停格并告警，禁止无限循环。代码/参数变更须新版本、完整diff/hash、新run_id，受影响的off/enforce配对重跑；失败运行永久保留。真实告警只通知已授权的实验agent，不增加对外群发。

## 验收顺序

本地正确性与完整交付→Session2针对新包复评→华为真实Python/native SHM/P/D、取消、事件、回退短验证→已有证据核对/必要短探测→冻结参数与通知演练→正式矩阵。全unknown、无有效事件、无真实tail入队或资源残留不得解释为算法收益；先debug再升阶。无LIFO越序但有真实入场调节时准确标记机制归因，不伪造越序。

本机mock/IPC、脚本测试和wheel验证不替代910B2验证。详见实施状态和 evidence/local。现场回传自包含Markdown，关键源码/diff/命令/表格/首错嵌入正文，内网路径仅作索引。无现场结果不合并main。
