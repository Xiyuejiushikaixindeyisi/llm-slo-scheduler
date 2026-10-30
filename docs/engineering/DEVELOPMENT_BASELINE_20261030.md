# 2026-10-30 研发基线：GF admission rc2、证据整理与下一轮 chunk 优化

本版是下一轮优化的可追溯研发起点，固定标签 **`baseline-20261030`**。用户已批准版本整理、提交和 GitHub 推送；本次按既定个人流程将 `backup/20261022-init` 合入 `main`，覆盖旧“无现场结果不合入 main”的阶段性限制。这个批准不等于 NPU 正确性或性能验收；后续提交和推送仍以当轮授权为准。

## 版本组成

| 层次 | 固定身份与状态 |
| --- | --- |
| 原始 g5 研发基线 | `3b63b00546e7a6ffb2526dafc341969cebe22359`；现场镜像与本机对齐边界见 [g5 对齐结果](G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md) |
| GF admission rc2 实现 | `75c5e519195b55ce314fc00bf81b068f382e9cb1`；交付记录提交 `8171c2da61a6fcfb3007e2fb30be57ce21b37337`；本轮不修改其运行源码、配置、补丁或包版本 |
| rc2 原交付包 | SHA256 `b23cee6b81d6f4f8b87b1e6cfd6fc28e7e8ed4bab3512c4ab6a4a7cecd1b0121`；[桌面交付记录](GF_ADMISSION_0.1.0rc2_DELIVERY_20261022.md)与[复评放行](GF_ADMISSION_0.1.0rc2_REVIEW_20261022.md)保留 |
| Chunk 研究 | [10 月 29 日统一入口](../modeling/README.md)、运行时批预算方向、时间约束纠正与 M/E/I 分工；模型/调研/B1 分析已完成，专题交接、集成设计、demo 与动态算法 NPU 验证尚未完成 |
| 项目与汇报 | [总工程师入口](../architecture/CHIEF_ENGINEER_SESSION_ENTRY.md)、[HTML 技术汇报](../reports/LLM_SLO_SCHEDULER_TECHNICAL_BRIEF_20261028.html)、来源与复核脚本；HTML 是 10 月 28 日快照，chunk 当前研究排序以 10 月 29 日入口为准 |

仓库地址：`git@github.com:Xiyuejiushikaixindeyisi/llm-slo-scheduler.git`。保留六个已有开发提交和全部历史，不 squash、不强推、不覆盖已有远程配置。标签固定的是项目快照，不另行发布 GitHub Release 或改变运行包版本。

## 本轮整理

- 纳入此前未提交的 rc1/rc2 评审、复现与本地测试证据、总工程师入口、HTML 汇报和 chunk 数学/业界调研材料，保留各会话现有修改。
- 更新根 README、文档索引、实施状态和协作入口，明确 rc2 已实现且本地复评通过；旧报告和交付原件不改写。
- 新增 `scripts/validate/run_rc2_local_tests.sh`：在独立 `artifacts/build/motor-rc2-validation/` 准备 g5＋rc2 钩子，以当前 runtime contract 校验后使用 Motor 规定的测试入口执行 CPU 回归。避免原 g5-only 指纹将合法 rc2 钩子误判为不匹配；不更改已有 `motor-g5` 开发副本。
- 忽略可重建的独立解包树和 HTML 中提取的 JavaScript 副本；原文件仍保留本地。小型原始验证日志及失败复现作为历史证据纳入版本，不删除或格式化历史证据。
- 原始现场 CSV/投递、模型、镜像、upstream、开发环境与交付压缩包继续保留本地，不纳入本次 Git 上传；GitHub 上的 HTML 正文/图表可离线使用，部分原始资料链接仅在完整本地工作区可用。

## 复核

本轮重新执行：项目 **96 passed**；Motor 配置/调度/路由 **309 passed、8 skipped**，合计 **405 passed、8 skipped、0 failed/0 errors**。7 项因本机无原生 SHM 库跳过，1 项为已有 endpoint `model_validate` 跳过；Python 3.13.11。历史交付的 75 项和 2 项评审补充不重复计入本轮。

rc2 runtime contract 及固定上游版本核验通过；运行源码、配置、补丁和包定义相对 `75c5e51` 不变。HTML 结构/锚点/本地引用复核通过：35 节、5 个内嵌 SVG、146 个链接、339 个唯一 ID、0 外部运行资源，内容 SHA256 仍为 `98c5b45edb73700810d2913606a2a2fb925eadcd167cd63ffb76cae382fd7770`。新增/待归档 Python AST、JSON、新 Shell 入口及 HTML 内嵌 JavaScript 语法检查通过。维护文件的 `git diff --check` 通过；研究文档/生成脚本仅清理行尾空白，内容不变。原始日志、补丁上下文及 HTML 内生成 SVG 的空白提示按文件记录于验证 JSON，为保持证据字节不改写。

结果、版本和日志 hash 见 [validation.json](../../artifacts/version-baseline-20261030/validation.json)，原日志/XML 位于同目录。最初尝试复用已带 rc2 的 `motor-g5` 被 g5-only 安装器安全拒绝，未改文件；最终入口改用独立副本后通过。此处记录准备阶段的问题，不将它称为运行算法故障。

复现：在根目录执行 `bash scripts/validate/run_rc2_local_tests.sh`。本轮未重建桌面交付包、未运行模型服务或 NPU 实验。

## 下一轮优化的固定边界

1. **共同目标与统计口径：**单 GF＋3P3D 集群，B16 是集群总并发而非每 P 16；AISBench 完成一条补一条，无整轮 barrier。全体请求 P90 TTFT 为主，吞吐提升或不下降，并满足分档 P90 TPOT SLO；失败/取消/未完成不能从总体消失。
2. **FGJSQ 与 TPOT：**继续保留两个当前问题：g4 相对同事 9.10 的约 +0.7～1.2 ms/token，以及 g5 相对 g4 的约 +7.5%。它们的对照版本不同，不相加成一个统一归因。
3. **GF admission：**rc2 本地评审通过，尚无新的现场性能证据。下一步仍为真实栈短验证、已有证据/必要短探测选择 H/L、通知演练、冻结后六格配对；入场并发调节与 LIFO 越序分别归因。合并不自动开启 enforce，不把示例参数当最优值。
4. **Chunk：**工程支持的运行时机制＋多项式成本＋剩余 TTFT/实例压力约束为当前方向；静态 B1 扫描是基线与反例，不是必须先大规模扫参的前置条件。M/E 交接后由 I 独立审阅并按任务开展 demo。P 保持原 FCFS/running-first，D 与 FG 公式不变，不提前引入 waiting 重排或 running/KV 抢占。
5. **证据限制：**B1 扫描 TTFT/TPOT 单位继续标“推定毫秒”、span 推定秒；每档单 r01，不能外推容量/高并发收益。完整现场 warm predictor 未取得；CPU mock/真实 IPC 均不替代真实 SHM/P/D/NPU 验证。

后续工作从标签读取完整上下文；最新进度优先更新维护入口，再链接版本化现场报告。旧初始版本说明、原件和 dated 汇报继续用于追溯。
