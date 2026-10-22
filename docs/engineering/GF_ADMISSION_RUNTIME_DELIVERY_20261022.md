# gf_admission 0.1.0rc1 桌面交付记录

已在 WSL 构建、解包核验后移动至 Windows 实际桌面；移动前后 SHA256 一致。

源码提交：`546bc7d349c1ed24fdb4acd868ad28e409eb0c11`。79 项项目测试、309 项 Motor 测试通过，8 项跳过；最终交付归档解包后 58 项测试通过。无华为/NPU/AISBench 结果；Session 2 评审在后续实验之前。

| 文件 | 大小 | SHA256 |
| --- | ---: | --- |
| `C:/Users/ALIENWARE/Desktop/gf-admission-0.1.0rc1-20261022.tar.gz` | 1448273 | `3e97e3ebdbd930f9ec0c5892870d07f04e415a1cf96865ff309c67588d3b14e3` |
| `C:/Users/ALIENWARE/Desktop/HUAWEI_AGENT_PROMPT_GF_RUNTIME_0.1.0rc1_20261022.md` | 4502 | `2d54d318962a1db3b5040c3af33b715fcd44486ba45ac307d2a12844f0bc8df7` |
| `C:/Users/ALIENWARE/Desktop/GF_ADMISSION_RUNTIME_GUIDE_0.1.0rc1_20261022.md` | 12705 | `59186a787da553120c354e746a2cd72156b23a60fe1140aad16f92f59e38067d` |

完整实现/参数/门槛：[运行指南](GF_ADMISSION_RUNTIME_GUIDE.md)；测试与局限：[实施记录](GF_ADMISSION_IMPLEMENTATION_STATUS.md)。

此交付为完整本地 runtime 候选，替代旧 dev1 纯核心包作为后续评审对象。实际现场镜像兼容、native SHM、真实 P/D 和性能收益尚未验证，不直接开始十小时压测。

共享工作区原有五份修改文档及启动 prompt 保留；未合并或推送 main。
