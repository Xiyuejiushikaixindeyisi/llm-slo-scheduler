# 版本与环境

当前以 [onsite-g5-frozen-reported.json](onsite-g5-frozen-reported.json) 为现场身份记录，以 [g5-baseline-files.json](g5-baseline-files.json) 为本机冻结源码指纹。配置/启动环境见 `configs/baseline/g5-frozen`。本机仅CPU开发，现场依赖版本不强制安装到WSL。下文 g4 是历史来源，旧“Motor版本未知”已由最终报告中的构建串补充（现场全树commit仍未提供）。

sources.lock.json 锁定公开源码的完整提交、来源及本地路径，同时单独标记现场版本核验状态。vLLM-Ascend 采用 v0.23.0 标签，不自动跟随 releases/v0.23.0 分支。

[onsite-g4-reported.json](onsite-g4-reported.json) 已记录用户提供的 g4 取证：镜像 Image ID、arm64 架构、vLLM/vLLM-Ascend 完整提交、predictor 工件摘要及额外 wheel 版本。RepoDigests 为空，Image ID 不冒充 registry digest。Motor 现场版本仍未知，Python/CANN/TorchNPU/Mooncake 等运行时细项待补充。源码已检出不等于运行环境已复刻。
