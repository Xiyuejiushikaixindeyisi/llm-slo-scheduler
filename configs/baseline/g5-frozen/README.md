# g5 冻结配置参考

来源：`docs/engineering/G5_FROZEN_BASELINE_HANDOVER.md`（截至 2026-10-21 13:09 UTC）。本目录同步现场配置语义，不是本机启动方案。

- `motor-config.reported.json`、`fgjsq.reported.json`：报告正文原样提取。
- `nm_launch_pd_hccl.reported.sh`、`Dockerfile.reported`：报告原样提取；保留现场路径、网卡、TAG 等上下文，**不能直接执行**。
- `runtime-contract.json`：对称 HCCL 环境、P-only 插件开关、唯一 JOB_NAME、启动顺序和十档压测参数的结构化摘要。

采用最终镜像 `vllm-ascend:g5-g4base-motor-20261021-r1`。原配置内残留的 rc1 image 字段不等于实际运行镜像，不能据此退回 rc1。保持 P async/SLO=0/8192 token/max_num_seqs=24；D 主模型 `enforce_eager=false`、`FULL_DECODE_ONLY`，MTP3 的 speculative `enforce_eager=true`。不要为了脚本字面对称把 D 改成全 eager。

后续交付复用华为机已固化启动链，增量加载策略。WSL 只核对源码与 CPU 逻辑，不构建相同 NPU 依赖、权重、网络或容器。
