# LLM 尾延迟与吞吐优化

本项目以现网 MaaS 开环流量下的 P90 TTFT 优化与 SLO 内服务能力提升为最终目标；高并发 AISBench 闭环实验用于验证同并发尾延迟或相同 SLO 下的并发承载能力。P95 TTFT 为补充指标，P90 TPOT 为约束。统一工作区为 `/home/zhangxiyue/llm-slo-scheduler`；后续代码、研究文档、原始材料、模型和实验记录均放在此目录下；华为交付压缩包在WSL准备并校验后移动到Windows桌面。

基线、入场设计、数学建模、入场编码与总工程师会话共享工作区：基线会话负责 Motor/g5 对齐；Session 2 负责双队列设计与评审；数学会话研究 chunk size 目标函数、批级成本预测与 KV 缓存宏观模型；入场编码会话负责实现、测试、交付及现场修复迭代；总工程师会话贯通进度、证据与技术汇报。已有 waiting 重排、保留 KV 的让行和释放 KV 的抢占保持 pending。研究边界为一个实例UUID对应的GF＋XPYD集群；双队列当前以GF（Motor/proxy）普通FIFO＋让行LIFO为主候选，P保持原生调度，D引擎及D路由保持现场基线。正式TTFT/TPOT统一AISBench口径。本机负责设计/编码/单元测试，华为机负责 debug/NPU 验证和完整压测，并回传关键源码与证据嵌入正文的自包含 Markdown。

## 入口

- [2026-10-30 研发基线说明](docs/engineering/DEVELOPMENT_BASELINE_20261030.md) · 固定版本 `baseline-20261030`，作为下一轮优化起点
- [项目总览与总工程师入口](docs/architecture/CHIEF_ENGINEER_SESSION_ENTRY.md) · [30–60 分钟 HTML 技术汇报](docs/reports/LLM_SLO_SCHEDULER_TECHNICAL_BRIEF_20261028.html)

- [会话分工与本机—华为机协作约定](docs/architecture/RESEARCH_COLLABORATION_AND_HANDOFF.md)
- [目录结构和维护约定](docs/architecture/WORKSPACE_LAYOUT.md)
- [新编码 session 完整启动 prompt](docs/engineering/GF_ADMISSION_CODING_SESSION_PROMPT.md)
- [研究文档索引](docs/README.md)
- [Chunk 当前研究入口与 fork 交接（2026-10-29）](docs/modeling/README.md) · [数学/工程/集成分工及启动提示](docs/modeling/CHUNK_RESEARCH_WORKSTREAMS_20261029.md)
- [研究指导文档](docs/LLM_TAIL_LATENCY_RESEARCH_GUIDE.md)
- [g5 GF双等待队列工程设计（独立包＋少量钩子已批准）](docs/admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md)
- [g5 最终冻结报告](docs/engineering/G5_FROZEN_BASELINE_HANDOVER.md) · [本机对齐审批稿与勘误](docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md)
- [g5 本机对齐完成：源码入口、验证与交付边界](docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md)
- [FGJSQ 与 predictor 复现计划](docs/engineering/FGJSQ_REPRODUCTION_PLAN.md)
- [早期成本函数与 KV 数学笔记](docs/modeling/CHUNK_SIZE_KV_CACHE_MATHEMATICAL_MODEL.md)
- [源码版本锁定](env/sources.lock.json)
- [实验机材料接收说明](evidence/README.md)

## 本地使用

当前 WSL 环境已有 CPU 测试依赖，从项目根目录执行：

```bash
cd /home/zhangxiyue/llm-slo-scheduler
bash scripts/validate/run_rc2_local_tests.sh
```

该命令核对固定源码，在 `artifacts/build/motor-rc2-validation/` 独立准备 g5＋rc2 Motor 副本，检查当前 runtime contract，并运行项目与 Motor 配置/调度/路由回归。输出在 `artifacts/local-validation/rc2/`，不会启动模型服务或下载 NPU 依赖。旧 `run_local_tests.sh` 保留为原 g5 历史入口，不能用其原始核心指纹验收已叠加入场钩子的 rc2。正式推理与性能验证仍在华为实验机执行；现场启动档位见 `configs/baseline/g5-frozen/`。

首次从 GitHub clone 后，`upstream/` 和 `.venv/` 不在仓库中：

```bash
python3 scripts/dev/prepare_sources.py --fetch
python3 -m venv .venv
source .venv/bin/activate
# Motor 自身已有的 CPU 开发/测试依赖；不安装 vLLM/NPU 运行栈
python -m pip install -r upstream/motor/requirements.txt pytest pytest-cov pytest-xdist
bash scripts/validate/run_rc2_local_tests.sh
```

`prepare_sources.py` 按 `env/sources.lock.json` 获取 Motor/vLLM/Ascend 固定提交，不重置已有目录；需要 diffusion 参考源码时加 `--repo vllm-omni --fetch`。离线环境须预先准备对应源码和 Python 依赖；本仓库不附带模型、镜像、原始现场投递。

## 个人开发流程

`main` 保存可复核的研发基线。`backup/20261022-init` 承载了 **gf-lifo-p90 / gf_admission rc2** 的开发提交；用户于 2026-10-30 批准将当前实现、评审、数学研究和汇报整理合入 main，并以 `baseline-20261030` 标记下一轮优化起点。该批准允许阶段性研发合并，不表示现场性能验收。采用个人直接合并方式，不需要 PR：

```bash
# 在 backup/20261022-init 完成开发、提交和测试后
git switch main
git merge backup/20261022-init
git push origin main
```

各会话共享同一 checkout，切换分支会同时影响所有会话；编码期间应使用同一分支，切换前先协调。当前版本、已知缺项及质量检查见 [2026-10-30 研发基线](docs/engineering/DEVELOPMENT_BASELINE_20261030.md)；[首次版本说明](docs/engineering/INITIAL_VERSION_20261022.md)保留历史。后续提交和推送仍需当轮授权。

## 当前阶段

**研发基线整理（2026-10-30）：**用户批准当前阶段进入 main，固定标签 `baseline-20261030`。GF admission rc2 已实现、交付并通过 Session 2 本地复评；华为真实栈短验证、H/L 标定与正式性能结果仍待完成。两层 TPOT 残差（g4 相对同事 9.10、g5 相对 g4）均继续跟进。Chunk 方向以 10 月 29 日入口为准；HTML 保留 10 月 28 日快照。详见上方版本说明。

**Chunk 研究更新（2026-10-29）：**当前方向是工程支持的运行时批预算决策：借鉴 DeepInfer、Ascend，结合多项式成本、请求剩余 TTFT 余量和实例压力，低成本约束累计完成时间。覆盖 10 月 28 日“静态优先、必要时才动态”的排序；已有 B1 现场扫描保留为基线证据。下一轮由用户 fork，数学与工程机制两线分别研究，后续新会话独立集成审阅并按任务开发 demo。当前已完成[文档与交接整理](docs/modeling/README.md)，未创建会话、实现动态预算或执行新实验。

**历史入场架构与编码交接（2026-10-22，完成状态已由 rc2 评审覆盖）：**独立 `gf_admission` 包＋少量 g5 显式钩子已批准；g5 基线已推送，commit `3b63b00546e7a6ffb2526dafc341969cebe22359`。用户选择新增编码 session 实现/测试/交付，Session 2 保持设计与评审，Session 3 负责数学建模；完整启动 prompt 见上方入口。本轮仅完成任务交接材料，尚未创建编码会话或实现算法。总目标为现网提升单卡吞吐、优化尾延迟。

**2026-10-22 更新：**用户已批准 A–D，已完成 [g5 本机基线对齐](docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md)：21 个算法核心文件保留，`artifacts/build/motor-g5` 含七文件适配＋NodeManager fix1，33 个指纹匹配、199 项 CPU 测试通过。配置/启动环境只同步为参考，未复刻 NPU 环境。当前基线为 `g5-g4base-motor-20261021-r1`（完整 g4 正式版引擎栈＋Motor）；现场 E2 两轮通过，报告截止时十档与人工验收仍未完成。该更新覆盖下列历史 rc1/仅冒烟状态；入场和 chunk 会话可从本机冻结源码开始增量研究。

以下为此前阶段记录：

2026-10-20 已接收 [g5 现场交接报告](docs/engineering/G5_BASELINE_HANDOVER.md)：实验机报告 3P3D FGJSQ＋predictor＋Motor 链路与冒烟通过；截至报告截止时 AISBench 尚未成功启动，无高压性能结论。本机未访问内网或运行 NPU。现场修改、证据边界和必要勘误见 [g5 研究上下文](docs/engineering/FGJSQ_REPRODUCTION_PLAN.md)。下一阶段以 g5 为起点讨论 super-p95 的入场分类与让行预算，候选为GF或P侧独立、默认关闭、可回退的demo/插件；不要求复刻现场环境，不提前实现 running/KV 抢占或动态 chunk。当前已收敛为9字段生产CSV离线分析，CSV留在内网；本机交付[处理脚本和说明](C:/Users/ALIENWARE/Desktop/CLUSTER_FLOW_PROFILE_DELIVERY.md)及[内网运行prompt](C:/Users/ALIENWARE/Desktop/HUAWEI_AGENT_PROMPT_CLUSTER_FLOW_PROFILE.md)，实验机回传单份Markdown。完整字段字典仅供备查；最新语义、已有等待实验与证据边界见研究指南第21节。本机8项合成测试及解包CLI冒烟通过。2026-10-21已收到[真实生产流量报告及核对](docs/traffic/CLUSTER_FLOW_PROFILE_ANALYSIS_20260924.md)：内网对单UUID的5,549条请求完成输入/命中/节奏画像；延迟单位和completion语义仍未解决，无P90或SLO结论。原 [工程交付说明](docs/engineering/FGJSQ_MOTOR_DELIVERY.md) 与 [agent prompt](docs/engineering/HUAWEI_AGENT_PROMPT_FGJSQ_MOTOR.md) 保留为交付历史。

历史约定（2026-10-21）：集中调研已结束，进入[GF侧super-p95方案讨论](docs/admission/GF_SUPER_P95_DESIGN_DISCUSSION.md)。主候选为GF普通FIFO＋让行LIFO、放行后沿用FGJSQ，P保持FCFS＋running-first＋共享token预算。Motor f203263d已确认有token化与分层KV前缀查询能力；分类credit、队列存量、前送窗口和年龄保护分开设计，尚未实施。两份报告及采用边界见[证据底稿](docs/admission/DUAL_WAITING_QUEUE_DISCUSSION_BRIEF.md)与[文档索引](docs/README.md)，不再以补齐负载模型或环境调查为前置条件。

## 目录总览

```text
llm-slo-scheduler/
├── README.md
├── AGENTS.md
├── docs/
│   ├── README.md
│   ├── LLM_TAIL_LATENCY_RESEARCH_GUIDE.md
│   ├── architecture/WORKSPACE_LAYOUT.md
│   ├── engineering/FGJSQ_REPRODUCTION_PLAN.md
│   ├── admission/
│   ├── modeling/CHUNK_SIZE_KV_CACHE_MATHEMATICAL_MODEL.md
│   ├── references/SUPER_P95_RESEARCH_AND_LLM_COMPARISON.md
│   └── decisions/
├── upstream/
│   ├── motor/
│   ├── vllm-v0.23.0/
│   ├── vllm-ascend-v0.23.0/
│   └── vllm-omni-super-p95/
├── src/
│   ├── fgjsq/
│   ├── motor_adapter/
│   ├── slo_patch/
│   ├── admission/
│   └── chunking/
├── evidence/
│   ├── huawei/
│   ├── source_drops/
│   │   ├── proxy/
│   │   └── slo_patch/
│   └── manifests/
├── env/sources.lock.json
├── configs/
│   ├── baseline/
│   └── experiments/
├── patches/
│   ├── motor/
│   ├── vllm/
│   └── vllm-ascend/
├── models/predictor/
├── tests/
│   ├── fixtures/
│   ├── unit/
│   ├── replay/
│   └── integration/
├── scripts/
│   ├── collect/
│   ├── validate/
│   └── package/
├── experiments/
│   ├── plans/
│   ├── runs/
│   └── analysis/
└── artifacts/releases/
```

## 版本与移交原则

根 Git 仓库管理我们维护的文档、src、配置、脚本、测试和补丁。upstream 下每个开源仓库独立保留 Git 元数据并固定提交，根仓库不重复收录它们的文件。原始取证、源文件投递、模型和大体积实验产物默认不进入根 Git，用清单记录来源、版本和摘要；它们仍保存在本工作区内。

2026-10-19 从原 vllm-omni 目录复制了三份研究文档，并修正新副本中的本地链接。后续只维护本项目中的副本；原目录和原文件保留供历史追溯。目录创建不代表 Codex 界面中的会话工作区已自动切换。


2026-10-22 rc2 修复交付入口：`docs/engineering/GF_ADMISSION_RC2_REPAIR_REPORT_20261022.md`；统一高压规则已获用户批准，阈值由华为正式实验前探测后冻结。旧 rc1 交付已撤回；[rc2 本地复评](docs/engineering/GF_ADMISSION_0.1.0rc2_REVIEW_20261022.md)通过，现场验收尚待完成。2026-10-30 用户另行批准当前阶段作为研发基线合入 main。
