# 双层优化项目的文件结构

统一根目录为 `/home/zhangxiyue/llm-slo-scheduler`。三个会话共享同一个 worktree：Session 1 负责 Motor/g5 基线，Session 2 负责入场与让行，Session 3 负责数学建模且当前不修改运行代码。职责、批准状态和现场交接以[2026-10-22 协作约定](RESEARCH_COLLABORATION_AND_HANDOFF.md)为准。目录按内容的来源与用途划分，不按会话复制工程。

## 完整结构

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

## 代码的位置

| 位置 | 内容 | 维护方式 |
| --- | --- | --- |
| upstream/motor | 指定 f203263d 提交的 Motor | 独立 Git、固定基准 |
| upstream/vllm-v0.23.0 | vLLM v0.23.0 | 独立 Git、固定基准 |
| upstream/vllm-ascend-v0.23.0 | vLLM-Ascend v0.23.0 标签 | 独立 Git、固定基准；不跟随 releases 分支漂移 |
| upstream/vllm-omni-super-p95 | dd9c0895 的参考实现 | 只用于源码对照 |
| evidence/source_drops/proxy | 用户提供的原 proxy 代码及 diff | 原始投递，保留来源与文件摘要 |
| evidence/source_drops/slo_patch | 用户提供的原 slo_patch 包 | 原始投递，保留来源与文件摘要 |
| src/fgjsq | 提取后的 FGJSQ 算法与账本 | 收到源码后实现；尽量不依赖 Web 框架 |
| src/motor_adapter | Motor 入口、事件与生命周期接线 | 收到接口证据后实现 |
| src/slo_patch | 我们交付的 P 引擎插件 | 与原始投递分开，保留可核对的差异 |
| src/admission | 入场分类及让行预算 | 基线通过、方案讨论后再实现 |
| src/chunking | 动态 token/chunk 算法的未来实现 | 当前仅预留；数学会话不写实现 |
| patches | 必须施加到固定上游版本的补丁 | 按 motor、vllm、vllm-ascend 分目录 |

上表保留初建工作区时的目录规划。2026-10-22 更新：`src/fgjsq`、`src/motor_adapter`、`src/slo_patch` 已有基线实现；不再视为占位。入场线已批准独立 `gf_admission` 包＋少量 g5 显式钩子，其拟新增文件布局以[工程设计](../admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md)为准；本轮不新建包或移动源码。

## 文档与实验材料

- docs/engineering：基线复现、调用链、兼容差异、交付与回退说明。
- docs/admission：分类条件、让行预算及其边界。waiting 重排和 KV 抢占仍为 pending。
- docs/modeling：数学假设、符号、推导、反例和与工程接口的对应。
- docs/references：论文、工业技术资料和 super-p95 源码调研。
- docs/decisions：双方采用的方案及变更理由，每项使用独立文件。
- evidence/huawei：现场报告、版本取证、原始日志和脱敏轨迹，按一次交付建立目录。
- evidence/manifests：来源、接收时间、文件 SHA256 和适用版本。
- env：源码锁定与后续运行时依赖锁定。conda/venv、镜像缓存需要时也放项目目录内。
- configs/baseline：核对后的实际部署配置；configs/experiments：只包含实验变更。
- models/predictor：模型、scaler、特征定义及模型版本清单。
- tests：确定性用例和小型固定数据；真实日志仍留在 evidence 或 experiments/runs。
- scripts：采集、校验与打包工具；experiments/plans：实验计划；experiments/runs：原始运行产物；experiments/analysis：分析结果。
- artifacts/releases：给华为实验机的发布包，包含版本清单、必要源码/补丁、配置、校验及回退说明。

## 版本管理

采用一个根 Git 仓库管理项目自身的文件，upstream 下各仓库独立管理并由 env/sources.lock.json 锁定完整提交。当前不使用 submodule，以便后续离线移交和现场核对。

原始材料、模型和大体积产物不自动进入根 Git；文件清单进入版本管理。这不是备份方案，完整移交或备份时应显式包含需要的原始材料。发布包应选择必要内容，不把整个 upstream 和所有实验结果一并打包。

每次改动上游源码必须能从固定基准和 patches 重建；不要把只存在于 upstream 工作树的手工改动作为唯一交付物。通常先用独立插件和适配层接入，是否必须 patch 由实际接口决定。

## 资料流转

原始文件进入 evidence → 记录来源与 SHA256 → 核对源码版本和接口 → 在 src 维护可交付实现 → tests 做逻辑核对 → artifacts/releases 打包 → 实验机运行 → 结果回到 experiments/runs → 结论写 experiments/analysis 和 docs。

历史研究文档复制后以本项目中的版本为维护入口。旧目录不会被删除或移动；本项目不依赖指向旧目录的软链接或共享 Git 对象。
