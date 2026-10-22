# g4 原始代码投递清单

统一根目录：`/home/zhangxiyue/llm-slo-scheduler`。本批次为 `g4-20261015`，对应栈 TAG `20261015_134536`。依据：[实验机取证报告](../../evidence/huawei/2026-10-19-g4-forensics/FGJSQ_P_ONLY_REPRO_FORENSICS.txt)。

## Proxy 代码

本地投递目录：

```text
/home/zhangxiyue/llm-slo-scheduler/evidence/source_drops/proxy/g4-20261015/
```

优先提供实验机冻结路径 `EXP_10.14/code_patch/proxy/load_balance_proxy_finegrained_p3d_pdhybrid.py`，保留文件名。它是报告确认的 g4 实际版本；`load_balance_proxy_finegrained_p3d.py` 和 `load_balance_proxy_finegrained.py` 是历史对照，不能替代 g4 文件。有 DOC2、相关 diff 和自有 import 依赖时一并放入，历史文件可放 `historical/`。

## 引擎插件

本地投递目录：

```text
/home/zhangxiyue/llm-slo-scheduler/evidence/source_drops/slo_patch/g4-20261015/
```

把实验机项目根 `/mnt/esfs/zhangxiyue/slo_patch/` 或冻结副本 `EXP_10.14/code_patch/engine_side/slo_patch_src/` 的内容放在此目录。setup.py 位于本地投递根，其下才是 Python 包 slo_patch；保留原有子目录。

```text
g4-20261015/
├── setup.py
├── slo_patch/
│   ├── __init__.py
│   ├── activate.py
│   ├── patch_runtime.py
│   ├── patch_core.py
│   └── slo/
│       ├── __init__.py                     # 若原包有此文件，保留
│       ├── scheduler_with_predictor.py
│       ├── batch_event_reporter.py
│       ├── predictor.py
│       ├── predictor_impl.py
│       └── batch_reporter.py               # 报告标为旧路径，也可保留
├── repro_wheels/                           # 可随后补充
├── REPRO_部署手册_新集群.md                 # 若可提供
├── FGJSQ_介绍.md
├── SLO_介绍.md
└── Overhead与精度_专题讨论.md
```

其他自有模块、包配置及依赖清单保持原名和相对位置。无需提供 __pycache__ 或 editable 安装产生的 egg-info。若先给最小文件集，优先 setup.py、activate.py、patch_runtime.py、patch_core.py、scheduler_with_predictor.py、batch_event_reporter.py、predictor.py 和 predictor_impl.py，并保留原包的 __init__.py。

## 启动脚本与模型

| 材料 | 本地投递目录，相对于统一根目录 | 内容 |
| --- | --- | --- |
| g4 启动脚本 | evidence/source_drops/stack_scripts/g4-20261015/ | run_2p2d_exp.sh、stack_up_g4.sh；相关配置保留相对结构 |
| 原始预训练模型 | models/predictor/g4-20261015/ | model.pkl，保持原始字节 |
| 运行期模型和评估日志 | models/predictor/g4-20261015/runtime/ | 按 P0/P1/P2 与原 predictor_results 目录分别保存，避免覆盖预训练模型 |
| 后续日志、配置与证据 | evidence/huawei/2026-10-19-g4-forensics/ | launcher.log、launch_env.txt、脱敏事件等；已归档报告勿覆盖 |

报告给出的预训练 model.pkl SHA256 是 `142f3364e8d7d8de58da62477b3fe852a797aa4cc8c79c582dda985853b54c9c`；文件到达后再核验。模型字典已包含 scaler/gbr，若原包还有外置工件也请保留。

Windows 文件资源管理器入口：

```text
\\wsl.localhost\Ubuntu-22.04\home\zhangxiyue\llm-slo-scheduler
```

## 接收后的处理

原始文件留在 evidence/source_drops，记录 SHA256 后审查调用链与依赖。可交付适配进入 src/fgjsq、src/motor_adapter 和 src/slo_patch。只创建了投递目录，没有生成占位的 .py 或模型文件。

当前四个源码仓库已检出并固定提交。vLLM 与 vLLM-Ascend 完整 SHA 与报告一致；Motor 为用户指定的设计提交，报告明确原 proxy 栈没有部署 Motor，因此不声称 Motor 版本与现场一致。

## 收到源码后需核对的报告细节

1. reporter 的 `req_id[:-9]` 和 Motor 的请求身份如何映射，不能直接把截尾规则作为通用接口。
2. 报告将 `(prompt-computed)/prompt` 称为 cache_hit_rate；按这个表达式它随已计算进度变化，不能直接等同于 APC 命中率。需确认字段来源和 N_uncached 是否确为本批实际计划 token 数。
3. 异步训练标签与 batch 的对应、计时边界需读取 patch_core 和 scheduler 源码确认；报告中的“已对齐”不能替代这一验证。
4. 新报告给出的无效样本规则允许 hit=0，与此前 g2 描述存在差异；按 g4 原实现核对。
5. D 在 g4 仍有 Hook3 chat_utils 防御包装，而无 predictor/reporter。后续保持 D 现场基线，不因仅 P 侧迁移而删除 D 已有兼容逻辑。
6. trace 与批日志关联是时间窗推断，尚无直接请求 ID 链接，不作为已完成的端到端事件重放样本。

## 2026-10-19 接收与审查进展

已收到 g4 proxy、9 个 slo_patch 包内文件，以及用户在聊天中粘贴的 setup.py（已原文归档），共 11 个代码文件。SHA256 与来源见 [接收清单](../../evidence/manifests/g4_source_intake_20261019.json)。原始文件未进行适配改写。

源码核对、确定性原函数检查和 Motor 文件级方案已完成，见 [适配审批稿](FGJSQ_MOTOR_ADAPTATION_REVIEW.md)，等待用户人工审批后实施。src 和 upstream 尚未修改。上述“收到源码后需核对”的 1–5 项已有源码结论，其中 ID 关联不相容、特征命名和异步标签边界已明确；历史现场行为仍需 trace 补证。模型、wheels、启动脚本尚未收到。