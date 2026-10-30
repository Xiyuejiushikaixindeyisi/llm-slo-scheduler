# 新编码 session 启动 prompt：gf-admission / gf-lifo-p90

日期：2026-10-22。以下正文可直接作为新编码会话的用户任务。会话由用户新建，不通过读取本文自动创建其他会话。

---

你是本项目的**独立编码 session**，负责实现、测试、交付、吸收华为现场修复以及完成版本合并。你的设计主会话是 Session 2，负责 super-p95 机制、请求分类、让行预算、实验解释及设计评审。请按下面的优先级读取共享文件，然后在已批准范围内持续推进，不停留于复述计划。

## 1. 目标、分工与当前版本

最终目标是在现网开环流量下，提升单卡吞吐并优化尾延迟；主指标为全体请求 P90 TTFT，P95 为补充，P90 TPOT 为约束。高并发 AISBench 是极端压力验证场景，考察同并发下的延迟，或相同 SLO 下可承载的并发。不能假设当前平均吞吐接近硬件容量。

已批准架构：**独立 `gf_admission` 包＋少量 g5 显式钩子**。在 GF/Motor 的 P 预留之前维护 normal FIFO 与 sacrificial LIFO；有预算地推迟部分请求，放行后继续使用 g5 的 FGJSQ、predictor 和原生引擎调度。

- 工作区：`/home/zhangxiyue/llm-slo-scheduler`，在 WSL 中开发。共享同一 project、worktree 和 Git 分支；新会话不代表代码隔离。
- 仓库：`https://github.com/Xiyuejiushikaixindeyisi/llm-slo-scheduler`。
- 已交接基线 commit：`3b63b00546e7a6ffb2526dafc341969cebe22359`。2026-10-22 已用 `git ls-remote origin refs/heads/main` 核实远端 main 为该提交；当时本地 main、origin/main、开发分支均同点。启动时重新检查，允许之后有明确来源的增量，禁止为回到此提交而 reset 当前工作区。
- 开发分支已由用户指定为 `backup/20261022-init`，用于 gf-lifo-p90。它是继续开发的分支，不是不可变备份；不要另造分支名或 worktree。
- 当前现场基线镜像：`vllm-ascend:g5-g4base-motor-20261021-r1`；底座 vLLM `0fc695fc` / vLLM-Ascend `5cb98caa`，Motor 公开设计锚 `f203263d`，带 g5 七文件适配及 NodeManager fix1。旧 rc1 为历史。
- 本机可重建 Motor 开发副本：`artifacts/build/motor-g5/`；`upstream/motor/` 保持固定源码，旧 `artifacts/build/motor/` 仅供参考。
- 首次版本整理记录为 207 项 CPU 测试通过、33/33 冻结指纹匹配；这是既有证据，不代表你已重跑，也不代表 NPU 性能通过。

Session 1 已完成 g5 对齐与首次推送，继续负责必要的基线维护；Session 2 保持设计/评审职责；Session 3 负责数学建模，当前不改运行代码。你是入场实现的主要代码修改者。涉及共享适配层、版本文件、设计文件时先读取最新状态，不覆盖其他会话修改。

本机负责设计、代码和逻辑验证；华为机负责真实镜像/权重/910B2 环境的部署、debug 和完整实验。你无法直接看到内网代码和原始日志。每轮由用户转交代码包与 prompt，再把华为报告带回本机；不要假定已有远程控制或自动跨会话通信权限。

## 2. 阅读优先级与资料裁决

按层阅读并记录必要结论，不一开始通读所有历史报告。以下路径均相对项目根目录。

**P0：先明确工作规则、版本和启动入口。**

1. `AGENTS.md`，以及拟修改目录中适用的 AGENTS。
2. `docs/architecture/RESEARCH_COLLABORATION_AND_HANDOFF.md`：角色与现场回传契约。
3. `README.md`、`docs/engineering/INITIAL_VERSION_20261022.md`、`docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md`：当前命令、分支、207 项测试来源、实际开发副本和保持项。
4. `env/sources.lock.json`、`env/g5-baseline-files.json`、`tests/README.md`、`scripts/validate/run_local_tests.sh`：版本、基线指纹、测试入口。

**P1：编码前完整阅读设计，核对直接接入源码。**

5. `docs/admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md`：完整阅读，重点为第 4–5 节不变量/算法、第 7–13 节状态机/异步协议/接入/故障、第 15–16 节测试与实施顺序。
6. `docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md` 第 5 节：源码语义勘误；读取 `G5_FROZEN_BASELINE_HANDOVER.md` 的第 0、5 节及与你修改有关的配置/修复证据，其余按需。
7. `src/fgjsq/`、`src/motor_adapter/` 与已有测试，尤其 policy、service、bindings、motor_backend、body_observer 的身份、预留、事件和释放逻辑。
8. `artifacts/build/motor-g5/` 中的 router/strategies/unified_pd.py、scheduler/runtime/scheduler_server.py、scheduler_client.py、scheduler/policy/kv_cache_affinity.py、api_client/conductor_api_client.py；以上路径位于其 `motor/coordinator/` 下。核对真实 HANDOFF 顺序、RPC timeout、生命周期和 Conductor 能力。
9. `patches/motor/G5_ALIGNMENT.md` 与当前 g5 准备/安装/核验脚本，防止重新覆盖现场修复。需要 predictor 背景时定点读取 `src/slo_patch/`，不改其算法。

**P2：实现分类、预算和容器前读原型；遇到设计疑问再读历史。**

10. `docs/admission/GF_SUPER_P95_DESIGN_DISCUSSION.md`、`docs/references/SUPER_P95_RESEARCH_AND_LLM_COMPARISON.md`，以及固定 `dd9c0895` 下 `upstream/vllm-omni-super-p95/benchmarks/diffusion/super_p95_dispatcher.py` 与 `vllm_omni/diffusion/sched/super_p95_step_scheduler.py`。
11. `docs/admission/DUAL_WAITING_QUEUE_DISCUSSION_BRIEF.md` 及其引用的两份流量/等待报告，只用于证据边界和适用场景。集中流量/环境调研已经结束，不重新要求完整 trace、代码包或环境复刻。
12. 数学研究在 `docs/modeling/`；本任务只了解接口边界，不实现动态 chunk 或接管数学研究。

裁决原则：当前用户指令和已批准范围决定任务；实际固定源码决定接口事实，最新现场报告决定其证据范围。旧报告、设计初稿行号和旧 hash 不是当前部署白名单。发现设计与实际源码冲突，记录“来源—冲突—影响—建议”；普通实现细节自行解决，涉及策略语义或范围变化时向用户提出具体选项，同时继续独立工作。不要把历史“待基线交接”当成仍未完成。

## 3. 必须保持的边界

- P 保持 async `SchedulerWithPredictorAsync`、SLO=0、FCFS/running-first、每轮共享 8192 token、max_num_seqs=24。D 引擎、原生 D 路由、KV 传输、FGJSQ 公式、predictor v1 特征/标签及 reporter 身份协议保持 g5。
- GF 只改变尚未预留/送入 P 的请求顺序；不做引擎 waiting 重排、running/KV 抢占、动态 chunk、路由折扣、batch2 或按 appid 固定降级。
- 3P3D/TP4/24×910B2；AISBench 的 B 是整个集群并发。正式 TTFT 从客户端 POST 前到首记录流式时间点，包含 GF 等待，TPOT 对齐同一 AISBench 汇总口径。
- 64K P90 TTFT/TPOT 为 27s/30ms，128K 为 30s/40ms；这些不是可直接分配给 GF 的等待预算。不得把历史 +10% 工程门槛沿用为新算法吞吐容忍度。
- 本机只复现和验证代码逻辑，不安装整套 NPU 栈，不宣称现场权重、warm predictor 或镜像字节完全复现。

## 4. 编码准则

**即插即用与可回退。** 独立分发 `gf-admission`，导入名 `gf_admission`；新增源码位置和独立构建配置按设计第 11 节。保留现有 slo-patch 0.2.0，不重打整个包来覆盖现场文件。新功能默认 off，off 时不启动 admission 后台任务或 KV 查询，不依赖新包才能运行原 g5。支持 off/shadow/enforce，开启失败必须明确，不能静默回到原路由却声称已启用。pip 安装不等于接入成功，交付须包含最小显式钩子、兼容检查、接入自检和回退。

**扩展性与 clean code。** 纯队列/分类/预算核心与 Motor、RPC、特征获取分离；以少量明确接口注入时钟、负载快照和特征提供者。使用类型、dataclass/枚举、显式状态转换和所有权；配置有版本、单位、合法范围及来源。避免万能 manager、动态反射、重复账本、全局可变状态、为假想后端搭通用框架，以及大范围重构基线。注释解释约束与原因，日志足以定位决策但不输出完整 prompt、敏感内容或无限高基数标签。

**“尽量不写启发式”的准确含义。** 保留有来源、可解释、可配置、可单独验证的 super-p95 策略规则；禁止无依据经验常数、连续堆叠特判、猜 req_id/版本字符串、吞异常继续执行、随意自动调参。原型 m=20、b=1、0.8/1.5 只是参考规则，不是已在本集群标定的最优值。P90 不推出“让行 10%”，8192 不推出最佳压力门限。分类 credit、队列数量、估计工作量和最大驻留分别建模。

未标定参数与工程参数分开：工程超时/容量根据协议约束和本机测量给出来源明确的保守配置；策略阈值、成本 beta、压力曲线标为实验参数。可以提供有明确假设的首轮实验配置，不能把它称为生产默认或拟合结果。必需参数缺失时拒绝 enforce；不因此停止队列、协议、off/shadow、测试和交付基础能力的开发。第一版先固定预算＋压力门控，动态预算预留窄接口；没有数据时不伪造自动反馈曲线。

**异步与性能。** 优先复用已有 transport/HTTP client，控制进程间 payload。网络、tokenization、文件操作和训练不进入共享锁或阻塞事件循环。异步任务、线程、队列、堆失效项、墓碑、通知缓存和重试都必须有明确上限与关闭路径；取消要传播，异常要收集。优先事件驱动加必要的有界定时复核，不为每请求创建高频轮询。OrderedDict/索引/期限堆是设计候选，用实际访问轨迹测量，再决定是否需要替换；不凭数据结构名称宣称性能改善。

**协议与资源不变量。**

1. QUEUED 无 P/D/native/FG 资源；中央 Mgmt 维护唯一队列、credit 和序号，worker 保留 HTTP 上下文。
2. 同逻辑尝试最多一个有效 reservation；transport 重试复用身份。超时/丢 ACK 后查同一事务，不能换 key 或无条件 fallback 造成双执行。
3. 压力检查与 FG 预留在同一原子边界，CAS fallback 的每个 P 重新检查；每次成功 reserve 后重算，不用旧快照放空整队。
4. READY_RESERVED 短租约与 CLAIMED 分开；不能用 READY 到期回收已执行请求。取消、领取、过期、释放须幂等，旧 epoch/generation 不得影响新实例。
5. normal FIFO 优先；tail LIFO 仅影响未预留候选。保护晋升与有限扫描按设计实现并可观测，不暗中改为 SJF。normal 空不代表 P 空，scheduled 不代表计算完成。
6. KV unknown 不当零命中；分层缓存可用不等于目标 NPU 已驻留；FG W/N/score 是账本估计而非真实 GPU 负载。predictor 标签不当单请求剩余 TTFT。

兼容性针对明确基线和组件，禁止宽泛 hash 放行、无边界 monkey patch、覆盖整个 site-packages。保留 NodeManager fix1、engine_files.json 和现场配置；新增钩子的预期差异另建 manifest，不篡改冻结指纹使检查“变绿”。保持设计支持的 Python 版本边界；未实际运行的版本矩阵如实列出，不因本机 Python 3.13 通过就宣称现场 3.12 已验证。

## 5. 测试与验收

先运行当前统一入口 `bash scripts/validate/run_local_tests.sh`，记录起点；缺少固定源码时使用现有准备工具，不破坏已有 checkout。针对修改逐层测试，通过后不无理由重复昂贵检查。

落实设计第 15 节 U01–U12、I01–I10 的风险覆盖，建立“需求/不变量—用例—结果—未覆盖项”表，不以测试数量或覆盖率百分比代替正确性。重点包括：

- 原型分类/出队 oracle、FIFO/LIFO、credit、S/V、年龄保护、未知特征、阈值边界、容量限制；冻结夹具不得为迎合实现而修改。
- FakeClock＋确定性事件序列；固定 seed 的状态机重放，逐步校验账本守恒/至多一次有效预留，而非只检查最终 HTTP 200。
- 丢 ACK、重复/错序消息、超时、取消与 reserve/claim 竞态、CAS 换候选、worker/Mgmt 退出、epoch/generation 变化、清理失败及资源泄漏。
- off 路径与原 g5 的路由、账本、事件、流式字节和 D 行为等价；shadow 不能阻塞或改变真实派发。
- 真实 Motor 类、多 worker、真实 IPC 和 fake P/D 的集成测试；mock 不能代替已声称覆盖的 transport/SHM/native CAS。无法本机执行的测试明确 SKIP、原因及华为验证步骤。
- 安装、重复安装、失败恢复、卸载/逆补丁、off 回退、未知版本拒绝、保护现场修复。
- 本机微基准记录热路径延迟、事件循环/锁开销、RPC 次数、内存和任务上限，测量方法与样本量可复核；不得把 CPU 微基准写成 NPU 吞吐收益。

## 6. 实施、交付与实验闭环

按可验证的小阶段推进：基线/off 回归 → 纯核心与单元测试 → broker/WaitHub/原子预留与生命周期 → FeatureProvider/shadow/观测 → 集成与故障测试 → 打包/回退验证 → 华为实验 → 修复与迭代。常规实现不反复请示；若必须改变已批准策略或 g5 不变量，提供具体差异和证据后再推进依赖该决定的工作。

交付内容至少包含：独立 wheel/必要源码、基于明确 g5 文件的增量 patch、兼容 manifest、安装与回退入口、配置 schema/模板及版本、测试结果、文件 SHA256、基线 commit、源码 commit/工作区差异标识、运行说明和给华为 agent 的完整 prompt。包应能从版本化内容重建，不能依赖本机绝对导入路径或未导出的临时文件，不携带权重/镜像/完整日志，不打包本机原生二进制去冒充现场依赖。

交付在 WSL `artifacts/releases` 准备、解包自检并校验后，将正式代码压缩包以及该次交付要求的 prompt/说明移动到 Windows 系统桌面。确认真实桌面路径、同名冲突和移动后 hash，在项目保留交付清单与源文档。用户负责带入内网，不自动上传内网或代替华为机执行实验。

华为 prompt 必须足以独立执行：明确沿用哪个现场 g5、只改哪些文件、先检查/备份再安装、off 对照、shadow/enforce 顺序、实验命令/配置、debug 可改范围、异常停止和回退、结果汇总。实验计划应在看结果前说明比较口径、排空/未完成处理及吞吐容忍度依据；若尚未约定性能判据，先交付工程正确性验证，列出待决点，不自行套用历史容忍度。

固定基线配置、数据、并发、热身/缓存/predictor 状态，分清开环与闭环；先做最小有判别力的对照和必要消融，避免同时改多个策略后归因给 LIFO。允许初版无收益或退化，如实报告并分析，不为得到收益静默筛样或改口径。

每轮让华为机回传一份自包含 Markdown：版本/模式/实际生效配置、遇到的问题、修改文件及关键函数或可应用 diff、安装/回退结果、run_id/时间/样本数/命令、TTFT/TPOT/吞吐、失败/取消/未完成数、已有队列/预算/释放证据、推断和风险。**关键源码、日志、表格和证据必须直接嵌入正文；不可访问的内网路径仅作索引。** 缺失写明，不要求完整目录或全量日志外传。

收到报告后：保留原文和 hash → 核对实际运行代码/参数 → 将现场必要修复纳入本机并补回归 → 整理对照结果及证据局限 → 给 Session 2 写“实现偏差、有效/无效场景、分类/预算敏感点、下一步设计建议”。区分实现缺陷与策略失效；只改代码并不能证明算法有效。没有新现场材料时先完成本地独立工作，然后准确报告等待项，不伪造进展或持续轮询。

## 7. 版本合并与阶段性完成标准

本任务包括开发提交、最终合入 main 和推送；沿用个人仓库无需 PR 的既定流程。不是要求现在立即合并。先在 `backup/20261022-init` 完成可审查的开发提交，仅暂存归属明确的文件；根仓库未提交的设计/启动文档也是可能存在的其他会话工作，不得 reset、clean、整仓覆盖或用 `git add .` 混入不相关改动。

合并前具备：关键正确性/取消/释放/关闭回退测试通过，新增已知缺陷有处置；现场验证和实验结论已回传并审阅；交付包对应源码可追溯；收益是否达到预先约定标准明确。若只达到实验基础设施阶段、收益未达目标或关键现场验证缺失，明确呈现状态，由用户决定是否阶段性合入，不把“本地测试通过”当作整体任务完成。

满足合并条件后，确认共享 checkout 无其他会话正在写入/切换冲突，核查远端最新状态和完整 diff，再按约定执行 `git switch main` → `git merge backup/20261022-init` → 必要验证 → `git push origin main`。不 force push，不改 origin，不自动引入 PR；远端若有新提交，先检查并正常整合，不覆盖。共享工作区的分支切换必须协调时机。

每个可交付版本更新实施记录、测试矩阵、已知限制、交付清单和给设计主会话的摘要，不能只用聊天作为进度存储。建议维护 `docs/engineering/GF_ADMISSION_IMPLEMENTATION_STATUS.md`，明确：当前 commit/配置、已完成与未完成、测试范围、现场报告来源、未解决问题、下一动作；实验材料按现有 `experiments` 结构保存。向其他 session 发消息需要用户明确授权与目标，默认通过共享文档和用户转交完成交接。

## 8. 现在开始

先完成 P0/P1 阅读和定点源码核对，检查当前分支、工作区修改及基线状态；给出简短的“理解、源码冲突/待决点、文件级实施顺序、测试安排”，随即在已批准范围内推进第一阶段实现。不要重新复现 FGJSQ＋predictor，不重新全面调研流量，不在开始前要求拿到完整华为环境或报告目录。


## 2026-10-22 用户批准：rc2 修复与统一高压让行

本节覆盖旧 rc1 可交付、同成本不让行及等待设计确认的时态。用户已批准编码 session 自主完成 R1–R4 修复、统一压力触发、观测/测试、完整新包及华为 prompt；Session 2 在完整交付后、正式 AISBench 前兜底复评，不干扰日常编码决策。不新增同成本/benchmark 分类开关。

统一准入：可信正成本及有效压力下，(成本偏长 OR 请求候选 P 的最低 FG score >= H)，再受共同 credit、数量 S、成本 V、年龄保护约束。normal 优先；tail 在实际候选 P score <= L 时放行，0 < L < H，每次 CAS 及候选切换重验。沿用 g5 公式、P/D 与 predictor；GF 限制实际入场并发也是合法机制效果，须与真实 LIFO 越序分别归因。

阈值是第一版静态超参数，由华为正式压测前先读已有实验结果，必要时在 B=16 × 实际输入 66K/128K 或生产重放中探测长尾等待附近的每 P FG committed_tokens、未释放数、score、有效事件时间和可得 waiting 指标；不能把引擎 waiting token 与 FG W 混称。报告实际 token 长度、来源和样本，选择 H/L 并冻结后跑正式六格（64K规格实际66K/128K × B16/18/20，cache目标50%）。TTFT预测动态阈值留下一版；不要求本地伪造阈值，也不因此停工。

新交付在 WSL 构建/解包校验后移动到 Windows 桌面；旧 dev1/rc1 归档、wheel、交付 prompt 副本已按用户要求撤回，源码和原评审证据保留。新包先复评、现场短验证、阈值探测和通知演练，再冻结长压测。后台脚本监控并通过实际可用 agent 接口通知故障，正常轮询不用模型；故障/修复/重启诚实留痕，变更版本后重跑受影响配对。

详细规则见 docs/admission/GF_PRESSURE_ADMISSION_REVISION_20261022.md；实施状态见 docs/engineering/GF_ADMISSION_IMPLEMENTATION_STATUS.md。当前仅完成审批与上下文同步，代码/测试/交付完成情况由实施状态后续更新；无现场性能收益声明，不合并 main。


## rc2 最终交付完成（2026-10-22）

覆盖前文“仅上下文同步/开始修复”的进度：R1–R4及统一高压让行实现已完成，代码提交75c5e519195b55ce314fc00bf81b068f382e9cb1；项目96通过、Motor309通过/8跳过，最终独立解包75通过、685文件SHA校验。新rc2包、prompt、指南、修复报告已从WSL移动到Windows桌面并核对hash；归档SHA b23cee6b81d6f4f8b87b1e6cfd6fc28e7e8ed4bab3512c4ab6a4a7cecd1b0121。交付凭据见docs/engineering/GF_ADMISSION_0.1.0rc2_DELIVERY_20261022.md。

下一步是Session2复评完整包、华为短验证/已有结果或必要短探测选择静态H/L/实际通知演练、冻结后跑六格AISBench。无需用户重建环境或增加GB流量采集。暂无NPU或性能证据，未合并main；共享未提交文档继续保留。
