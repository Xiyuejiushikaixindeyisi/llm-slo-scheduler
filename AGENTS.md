# 项目工作约定

## 工作范围

- 统一根目录：/home/zhangxiyue/llm-slo-scheduler。此项目之后的新代码、文档、数据、模型、运行日志和交付包均在根目录下准备；最终交付文件按下述桌面交付约定处理。
- 2026-10-22 用户已批准 g5 对齐 A–D，且明确算法优先、配置/环境只同步。已完成本机对齐与199项CPU测试，入口 docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md；不复刻NPU环境。未经后续方案确认，不提前实现 waiting 重排、running/KV 抢占或动态 chunk。
- 研究边界为一个实例UUID对应的GF＋XPYD（当前3P3D）集群；GB只作背景，不采集/研究GB。2026-10-21用户提出以GF普通FIFO＋让行LIFO为主候选；P保持FCFS、running-first和共享token预算。2026-10-22 用户已批准独立 gf_admission 包＋少量 g5 显式钩子；待 Session 1 完成 g5 修复、对齐、版本整理和 GitHub 推送后可基于设计编码。参数仍待细化/标定，本轮仅记忆与分工。
- 正式TTFT/TPOT统一AISBench口径：客户端HTTP POST前起点、首记录流式时间点计算TTFT，TPOT沿用同一汇总器；GF/P分段耗时仅作解释。
- D 引擎和 D 路由保持现场基线。主指标为全体请求 P90 TTFT，吞吐提升或不下降，并满足分档 P90 TPOT SLO；P95 为补充。
- 不能假设当前平均吞吐接近硬件容量。不能把本地逻辑验证、模拟器结果或公开源码版本等同于 910B2 现场性能或现场镜像。

## 三个会话（2026-10-22 用户确认）

- Session 1（Motor 适配/基线）负责跟进华为机，对齐本机 g5 源码、配置、安装/核验与交付契约，并完成基线修复、版本整理和 GitHub 推送。
- Session 2（入场与让行）负责 GF 双队列设计及后续实现/迭代：normal pending FIFO、sacrificial pending LIFO；接收 Session 1 修复、对齐及 GitHub 版本交接后推进。是否继续本会话编码、fork 或新建 session 留到下一轮讨论，本轮不决定或创建。
- Session 3（数学建模）负责 chunk size 目标函数、batch predictor 成本映射与 KV 宏观微分模型；当前维护 docs/modeling，不修改运行代码，工程接口需求另行协调。用户报告已完成模型 1.0/权重优化；微分方程联合求解仍是研究方向，不当成已验证成果；保留公式 d_k 与 d_2 的明确区别。
- 三个会话属于同一 work tree，共享工作区。src/motor_adapter、slo_patch 及补丁等共享文件变更先核对最新状态，不覆盖其它会话的改动。
- 工作闭环：本机设计/编码/单元测试 → 华为机 debug/NPU 验证/完整压测 → 单份自包含 Markdown 回传 → 本机核对与迭代。关键源码、diff、配置、实验结果和证据必须直接嵌入正文，内网路径只作来源索引；不要求完整内网目录外传。
- docs/LLM_TAIL_LATENCY_RESEARCH_GUIDE.md 和 docs/decisions 为共同结论入口。编辑共享文件前读取最新内容，保留另一会话的修改；不要同时重写整个共享文档。
- 详细分工与每轮现场回传契约：docs/architecture/RESEARCH_COLLABORATION_AND_HANDOFF.md。本机主导设计、编码、逻辑测试与迭代；华为机部署/debug/完整压测，必须将现场修改及关键源码、证据嵌入报告正文。本机不可直接看到完整内网结果，不要求全目录外传；现场修复经本机核对吸收后进入下一版。
- 总目标为现网提升单卡吞吐、优化尾延迟；高并发 AISBench 为极端验证场景。入场线决定谁执行，数学线研究每批执行量，两线分开归因和版本化。
- 不因本文件自动创建、fork 或向其他会话发送消息；本轮架构批准不自动批准 Session 1 独立的基线修复审批项，也不执行其 GitHub 推送。

## 源码与材料

- 版本权威记录为 env/sources.lock.json；现场核验状态与公开源码版本分开记录。
- upstream 是固定版本的独立仓库。优先在 src 维护算法、插件和适配层；确需更改上游源码时，将针对明确基准的补丁保存在 patches，并记录应用与回退流程。
- 原始投递放 evidence/source_drops，原始报告和日志放 evidence/huawei；保持原文件内容，记录 SHA256。分析结论写 docs 或 experiments/analysis。
- 修改任何 upstream 仓库前阅读其 AGENTS.md 和适用技能，遵守该仓库的构建、测试要求。
- 已有 vllm-omni 等旧目录为历史来源；新研究只引用本工作区中的维护副本及固定源码。

## 复现与交付

- 用户于2026-10-21确认：今后交付华为实验机的代码压缩包，均须先在WSL项目中准备并校验，完成后移动到Windows桌面（当前为C:/Users/ALIENWARE/Desktop，执行时通过系统桌面路径确认），不能只留在WSL。明确要求随包移动的prompt/说明也一并移动；移动前检查同名冲突，移动后校验SHA256，更新项目中的交付位置记录。研发源码、研究文档默认仍在项目内。
- 未收到原始实现前不要按摘要自行猜写 FGJSQ 公式、predictor 特征或训练标签并称其为复现。
- 保留实际 P 异步调度与 SLO=0 原生决策路径。核对请求 ID、批次 ID、提交/完成时序、预测单位、训练标签及负载释放。
- 本地通过确定性事件重放、算法输出对比及必要的接口测试验证逻辑；NPU 正确性和性能由实验机验证。
- 输出的安装包应有版本检查、P 侧启用边界和明确的停用回退方法。不可在本地编译不兼容的原生依赖后宣称可直接用于实验机。
- 不自动提交或推送根 Git 仓库，不对 upstream 进行破坏性清理。
- 2026-10-22 用户明确授权本次版本整理、首次提交、添加缺失 origin 并推送 main，已有 remote 不擅自更改。目标 git@github.com:Xiyuejiushikaixindeyisi/llm-slo-scheduler.git；随后创建本地 backup/20261022-init 用于 gf-lifo-p90（控制GF入场顺序优化P90 TTFT）。个人项目不用PR，用户指定流程为 switch main → merge backup/20261022-init → push origin main；后续提交/推送仍以当轮授权为准。

## g5 冻结基线（2026-10-22，覆盖下文旧 g5 身份与时态）

- 原件 docs/engineering/G5_FROZEN_BASELINE_HANDOVER.md，SHA256 `0995514a020978159fa49803e956380da435f2279cf9431f0920cbc5dbcc7aae`，保持原文；数据截至2026-10-21 13:09 UTC。核对与审批入口 docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md；证据清单 evidence/manifests/g5_local_alignment_audit_20261022.json。
- 冻结镜像 `vllm-ascend:g5-g4base-motor-20261021-r1` = 过程 tag `v0.23.0-motor310-g4base-r2`；完整 g4 正式版底座 vLLM 0fc695fc / Ascend 5cb98caa / torch_npu post4 加 Motor、FGJSQ、predictor；旧 rc1 不再是当前开发目标。本机两个引擎 upstream 已匹配、无需换源码。
- P 仍 async SchedulerWithPredictorAsync、SLO=0、FCFS/running-first/8192 token、max_num_seqs=24；D 原生 async，主模型 enforce_eager=false + FULL_DECODE_ONLY，MTP3 speculative enforce_eager=true。不能把全栈说成全 eager；D 算法保持基线，通信 env 需双侧对称。
- E2 128K B16 两轮各通过工程阈值：TTFT mean 38.18/38.49s、P90 43.84/43.76s；TPOT mean 13.2/13.1ms、P90均14.2ms；QPS .298/.2973；零失败。TPOT对g4仍约+7.5%，不称完全无回归。报告截止十档未完成，B1 TPOT mean/P90两项未过，用户最终验收待后续；业务128K P90 TTFT30s/TPOT40ms，TTFT仍未达标。
- 本机三个包21个Python/JSON文件与原交付及wheel一致；报告称现场沿用。已在 artifacts/build/motor-g5 补齐原七文件patch及独立NodeManager lookup_rpc_port fix1；旧 artifacts/build/motor 保留参考。新入口 scripts/dev/prepare_g5_motor.py、scripts/deploy/g5_motor_install.py、scripts/validate/verify_g5_baseline.py；33个指纹匹配，199项CPU测试通过。没有完整现场逐文件清单，不能宣称远程字节校验完成。
- 报告重要勘误：async_scheduler hash写为`...06f6a6...`，本机/原wheel/上游实测为`...06f6e6...`；activate摘录`import verify_engine()`语法错误。保留本机三锚，不能照抄或只回填hash。fix1已按报告重建顶层优先/nested/default0且保留int/offset/UCM，现场after仅前缀c098842c，本机46800951完整hash另存；这是语义对齐，不覆盖不同字节的现场修复。
- 算法语义以审批稿第5节源码核查为准：computed在_update_after_schedule提前推进；actual标签由patch_core写入，是主机提交/相邻取结果间隔；predict会改计数/日志，非严格纯函数；get_computed_blocks不等同touch/占块；reserve_window_s限制首次命令有效期，不是衰减周期/active TTL；score越大越不优先，系数非指数；HANDOFF先P后D，finish_attempt为abort双账兜底。
- 现场warm model未外传，本机只有占位目录，完整hash也未提供；不宣称数值复现。不因基线同步改predictor v1特征/标签或FG公式；新cost model由数学/工程会话另行版本化。所有后续策略应在已有g5上增量接入，可关闭回到完整g5，不全量覆盖现场修复。

## g5 上下文记忆（2026-10-20，历史）

- 原始报告：docs/engineering/G5_BASELINE_HANDOVER.md，保持原文；最新现场摘要和本机源码勘误：docs/engineering/FGJSQ_REPRODUCTION_PLAN.md 的 g5 节。先读两者，不能把报告中的工程建议等同已验证事实。
- 报告截止时 AISBench 尚未成功启动；链路通过不代表高压基线或收益已验证。P 为异步 predictor scheduler，FCFS＋running-first＋共享8192 token，max_num_seqs=24。
- g5交接用于补充上下文和设计可独立接入/回退的demo，不要求复刻内网环境或完整代码目录；历史P-only偏好已调整为GF/P位置待调研，D保持基线。
- 现场 Python 算法沿用交付包；Motor node_manager 有配置读取修复，安装后的 engine_files.json 已适配现场 Ascend hash。后续包不得覆盖这两项现场适配或丢失 predictor/async 链。
- 长 waiting 会通过 FG 预留账本反馈路由；预测是 batch 级主机观察耗时，非请求剩余 TTFT；不可将 legacy cache_hit_rate 当真实 KV 命中。
- 报告关于 computed 更新时间、缓存查询占块、事件数解释及“双队列必须改核心”的结论有勘误/待核对项，详见研究上下文；不能据此直接决定方案。

## 开环/闭环研究目标（2026-10-20）

- 用户确认：最终需要在现网 MaaS 开环流量下取得效果；AISBench 闭环用于同并发改善 P90 TTFT 或在相同 TTFT/TPOT SLO 下提高可承载并发。不能用闭环结果直接保证生产效果。
- 机制拆分见研究指南第17节，边界见第19节，最新可获取字段与执行安排以第21节为准。成本分类、FIFO＋老化、额度/存量/时间三类预算均是讨论候选，不是已批准实现；第18节旧采集清单已被替代。
- super-p95 的 step 让行、LIFO、路由折扣、可选 batch2 与双等待优先级必须分开归因；仅首次入场策略无法中断已 running 的长 prefill。
- MaaS 结构已由用户补充，见研究指南第18节：AI鉴权→多GB租户并发403/规格分流/VIP局部队列/集群路由→单集群GF协议转换/实例路由→P/KV/D。流量分布仍待采集；不预设P入口为泊松。

## MaaS最新业务约束（2026-10-20）

- 长度分流后32K/64K/128K是独立路由的逻辑规格；研究同规格集群内的流量构成、跨P状态及P内候选差异，不默认跨规格混排。GF实际到达是本轮建模输入，上游结构仅作背景。
- GB以无chat template的JSON tokenization分流只是背景；本轮不要求GB/引擎长度配对。研究集群内真实prompt长度与可得P命中差异，不预设GB偏差。
- 用户已确认B=16为整个3P3D集群总施压并发，不能再乘3个P得到48。各GB自行计运行请求，从Redis读到E2E完成后自行减一；多GB面向同一集群的限额分配/协调未知，不能因使用Redis就假定全局原子限额。
- 新口述SLO：32K 12s/32ms，64K 27s/30ms，128K 30s/40ms（TTFT/TPOT）；40ms按最新业务描述记录，旧45ms属历史。用户已明确正式计时对齐AISBench，不再以首有效content重定义终点，也不将计时起点列为未答问题；公开路径见指南18.5。
- GB计数/E2E反馈仅保留背景，本轮不采GB队列、限额或协调信息。集群内完成、取消和失败仍用于完整统计，不扩展到GB排查。
- 排队论可以用于单集群建模；完整分布拟合不是前置条件。计划先用GF到达标记与各P路由/队列/批服务状态判断分类、让行预算和GF/P放置，保留P/D ID避免集群平均掩盖局部积压。
- FGJSQ的泊松/异质适用、稀疏/同质闭环弱收益属于待验证场景假设；不认定泊松是必要条件或AISBench必然无效，不以总在途数直接代替P忙闲。
- 用户反馈第20节字段过多难以获取，已收敛为9列：instance_uuid/hash_id/appid/model_handle_start_time/prompt_tokens/completion_tokens/cached_tokens/model_ttft/model_tpot。第20节仅备查，不要求补齐P ID、batch或候选。
- 本批用户配置：生产64K，原生proxy，3P3D/TP4/24×910B2/Qwen3.6-27B W8A8/v0.23.0，8192 token、max_num_seqs=16；历史g5的24保持为历史，不把本批自动标为FGJSQ/Motor g5。
- request_time已确认是请求到达时间（未导出）；model_handle_start_time是UTC、对齐约定TTFT起点。历史用户口径completion_tokens为输入＋输出；本批数据已发现系统性冲突，当前暂停派生输出，见后续记忆。cached_tokens为prefix命中。两种延迟单位尚未知，交由内网按表头/来源核对，不猜量级。
- CSV只在内网可读；用户已授权本机规划和编写离线分析脚本+prompt，由华为机执行并回传一份Markdown。工具scripts/collect/profile_cluster_csv.py、prompt及说明见研究指南第21节；不访问数据库或改运行服务。
- 已接收EXP_10.9生产trace重放/EXP_10.12闭环等待摘要，原件evidence/huawei/2026-10-20-waiting-study/WAITING_RUNNING_OPEN_CLOSED_REPORT.txt。waitproxy不是queue_time，聚合分位不能相减成阶段等待；无突发不证明ρ≈1，Erlang-B不证明闭环队列无界。
- 9列可支持流量/成本异质性和尾部构成画像，不能精确复原入场等待、实例负载或反事实收益。实际cached是后验信息，不自动作为在线可知特征；不要求先补完整日志。

- 九字段离线包cluster-flow-profile-0.1.0-20261020.tar.gz及对应运行prompt、使用说明已于2026-10-21从WSL移动到C:/Users/ALIENWARE/Desktop，三文件SHA256校验一致（记录：artifacts/releases/cluster-flow-profile-0.1.0-20261020.delivery.json），8项合成测试、解包校验和CLI冒烟通过；真实CSV仍只在内网，2026-10-21已接收流量画像报告，最新结论与限制见下节。


## 生产流量报告记忆（2026-10-21）

- 用户要求原文归档到docs：docs/traffic/CLUSTER_FLOW_PROFILE_REPORT_20260924.original.md（完整附件字节，SHA256 b42c5fe3ad7fa58f7f7373e421fb6e3673d263936a58c24f979f02c6ace5ae63）；核对为同目录CLUSTER_FLOW_PROFILE_ANALYSIS_20260924.md，入口为研究指南第22节。
- 实验机分析单UUID 9a1c5866-aab8-4229-ae4c-51686b863d6e的5,549条、2026-09-24约两小时UTC处理起点。配置仍是用户背景；不将原生proxy流量标为Motor g5，也不以九UUID推翻用户的集群粒度（原SQL无UUID过滤）。
- 输入<8K占20.33%，零命中45.50%，高命中≥90%占12.58%；≥32K零命中应为1,268条/22.85%，约47.7%uncached。原文1,235条只含32—64K、工作量约45.9%；两者不要混用。
- 0.7712次/s、17.2K uncached token/s、Fano 1.218/1.281/3.122是处理起点的描述，非执行吞吐、利用率或泊松证明。成本异质性不证明同P候选竞争、实际阻塞或双队列收益。
- 延迟单位仍未知、有效延迟样本0；0违约不能读成达标。completion<prompt为5,548/5,549，历史总token语义与本CSV冲突；输出量暂不可用，未授权自行改口径。
- 8192为每轮组批预算，不是单请求输出上限；原报告以completion≥8192判硬异常错误。空UUID骨架记录不可归给目标集群，也不能解释为确定的过载丢日志。
- 实验机在副本加D/M/Y UTC解析，报告测试通过；本机原脚本hash吻合，补丁未回传。本轮仅文档，不改脚本/调度、不产新代码包。
- 后续优先确认TTFT/TPOT单位和completion赋值语义，仍只回传修订Markdown；不要求完整CSV外传或全链路日志。分类、让行预算、GF/P位置均待讨论，不将22.85%高成本组直接全体降级。


## 最后一次历史资料调研边界（2026-10-21）

- 用户再次明确：负载建模不是重点。以EXP_10.14_TRACE的等待时间、running/waiting和等待分布研究为主，以EXP_10.9核对生产重放原始资料，做最后一次既有材料只读调研。不得将报告目录名直接当运行身份。
- 内网执行prompt：docs/engineering/HUAWEI_AGENT_PROMPT_FINAL_WAITING_REVIEW.md；仅回传FINAL_WAITING_AND_ADMISSION_EVIDENCE.md。关键源码、日志/表格、指标定义、计算过程和来源身份须嵌入正文，不能只给不可访问路径。
- 只读现存文件，可离线汇总；不做实验、不重放、不压测、不改代码/环境、不新采集、不查询在线服务补数。缺项写明/跳过，不把后续采集作为交付前提。
- 本轮报告回来后必须转入super-p95有效机制、双队列请求分类/让行预算及GF/P兼容讨论。未解决字段和环境项保留为假设边界，不自动追加流量/环境调研，不要求完整负载模型。此前“优先补字段”只在这次现存范围内核对，不形成继续采集任务。


## 两份报告已接收，下一轮只讨论算法（2026-10-21）

- 最终报告原件：docs/traffic/FINAL_WAITING_AND_ADMISSION_EVIDENCE_20261021.original.md（SHA256 29a964d3342d94a72e8c9f73cfa2783a67610e82e10e4128d91b6729a28b301a），核对：同目录FINAL_WAITING_AND_ADMISSION_REVIEW_20261021.md。两份原始资料均保持字节不变。
- 主入口：docs/admission/DUAL_WAITING_QUEUE_DISCUSSION_BRIEF.md及研究指南第24节。EXP_10.14_TRACE是10.9/10.12二次分析；生产记录、g2历史实验、g5 Motor不能混成同一性能总体。
- 集中流量/环境调研已结束。单位、completion、逐请求分解、完整候选集和容量等未决项接受为设计边界；不再自动要求补数据或调研，只有用户明确要求才重开。
- 历史开环F的TTFT P90 15.444s、P首次queue P90 7.811s；N为16.859/8.746s。52.5%为126/240个池化快照非零，并非等待请求占比。126k_B16 waiting均值引用6.94（三P、10s稳态窗），旧5.87停用。
- 不能采用R2的“waitproxy是等待下界”“66k运行内4.2s已定位”“ρ≈1工作默认”“边际分位证明同时竞争”等推断。66k首次queue较小只作能力边界线索，不定位其余阶段。
- FG retention=5%是scheduled负载预测保留，不保证最低进展；D首非空body释放不是入场保护。FG waiting项包含running请求后续未调度量，不是让行队列存量。未入场通常无事件、全额预留持续，会反馈路由。
- 下一轮讨论：super-p95分类/优先级/step暂停/路由折扣分别有什么作用；只改首次入场的边界；分类、四类预算（额度/存量/驻留或越过/最低服务）、GF预留前后与P入场前放置。保留g5旧SLO硬关、async链、事件身份、双释放和D基线。本轮未改任何调度代码，不做实验。


## GF双队列主候选与Motor能力核对（2026-10-21）

- 最新讨论入口：docs/admission/GF_SUPER_P95_DESIGN_DISCUSSION.md及研究指南第25节；替代前一节“下一轮讨论”的时态。用户优先借鉴super-p95，GF普通FIFO＋让行LIFO为主候选；推荐在P预留前等待、放行后沿用FGJSQ，具体接口未批准。
- 固定Motor f203263d源码已核对：kv_cache_affinity可复用engine_token_ids或套chat template编码，Conductor按实例/DP返回NPU、CPU、Disk连续前缀互斥覆盖。此前“GF只有body/4”仅限当前src/motor_adapter/bindings.py的FG估算路径，不能再表述为Motor无KV感知能力。查询是否接入g5仍区别于源码能力，不重开现场调查。
- 用户补充集群有Mooncake式KV池化。CPU/其他层可用KV不等于目标NPU已驻留；计算量代理与加载代价分开，原始命中与weighted affinity分数分开。Conductor tenant_id不能自动当业务appid；appid只作辅助先验/分组，不能固定让某租户承担让行。
- super-p95源码明确普通FIFO、让行LIFO，意图是让较新让行请求先完成，把更长等待集中于少数较老请求。分类、额度、普通优先、LIFO与step暂停共同构成原型；没有模块消融就不声称某一项已证明独立有效。历史吞吐代价仍保留。
- 原型每20次到达补1分类credit（默认）不是队列长度上限、时间保护或滑窗比例；完全等成本不满足long/min分类条件。P90不直接对应10%让行。
- GF无法暂停已经派发的请求。需区分分类credit、让行存量（数量/工作量）、前送放行窗口、年龄/越过保护；把请求全发进P后再讨论GF LIFO无实质控制权。普通为空且有可用放行空间时及时取LIFO，不能无条件等待未来短请求。
- 保留FG预留/批事件/释放契约，门控不以scheduled当完成、不以D E2E作为唯一补发信号。P/D调度不变，running/KV抢占、动态chunk和代码实现仍pending。本轮仅源码核对与文档讨论，不采集、不实验。


## LIFO释放规则澄清与压力拟合方向（2026-10-21）

- 用户提出按每P的FGJSQ token负载/压力拟合排队曲线，调节LIFO释放条件及预算；已纳入docs/admission/GF_SUPER_P95_DESIGN_DISCUSSION.md第9节。不是要求用户提供算法阈值。
- “提前放行”仅指P尚在执行时GF将后续请求发到其waiting，不是提前执行。统一前送窗口是可选扩展；首版可普通请求沿用现有派发、仅对LIFO施加P压力条件，不要求重做全部普通队列门控。
- 原型已有出队规则：active继续；需要新active时先普通、无有效普通才LIFO。普通可在step边界抢占active让行，新让行不会抢占旧active让行。分类credit不是出队credit。
- GF普通队列为空不等于P普通工作已排空。拟合可使用committed_tokens、FG未释放请求数或既有score；均为账本估计，不是准确running数或剩余token。批8192预算/已占KV不能直接作为此压力。
- 候选释放：普通GF候选空且FG选中可用P压力低于阈值时出LIFO，每条reserve后重算，检查与实际派发P一致；年龄保护另议。曲线尚未拟合，预算函数/阈值待设计。本轮仅文档，无实现、实验或新采集任务。


## 双队列工程设计 v0.1（2026-10-21）

- 用户本轮仅要求初步设计文档，已写docs/admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md。含17节、类图/状态图/两张时序图/活动图与部署数据流、U/I测试矩阵。尚未实现或运行新测试，不创建华为交付包。
- 主推荐：独立gf_admission包＋g5适配层窄hook；Mgmt统一轻量FIFO/LIFO，worker保留HTTP；OrderedDict支持按ID取消、期限heap、有界特征准备、每worker单WaitHub。接口/文件名都是拟新增，不能以后误称已存在。
- 源码核对：HANDOFF先P且延后D；先D是g5拒绝的TRIGGER，不能拿它当g5 P allocate长等待会占D的证据。首版P allocate生成reserve命令前接入即可，不改unified_pd核心。
- Motor dispatch timeout=5s；采用短enqueue和有界long-poll，不能直接悬挂原reserve。新RPC须区分transport CANCELLED与timeout并继续传播取消。
- FG候选压力检查必须在同锁CAS前且每个fallback候选重验。推荐service提取等价locked helper＋可选candidate_guard，默认分支保留g5语义；policy/账本/事件/双释放保持基线。
- QUEUED无资源，后台READY_RESERVED有短交付租约且需claim；CLAIMED不能由该租约自动释放。普通fast path一个RPC直接reserve/CLAIMED，失联复用原key查询/清理。结果未知不得fallback重复分配。
- 保留现场NodeManager fix1和engine_files.json，不全量重装slo-patch。off/shadow/enforce分开；压力、beta、队列上限与时限待标定。源码hash清单evidence/manifests/gf_dual_queue_design_sources_20261021.json仅作设计来源，不是部署allowlist。


## 2026-10-22 用户批准：rc2 修复与统一高压让行

本节覆盖旧 rc1 可交付、同成本不让行及等待设计确认的时态。用户已批准编码 session 自主完成 R1–R4 修复、统一压力触发、观测/测试、完整新包及华为 prompt；Session 2 在完整交付后、正式 AISBench 前兜底复评，不干扰日常编码决策。不新增同成本/benchmark 分类开关。

统一准入：可信正成本及有效压力下，(成本偏长 OR 请求候选 P 的最低 FG score >= H)，再受共同 credit、数量 S、成本 V、年龄保护约束。normal 优先；tail 在实际候选 P score <= L 时放行，0 < L < H，每次 CAS 及候选切换重验。沿用 g5 公式、P/D 与 predictor；GF 限制实际入场并发也是合法机制效果，须与真实 LIFO 越序分别归因。

阈值是第一版静态超参数，由华为正式压测前先读已有实验结果，必要时在 B=16 × 实际输入 66K/128K 或生产重放中探测长尾等待附近的每 P FG committed_tokens、未释放数、score、有效事件时间和可得 waiting 指标；不能把引擎 waiting token 与 FG W 混称。报告实际 token 长度、来源和样本，选择 H/L 并冻结后跑正式六格（64K规格实际66K/128K × B16/18/20，cache目标50%）。TTFT预测动态阈值留下一版；不要求本地伪造阈值，也不因此停工。

新交付在 WSL 构建/解包校验后移动到 Windows 桌面；旧 dev1/rc1 归档、wheel、交付 prompt 副本已按用户要求撤回，源码和原评审证据保留。新包先复评、现场短验证、阈值探测和通知演练，再冻结长压测。后台脚本监控并通过实际可用 agent 接口通知故障，正常轮询不用模型；故障/修复/重启诚实留痕，变更版本后重跑受影响配对。

详细规则见 docs/admission/GF_PRESSURE_ADMISSION_REVISION_20261022.md；实施状态见 docs/engineering/GF_ADMISSION_IMPLEMENTATION_STATUS.md。当前仅完成审批与上下文同步，代码/测试/交付完成情况由实施状态后续更新；无现场性能收益声明，不合并 main。


## rc2 最终交付完成（2026-10-22）

覆盖前文“仅上下文同步/开始修复”的进度：R1–R4及统一高压让行实现已完成，代码提交75c5e519195b55ce314fc00bf81b068f382e9cb1；项目96通过、Motor309通过/8跳过，最终独立解包75通过、685文件SHA校验。新rc2包、prompt、指南、修复报告已从WSL移动到Windows桌面并核对hash；归档SHA b23cee6b81d6f4f8b87b1e6cfd6fc28e7e8ed4bab3512c4ab6a4a7cecd1b0121。交付凭据见docs/engineering/GF_ADMISSION_0.1.0rc2_DELIVERY_20261022.md。

下一步是Session2复评完整包、华为短验证/已有结果或必要短探测选择静态H/L/实际通知演练、冻结后跑六格AISBench。无需用户重建环境或增加GB流量采集。暂无NPU或性能证据，未合并main；共享未提交文档继续保留。
