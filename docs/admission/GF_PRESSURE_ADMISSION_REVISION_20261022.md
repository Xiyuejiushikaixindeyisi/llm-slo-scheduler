# 高压触发统一让行规则：rc1 修复设计增补

日期：2026-10-22。状态：用户已批准统一规则与实施；开始 rc2 修复，阈值由华为正式压测前探测后冻结，动态 TTFT 阈值留下一版。本文件不覆盖 Session 2 评审原件或其他会话正在编辑的设计文件。

## 用户决定与目标

用户认可修复、复评、现场短验证、冻结参数后正式压测的推进门槛；否决为同成本场景增加实验专用模式或分类开关。高 P token 压力下，同成本新请求也应能够进入让行 LIFO。GF 扣留请求占用闭环客户端并发槽、减少引擎实际在途量，是允许研究的算法作用，必须诚实报告，不能只当成统计干扰。

正式场景为 prefix cache 目标命中率 50% × 输入 64K/128K × 集群闭环并发 16/18/20，共六格；目标是 B=16 全体请求 P90 TTFT 改善，或在同一 P90 TTFT SLO 下支持更高并发。实际缓存命中率、输出长度、成功/失败/超时和吞吐必须一并记录。历史 g5 十档不替代这六格。

## 统一规则建议

以已有长成本判定 long_cost 与新的高压力判定 high_pressure 作为两种触发原因，使用同一队列和同一预算：

    tail_eligible = known_positive_cost and fresh_pressure \
                    and (long_cost or high_pressure) \
                    and credit_available and count_cost_budget_available \
                    and supported and not protected and not draining

同一逻辑请求只分类一次、只消耗一次 credit；传输重试或确认未预留后的新提交轮次不补扣。成本与压力同时满足时也只扣一次，可记录两个触发标记。成本未知/零、压力无效/陈旧仍按既有保守规则走普通队列。这里的 known_positive_cost 用于维持工作量预算语义，不把未知缓存伪装成零命中。

原 long_request_ratio > 1 的定义保留，表达成本异质性；不将它改成 1 来制造同成本入队。新增压力触发是全场景统一算法规则，无 benchmark 或 homogeneous 开关；已有 off/shadow/enforce 是部署控制，继续保留。

## 压力定义与两个阈值

沿用当前 g5 FG score 作为初版压力代理，不改 FG 路由公式：

    score_p = W_p * (ceil(N_p / max_seqs_p) + 1) / 2

W/N 是 FG 未释放工作量估计及请求数，不是设备忙闲、KV 使用率或准确剩余 token。阈值单位为 fg_score，不能换称毫秒。

分类前，在 Mgmt 同一临界区内按当前请求的 target、能力、健康状态和 endpoint generation 取得候选，重算预测衰减后的 score。令 A 为此时满足路由资格的 P 集合，P_min = min(score_p for p in A)。A 非空且所需压力有效时，high_pressure = P_min >= H；无候选或缺少可信压力不推断为高压，走已有资源失败/回退契约。候选快照不保证随后 CAS 成功。

这样不会因为一个 P 积压就忽略另一可用 P 的低压空间。target 约束自然缩小 A；不使用全池 max/平均压力替代请求自己的候选状态。

设置两个显式、可校验的阈值，0 < L < H：

- H：同成本请求也可以获得让行资格的高压阈值；不是硬并发上限。
- L：normal 为空后，tail 可在选定 P 上放行的低压阈值。

两个边界形成进入/释放间隔；首版不额外引入全池高压状态锁存。中间区域不会仅因压力新增同成本 tail，已有 tail 仍等待满足放行条件或年龄保护；长成本触发仍可成立。

每次实际 reserve 前，重新检查实际候选 P 的压力、身份与资源，CAS 失败换 P 时再检查；每条成功预留后更新账本并重算。不能分类时读一次低压，就在稍后任意 P 上直接放行。

## 优先级和保护边界

normal FIFO 优先；normal 为空后，资源资格允许的 tail 按最新优先尝试。新 tail 不抢占已派发 tail，也不把已发往 P 的请求拉回 GF。FIFO/LIFO 顺序按 Mgmt enqueue 序号定义，不宣称严格 HTTP 物理发送时序。

quota、tail 数量 S、估计成本 V、最大让行驻留时间继续约束两个触发原因。超过驻留时间只恢复 normal 优先级，并不保证硬端到端期限；保护后不再降级。不靠无限延长驻留制造两个并存 tail。压力无效或 drain 的晋升要与 age 晋升分别计数。

普通请求仍沿用 g5 预留；本修订形成有限比例的压力调节，不承诺把全体 P 负载严格限制在阈值以下。持续高压时可能只有延迟入场而没有 LIFO 越序，必须用证据区分。

## 观测与验收

分别记录 cost/pressure/both 分类原因、未获得 quota/预算/有效特征的原因、tail 直接出队、age/stale/drain 晋升、选定 P 与当时 score。逻辑请求数和提交轮次分开。

将效果分成两项解释：

1. GF 保留部分请求，减小 P 的实际在途和等待；闭环客户端槽仍被占用，这是机制效果，GF 等待计入客户端 TTFT。
2. 多个可执行 tail 并存时，较新者越过较旧者形成真实 LIFO 重排；没有这种事件就不能声称 LIFO 已生效。

同时报告全体请求延迟、完成吞吐、失败/取消/超时/未完成、实际客户端并发、GF pending、P 工作状态与 tail 延迟。引擎 queue_time 下降不单独证明端到端改善。未知/失败不从请求总体消失，不通过测量提前结束排除旧 tail。

确定性测试至少覆盖：同成本低压正常/高压可让行；单 P 高压但另一个候选低压不触发；target 约束；阈值边界；无候选/陈旧压力；双触发只扣一次；无 quota/预算；真实 LIFO 越序；每次 CAS 的候选压力重验；年龄晋升不可再次降级；重试与取消不破坏逻辑计账。工程修复 R1–R4 与真实 IPC 生命周期回归仍是交付前条件。

## 推进及来源

先关闭 R1–R4，再完成统一压力规则和机制观测，进行本地定向/IPC验证；形成完整新包、运行 prompt、六格实验配置和后台 watchdog 后复评。现场短验证确认事件/特征、真实释放、通知唤醒和机制触发，再冻结版本与参数跑长压测。Session 2 负责交付后的兜底评审，不成为日常编码前置依赖。

初始 quota 1/20、S=2、驻留 5s（备用 10s）仍只是候选，是否可用取决于机制测试与 SLO 余量；H/L 要基于相同长度、相同缓存条件下的有效 FG 压力分布选择并冻结，不能使用旧场景阈值冒充标定结论。

依据：用户本轮修正；[rc1 评审](../engineering/GF_ADMISSION_0.1.0rc1_REVIEW_20261022.md)；[既有工程设计](G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md)；[classifier](../../src/gf_admission/classifier.py)、[broker](../../src/gf_admission/broker.py)、[FG policy](../../src/fgjsq/policy.py)、[Motor 候选过滤](../../src/motor_adapter/motor_backend.py)源码核对。本文是本项目设计推导，不声称已由论文、现场性能或 super-p95 消融证明。


## 2026-10-22 用户批准：rc2 修复与统一高压让行

本节覆盖旧 rc1 可交付、同成本不让行及等待设计确认的时态。用户已批准编码 session 自主完成 R1–R4 修复、统一压力触发、观测/测试、完整新包及华为 prompt；Session 2 在完整交付后、正式 AISBench 前兜底复评，不干扰日常编码决策。不新增同成本/benchmark 分类开关。

统一准入：可信正成本及有效压力下，(成本偏长 OR 请求候选 P 的最低 FG score >= H)，再受共同 credit、数量 S、成本 V、年龄保护约束。normal 优先；tail 在实际候选 P score <= L 时放行，0 < L < H，每次 CAS 及候选切换重验。沿用 g5 公式、P/D 与 predictor；GF 限制实际入场并发也是合法机制效果，须与真实 LIFO 越序分别归因。

阈值是第一版静态超参数，由华为正式压测前先读已有实验结果，必要时在 B=16 × 实际输入 66K/128K 或生产重放中探测长尾等待附近的每 P FG committed_tokens、未释放数、score、有效事件时间和可得 waiting 指标；不能把引擎 waiting token 与 FG W 混称。报告实际 token 长度、来源和样本，选择 H/L 并冻结后跑正式六格（64K规格实际66K/128K × B16/18/20，cache目标50%）。TTFT预测动态阈值留下一版；不要求本地伪造阈值，也不因此停工。

新交付在 WSL 构建/解包校验后移动到 Windows 桌面；旧 dev1/rc1 归档、wheel、交付 prompt 副本已按用户要求撤回，源码和原评审证据保留。新包先复评、现场短验证、阈值探测和通知演练，再冻结长压测。后台脚本监控并通过实际可用 agent 接口通知故障，正常轮询不用模型；故障/修复/重启诚实留痕，变更版本后重跑受影响配对。

详细规则见 docs/admission/GF_PRESSURE_ADMISSION_REVISION_20261022.md；实施状态见 docs/engineering/GF_ADMISSION_IMPLEMENTATION_STATUS.md。当前仅完成审批与上下文同步，代码/测试/交付完成情况由实施状态后续更新；无现场性能收益声明，不合并 main。
