# 发布与移交

releases/<版本>/ 保存给华为实验机的交付包及清单，保留在本地、不重复进入 Git。正式交付压缩包按项目约定校验后移动至 Windows 桌面。

`build/` 为可重建源码副本；`local-validation/` 为重复运行的测试输出，均忽略。`g5-alignment/` 及已有小型测试摘要/日志是冻结基线证据，本次保留进 Git。新实验原始数据放 `experiments/runs/`；不要删除旧证据来“清理目录”。
