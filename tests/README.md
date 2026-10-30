# 逻辑与接口验证

unit 放算法单元验证；replay 放原实现与迁移实现的确定性事件对照；integration 放 Motor 与引擎接口验证；fixtures 只放小型、固定的测试数据。真实运行数据放 evidence 或 experiments/runs。

当前已有 FGJSQ 等价事件重放、账本/取消/释放、SSE、Motor 接口、EngineCore 控制流、采集脚本与安装回退测试。项目根执行 `bash scripts/validate/run_rc2_local_tests.sh`，统一使用 Motor 规定的 `bash tests/run_tests.sh` 入口；结果保存在 `artifacts/local-validation/rc2/`。

`fixtures/g4_fgjsq_reference.py` 是现场原 proxy 的两个算法类原样摘录，来源/行号/hash 见相邻 provenance JSON。它使对照测试无需依赖未纳入 Git 的完整现场投递；不要修改夹具来迎合新算法。硬件与性能实验仍由华为机执行。

当前入口在独立 `artifacts/build/motor-rc2-validation/` 准备并核对 rc2 钩子，避免用原 g5 指纹误判合法变更。原 `run_local_tests.sh` 仅保留为 g5 历史入口。当前基线结果见 [版本说明](../docs/engineering/DEVELOPMENT_BASELINE_20261030.md)。
