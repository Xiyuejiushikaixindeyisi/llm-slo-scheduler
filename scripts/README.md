# 项目工具

collect 用于现场材料收集；validate 用于版本、协议及交付检查；package 用于生成可安装、可回退的移交包。实现随源码和环境核对逐步补充。

g5 当前入口：`dev/prepare_g5_motor.py --with-tests` 准备本机副本；`validate/verify_g5_baseline.py` 校验源码；`deploy/g5_motor_install.py` 检查/增量安装/仅回退本次修改；`package/build_g5_alignment_bundle.py` 默认检查、`--stage` 准备新目录。旧0.2.0打包和安装脚本保留历史，不用于覆盖已冻结现场。说明见 `docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md`。

版本初始化：`dev/prepare_sources.py` 默认只检查固定上游，`--fetch` 仅获取缺失目录；`bash validate/run_local_tests.sh` 一次运行 CPU 检查与回归，不下载 NPU 依赖。一次性 `prepare_engine_overlay.py` 已原样归档至 `archive/20261019/`，不要对当前源码重新执行它。
