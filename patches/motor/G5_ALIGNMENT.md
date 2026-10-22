# g5 补丁边界与入口

基准 Motor：`f203263d9742dd6fa76eaef658e0ff3a0f380301`。

1. `f203263d-p-fgjsq.patch`：原七文件适配，保留不变。
2. `f203263d-g5-node-manager-lookup.patch`：独立 fix1，顶层端口优先，然后 nested extra_config，缺省 0；保留 int 转换、角色 offset 与 UCM 跳过逻辑。
3. `f203263d-g5-tests.patch`、`f203263d-g5-development-notes.patch`：仅测试与研发说明，不是运行补丁。

fix1 根据最终交接报告重建语义；现场完整文件及 SHA 未提供，不能宣称与现场逐字节一致。安装器对不同字节的现场修复拒绝覆盖；保留现场文件，审查实际 diff 后再决定是否需要适配。此差异不阻止以已通过 E2 的现场 g5 开展增量研究。

从项目根目录准备本机副本：

```bash
python3 scripts/dev/prepare_g5_motor.py --with-tests
python3 scripts/validate/verify_g5_baseline.py
```

当前研发副本为 `artifacts/build/motor-g5/`。`upstream/motor` 是干净上游，旧 `artifacts/build/motor` 保留为原七文件参考，不继续作为 g5 研发入口。

针对明确的源码目录，安装器默认只检查：

```bash
python3 scripts/deploy/g5_motor_install.py --motor-root /path/to/motor-parent
# 确需应用缺失补丁时，指定全新的回退目录：
python3 scripts/deploy/g5_motor_install.py --motor-root /path/to/motor-parent --action apply --state-dir /path/to/new-backup
python3 scripts/deploy/g5_motor_install.py --motor-root /path/to/motor-parent --action revert --state-dir /path/to/new-backup
```

`--target g5` 默认包含七文件和 fix1；`--target fgjsq` 仅管理原七文件。支持 pristine、仅七文件、仅 fix1、完整 g5；已装不重复写；混合/未知状态失败关闭。回退只撤销该次交易新装的文件，并拒绝覆盖安装后新增的修改。不要用旧 `install_motor_patch.py` 的 pristine-only 流程覆盖已冻结现场。

冻结现场无需重装算法 wheel。后续策略应叠加独立版本，禁用策略后回到完整 g5。
