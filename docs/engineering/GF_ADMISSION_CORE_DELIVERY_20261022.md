# gf_admission 纯核心交付说明（2026-10-22）

用途：华为机离线 CPU 逻辑与 Python 兼容性验证。不是线上 admission 插件，不支持 shadow/enforce，也不能验证 TTFT/TPOT/吞吐收益。

源代码 commit：7055b220c6ac640ef32837e4bbe0ff50b22bbf19。
包内有独立 wheel、可重建源码、22 项测试、原型 oracle、微基准脚本、逐文件 SHA256 和完整运行 prompt。
WSL 解包验证：22 passed；wheel 隔离导入和逐文件 SHA256 通过（Python 3.13.11）。华为 Python 3.12 未验证，需按 prompt 执行。
既有统一回归 229 passed、冻结指纹 33/33 为本机证据，不是现场结果。

## 文件完整性

- gf-admission-core-0.1.0.dev1-20261022.tar.gz
  SHA256: `849da295b8541a4b6b8fc9d1f54f650cdcda2ebe37c910df8af7ddbaf0bbda01`
- HUAWEI_AGENT_PROMPT_GF_CORE_20261022.md
  SHA256: `a93e11a476273011ad6c331e9af03f9f45d96c93648f282cf5e83895cbc05354`

请将代码压缩包、prompt 和本说明一起带入内网，将 prompt 正文交给华为 agent。
解包后运行 `python scripts/validate/verify_gf_core_bundle.py`，不安装到生产环境。
回传一份自包含 `GF_ADMISSION_CORE_VALIDATION_REPORT_20261022.md`。
不需要停止服务或重新复现 FGJSQ/predictor；本包不会使真实请求进入 GF 双队列。

## 下一阶段门槛

1. broker/原子预留：同 key 至多一个有效预留、queued 无资源、每个 CAS fallback 候选重验压力、每次成功 reserve 后重算。
2. 等待协议：取消传播；READY 与 CLAIMED 分开；丢 ACK 查同事务；租约不回收已执行请求；清理失败有明确残余记录。
3. 集成与回退：多 worker 和真实 IPC/fake P-D 测试；off 等价；shadow 不影响派发；启用失败不能静默回原路径；安装/逆补丁保护现场 fix1。
4. 现场实验：前三项具备后交付 runtime 包，先 off/shadow，再 enforce。固定数据、负载、缓存与 predictor 状态，报告全体成功请求延迟及失败/取消/未完成/排空。
5. 合入 main：现场正确性及实验报告回传审阅、修复可追溯、收益按预先约定标准判断。吞吐容忍度未约定，不套用历史 -10%；不足时须用户决定是否阶段性合入。

依据是已批准设计第4–5、7–13、15–16节及编码任务第4–7节；另外，实际 Motor dispatch timeout=5s、transport 把取消转成 CANCELLED、reserve_deadline 在现有 worker 中提前生成，决定了必须有短 RPC、取消传播与服务端临预留生成命令。
纯核心到此是阶段进度，不是等待华为环境的强制关卡；上述 broker/协议/IPC 工作可以继续在本机实现。
