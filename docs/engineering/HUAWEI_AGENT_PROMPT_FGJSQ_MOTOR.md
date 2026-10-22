# 给华为实验机 agent 的执行 prompt

你在可访问 910B2、镜像及模型权重的华为内网实验机执行。本机已提供 `fgjsq-motor-p-0.2.0-20261019.tar.gz`；请阅读包内 `docs/engineering/FGJSQ_MOTOR_DELIVERY.md` 和适配审查文档，再开展以下工作。目标是尝试拉起 3P3D Qwen3.6-27B，并验证 P 侧 FGJSQ＋predictor＋Motor 链路和效果。用户已批准该工程组合及本实验工作；不要反复索要已授权步骤的批准。缺少无法推断的机器/权重/资源归属信息时再询问。

## A. 范围与不可混淆的基线

- 用户指定镜像归档：`vllm-ascend:v0.23.0rc1-mindie-motor-3.1.0-main-0917.tar.gz`。使用现场文件、记录 image ID 与 sha256；文件名不是版本证明。历史 g4 用 v0.23.0 镜像，不能把历史证据套到新镜像。
- 目标拓扑：3 节点，每节点 8×910B2-64G，一个 TP4 P＋一个 TP4 D，共 3P3D。使用现场 Qwen3.6-27B 权重，核实实际模型名、量化格式（历史报告 W8A8）、tokenizer、模型版本及支持的长度。禁止下载替代模型后冒称已复现。
- 仅 P 路由算法与 P predictor/reporter 改动。D 引擎、D 选路、MTP3、KV 参数和已有兼容补丁保持本次捕获的现场基线；若镜像不支持某基线参数，请记录具体原因与差异，不能默默更改。
- SLO-aware 组批、EDF、降级关闭，`ENABLE_VLLM_TTFT_SLO_MS=0`。不实施双等待队列、waiting 重排、让行、动态 chunk 或 KV 抢占。
- 本包先支持 native OpenAI chat/scalar completion、n=1、HANDOFF、每 P 一个 endpoint、单 Mgmt。HA、Render/tokenized、多 prompt、TRIGGER、hybrid fallback 不在本次范围；需要这些能力时报告阻点，不能绕过检查伪装成功。
- 在独立实验容器/目录中操作，保留原镜像与现场基线；不停止无关业务，不覆盖权重，不对运行中服务热替换。

## B. 先取证，再判断直接安装或移植

1. 解压、在包根执行 `sha256sum -c MANIFEST.sha256`。将本轮日志、配置、源码差异、版本信息置于一个新建带时间戳的运行目录，记录每条实际命令及 exit code；输出敏感字段须脱敏。
2. 检查 Docker 归档及现场可用镜像。必要时导入指定归档，记录 `docker image inspect` 的 ID、architecture 和 labels；不要以 latest/tag 名代替内容身份。记录 OS、aarch64/其他架构、Python、CANN、驱动、torch/torch_npu、vLLM、vLLM-Ascend、Motor、Mooncake 版本与 native SHM 库路径。记录三节点卡型号和可用资源。
3. 在目标镜像内运行（尚未启用 P 插件）：

```bash
python scripts/collect/collect_runtime.py --output /ABS/RUN/runtime-before --include-source
```

`/ABS/RUN` 和以下 `/ABS/...` 均需替换成你从现场确定的绝对路径，不能直接执行占位符。

4. 采集原 P/D 启动命令、additional_config、KV connector 配置、环境变量、Motor 配置及 Controller/NodeManager/standalone 的实际部署方式。记录 P 实际 scheduler class/MRO、async_scheduling、chunked_prefill、max_num_seqs、max_num_batched_tokens、long_prefill_token_threshold、prefix cache、MTP、enforce_eager。P 无 CLI --async-scheduling 不等于同步，以最终配置和日志为准。
5. 本机已按 Motor `f203263d9742dd6fa76eaef658e0ff3a0f380301`、vLLM `0fc695fc6d1d82e9a5ac6835ac8e4e1c83703665`、Ascend `5cb98caaadeff42b5b62b996e34bb2aaa29d20fd` 设计。比较本包清单与镜像实际文件。版本不同但内容一致仍需记录；内容不同则不能直接应用补丁或仅替换 hash。
6. 如有差异，你可以在实验副本按已批准语义移植：保留该镜像原生 AsyncRecomputeScheduler 和 EngineCore 机制，将本包显式关联/冻结快照/计时 hook 嵌入真实控制流；保留该镜像 MTP、KV、异步容量断言。Motor 比对原子预留、协议对象和 lifecycle。先展示具体差异和移植依据并运行必要测试；遇到改变 D 或调度语义的方案则停止此变更并报告。最终输出小范围 `.py`/patch、修改前后 hash 及测试证据。本包 upstream 下选定源码仅作参考，不允许整文件覆盖新镜像核心实现。
7. 定位现场 g4 predictor model.pkl 和离线 wheels。历史记录模型 SHA256=`142f3364e8d7d8de58da62477b3fe852a797aa4cc8c79c582dda985853b54c9c`，仅作核验依据；记录实际 hash。依赖用现场可用版本并验证模型可加载；历史 lightgbm/scikit-learn 版本不是新镜像的已知事实。不要安装本机 x86_64 wheel 到 aarch64。模型缺失时允许 cold smoke，必须标注不能证明 warm predictor/性能复现。

## C. 安装与配置

若源文件与本包精确匹配，在暂停的实验容器中：

```bash
python scripts/deploy/install_motor_patch.py --motor-root /ABS/MOTOR_PARENT --state-dir /ABS/RUN/motor-backup --action check
python scripts/deploy/install_motor_patch.py --motor-root /ABS/MOTOR_PARENT --state-dir /ABS/RUN/motor-backup --action apply
python -m pip install --no-deps --force-reinstall dist/slo_patch-0.2.0-py3-none-any.whl
```

`MOTOR_PARENT` 是包含 `motor/` 包的目录，用取证得到的实际 import 路径确定。Coordinator 和 P 容器/进程都须能 import overlay；D 如果与 P 共用 site-packages，应保持 P 角色开关为空，原有 Hook3 按基线保留。确认只存在一个 slo_patch general plugin entrypoint，处理旧 editable 安装时保留回退信息。若曾使用 `VLLM_PLUGINS` allowlist，保留原插件并加入 slo_patch，不要覆盖 Ascend 插件选择。

填写 `configs/baseline/fgjsq.example.json` 的 event_url 为三路 P 都能到达的 Mgmt 地址，路径必须 `/fgjsq/v1/events`。全部 Coordinator 子进程设置同一个 `FGJSQ_CONFIG=/ABS/fgjsq.json`；不要设置在 P-only 容器代替 Coordinator。P 的 metadata 从请求携带该 URL，reporter 不再猜测 request ID 后缀。

P 环境：

```text
SLO_PATCH_ROLE=prefill
ENABLE_BATCH_REPORTER=1
ENABLE_VLLM_TTFT_SLO_MS=0
SLO_PREDICTOR_MODEL_PATH=/ABS/model.pkl  # warm 基线；cold smoke 时不设置
```

P additional-config 合并 `scheduler_with_predictor_enable: true`、`api_server_host`、`api_server_port`，保留现场原值和其他字段。host/port 在本版用于初始化兼容检查，实际回调 URL 来自 reservation。若 Mgmt 启用 API key，P 设置 `FGJSQ_MGMT_API_KEY_FILE` 为只读 key 文件，和 Motor `X-Motor-Management-Key` 校验对应；不要输出 key。HTTPS 配置可信 CA，必要时 `SSL_CERT_FILE`。若要求 mTLS，本包未配置客户端证书，须先完成对应小范围适配与验证；不能关闭现场安全策略迁就本包。

三路 P 使用一致 max_num_seqs（历史 24）并与 FG 配置相同。历史 token budget≈8192、long_prefill_token_threshold=0、enforce_eager 为复现起点，必须现场确认新镜像支持及实际运行值；不能把 max_model_len、输出 max_tokens 与 max_num_batched_tokens 混为一项。保持现有 chunked prefill＋running-first＋共享 token 逻辑。

填写 `configs/baseline/deployment.example.json`：每节点 P/D 的真实 argv、cwd、环境，以及 Coordinator argv。默认计划不执行；如采用直接命令启动，可用：

```bash
python scripts/deploy/launch_local.py --plan /ABS/deployment.json --node node0 --role P
python scripts/deploy/launch_local.py --plan /ABS/deployment.json --node node0 --role P --execute
```

如果镜像通过 NodeManager/Controller 启动引擎，应在其原生配置中注入同样的 P-only 环境和参数，不要同时手工再启动一套引擎。本脚本不负责注册、KV网络或进程守护。现场 agent 根据镜像自带文档/技能确定实际部署命令，交付包没有伪造未知 CLI。

分角色运行 preflight；随后确认 P 日志出现 SchedulerWithPredictorAsync、实际 native MRO、reporter enabled、warm model 加载（如有）和批级预测/更新打点。D 保持原生 AsyncRecomputeScheduler，不注入 P Hook1/2。新镜像如原本同步，不能仅为通过类名检查而改调度，先报告与历史基线差异。

## D. 测试顺序与链路门槛

1. 在实际 Motor 源码目录按其 AGENTS.md 使用 `bash tests/run_tests.sh`（不要直接 pytest）。可设置 `PYTHONPATH=/ABS/RELEASE/src` 跑交付项目 tests/unit、tests/integration；确认导入实际待部署 Motor，而非意外的旧安装。
2. 包内本地记录：新增 20 passed，选定上游 169 passed/8 skipped。现场必须补验 native SHM/schema-4 和 aarch64 ABI。优先重跑包中测试和以下上游文件：scheduler/test_scheduler_client.py、scheduler/test_scheduler_server_main.py、router/test_router_native_handoff.py、router/test_unified_pd_router.py、router/test_base_router_request_timeout.py、router/test_base_router_prepare_resource.py（均在 tests/coordinator/ 下）。缺 tests/harness 时记录限制，使用镜像对应源码的测试或等价现场检查，不得填写未运行的通过结果。
3. 先逐个验证 P/D 引擎健康和各自模型配置，再完成 Motor 注册，确认看到 3P、3D，每 P 一个可用 endpoint、正确 generation，HANDOFF 能完成 KV 交接。短请求 smoke 不足以证明长上下文 KV 正确，后续必须有真实长度验证。
4. 经 Motor 做一次流式和一次非流式请求，验证输出非空、终止标记和状态码。然后运行：

```bash
python scripts/validate/smoke.py --url http://MOTOR_INFERENCE --mgmt http://MOTOR_MGMT --model ACTUAL_SERVED_NAME --concurrency 3 --output /ABS/RUN/smoke.json
```

地址需含实际端口；如推理 API 有鉴权，设置 `FGJSQ_SMOKE_API_KEY`；Mgmt key 使用前述文件环境变量。此脚本只做流式 smoke，不替代第 4 步非流式请求或下面各 P 覆盖检查。

5. 保留一次完整关联 trace：reserve(key/attempt/epoch/instance/endpoint/generation/reservation) → P body metadata → schedule 冻结的 engine_epoch/batch_seq → 事件 matched → P native release → D 首个非空 bytes → FG release → finally。不用 `req_id[:-9]` 猜关联；不能以 HTTP200 或 received>0 代替 matched>0。
6. 保证三路 P 都被路由并各有 matched 事件及 predictor 更新证据。短 smoke 可能只落在部分 P，应扩展并发/请求长度或使用受支持的目标实例调试路径；不能更改路由公式强行制造均衡。记录 actual_batch_exec_time 和预测毫秒，确认标签与提交批次配对。
7. 在无其他请求的实验栈中，请求结束后 `/fgjsq/v1/loads` 的 open_fg、open_native 归零，native P active_tokens 回落基线。覆盖正常结束、客户端取消、P错误、D错误、重试后的旧事件与重复释放；其中故障注入必须局限于本实验请求。记录 reporter dropped/send_failed、unknown_or_released/stale/invalid，不应假设都必须永远零（合法迟到/重复可存在），需解释每一类来源。
8. 验证 D 收到的 body 无 `_motor_fgjsq_observer`/fgjsq 元数据，D 参数及调度与原基线一致；验证 KV external 命中、重算情况、输出正确性。历史 100% 命中不视作新栈既成事实。
9. Mgmt 内存账本无 HA 持久化；压测期间避免 Mgmt/worker 强杀或滚动重启。若发生，停止新流量、保存未清账本证据、排空/重建独立实验栈。不能用随意超时清账掩盖问题。

仅当以上版本/插件/3P3D/事件/释放/输出/KV 条件都有证据，才标记 chain_pass=true。部分成功应精确指出断点，并回传最小必要源码/patch/日志，不需要发送完整镜像或代码仓。

## E. 链路通过后的效果验证

本轮仍停留在基线迁移验证。若链路通过，比较同一新镜像、相同 D 与相同模型/负载下的 native Motor P 选路和 FGJSQ P 选路。尽量保留两组相同 P predictor/reporter 观测开销；额外记录原生全无 instrumentation 对照，区分观测开销与路由收益。禁用 FG 时 reporter 无显式 reservation 事件是预期差异，不能误作故障。

AISBench 按现场“0630提交”确认完整 commit 和发压代码，参数 concurrency=1/4/8/16、request_rate=1、pressure_time=900。不要未经源码核验断言是整轮 barrier 或持续补发，保存请求实际到达时间，辨别该版本闭环语义。64K/128K 分档、输入输出长度分布、缓存冷热、随机种子、warmup、重复次数须可比较。

| 档位 | P90 TTFT SLO | P90 TPOT SLO |
| --- | --- | --- |
| 64K | 27 s | 30 ms |
| 128K | 30 s | 45 ms |

记录全体请求 P90/P95 TTFT、P90 TPOT、E2E、成功率、成功请求吞吐和输出 token 吞吐、样本数、置信范围/重复实验波动、每 P 排队与计算/KV 时间。SLO、吞吐或正确性退化必须如实报告。不要因为长请求或失败请求影响分位数而删样本。优先确认效果是否可信，不假定已有平均负载接近容量。

## F. 回退和回传

回退前停止发压并排空。对精确本包补丁运行 `install_motor_patch.py --action revert`，使用对应 --motor-root 和 --state-dir；先恢复 Motor 文件再卸载 overlay，或重建原实验容器恢复原安装。D 原 Hook3 若必需则恢复其原包/开关。所有 Coordinator workers 同步切换，禁止热混用协议。保存已修改实验副本及 diff 供本机审查。

请回传一份 `ONSITE_RESULT.md` 和小型证据包：

- image ID/hash、各组件版本/commit、10 个目标文件 SHA256、native SHM ABI；实际拓扑/IP端口（按允许范围脱敏）。
- 最终完整启动 argv、环境变量名和非敏感值、Motor配置、模型/量化/上下文参数、predictor模型hash、P/D scheduler证据。
- 如移植：每个修改文件/patch、变更前后hash、原因、测试命令/结果。禁止仅说“修复兼容”。
- 3P3D健康/注册、流式/非流式、三P事件matched与训练更新、取消/错误/重试/释放、KV交接与正确性证据；最终账本快照。
- chain_pass 的判定与未完成项；如运行性能对照，附原始逐请求数据和汇总，不只贴百分比。
- 回退方法和实际验证状态、残留实验进程/文件清单。

不要进入让行算法开发。本机收到你的链路证据后，再和用户讨论下一研究阶段。
