# gf_admission 实施记录

更新：2026-10-22。开发分支 `backup/20261022-init`。本次入场基线及启动时远端 main 均为
`3b63b00546e7a6ffb2526dafc341969cebe22359`。

**阶段状态：纯核心开发里程碑 0.1.0.dev1；不是可部署的 admission 版本，整体任务未完成。**
未接通 Motor，不提供可用的 shadow/enforce，不将安装 wheel 称为启用成功。
没有现场回传、NPU 验证或收益结论，不满足合入 main 条件。

## 本次完成

- 完整读取启动 prompt、当前设计，按 P0/P1 核对 g5 与实际源码；P2 阅读原型分类、取序和迁移证据。
- 新增独立 `src/gf_admission` 与 `packages/gf_admission`，保留 slo-patch 0.2.0 构建范围。
- 分类器：先补 credit 再分类；正值历史 min/max、双阈值、credit cap、unknown/保护/预算回退。
  容量与 nonce 去重必须由未来 broker 在调用分类器之前完成；当前纯函数不承担请求身份协议。
- 纯队列：normal FIFO、tail LIFO、normal 优先、按 key 幂等移除、S/V 上限、有限 K 候选、
  有界到龄/强制晋升至 normal 尾部。无 reserve/释放副作用。
- 成本：候选实例/endpoint/generation 对齐、互斥 NPU/CPU/Disk 覆盖、显式 beta 与版本、
  过期/未知回普通；不把 weighted affinity 当 cached_tokens，不改变 FG body/4 估算。
- 压力：显式 `fg_score`/`g5_score_v1` 单位及版本校验、包含等号的阈值；未实现拟合曲线或事件健康跟踪。
- 从 dd9c0895 原样冻结分类片段及 provenance，3,044 次正值分类与原型逐步对照；
  固定 seed 的 5,000 步队列重放逐步检查次序和 S/V。夹具未按实现修改。
- 自包含源码暂存、独立 wheel 构建与隔离导入检查；容器访问轨迹微基准。

没有修改 `src/fgjsq`、`src/motor_adapter`、`src/slo_patch`、Motor 或引擎源码。
启动时已有的 AGENTS、README、docs/README、设计文档、分工文档及启动 prompt 保留，
不纳入本会话开发提交。`.gitignore` 仅新增本会话可重建输出目录。

## 源码核对与冲突裁决

| 来源 | 事实或冲突 | 影响与处理 |
| --- | --- | --- |
| `unified_pd.py:_create_attempt/_run_handoff_stream_attempt` | HANDOFF 先 P，P 完成才申请 D；TRIGGER 才先 D | 原 P allocate 创建 command 前可接入，不改 router 主流程 |
| 设计 §3 的旧行号/旧 Motor 目录 | 设计快照不等于当前部署 allowlist | 接入目标采用 motor-g5 实际文件和冻结 manifest；新 hook 另建差异 manifest |
| `scheduler_server.py:_handle_request_async` | 普通 dispatch timeout 5s | broker 等待必须用短 enqueue＋有界 long-poll；不能悬挂原 reserve |
| `scheduler_client.py:send_request_result` | 捕获取消并返回 CANCELLED；原 `_rpc` 仅使用 send_request | 新 AdmissionClient 必须重新抛取消；结果未知查同 key，不 fallback |
| `bindings.py:allocate` | 当前在 worker 先创建 reserve_deadline | enforce 要推迟到 Mgmt 真正 reserve 时创建，并冻结 canonical command |
| `service.py:_reserve` | CAS 后部分提交异常会尝试 release，但未检查 release 返回值 | 新 bridge 必须保留清理未确认记录并阻止再派发；不得吞异常或尝试另一 P。当前未改变既有 g5 行为 |
| `conductor_api_client.py:query_conductor` | 同步 HTTP、3s timeout、独立客户端与熔断 | 不能在共享锁/事件循环直接调用；后续 provider 保留协议与认证并限制执行资源 |
| `kv_cache_affinity.py` | 有 token/template 复用及分层覆盖，weighted score 另算 | 本次只实现纯快照/成本，尚未声称在线 provider 接通 |
| 设计固定最大驻留＋FIFO tail 插入 | 所有待晋升项 deadline 与插入顺序一致 | 队首检查即可；不用年龄 heap，没有惰性失效项。READY 租约以后独立管理 |

这些处理没有改变批准的策略语义。运行参数未标定不阻塞基础实现，但不会生成伪生产默认值。

## 本地结果与证据

本次先实际重跑统一入口，起点 **207 passed（37＋170），33/33 指纹匹配**。
最后统一入口 **229 passed（59＋170），0 failures/errors/skips**；新增 22 项均为纯核心测试。
这里的 0 skips 仅描述已执行的测试集合，不表示下面未实现的 I02–I10 已覆盖。

- 入口：`bash scripts/validate/run_local_tests.sh`，未安装 NPU 栈。
- 持久摘要与源码 SHA：`evidence/manifests/gf_admission_core_20261022.json`。
- 原始本地输出：`artifacts/gf-admission/baseline/`、`regression-final.log`、
  `python310-smoke.log`、`container-benchmark.json`、`core-build-final/manifest.json`。
- Python 3.13.11：上述完整 CPU 测试；Python 3.10.12：隔离导入、分类、队列晋升冒烟通过。
  系统 3.10 无 pytest，未运行完整测试；Python 3.12 未验证，不能称现场版本矩阵已通过。
- 浮点 V 使用补偿求和，新增“大成本移除后保留小成本”的回归；V 仍是冻结成本估计、受浮点精度限制。
- `git diff --check` 通过。冻结 33 项内容未变。

### 需求—测试—缺口矩阵

| 设计 ID | 本次结果 | 未覆盖/下一验证 |
| --- | --- | --- |
| U01 | PASS：原型分类 oracle、同质/unknown/零成本、双阈值边界 | broker 首次逻辑请求入口 |
| U02 | PARTIAL：补给、cap、守恒、队列移除不退款 | nonce/attempt/transport 去重 |
| U03 | PASS（纯容器）：FIFO/LIFO、优先级、取消、heap oracle 重放 | broker 事务出队 |
| U04 | PARTIAL：数量/工作量上限、移除/晋升扣减、非法数值 | 动态预算不在首版；broker 原子扣账 |
| U05 | PARTIAL：score 单位、未知、阈值 | 事件陈旧、真实 FG snapshot、CAS guard；曲线未实现 |
| U06 | PASS（FakeClock）：边界晋升、normal 尾部、有界批量 | HTTP 请求期限与 worker 失活 |
| U07–U09 | NOT IMPLEMENTED | 指纹/epoch/submission_round、原子 reserve、READY/claim/expire |
| U10 | PARTIAL：pending/key/S/V/扫描上限；无年龄 heap | 墓碑、通知缓存、字节/worker 总容量 |
| U11 | PARTIAL：纯分层成本、过期、unknown、generation | tokenizer/Conductor、有界 executor 与线程取消 |
| U12 | NOT IMPLEMENTED | 取消传播、shielded cleanup、任务关闭 |
| I01 | 原 g5 既有回归 PASS；宿主未修改 | 未来含 off hooks 的真实回归仍须跑 |
| I02–I10 | NOT IMPLEMENTED / NOT RUN | 多 worker、真实 IPC/SHM/fake HTTP、故障、安装逆补丁与背压 |

未实现项不是“因没有华为环境而跳过”。broker、WaitHub、hook 和可在本机运行的故障/IPC 测试仍是后续本地工作。

### 容器测量

`scripts/validate/benchmark_admission_containers.py`：seed=20261022，各规模100轮；
先入队，随机取消25%、晋升25%，排空其余；三容器逐次输出一致。时间按整个轨迹计，
P99 用排序后的下取整秩；tracemalloc 单独跑，报告 Python 分配峰值而非进程 RSS。

| 初始项数 | OrderedDict P50/P99 µs | deque P50/P99 µs | heap P50/P99 µs |
| --- | --- | --- | --- |
| 16 | 3.81 / 5.43 | 3.06 / 5.43 | 5.25 / 9.84 |
| 256 | 48.97 / 99.42 | 115.17 / 151.41 | 123.23 / 197.58 |
| 4096 | 1076.76 / 1523.41 | 19477.31 / 20660.14 | 2798.57 / 3208.68 |

仅支持当前按 ID 取消/晋升访问模式采用 OrderedDict；不是普适最优证明。
未测锁、事件循环、FG recompute/prune、RPC 次数、在线热路径与 NPU 吞吐；不对这些给出收益结论。

## 构建及交付状态

`scripts/package/build_gf_admission_core.py` 把版本化源文件复制到独立 source tree，
将构建相对路径改为 stage 内的 `src`，无网络依赖下载，构建 wheel 并校验隔离导入。
最新本机产物为 `artifacts/gf-admission/core-build-final/`；早期 core-build/wheels 是中间产物，勿交付。
独立 wheel 不包含 fgjsq/motor_adapter/slo_patch 或 vLLM entrypoint。

上述为首阶段开发自检产物。用户随后要求提供代码包＋prompt：现新增
`scripts/package/build_gf_core_validation_bundle.py`，用于**华为离线 CPU 核心验证**，
附 `HUAWEI_AGENT_PROMPT_GF_CORE_20261022.md`，解包复验后移动 Windows 桌面。
这不是可运行的 shadow/enforce 交付。线上版本仍欠：显式 hooks、兼容 manifest、
接入自检、安装/回退、runtime schema/模板及真实链路实验 prompt。
现场报告吸收与 main 合并均尚未开始。交付位置/hash 另见 gf_admission_core_delivery_20261022.json。

## 给 Session 2 的设计建议与下一实施步骤

1. 保留当前固定预算＋score 门控；不用未拟合的毫秒曲线。原型对照已支持分类规则实现一致，不能据此推断 LLM 收益。
2. 下一阶段先完成同锁 `reserve_locked`/逐候选 guard 与 `CLEANUP_PENDING`，再接 broker；
   优先测 CAS 失败后换候选重验、每次 reserve 重算、取消/claim/expire 和 release 未确认。
3. 逻辑记录由 broker 唯一拥有，纯分类器不再另造 nonce 账本；保持“已知 UNAVAILABLE 才能增加 submission_round”。
4. 一条每 worker 的 WaitHub，强制传播 CANCELLED；先完成 unknown FeatureProvider，再接有界真实查询。
5. 安装包与完整华为 prompt 应在协议和回退具备可审查结果后产出。吞吐容忍度尚未约定，
   首轮现场先做工程正确性；不继承历史 −10% 门槛。

当前无新现场材料需要等待，也没有向其他 session 自动发消息。后续本地工作按上述顺序继续，
不以补全环境或完整 trace 为前置条件。
