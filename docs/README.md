# 研究文档索引

本目录是基线适配、入场策略、数学建模三个会话共享的研究入口。结论需要区分用户报告、对应版本源码事实、论文结论与待验证假设。当前 g5 身份以最终冻结报告及本机核查为准；旧 rc1 文档保留为历史。

| 内容 | 位置 | 主要维护者 |
| --- | --- | --- |
| 三会话职责、本机/华为机分工、批准状态与现场回传契约 | [研究协作约定](architecture/RESEARCH_COLLABORATION_AND_HANDOFF.md) | 三会话共享；2026-10-22 用户确认 |
| 总体研究目标、基线及边界 | [研究指导文档](LLM_TAIL_LATENCY_RESEARCH_GUIDE.md) | 主会话协调 |
| 目录、模块与接口架构 | [工作区结构](architecture/WORKSPACE_LAYOUT.md) | 主会话 |
| FGJSQ、predictor 和 Motor 适配 | [复现计划](engineering/FGJSQ_REPRODUCTION_PLAN.md) | 主会话 |
| 源码核对、Motor 文件级改动与人工审批 | [适配审批稿](engineering/FGJSQ_MOTOR_ADAPTATION_REVIEW.md) | 主会话；已批准 |
| g4 原始代码投递 | [投递清单](engineering/G4_SOURCE_INTAKE.md) | 用户提供原件，主会话接收 |
| g5 最终冻结现场事实 | [最终冻结交接](engineering/G5_FROZEN_BASELINE_HANDOVER.md) | 用户提供原件，不改写；E2通过，十档验收待后续报告 |
| 本机与冻结 g5 对齐：文件差异、应改/保留项及源码勘误 | [对齐审批稿](engineering/G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md) · [核查清单](../evidence/manifests/g5_local_alignment_audit_20261022.json) | 基线会话；A–D已批准，历史审查记录保留 |
| 当前 g5 本机源码入口、已完成修改、测试与交付边界 | [对齐结果](engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md) · [冻结指纹](../env/g5-baseline-files.json) | 基线会话；199项CPU测试通过，配置/环境只同步参考 |
| 早期 g5 rc1 链路状态（历史） | [早期交接报告](engineering/G5_BASELINE_HANDOVER.md) · [当时的核查](engineering/FGJSQ_REPRODUCTION_PLAN.md) | 保留历史，不作为当前部署目标 |
| 当前主候选：GF普通FIFO＋让行LIFO、KV分类与放行预算 | [GF方案讨论](admission/GF_SUPER_P95_DESIGN_DISCUSSION.md) · [两份报告证据底稿](admission/DUAL_WAITING_QUEUE_DISCUSSION_BRIEF.md) · [研究指南第25节](LLM_TAIL_LATENCY_RESEARCH_GUIDE.md#25-gf普通fifo让行lifo主候选2026-10-21) | Session 2；GF 架构已批准，参数待细化，未实施 |
| 双队列工程初稿：架构、异步协议、文件级接入、故障与测试 | [g5工程设计 v0.1](admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md) | Session 2；独立包＋少量钩子已批准，待 Session 1 对齐/版本整理/推送后编码 |
| 完整SQL字段字典（历史备查，已收敛为9字段） | [研究指南第20节](LLM_TAIL_LATENCY_RESEARCH_GUIDE.md#20-sql导出逻辑字段字典2026-10-20) | 主会话维护需求，用户映射数据库 |
| 2026-09-24生产流量建模原始资料与核对（单UUID、9字段） | [实验机原文](traffic/CLUSTER_FLOW_PROFILE_REPORT_20260924.original.md) · [分析与勘误](traffic/CLUSTER_FLOW_PROFILE_ANALYSIS_20260924.md) | 用户提供报告；主会话核对 |
| 最终等待/入场调研（已完成，原始资料） | [实验机原文](traffic/FINAL_WAITING_AND_ADMISSION_EVIDENCE_20261021.original.md) · [核对与采用范围](traffic/FINAL_WAITING_AND_ADMISSION_REVIEW_20261021.md) · [历史prompt](engineering/HUAWEI_AGENT_PROMPT_FINAL_WAITING_REVIEW.md) | 原文不改；集中调研已闭合 |
| chunk size、成本函数与 KV 模型 | [数学笔记](modeling/CHUNK_SIZE_KV_CACHE_MATHEMATICAL_MODEL.md) | Session 3；数学建模，当前不改运行代码 |
| Diffusion 原型与论文阅读 | [super-p95 对比](references/SUPER_P95_RESEARCH_AND_LLM_COMPARISON.md) | 三会话按主题维护 |
| 共同采用的设计决定 | decisions/ | 主会话协调 |

当前9字段离线分析：[交付说明](C:/Users/ALIENWARE/Desktop/CLUSTER_FLOW_PROFILE_DELIVERY.md) · [内网执行prompt](C:/Users/ALIENWARE/Desktop/HUAWEI_AGENT_PROMPT_CLUSTER_FLOW_PROFILE.md)；CSV留在内网，仅回传分析Markdown。

实验原始结果放 experiments/runs；整理后的分析放 experiments/analysis。原始内网材料通常存evidence；本次流量原报告按用户要求完整存docs/traffic，接收hash仍存evidence/manifests。正文使用相对链接引用。三份已有研究文档的迁移记录见 [迁移清单](../evidence/manifests/workspace_import.json)。

当前工程交付：[FGJSQ＋predictor＋Motor 说明](engineering/FGJSQ_MOTOR_DELIVERY.md) · [实验机 agent prompt](engineering/HUAWEI_AGENT_PROMPT_FGJSQ_MOTOR.md)。
