# 首次 Git 版本整理：g5 基线与 gf-lifo-p90 开发起点

日期：2026-10-22。用户确认允许添加缺失 `origin` 并推送 `main`；已有远程不擅自更改。目标：`git@github.com:Xiyuejiushikaixindeyisi/llm-slo-scheduler.git`。首次检查时本地已初始化、尚无提交、无 remote，远程仓库没有分支；无需再次 `git init` 或覆盖远程历史。

## 本次整理

| 文件 | 修改与原因 |
| --- | --- |
| `.gitignore` | 补充环境密钥、编辑器缓存、覆盖率和新测试输出；保留 docs/configs/tests/src/scripts/README 与实验计划/报告 Markdown。既有小型 g5 证据继续纳入版本 |
| `scripts/archive/20261019/prepare_engine_overlay.py`、相邻 README | 从 `scripts/dev/` 原样移动一次性历史生成脚本，避免再次运行造成重复注入；SHA256 保持 `b4cf3b192bf5ea9a87e82f8fb36e15f54976b78ac764cd15051db3b549e4ec67` |
| `scripts/dev/prepare_sources.py` | 按 sources.lock 获取缺失的固定上游源码；默认只检查，拒绝重置已有修改 |
| `scripts/validate/run_local_tests.sh` | 统一 CPU 测试入口，使用 Motor 规定的测试脚本；默认禁止在测试期间联网安装缺失依赖 |
| `tests/fixtures/g4_fgjsq_reference.py`、provenance JSON、`tests/unit/test_fgjsq.py` | 原对照测试依赖被 Git 忽略的完整原 proxy；现在只保存两个原样算法类作为测试参照，记录来源/行号/hash，并验证 AST 一致 |
| `README.md`、`tests/README.md`、`scripts/README.md`、`artifacts/README.md` | 补充当前运行步骤、首次 clone 恢复方式、个人分支流程，修正“无测试/无交付”的旧描述 |
| `THIRD_PARTY_NOTICES.md`、`licenses/` | 明确原始材料保留本地，并附上三个固定上游仓库的许可原文；未擅自选择项目新许可证 |
| `AGENTS.md`、本文 | 记录本轮授权、分工和版本交接约定 |

没有大规模目录重构，没有删除实验数据、报告、缓存或旧交付包。原始材料、大模型、镜像、venv、嵌套上游仓库和可重建开发副本留在本地，不重复进入根 Git。现有 docs 内的自包含交接/研究报告保留。

**FGJSQ / predictor / Motor adapter 共 21 个核心文件未变。** 算法版本仍为 `slo-patch 0.2.0`；Motor fix1 和 g5 对齐状态见 [对齐结果](G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md)。本轮不编写 gf-lifo-p90 算法。

## 验证与运行

在当前 WSL 项目执行：

```bash
cd /home/zhangxiyue/llm-slo-scheduler
bash scripts/validate/run_local_tests.sh
```

- 项目单元/集成测试 **37 passed**。
- Motor 配置与 backend 回归 **170 passed**。
- 合计 **207 passed，0 failed / 0 errors / 0 skipped**；比上一轮 199 项多出的 8 项来自现有流量采集脚本测试。
- 冻结指纹 **33/33 match**；算法参照夹具与原类 AST 一致。
- 新源码准备工具已用临时 Git 仓库验证获取固定提交、重复检查、拒绝覆盖脏目录。
- 语法、JSON、Shell 静态检查与提交内容检查记录在 `artifacts/initial-version-check.json`。无新增运行依赖。
- 新增维护代码的 `git diff --check` 通过。全快照检查仍提示历史日志、原始报告、许可原文和补丁上下文中的空白格式，逐文件记录在检查 JSON 中；为保持证据和补丁字节，未统一格式化这些文件。
- 可重复输出位于 `artifacts/local-validation/`，该目录被忽略；冻结 g5 证据仍保留版本。

本机没有运行 NPU 模型服务，也没有新增 TTFT/TPOT 性能结论。首次 clone 后按根 README 恢复固定源码及 CPU 开发依赖；原始现场投递不是运行当前对照测试的前提。

## 分支和直接合并

首次提交使用用户指定备注：`init: 项目首次上传`；描述为 g5 冻结源码、研究文档、测试与开发工具的初始快照。主分支推送成功后，在同一提交建立本地 `backup/20261022-init`，并切换到它作为 **gf-lifo-p90** 开发分支。不自动推送该分支，不要求 PR。

后续开发提交、测试通过后，按用户约定：

```bash
git switch main
git merge backup/20261022-init
git push origin main
```

这是会继续产生提交的功能开发分支；初始基线仍由 main 的首次提交保留，不把分支名误认为不可变备份。三个会话共享同一 checkout，切换分支会同时影响它们。

## 未完成能力与证据边界

1. `gf-lifo-p90`：独立 gf_admission 包和少量 hook 的架构已获批准，FIFO/LIFO 队列、取消/领取生命周期、分类与预算、off/shadow/enforce 及收益实验尚待实现。
2. chunk size 寻优仍处于数学建模阶段，尚未接入在线组批；本轮不改变共享 8192 token 预算。
3. 现场 warm predictor model、完整 fix1 源文件和全树 hash 未外传；本机保持报告支持的语义基线，不能宣称镜像/数值/性能一比一复现。
4. 正式十档实验的最终人工验收未在已有截止报告中完成；不能将 CPU 测试通过当成 SLO 达标。
5. 自包含文档保留现场路径与配置来源；其中的内网路径在 GitHub clone 后通常不可访问。历史打包/取证工具可能仍依赖本地原件，使用当前 README 列出的 g5 入口。
6. 没有本次新增的 CI、PR 流程或统一自动格式化依赖；不为了消除历史源码/原始证据格式差异而改写冻结算法。
