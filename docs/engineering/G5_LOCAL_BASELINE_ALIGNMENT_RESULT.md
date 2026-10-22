# g5 本机基线对齐结果

日期：2026-10-22。用户已批准 [审批稿](G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md) A–D，并明确“算法核心最关键，配置、启动环境只同步，本机不复刻正式实验环境”。本次按此边界完成本机同步；不代表现场十档压测最终验收。

## 1. 后续两个研究会话从哪里开始

**算法核心沿用 `slo-patch 0.2.0`，本机 g5 源码基线已就绪。**

| 用途 | 当前入口 | 约束 |
| --- | --- | --- |
| FGJSQ 算法、预留账本与 Motor 接口 | `src/fgjsq/`、`src/motor_adapter/` | 保留冻结语义；新入场策略增量实现、可关闭回到 g5 |
| predictor、reporter、EngineCore overlay | `src/slo_patch/` | 不改 v1 特征、训练标签、事件身份和 async/SLO=0 路径 |
| 含原七文件适配和 NodeManager fix1 的 Motor 研发副本 | `artifacts/build/motor-g5/` | 公开锚 f203263d；只作 CPU 开发与源码接口核对 |
| vLLM / Ascend 固定源码 | `upstream/vllm-v0.23.0/`、`upstream/vllm-ascend-v0.23.0/` | 保持干净；对应 0fc695fc / 5cb98caa |
| 冻结指纹 | [env/g5-baseline-files.json](../../env/g5-baseline-files.json) | 记录基线，不随新策略修改而偷偷更新 |
| 现场身份、依赖与缺失证据 | [onsite-g5-frozen-reported.json](../../env/onsite-g5-frozen-reported.json) | 报告事实与本机检查分开 |
| 配置、HCCL 环境、启动顺序和压测档位 | [configs/baseline/g5-frozen](../../configs/baseline/g5-frozen/README.md) | 参考资料；复用现场启动链，不在 WSL 运行 |

旧 `artifacts/build/motor/` 保留为原七文件适配参考；新的本地开发应使用 `motor-g5`。`upstream/motor/` 不打补丁。三个会话共享工作区，本次未修改入场设计、数学文档或引入新调度策略。

本机快速复核：

```bash
cd /home/zhangxiyue/llm-slo-scheduler
python3 scripts/dev/prepare_g5_motor.py --with-tests
python3 scripts/validate/verify_g5_baseline.py --output artifacts/g5-alignment/fingerprint-check.json
```

准备脚本不会 reset 既有 checkout，已有补丁重复运行不重写；遇到不匹配停止。新策略修改完成后严格基线指纹报差异是预期行为，应另建策略版本/差异清单。

## 2. 实际修改与保留

| 审批项 | 已完成内容 | 核心语义影响 |
| --- | --- | --- |
| A | 新增独立 NodeManager fix1 补丁/指纹；新建可重建 `motor-g5` 副本；补齐 Motor 测试和开发记录 | 修复配置读取；FGJSQ 七文件原补丁保留 |
| B | 同步最终 g4-base 镜像身份、源码锚、冻结配置和角色环境；只读采集增加 fix1、21 核心文件、模块路径/依赖 | 不装 NPU 依赖，不新建启动编排器 |
| C | smoke 补认 `delta.reasoning`；新增安全安装/回退、基线检查和版本化打包入口；CPU 回归通过 | 不改变 Motor 字节观察器和 AISBench 指标口径 |
| D | 三个包 21 个 Python/JSON 文件全部不变，三个引擎文件不变，D 调度/路由不变 | 保留完整 g5 算法基线 |

21 个文件与 2026-10-19 原交付目录/wheel 相同；冻结报告称现场沿用。指纹检查通过 **33/33**：21 核心文件＋3 引擎锚文件＋8 个 Motor 运行文件＋原始交接报告。Motor 八个文件的 after hash 表示本机可重建状态；这不是对内网机器的远程逐文件认证。

NodeManager 修复的决策片段为：

```python
if store.get(KV_CONNECTOR_KEY) != UCM_CONNECTOR:
    if LOOPUP_RPC_PORT_KEY in store:
        lookup_rpc_port = store[LOOPUP_RPC_PORT_KEY]
    else:
        extra = store.get(KV_CONNECTOR_EXTRA_CONFIG_KEY) or {}
        lookup_rpc_port = extra.get(LOOPUP_RPC_PORT_KEY, "0")
    config.lookup_rpc_port = int(lookup_rpc_port) + lookup_rpc_port_offset
```

即顶层优先、nested 回退、缺省 0；保留 int 转换和角色偏移，UCM 跳过。非法显式端口仍报错。现场只提供 after hash 前缀 `c098842c…`，本机重建文件完整 SHA 为 `46800951b22e5011045f33494cc21e4435940bedd09ac91854a76b96f56a648d`；**此处是语义对齐，不是字节对齐**。不应为统一 hash 覆盖现场已验证 fix1。

安装入口及回退细节见 [G5_ALIGNMENT.md](../../patches/motor/G5_ALIGNMENT.md)。新安装器识别 pristine / 已七文件 / 已 fix1 / 完整 g5，回退只管理本次新增文件；对未知文件或安装后研究改动拒绝覆盖。旧安装器和旧交付包保留历史，新入口为 `scripts/deploy/g5_motor_install.py`。

## 3. 算法核心的继承契约

- **FGJSQ**：保留 score、预留/提交账本、批事件匹配、请求/尝试身份、正常释放与 abort 双账兜底。`reserve_window_s=30` 是初次命令有效期，不能当作负载衰减或 active TTL。
- **Motor 链路**：保留 g5 HANDOFF 先 P、后 D 的现有顺序及 P leg 完成后的原生账本释放。后续 GF 等待不能漏释放、重复预留或误将 scheduled 当完成。
- **P 引擎**：async `SchedulerWithPredictorAsync`、SLO=0，保持 FCFS/running-first/共享 8192 token，max_num_seqs=24。computed 在 `_update_after_schedule` 提前推进，不等于已计算完成。
- **predictor**：现有批级特征/模型接口及标签不变。`actual` 是主机提交到取结果或相邻取结果间隔，不能直接当纯 NPU kernel 时间或单请求剩余 TTFT；`predict` 也会更新计数/日志。chunk 数学模型的新增特征需另行版本化。
- **D**：原生 async，主模型 `enforce_eager=false`＋`FULL_DECODE_ONLY`；MTP3 的 speculative `enforce_eager=true`。不因同步 P 环境而更改 D 算法或图模式。

完整源码勘误仍以审批稿第 5 节为准。本次没有改造 KV 命中感知、双队列、让行预算、waiting 重排或抢占。

## 4. 验证结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 新端口回归对旧代码 | 4 failed / 2 passed，失败为 nested/default 两类的 P/D `KeyError` | [node-manager-red.log](../../artifacts/g5-alignment/node-manager-red.log)，预期失败证据 |
| 修复后 NodeManager 配置测试 | **74 passed**，含新增 7 项 | [node-manager-green.log](../../artifacts/g5-alignment/node-manager-green.log) |
| Motor 配置解析与 vLLM backend 契约 | **96 passed** | [motor-config-regression.log](../../artifacts/g5-alignment/motor-config-regression.log) |
| FGJSQ、事件观察、EngineCore、Motor 集成及新工具测试 | **29 passed**，含新增工具 9 项 | [project-tests.log](../../artifacts/g5-alignment/project-tests.log) |
| 固定源码指纹 | **33/33 match** | [fingerprint-check.json](../../artifacts/g5-alignment/fingerprint-check.json) |
| 干净副本重建、重复执行、打包暂存清单 | 全部通过；暂存73文件hash验证，40个Python文件语法检查，三个upstream保持clean | [汇总](../../artifacts/g5-alignment/result.json) · [工具检查日志](../../artifacts/g5-alignment/tooling-checks.log) |

合计 **199 项通过**。测试通过 Motor `bash tests/run_tests.sh --serial ...` 入口执行，日志记录详细用例；覆盖新增补丁的旧代码失败/修复后通过、重复安装、已有补丁保护、失败恢复、研究改动保护和 reasoning-only SSE。`.venv` 为本机 Python 3.13 CPU 环境，不强制与现场 Python 3.12/aarch64 对齐。

## 5. 交付工具与适配边界

- `scripts/validate/verify_g5_baseline.py`：默认核对本机源码；`--scope runtime --output ...` 检查当前解释器实际可见包的路径/hash；可选 `--imports` 逐模块隔离导入，不加载权重或启动服务。依赖版本只记录，不要求本机等于现场。
- `scripts/collect/collect_runtime.py`：仍为只读采集，覆盖 21 核心文件、Motor 八文件、三引擎文件；`--image` / `--image-archive` 按现场已知值填写，不再默认 rc1。
- `scripts/package/build_g5_alignment_bundle.py`：工具包版本 `g5-baseline-alignment-0.1.0-20261022`；默认检查清单，`--stage <新目录>` 生成带 SHA256 的暂存目录，不构建 native 依赖、不重打算法 wheel、不启动服务。算法仍为 0.2.0。

本轮完成本机基线和交付准备入口，没有重发算法包、生成正式交付压缩包或操作华为服务。后续策略交付按项目约定在 WSL 准备校验后移动到 Windows 桌面；现场应保留已冻结算法/权重/启动链，只叠加需要的增量。

仍存在的证据边界：现场 warm predictor model 和其完整 SHA 未外传；Motor 现场全树 commit/完整 fix1 文件未提供；本机不能宣称数值预测、NPU ABI 或性能已复现。报告两个明显摘录问题（async_scheduler hash 字符、`import verify_engine()`）未抄入代码，三个引擎允许 hash 保持实测值。

最终现场状态仍以原报告截止为准：E2 两轮通过，TPOT 对 g4 约 +7.5%，完整十档及人工验收待后续文档。**本机源码已可支持入场与 chunk 研究；本轮没有产生新的性能结论。**
