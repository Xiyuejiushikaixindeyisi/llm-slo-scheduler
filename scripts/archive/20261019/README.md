# 一次性生成记录

`prepare_engine_overlay.py` 是 2026-10-19 从现场投递生成首版适配代码的历史脚本，原样保存。它依赖私有原始投递和旧绝对路径，反复运行会重复注入内容，**不能用来初始化、更新或修复当前 g5**。

当前可复现的源码已进入 `src/`，新机器使用 `scripts/dev/prepare_sources.py --fetch` 和 `scripts/dev/prepare_g5_motor.py --with-tests`。本次归档只移动脚本，没有删除源材料、实验结果或修改算法。
