# G5 冻结基线交接文档（G5_FROZEN_BASELINE_HANDOVER）

> **用途**：外网机器/外部 agent **仅凭本文档**（无法访问内网源码、容器、日志）以 g5 冻结基线为起点，设计**入场/让行策略**与 **chunk size 寻优策略**。所有关键源码、配置、diff、日志、实验数据直接嵌入正文；内网路径仅作来源索引，不依赖其可访问性。
> **冻结版本**：`vllm-ascend:g5-g4base-motor-20261021-r1`（= 过程 tag `v0.23.0-motor310-g4base-r2`，同一镜像双 tag）
> **数据截至**：2026-10-21 13:09 UTC（十档压测进行中，进度见 §0.5/§8.4；本文落稿不等待十档完成）
> **时间口径**：全文时间均为 **UTC**。引擎日志行（如 `INFO 10-21 10:45:39`）为容器本地时间=UTC；压测脚本 `date -u` 同。唯一例外=宿主 `ps lstart`（宿主本地时区 UTC+8），出现处单独标注。
> **文档 SHA256**：落盘后计算并随交付消息报告（本文不自我嵌入）。
>
> 证据分级（全文逐项标注）：
> - 【源码确认】= 冻结版实际运行源码逐行读取（来源=构建上下文 `10_g4base_motor/01_artifacts/g5_export/`，与镜像内容同源，见 §5.2）
> - 【运行实证】= 现场日志/接口/进程实测
> - 【实验对照支持】= 同负载前后/多臂对照实验数据
> - 【推断】= 由前两类推导，未闭环
> - 【未核实】= 未采集/无法确认，如实标注

---

## 0. 开篇一页（结论速览）

### 0.1 g5 当前实际组成

| 层 | 实际内容（冻结版） | 证据 |
|---|---|---|
| 镜像 | `vllm-ascend:g5-g4base-motor-20261021-r1`，三节点镜像 ID：.49=`9ff2237f0ebe` / .151=`c590300504b9` / .175=`fb149ce8f7d2`（同 Dockerfile + 同 esfs 构建上下文，三节点各自 build；ID 不同=层时间戳，内容同源） | 【运行实证】SOLIDIFY.md §1 |
| 底座（不动） | `quay.io/ascend/vllm-ascend:v0.23.0` = `660ce23a8357`（g4 压测实际镜像）：vllm **0.23.0+empty@0fc695fc**（editable `/vllm-workspace`）、vllm-ascend **0.23.0 正式版@5cb98caa**、torch-npu **2.10.0.post4**、torch 2.10.0+cpu、CANN 9.0.1、mooncake 0.3.11.post1、python 3.12.13 | 【运行实证】BUILD_RECORD §1、import_battery |
| 增量（纯新增 22 组） | motor 3.1.0（含现场 fix1 与交付包七文件 patch）、slo_patch 0.2.0、fgjsq、motor_adapter、lightgbm 4.7.0、narwhals 2.26.0、OpenSSL/pyopenssl 26.4.0、sklearn 1.9.1(+libs)、joblib 1.6.0、threadpoolctl 3.7.0、kubernetes 35.0.0、durationpy、oauthlib、requests_oauthlib、websocket(client 1.9.2)、watchdog 6.0.0 + 各 dist-info | 【源码确认】Dockerfile 全文 §4.7 |
| 编排 | MindIE-Motor 3.1.0-main-0917（Coordinator .49 :18080/:18081 + Controller .49 :18083/:18084 + 三节点 NM :1026(P)/:1027(D)）；fgjsq 账本内嵌 Coordinator | 【运行实证】 |
| 模型 | Qwen3.6-27B-w8a8（`Qwen3_5ForConditionalGeneration`，text 256k，MTP 1 层，W8A8 ascend 量化），只读挂载 `/mnt/esfs/Qwen3.6-27B-w8a8` | 【运行实证】 |
| 硬件/拓扑 | 3× 910B 节点（7.193.130.49/.151/.175），每节点 8 卡：P 引擎 TP4（卡 0-3，:10000）+ D 引擎 TP4（卡 4-7，:10002）；容器 `motor3p3d-zxy` ×3 | 【运行实证】 |

候选版本名沿革：`v0.23.0-motor310-g4base-r1`（废弃，依赖不全）→ `v0.23.0-motor310-g4base-r2`（E0-E2 用）→ 固化双 tag `g5-g4base-motor-20261021-r1`（=r2，正名）。

### 0.2 E2 判定：**双轮全项 PASS → 已固化**

判定实验 E2（=候选 S2 复用口径）：128k×B16×PT900×2 轮连续服务生命周期（轮间零重启），seed 20261014，prefix 0.5，客户端=.216 `agent_1017_aisbench` 容器（与 g4 基线客户端同构）。

| 指标 | r01 (n=284) | r02 (n=283) | 阈值（g4 均值×±10%） | 判 |
|---|---|---|---|---|
| TPOT mean | **13.2 ms** | **13.1 ms** | ≤13.42 | ✅ |
| TPOT P90 | 14.2 ms | 14.2 ms | ≤14.39 | ✅ |
| TTFT mean | 38.18 s | 38.49 s | ≤44.77 s | ✅ |
| TTFT P90 | 43.84 s | 43.76 s | ≤51.93 s | ✅ |
| QPS | 0.298 | 0.2973 | ≥0.2538 | ✅ |
| 零容忍（失败/503/引擎退出） | 0 | 0 | =0 | ✅ |

双轮差异 <1%（高度可重复）。extract_metrics 原文（r01）：`ttft_mean=38176.3, ttft_p90=43844.2, tpot_mean=13.2, tpot_p90=14.2, e2e_mean=51640.0, qps=0.298, total=284, success=284, failed=0, duration=952862ms`；r02：`ttft_mean=38489.1, ttft_p90=43759.7, tpot_mean=13.1, tpot_p90=14.2, e2e_mean=51903.0, qps=0.2973, total=283, success=283, failed=0, duration=951849ms`。run_id=`E2_128kB16_r01/r02`（`04_e2/runs/`），时间窗 r01 11:21:19-11:39:49、r02 11:45:01-12:03:30 UTC。【运行实证】

### 0.3 相对 g4 与旧 g5 的变化

| 指标 | **D. 方案 E 新 g5（本基线）** | C. 通信修复后 rc1（S2 轮） | B. 初始 rc1 | A. g4 基线 |
|---|---|---|---|---|
| TPOT mean | **13.1-13.2 ms** | 16.8 / 16.7 ms | 17.2 / 18.5 ms | 12.228 / 12.181 ms |
| 对 g4 偏差 | **+7.5%（±10% 工程容忍内）** | +37% | +41% | — |
| TTFT mean | 38.2-38.5 s | 33.0 / 34.8 s | 110.1 / 127.1 s | 40.70 s |
| QPS | 0.297-0.298 | 0.3072 / 0.2979 | 0.115 | 0.2812 / 0.2834 |

- **TPOT 恢复**：对 rc1 −21%，回到 g4 ±10% 内——方案 E「消除版本倒挂」目标达成；剩余 +7.5% 未做单变量分解（见 §0.4）。
- **TTFT/QPS 优于 g4 基线**（TTFT −6%、QPS +5%）。
- 对 B（初始 rc1）：TTFT 110s→38s（−65%）、QPS 0.115→0.298（2.6×）——通信环境修复+底座替换的合并效果。

### 0.4 已知错误 / 性能残留 / 未解释现象（全部如实）

1. **TPOT 对 g4 仍 +7.5%**：版本倒挂（rc1 vs 0.23.0 final）消除后的残差；无单变量实验分解（E1 B4 距阈值差 1.8% 同向）。【实验对照支持，未闭环】
2. **十档 E2_128kB1 档 TPOT mean 12.9 ms vs 阈值 12.89 ms**（差 0.01ms 边缘未过，TTFT/QPS/零容忍过）——已在进行中的十档如实记录，最终裁定属验收报告（§8.4）。【运行实证】
3. predictor 在线再训练 r2 偏低（0.05-0.48，见 §6.C.6）——预测精度有限，已知的既有实现，非本轮回归。
4. 10.20 P-only 修复期曾出现「errmsg 空的 Transfer failed 新类」（~5.7 次/请求，请求仍全成功）；方案 E 栈 E0 起时间窗内六引擎日志该类计数=0，视为随 rc1 栈消失，未做专项复现。【运行实证（消失）/未核实（机理）】
5. Motor attempt 生命周期超时上限：源码未见显式 waiting 段超时（§7.1 约束行）。【未核实】

### 0.5 固化状态 / 十档进度 / 待验收项

- **固化**：已完成（`05_solidify/SOLIDIFY.md`）：三节点 tag + `motor3p3d-zxy-imgkeep` 占位防 GC 已落；回退工件全保留（§2、§5.7）。
- **十档**（全部引用本固化版本；128kB16 档=E2 双轮计入）：截至 13:09 UTC 完成 2/9 余档——`E2_128kB1`（12:11-12:29，37/37 成功，TTFT/QPS/零容忍过、TPOT mean 12.9 vs 12.89 阈 0.01ms 边缘未过+TPOT P90 13.8 vs 13.61 未过，extract 原文见 §8.4）、`E3_128kB2`（12:34-12:51，77/77，全项过）；`E4_128kB4` job 12:56:43 起运行中；后续 E5-E10 待跑。档间零重启（同一服务生命周期，predictor 状态跨档继承）。
- **待用户验收**：① 十档全部完成后汇总报告 `G5_G4BASE_MOTOR_ACCEPTANCE.md`（后续独立任务）与用户最终验收；② E2_128kB1 档 TPOT 边缘项（0.01ms）的裁定；③ 本文文档本身的审阅。

---

## 1. 证据规则、时间口径与术语防混淆

### 1.1 结论与证据强度对齐原则

- 每项重要结论标注五级证据之一；【推断】不得写成事实；「未保存/未采集」直接写明，不为完整而猜测，也不为补齐而新开实验（本任务零新实验、零算法修改、零配置调整）。
- 性能数字必须带：run_id、n（样本数）、统计口径（AISBench 原生分位）、时间窗、并发/输入/种子。本文所有表格均含。
- 归因纪律（承 10.21 计划裁定）：
  - **不机械沿用累加估算**：10.20 的「15.9 keys × 3.4s ≈ 54s ≈ TTFT 差值 66s 的 80%」是**重叠感知前的上界估算**（重试可并发/重叠），定位期用于缩小范围；修复效果的证明=同负载前后对照（110s→33s），不以累加为证。
  - **无单变量算子实验 → 不得写「sampler 已被证明为 TPOT 根因」**；正确表述=「版本倒挂为主因假设（B 档证据支持），sampler 实现代差为最热单点嫌疑」（§3.P13）。
  - 区分「仅提出过」与「真正执行过」的尝试（§3 各问题「实际修复」字段）。

### 1.2 易混淆概念对照（本文统一口径）

| 易混对 | 本文口径 |
|---|---|
| 镜像 tag vs 实际源码版本 vs 加载路径 vs 运行时 monkey patch | 四层分开陈述：tag 只是名（§2 表）；源码版本以 commit/镜像 ID 为准（§0.1）；引擎加载路径=`/vllm-workspace/{vllm,vllm-ascend}`（editable，非 site-packages）；运行时行为修改=monkey patch 清单独立列出（§5.6，不能以「磁盘源码未修改」代表无行为修改） |
| g4 / 旧 g5-rc1（B） / 通信修复后 g5-rc1（C） / 方案 E 新 g5（D，本基线） | 版本演进表 §2，四版身份互不混用；「g5」未加限定时=本冻结基线 D |
| 冒烟通过 / S2、E2 通过 / 十档完成 / 用户最终验收 | 四级验证状态严格分开；当前：E2 ✅、十档进行中 2/9+128kB16、验收未开始（§0.5） |
| 运行栈版本差异 vs 已定位到具体算子的根因 | 版本倒挂（435 文件面）是【实验对照支持】的栈级归因；sampler 等单算子仅【推断】级嫌疑（§3.P13） |
| 实际缓存命中 / 预测缓存收益 / predictor 的 cache_hit_rate 代理特征 | 三者严格区分（§6.C.1、§6.D）：predictor 的 `cache_hit_rate` **不是任何真实缓存命中**，是批内「剩余未算比例」 |
| TTFT 恢复 vs 业务 SLO 达标 | 两项独立判断（§8.5）：E2 恢复到 g4 水平=是；128k 业务 SLO（P90 TTFT≤30s）= g4 自身未达，本基线也未达，另行如实报告，不因修复被追责也不宣称达标 |
| AISBench SSE 间隔 vs 设备 forward 时间 | TPOT/ITL 是**客户端流式间隔口径**，含传输/组包；每 step 设备时间另有引擎侧 `[slo]` 打点（§8.6），不得互替 |

### 1.3 脱敏声明

本文不含凭据、鉴权 token 内容、真实业务正文。示例请求保留字段结构、单位与跨事件 ID 对应关系（reservation_id/nonce/engine_epoch 等以真实格式的前缀+省略号呈现）。`FGJSQ_MGMT_API_KEY_FILE` 仅出现路径名（键值从不落盘于本文）。

---

## 2. 版本演进（A→D 四版，身份互不混用）

| 版本 | A. g4 | B. 初始 g5-rc1 | C. 双侧通信修复后 g5-rc1 | D. 方案 E 新 g5（**本冻结基线**） |
|---|---|---|---|---|
| 存在时段 | 2026-10-13/14 压测；镜像一直在位 | 2026-10-19 拉起 ~ 10-21 E0 切换 | 2026-10-21 06:12(D 修复)~07:32(Phase A 全重启) ~ 10-21 10:39 E0 切换 | 2026-10-21 10:39 起，运行中 |
| 镜像身份 | `quay.io/ascend/vllm-ascend:v0.23.0`=`660ce23a8357` | `vllm-ascend:v0.23.0rc1-mindie-motor-3.1.0-main-0917`=`fe76ab99901a…`（三节点） | 同 B（镜像未换） | `g5-g4base-motor-20261021-r1`（.49=`9ff2237f0ebe`/.151=`c590300504b9`/.175=`fb149ce8f7d2`；底座=A 的 660ce23a8357 + 纯新增 22 组） |
| vllm / vllm-ascend / torch-npu | 0.23.0+empty@0fc695fc / **0.23.0 正式版@5cb98caa** / **post4** | 0fc695fc（同）/ **0.23.0rc1@f4a08bdd**（07-19 冻结，倒挂）/ **post2** | 同 B | 0fc695fc / **0.23.0 正式版@5cb98caa** / **post4**（=A，倒挂消除） |
| 编排层 | proxy（pd-hybrid，`run_2p2d_exp.sh`）+ 镜像外 slo_patch 0.1.0 + proxy 内 fgjsq | MindIE-Motor 3.1.0（Coordinator/Controller/NM）+ 三合一 wheel 0.2.0（fgjsq+motor_adapter+slo_patch 内嵌） | 同 B | 同 B（motor/slo_patch 等自 B 运行容器导出，三节点 md5 一致后 COPY 进新镜像） |
| 关键修改（相对其前一版） | —（历史基线） | Motor 七文件 FGJSQ patch（交付包）+ fix1-8 现场修复；**拉起链无 g4 setup_env** | D 侧补 setup_env 15 项（06:12）；Phase A 全栈用 `nm_launch_pd_hccl.sh` 受控重启（07:24-26，P/D 同批双侧对称 env） | 换底座=A 镜像 + B 的 site-packages 增量（r2 证据法 22 组）；engine_files.json recompute 锚回 g4 值 38111806…（=交付包原值）；`__editable___vllm_ascend*rc1*` finder 绝不带 |
| 运行/实验编号 | T128kB16_r01/r02 等（`summary_metrics_1013_1014.csv` 22 行） | S4 拉起 / S5 链路 / B16 正式档 `128kB16_g5_p01` | `S0`/`S1`/`S2_128kB16_{r01,r02}`（rc1 栈小型对照） | `E0`（五轮编排）/`E1`（单流+B4）/`E2`（=判定双轮）/十档（进行中） |
| 核心结果 | B16：TTFT 40.70s、TPOT 12.20ms、QPS 0.282（n=235/234） | B16：TTFT 110.1s、TPOT 17.2ms、QPS 0.115（120/120）；TRANSFER_FAIL ~5,700/窗 | S2：TTFT 33.0/34.8s（过）、TPOT 16.8/16.7ms（**不达标 +37%**）、QPS 0.3072/0.2979、n=293/283 | E2 双轮全过（§0.2）；TPOT 13.1-13.2ms |
| 判定 | g4 基线（对照锚点） | TTFT 2.7× 劣化=通信 env 缺失（§3.P10）；TPOT 劣化=版本倒挂主嫌（§3.P13） | TTFT 恢复 ✅；TPOT 仍 +37% → S2 判不达标 → 不固化 → 方案 E 获批 | **E2 PASS → 固化 → 十档** |
| 是否保留回退 | 是（g4 runbook=EXP_10.14，镜像在位） | 是：容器 `motor3p3d-zxy-rc1-keep`（Exited，FS 完整）+ 镜像 `fe76ab99901a` 三节点在位 + 10.20 日志备份 `02_e0/prelogs/`（9 文件） | （中间态，已被 Phase A 重启覆盖；其脚本与报告在案 `01_d_env_fix/`） | 本版=现役；软复位脚本 `e0_soft_reset.sh`；imgkeep 占位防 GC |

**D 版内部小版本**：`r1`（废弃：只带 docker diff 增量，缺 OpenSSL 等 101 项中的必需子集，E0 第三轮 `ModuleNotFoundError: No module named 'OpenSSL'` 启动即死）→ `r2`（证据法补齐 22 组 + import_battery 成为构建必检，三节点 BATTERY_PASS）→ 固化 tag `g5-g4base-motor-20261021-r1`（=r2 双 tag）。r1 镜像 ID 仅备查（.49 两个早期 ID 已被宿主「无容器引用即删」GC 机制删除），不作回退目标。【运行实证】

**注**：C 版不是一个独立镜像，是 B 镜像 + 双侧 env 修复 + 最终启动脚本（`nm_launch_pd_hccl.sh`）的运行形态；其「镜像身份」行与 B 相同是有意为之——C 与 B 的差异全在启动环境与编排脚本层。

---

## 3. 问题全史（Motor 接入 → 方案 E 冻结）

### 3.1 总表

| # | 症状 | 影响范围 | 发现证据 | 根因/假设 | 实际修复 | 验证结果 | 最终状态 | 复发预防 |
|---|---|---|---|---|---|---|---|---|
| P01 | P/D 引擎 APIServer 起即死：`pydantic ValidationError: VllmConfig / lookup_rpc_port Unexpected keyword argument '0'` | 全部 6 引擎无法启动 | NM 日志 pydantic 栈 | Motor backend 写 `kv_connector_extra_config`（正位），Motor nm（`config/node_manager.py`）读 store **顶层键**——Motor 3.1.0 内部两侧位置期待不一致 | fix1：现场 8 行补丁（读法兼容化：顶层缺失→回落 extra_config→缺省 "0"），三节点 sha256 一致 `c098842c…` | 干跑 NM_P_OK lookup=0 / NM_D_OK lookup=1；全栈 count=6 | 已闭环（随 motor 包进入 D 版镜像） | 新 Motor 版本升级时 diff `config/node_manager.py` 读键位置 |
| P02 | D 引擎 `vllm: error: unrecognized arguments: false` | D 引擎 | NM 日志 | Motor `_add_argument_to_list` 对 bool 生成 `--key value`，vllm BooleanOptionalAction 不吃裸值 | fix2：config 用否定式键 `"no_enable_prefix_caching": true` → `--no-enable-prefix-caching` | D 引擎 non-default args `enable_prefix_caching: False` | 已闭环（config_sample.json 现值） | D 侧布尔参数一律用 `no_` 前缀键 |
| P03 | 每节点只起一个引擎（P 或 D 之一） | 拓扑 6 引擎 | Controller/NM 日志 | `has_node_mgr(pod_ip)` 仅按 IP 匹配去重（`instance.py:200`） | fix3：P/D 各独立 JOB_NAME（当时 role 级） | 6/6 start_cmd | 已闭环，但引出 P08（见下） | 每节点每**角色**唯一 JOB_NAME |
| P04 | P 实例 endpoints 2/1、3/1 永不 enough，无 start_cmd | 拉起期 | Controller 日志 | 实例组装 filter 周期错过 1/1 窗口；`is_endpoints_enough` 要求 total==dp_size | fix4：拉起规程改**串行逐节点**，确认 :1026+:1027 双 start_cmd 再下一节点 | Controller 日志 6/6 | 已闭环（规程固化于启动脚本链） | 多节点拉起一律串行+双端口确认 |
| P05 | D 引擎 `Free memory (5.79/60.96 GiB) < 0.9×…` | 拉起期 | 引擎日志 | 10.16 遗留 vllm 引擎占满三节点 24 卡 | fix5：经用户批准清引擎留容器，按 cgroup 圈定 kill | 三节点 HBM 回 ~3414/65536、VLLM 进程 0 | 已闭环 | 拉起前 NPU 占用检查进验收第一步 |
| P06 | ① 两套 mooncake 集群严禁共压同一 L2；② 方案 E E0 引擎全 Worker `Initialize mooncake failed ret=-600` | ①共享设施 ②E0 三、四轮 | ①纪律 ②n49_nmp.log | ②E0 编排漏启 mooncake master（.49:50089） | ①fix6：.49 容器内自持 master（`mooncake_start.sh`，P2PHANDSHAKE/ascend/10GB）②编排补 2.5 步 | Clients=24 指向 .49:50089；ret=-600 归零 | 已闭环 | 启动序正本：容器→**mooncake master**→coord/ctrl→NM |
| P07 | P 引擎 `RuntimeError: P reporter requires api_server_host and api_server_port`（0.2.0 硬校验） | P 引擎 | nmp 日志 | slo_patch 0.2.0 把 g4 版 warning 升为硬 raise；`BatchEventReporter` 实际不消费 addr/port（真实上报 URL 来自 reservation 的 event_url） | fix7：P additional_config 填占位 `api_server_host="motor3p3d-zxy-p"`、`api_server_port=10000` 过校验 | 三节点 `[slo] batch reporter enabled` 且 0 raise | 已闭环（占位值不消费） | 若未来版本让 reporter 消费该 addr，占位值失效需复核 |
| P08 | 6/6 引擎健康但 Coordinator /instances count=2 | 实例池 | coord 日志 "removing stale instance and refreshing" | fix3 的 role 级 JOB_NAME 使三节点 P/D 互踩——池按 (role, job_name) 去重级联替换 | fix8：**每节点每角色唯一** job_name（p49/p151/p175 + d49/d151/d175） | count=6、级联替换 0、mooncake Clients=24 | 已闭环 | JOB_NAME 命名规范=角色+节点 |
| P09 | `Engine compatibility mismatch for vllm_ascend.core.recompute_scheduler`（期望 38111806，rc1 镜像原生 23abae3c） | B/C 版 activate | 引擎启动报错 | 交付包 engine_files.json 期望值锚定 g4 世代文件；rc1 的 recompute_scheduler.py 有 6 行 failed_kv 扣减顺序差异 | B/C 时代：期望值再锚定 23abae3c（改 hash 白名单非改引擎文件，原值备份）；**D 版：底座即 g4 文件，期望值还原为交付包原值 38111806…，无需再锚定** | 三节点引擎文件 sha256 实测=期望值 | 已闭环（D 版 anchor=底座原生值） | 引擎文件三模块任何改动必须同步 bump engine_files.json（compatibility.py raise 硬失败无豁免） |
| P10 | B16 压测 TTFT 110s（g4 40.7s 的 2.7×）、QPS 减半；P 日志 `HcclBatchPut hccl_result=4`（E19999，channel.cc:314）~5,700 条/窗 | B 版全部正式压测 | `04_stack_logs`（引擎正本日志；注意 docker logs 为空≠无故障） | g5 拉起链（nm_launch_one.sh）从未 export g4 setup_env 15 项 → 本机 P→D HCCL put 通道整批（170-op）失败-revoke-重试循环 | 10-20 12:03 P 侧补 env（`nm_launch_p_only_hccl.sh`）；10-21 06:12 D 侧对称（见 P12）→ Phase A 起统一 `nm_launch_pd_hccl.sh` | 冒烟 TTFT 110s→6-22s；S2 33-35s（同负载前后对照，差分法）；HcclBatchPut=0 | 已闭环（env 为启动序正本组成部分） | 引擎进程 `/proc/<pid>/environ` 断言 HCCL_INTRA_ROCE_ENABLE=1 等进入验收（正本已含） |
| P11 | P-only 修复后 D 侧 `HcclCommPrepare` 0x9 → D 引擎×3 死 → NM 自杀（k8s 设计裸 docker 失效）→ 客户端 503 | 10-20 B16 灾难（8779/8796 503） | nmd.log 灾难段（已整本备份 `n*_nmd.log.disaster.bak`；注意 NM 重拉 `>` 截断日志） | P/D 通信 env **不对称**：P 带全套 HCCL env、D 无 → D 侧通信域初始化失败 | 灾难后 10-21 06:12 D 对称修复（P12）；NM 自杀未被自动恢复=k8s 编排设计在裸 docker 不生效，需人工重拉 | D 重拉后 count,d=6,3、health×3、错误窗 0 | 已闭环（对称性成为正本） | 验收断言「P/D env 对称性」逐项比对（verify 已含）；503 突增即停发压保留现场 |
| P12 | （承 P11）D 侧需与 P 对称的通信环境 | D 引擎 | /proc/environ 实测 D 无 HCCL_* | 同 P10 根因 | `nm_launch_d_only_hccl.sh`（10-21 06:12-06:19 三节点串行）；Phase A（07:23-07:32）起与 P 合并为 `nm_launch_pd_hccl.sh` 同批拉起 | count,d=6,3；D health 200×3；时间窗错误 P:0 D:0 | 已闭环（并入正本启动脚本） | 见 P10/P11 |
| P13 | C 版 S2：TPOT 16.8/16.7ms vs 阈值 ≤13.42（+37%）不达标；TTFT/QPS 过 | 判定实验 | S2 双轮（n=293/283） | **主嫌疑=vllm-ascend rc1（07-19 冻结）vs 0.23.0 final（08-17）版本倒挂**（435 文件差异；decode 每 step 热路径：sampler AscendC 自定义算子 vs CANN npu_top_k_top_p 为最热单点嫌疑；torch_npu post2 vs post4 并列）。**无单变量算子实验，不写「sampler 已被证明为根因」** | 方案 A（sampler 单文件 A/B）/B（整树替换）/C（换镜像）/D（现状固化）**仅提案未执行**；用户批准**方案 E**：g4 完整引擎底座 + Motor 迁移（r2） | E1 单流 12.1-12.5ms 回 g4 水平（rc1 15.6-16.2）；B4 16.3→13.2ms；E2 全过 | 已闭环（栈级归因成立；单算子贡献未分解，如实保留） | 新镜像前必查 vllm-ascend/torch-npu 版本与目标基线一致（import_battery 含底座版本断言） |
| P14 | ① 10.20 客户端 venv 依赖地狱（bench_lib cp311 编译件 23 个 MISSING 等）；② 10.21 `/tmp/aisbench_venv_20` 被 清空丢失；③smoke 对 Qwen3.6 输出误判 | 客户端侧（非服务侧） | 10.20 venv 构建日志；10.21 06:09 发现丢失；smoke.json passed=false 但 3/3 done | ①宿主 python3.12 与 bench_lib cp311 编译件不匹配链；②.216 /tmp 会被清；③Qwen3.6 流式 delta 文本在 `reasoning` 字段（非 content） | ①逐包补装（已废弃路线）；②**定型=.216 `agent_1017_aisbench` 容器**（cp311，与 g4 客户端同源）+ 05_small_comparison 自持链；③采集侧三字段兼容 `delta.get("content") or delta.get("reasoning") or delta.get("reasoning_content")`（EXP 副本 smoke.py，交付包正本未动） | resolution_check 10 包全命中；DRY_RUN 渲染对；S0 3×40k 冒烟 all_ok | 已闭环（客户端方案=容器 Plan A 正本） | 客户端不复用 /tmp 路径；Qwen3.6 流式字段三兼容 |
| P15 | D 版 r1 镜像 coord/ctrl/NM 启动即死 `ModuleNotFoundError: No module named 'OpenSSL'` | r1 候选 | E0 第三轮 | docker diff 只见容器层增量——**rc1 镜像层预装而 g4 底座没有的依赖对 diff 不可见**；浅层 `import motor` 不触发 cert_util 链 | r2 证据法：缺失集=（rc1-keep 容器 site-packages）−（g4 底座镜像）=101 项逐类裁定，带 22 组；**import_battery.py（14 模块+底座版本断言）成为构建必检** | 三节点 BATTERY_PASS；E0 第五轮全过 | 已闭环 | 构建新候选镜像必跑 import_battery；绝不能带 rc1 的 `__editable___vllm_ascend*rc1*` finder（会劫持 vllm_ascend import 回 rc1 树） |
| P16 | 工程坑集合（取证/脚本环境） | 调查效率与正确性 | 各处 | 见 §3.3.P16 六要素清单 | 逐项记入检查清单 | — | 已闭环（记录在案） | §9 检查流程吸收 |
| P17 | FGJSQ 账本 abort 计数 ≈ +2/请求 | 指标解读（非故障） | d6 探针 + loads 快照 | 正常完成=release_native+release_fg 各 1；abort 计数含 P/D attempt 清理路径各 1 次的幂等空操作 | 无需修复（口径说明） | 定量验证 | 已闭环（口径） | 结果分析中按口径扣除 |
| P18 | B1/B3 流量落单实例（如 n175 主导，n151 无流量） | 指标解读（非故障） | E1 覆盖检查 + S2 观测 | fgjsq 路由按 score 排序，低并发下负载粘性 | 无需修复 | 与 2026-10-09 用户与同事定性一致（正常现象） | 已闭环（定性） | B 档分析注明实例覆盖 |
| P19 | 同 seed warmup/前序流量污染后续轮 TTFT 口径 | 指标解读 | E1（TTFT 14.0s 较 rc1 12.2s 反升的核查） | warmup 与 job 同 seed 同前缀 → P 本地 prefix cache 命中 → TTFT 不可比；TPOT 不受影响 | 无需修复（口径说明）；E2 双轮为连续生命周期，轮间状态如实记录（r02 与 r01 差 <1%） | warmup md5 序与 S2/S1 完全一致（`309c68de4aed…f17656b7ebdd`）锁定客户端口径 | 已闭环（口径） | 跨 run 比 TTFT 必须注明缓存冷热态 |
| P20 | g5 注入 `--cp-kv-cache-interleave-size 1` 而 g4 无此参数 | 配置审计〔C〕项 | /proc cmdline 对照 | 该参数仅 Context-Parallelism 路径（mla_cp/sfa_cp）使用；D 引擎未传 --context-parallel-size（=1）→ CP 路径不激活 → **no-op**；platform 校验也仅 cp_size>1 触发 | 无需修复 | 源码路径核查（CONFIG_AUDIT §B + S2_VERDICT §2.2 排除表） | 已闭环（no-op 结论） | 参数对照表中保留该行备查 |

（P01-P08=10.19-10.20 拉起期 fix1-8 的对应关系：fix1→P01、fix2→P02、fix3+fix8→P03/P08、fix4→P04、fix5→P05、fix6→P06①、fix7→P07；P09-P12=10.20-10.21 通信问题链；P13-P15=方案 E 决策与构建；P16-P20=口径与坑。）

### 3.2 拉起期问题六要素详述（P01-P09）

**P01（fix1）Motor nm lookup_rpc_port 读取位置冲突**
- ①为何发生/误判：Motor 3.1.0 内部不一致——backend 侧把 `lookup_rpc_port` 写进 `kv_connector_extra_config`（vllm 正位），nm 侧（`motor/config/node_manager.py` 读 store 顶层键）期待顶层；缺键即以意外参数构造 `VllmConfig` → pydantic `Unexpected keyword argument '0'`。初期曾疑 Motor patch 应用错误，94 文件 sha256 清单核对排除交付包侧。
- ②证据收窄：报错栈直指 config 构造；对照 Motor 原始镜像文件（`records/motor_pristine_from_image/`）确认读法为上游原生。
- ③实际修改（现场唯一 Motor 源码级补丁，非交付包内容）：

```python
# motor/config/node_manager.py（原版 → fix1，读法兼容化；备份 .orig_fix1）
# before:
#   lookup_rpc_port = store[LOOPUP_RPC_PORT_KEY]            # 直索引顶层，缺键即炸
# after:
    if LOOPUP_RPC_PORT_KEY in store:
        lookup_rpc_port = store[LOOPUP_RPC_PORT_KEY]
    else:
        extra = (store.get("kv_connector_extra_config") or {})
        lookup_rpc_port = extra.get(LOOPUP_RPC_PORT_KEY, "0")
```
- ④证明：干跑断言 NM_P_OK lookup=0 / NM_D_OK lookup=1；全栈 6 引擎健康；三节点文件 sha256 一致（`c098842c…`）。该补丁随 motor 包导出进入 D 版镜像（聚合 md5 `fcce4957d1fa5a22a844b338521916ee` 三节点一致）。
- ⑤未闭环：无（若上游 Motor 修复，此补丁幂等无冲突）。
- ⑥提前发现检查：换 Motor 版本时 diff `config/node_manager.py` 的键读取位置 vs backend 写入位置。

**P02（fix2）D 关 prefix caching 的 bool 序列化**：①Motor `_add_argument_to_list` 对 bool 生成 `--key value` 而 vllm BooleanOptionalAction 不吃裸值；②错误行 `unrecognized arguments: false` 直指；③config 用否定式键 `"no_enable_prefix_caching": true`（现值见 §4.4 配置原文）；④D 引擎 non-default args `enable_prefix_caching: False`；⑤无；⑥D 侧布尔一律 `no_` 前缀键。

**P03+P08（fix3+fix8）同节点 P/D 去重**：①Controller `has_node_mgr(pod_ip)` 仅按 IP 匹配→每节点只容一个 NM；先用 role 级 JOB_NAME 绕过（fix3）→ 又暴露实例池按 (role, job_name) 去重的级联替换（三节点同 role 同 job_name 互踩，count=2）；②count 从 6 掉 2 + "removing stale instance" 日志定位池层；③每节点每角色唯一 JOB_NAME：`motor3p3d-zxy-p49/p151/p175` 与 `motor3p3d-zxy-d49/d151/d175`；④count=6 稳定、级联替换 0、mooncake Clients=24；⑤无；⑥JOB_NAME=角色+节点命名规范进启动脚本。

**P04（fix4）Controller 实例组装竞态**：①filter 周期错过 endpoints 1/1 窗口（要求 total==dp_size）→ 永不 enough；②Controller 日志 endpoints 2/1、3/1 停滞；③拉起规程改串行逐节点、双端口确认（:1026 NM API + :1027）再下一节点；④6/6 start_cmd；⑤无；⑥多节点拉起串行化（正本脚本内置 sleep 与确认步）。

**P05（fix5）遗留占卡**：①10.16 会话遗留 vllm 引擎占满三节点 24 卡（空壳容器 Up 无进程但引擎进程在）；②引擎报 `Free memory (5.79/60.96 GiB) < 0.9×…` + npu-smi 占用；③用户批准清引擎留容器，按 cgroup 圈定 kill；④HBM 回基线、VLLM 进程 0；⑤无；⑥拉起验收第一步=NPU 占用检查。〔关联记忆：qwen3627b-slo 遗留占卡〕

**P06 mooncake master（两 episode）**：①纪律上两套 mooncake 集群严禁共压同一 L2 → fix6 自持 master 于 .49:50089（配置 `/mnt/esfs/zhangxiyue/qwen3.6-27b/mooncake_exp_cluster49.json`）；②方案 E E0 第三/四轮全 Worker `Initialize mooncake failed ret=-600`——**E0 编排漏启 master**（它是编排步骤不是镜像内容：引擎 AscendStoreConnector 连 .49:50089）；③编排补 2.5 步（`e0_orchestrate.sh` 内置）；④master LISTEN + 引擎失败计数 0；⑤无；⑥启动序正本把 mooncake master 列为第 2 步（容器之后、coord/ctrl 之前），漏启即全引擎拒起——**E0 教训**。

**P07（fix7）0.2.0 reporter 占位硬校验**：①交付包 slo_patch 0.2.0 将 g4 版 warning 升为硬 raise：`P reporter requires api_server_host and api_server_port`（scheduler_with_predictor.py:91），而 `BatchEventReporter.__init__` 实际不消费 addr/port（真实回调 URL 来自 reservation 的 `event_url`）；②P 引擎拒启栈；③P additional_config 填自述身份占位 `api_server_host="motor3p3d-zxy-p"`、`api_server_port=10000`；④三节点 `[slo] batch reporter enabled` 0 raise；⑤若未来版本消费该 addr 则占位失效（记录在案）；⑥升级 slo_patch 时核对 reporter 构造参数消费情况。

**P09 engine_files.json 锚点沿革（三阶段）**：
- ①B 版：compatibility 校验 raise（期望 38111806…=交付包锚定 g4 世代文件；rc1 镜像原生 23abae3c…）——两者差异=6 行 failed_kv 扣减顺序（g4 版将 `num_in_flight_tokens` 扣减移入 `requests.get` 命中分支=上游 bugfix）。修复=再锚定期望值至 23abae3c（改白名单非改引擎文件；原值备份 `records/engine_files.json.orig_rc1_anchor`）。
- ②C 版：沿用 23abae3c。
- ③**D 版（冻结）**：底座即 g4 树，实测文件 sha256=`38111806d9434e4267482a63a453f6f4328a5d0bf9ae931fa17ad38208d79202` → 期望值**还原为交付包原始值**（g5_export 内 engine_files.json 现值，见 §4.6）。因此**D 版三组件对交付包零修改**（含此文件）。
- ④证明：activate 链 verify_engine 通过 ×3 节点（引擎文件三模块 sha256 实测=期望值）。
- ⑤⑥：改三个被锚模块（vllm.v1.engine.core / vllm.v1.core.sched.async_scheduler / vllm_ascend.core.recompute_scheduler）任一必须同步 bump 期望值，否则拒启（raise 硬失败无 env 豁免）——新算法插件的硬约束（§6.E）。

### 3.3 通信问题链六要素详述（P10-P13，本文档最重要的问题链）

**P10 TRANSFER_FAIL / setup_env 缺失（B 版 TTFT 2.7× 劣化根因）**
- ①为何发生/误判：Motor NM 拉起链（`nm_launch_one.sh`）从未 export g4 `run_2p2d_exp.sh:208-228 setup_env()` 的 15 项 HCCL/ASCEND 传输变量——**g2/g4 全系带、唯 Motor 栈没带**。早期误判方向曾含「客户端计量虚高」「Motor 派发/锁瓶颈」「fgjsq 账本差异」，均被 06.5 定位轮逐一排除（Tracer 全量：TTFT 损失 98.3% 在 P-leg；Motor 派发 5.7ms；fgjsq 六项对照+确定性回放逻辑等价）。
- ②证据收窄（06.5 Phase 2 + E2 取证，全只读）：
  - 失败单位=**整个 170-op batch 全灭**（`task_ids=[0..169]`），非单 key；全部失败目标=**本机 D**（n49 的 P → 7.193.130.49:20xxx 即本机 dcp0 segment）；
  - 单次失败完整链条（n49 B1 窗，行 58275-58320）：

```
transfer_executor_base.cpp:587] Retry transfer to:7.193.130.49:20521
  ↓ ~130ms
transfer_executor_base.cpp:597] Transfer failed to: 7.193.130.49:20521, errmsg: E19999: Inner Error!
E19999: Failed to invoke HcclBatchPut, hccl_result = 4 [channel.cc:314]
  TraceBack: Flush[499]←Put[491]←TransferAsync[318]←TransferSync[372]←adxl_engine_impl[116/257]
  → op_descs size:170, timeout:33064 ms（一个 170-op batch）
transfer_task.cpp:305] Batch 281432228540160 completed with task failures: task_ids=[0..169]（整批全灭）
client_service.cpp:1685] Transfer failed for key …@pcp0@dcp0@…@<hash>: TRANSFER_FAIL
client_service.cpp:1786] Successfully revoked failed put ×5 keys
(Worker_TP1) ERROR mooncake_backend.py:209] Failed to put 5 keys out of 5. error_codes=[-1]
```
  - 统计画像（B1/A1 两臂逐位一致，fgjsq 无关再证）：失败 ~5.8 条/s、每 key 2.93-2.97 次、重试跨度 mean 3.4s（p90 7.1s）、相邻失败间隔 p50 0.58s=连接-失败-revoke-重连稳态循环；
  - 对照三源：g4 存档（g2 栈 launch_env.txt 全套在位 + P0.log 零失败 + 92 条 segment 终身复用）vs g5 现场（P 进程 /proc/environ 实测 MOONCAKE_CONFIG_PATH 在而 HCCL_*/ASCEND_* 全无）vs 拉起脚本（无 setup_env 段）；
  - 定位期累加估算（**上界口径，不作为证明**）：每请求 ~15.9 失败 key × 3.4s ≈ 54s ≈ TTFT 差值 66s 的 ~80%——量级闭合但重试可重叠。
- ③实际修复：10-20 12:03 P 侧 `nm_launch_p_only_hccl.sh`（P-only + g4 setup_env 逐字，NIC=enp67s0f5 三节点统一、HCCL_IF_IP=$IP 逐节点）；10-21 D 侧对称（P12）；Phase A 起统一 `nm_launch_pd_hccl.sh`（正本，全文见 §4.5）。
- ④证明（差分法，同负载同种子同客户端）：修复前 B16 TTFT 110.1s → P-only 修复冒烟热引擎 6.1/10.1/22.4s + HcclBatchPut=0 → 双侧修复 S2 33.0/34.8s → 方案 E E2 38.2-38.5s（阈值 44.77s 内）。【实验对照支持】
- ⑤未闭环：10.20 P-only 修复期残留「errmsg 空的 Transfer failed 新类」（~5.7/请求，请求全成功）；方案 E 栈时间窗内=0，视为随 rc1 栈消失，机理未复现。
- ⑥提前发现检查：验收断言「引擎进程 environ 含 HCCL_INTRA_ROCE_ENABLE=1/HCCL_IF_IP=本机 IP」+「时间窗 HcclCommPrepare/HcclBatchPut/Transfer failed 计数=0」（正本验收已含）；新拉起链 diff setup_env 段。

**P11 P-only 修复 → P/D 不对称 → D 死亡 → NM 自杀 → 503（10-20 B16 灾难）**
- ①为何发生：P-only 补 env 后 P/D 通信环境不对称 → D 侧 `HcclCommPrepare` 返回 0x9 → D 引擎×3 崩溃 → NM 判断节点故障自杀（k8s 编排设计：裸 docker 下无自动重拉）→ 全集群 503（客户端 8779/8796 号请求）。外网报告=EXTERNAL_DEBUG_REPORT.md。
- ②证据收窄：nmd.log 灾难段逐字链（HcclCommPrepare 0x9 → 引擎退 → `NodeManager shutdown complete (exit_code=-1)` 12:32:48）；10-21 06:04 核实 D :10002 全死、无人恢复。
- ③实际修复：见 P12。**取证保护**：NM 重拉会 `>` 截断日志——灾难段 nmd.log ×3 先整本备份（`01_d_env_fix/pre_state/n*_nmd.log.disaster.bak`）再动手。
- ④证明：D 对称重拉后 count,d=6,3、D health 200×3、时间窗错误 0；链路 2 请求 PASS。
- ⑤未闭环：单次事件因果未做受控复现（不对称性机理以逐字日志+对称修复后零错误为证）。
- ⑥提前发现检查：验收新增「P/D env 对称性逐项比对」；监控 503 突增即停发压保留现场。

**P12 D 侧对称修复（10-21 06:12-06:19）**
- ①为何发生：P10 修复只动了 P（当时判断 HCCL put 发起方在 P，先只动 P 是最小扰动决策——事后证明 D 侧也参与通信域初始化，不对称即死）。
- ②证据收窄：P11 灾难链 + /proc/environ 实测 D 无 HCCL_*。
- ③实际修复：`nm_launch_d_only_hccl.sh`（D 段 + setup_env 15 项与 P 逐字段相同，仅 HCCL_IF_IP 逐节点；D 保持无 SLO_*/predictor env 纯净）。此后 Phase A（07:23-07:32）以 `nm_launch_pd_hccl.sh` 将 P+D 同批受控重启（用户修改 1：S0 起全部用固化交付同款启动方式）——**测试与固化同一份脚本**。
- ④证明：count,d=6,3；三节点 D :10002=200；D env 实测（ASCEND_RT_VISIBLE_DEVICES=4,5,6,7 / HCCL_INTRA_ROCE_ENABLE=1 / ROLE=decode / 无 SLO_*）；时间窗六日志错误 P:0 D:0。
- ⑤未闭环：无。
- ⑥提前发现检查：任何单侧环境改动必须评估对侧对称性。

**P13 TPOT +37% → 版本倒挂归因 → 方案 E（本基线的由来）**
- ①为何发生/现象刻画：C 版 S2 TPOT 16.8/16.7ms（+37%）双轮不达标而 TTFT/QPS/零容忍过；B 无关（B1 单流 16.3 vs g4 11.72 → 单流逐步变慢非批效应）；分布均匀偏移（min 15.6/median 16.5/max 21.7）系统性非尾部；步时分解 ITL 59.8ms≈TPOT×3.56 tok/step → 每 forward step +37%。
- ②证据收窄（全部只读取证+外网调研，2026-10-21 08:3x-09:1x）：
  - 已排除：MTP 接受率（3.20-3.93 vs g4 3.24-3.98 一致）、cascade attention 禁用差异（g4 同样有该行）、cp-kv-cache-interleave-size（P20 no-op）、客户端/负载/种子（逐位同 g4）。
  - 主嫌疑=**版本倒挂**：v0.23.0rc1 发布 2026-07-20（镜像内文件时间戳 07-19）vs v0.23.0 final 2026-08-16（g4 镜像 08-17，含 rc1 之后合入的 † 标记 PR）→ g5 缺约一个月修复/优化；两镜像 vllm_ascend 树 diff=435 文件。decode 每 step 热路径代差：

| 文件 | rc1（g5 当时） | 0.23.0（g4） |
|---|---|---|
| `sample/sampler.py` | `_C_ascend.npu_apply_top_k_top_p`（自编译 AscendC 自定义算子） | `torch_npu.npu_top_k_top_p`（CANN 内置算子） |
| `ops/linear_op.py` | `torch_npu.npu_mm_reduce_scatter_base(comm_mode="aiv")` | `DeviceOperator.npu_mm_reduce_scatter_base(...)`（新封装自动选路径） |
| `attention/attention_v1.py` | 直接传 key/value | 传 `key/value.contiguous()` |
| `sample/rejection_sampler.py` | 无 NaN/Inf 清洗 | `nan_to_num` 单趟清洗 |
| g4 独有 | — | `patch/platform/patch_async_swa_kv_lifetime.py`、`patch_shm_broadcast.py` |

  - 社区佐证：vllm-ascend issue #14138（top-p/top-k 采样某场景占 step ~50% 为最大设备端算子）、PR #12232（v0.26.0rc1 移除 AscendC top-k/top-p 改用 CANN 算子——正是 rc1 在用、g4 已不用、社区最终移除的那条路径）、rc1 Known Issues #12337（TP4 B1 存在 1-2ms TPOT 回归先例）。
  - **归因结论强度**：栈级「版本倒挂为主因」获 B 档证据支持；sampler 为最热**单点嫌疑**（【推断】）；无单变量算子实验 → 不写「sampler 已被证明为根因」。
- ③实际修复：方案 A（sampler 单文件 A/B）/B（vllm-ascend 整树覆入）/C（外网找 0.23.0final 基 motor 镜像）/D（现状固化）四案**仅提案**；用户批准**方案 E**：放弃在 rc1 镜像上打补丁，改以 g4 完整引擎底座（660ce23a8357）+ 从 B 运行容器导出的 Motor/FGJSQ/predictor 增量构建新镜像（r2，构建教训见 P15）。
- ④证明：E1 单流 TPOT 12.137/12.509/14.380ms（干净两条 12.1-12.5，g4 B1=11.72 容差内；rc1 同款 15.6-16.2）；B4 PT300 TPOT 16.3→13.2ms（−19%）；E2 双轮全过（§0.2）。
- ⑤未闭环：+7.5% 残差未分解（sampler/torch_npu post 系/其它 435 文件贡献比例未知——如需单算子结论须专项 A/B，未排）。
- ⑥提前发现检查：候选镜像构建必跑 import_battery（含底座版本断言 vllm-ascend=0.23.0 正式版、torch-npu=post4）。

### 3.4 客户端 / 构建 / 口径问题（P14-P20）

**P14 AISBench 客户端管道**
- ①为何发生：10.20 走 .216 宿主 venv 路线，撞上宿主 python3.12 vs bench_lib cp311 编译件不匹配（23 个 MISSING 批装）、torch cp312、hf-hub 降级、vendor torch_npu 空 stub 骗过 transformers NPU 探测、mp 子进程只继承 PYTHONPATH 等一串坑；10.21 06:09 又发现 `/tmp/aisbench_venv_20` 被 清空（机器未重启）。
- ②证据收窄：resolution_check 包核对；冒烟 rc=0 验证；.216 无外网 DNS（venv 不可重建）。
- ③实际修复（定型方案，用户 docker 建议落地）：**.216 `agent_1017_aisbench` 容器**（cp311 与 g4 客户端同源）+ `05_small_comparison` 自持链（launcher_10_21 删 HOST_SITE、vendor 回归 janus 2.0.0、bench_10_21 容器 python）；采集侧 Qwen3.6 流式 delta 三字段兼容（`content`/`reasoning`/`reasoning_content`——P08 勘误：输出文本在 `reasoning`）。
- ④证明：resolution_check 10 包全命中 bench_lib/deps 同构 g4；DRY_RUN 渲染对；S0 3×40k 冒烟 all_ok；S1/S2/E0-E2/十档全部用此管道。
- ⑤未闭环：无（venv 路线废弃不回头）。
- ⑥提前发现检查：客户端环境以容器为正本；/tmp 不放持久物。

**P15 r1→r2 构建教训（方案 E 镜像）**
- ①为何发生：r1 只带 `docker diff` 增量；**diff 只见容器层增量，rc1 镜像层预装而 g4 底座没有的包对 diff 不可见**（OpenSSL/pyopenssl——`motor.common.http.cert_util:18` 直接 `from OpenSSL import SSL, crypto`，coord/ctrl/NM 三入口共同链；kubernetes 等）；且浅层 `import motor` 不触发 cert_util 链 → 冒烟漏检。次级误判：diff 增量里 motor_adapter（FGJSQ 补丁的 P 侧入口）和 sklearn/joblib（predictor 侧）曾判可省——必需。
- ②证据收窄：E0 第三轮 coord/ctrl/NM 全部 `ModuleNotFoundError: No module named 'OpenSSL'`。
- ③实际修复（r2 证据法）：缺失集 = rc1-keep 容器 site-packages − g4 底座镜像 site-packages = 101 项 → 逐类裁定：import 链直接命中必带（OpenSSL）、diff 误判必带（motor_adapter、sklearn 系）、源码引用计数>0 带（kubernetes+传递依赖、watchdog）、0 引用不带（confluent_kafka 等）、**绝不带** rc1 的 `__editable___vllm_ascend_0_23_0rc1_finder.py`/`__editable__.vllm_ascend-0.23.0rc1.pth`（会把 vllm_ascend import 劫持回 rc1 树，直接破坏底座前提）、dist-info-only 项不带（避免同名冲突/变相降级）。最终 22 组（§4.7 Dockerfile）。**import_battery.py（三服务入口+插件链+predictor 依赖 14 模块+底座版本断言）成为构建必检**。
- ④证明：三节点 BATTERY_PASS（10:17-10:20）；E0 第五轮编排全过。
- ⑤未闭环：无。
- ⑥提前发现检查：新候选镜像必跑 import_battery；底座版本断言（vllm-ascend=0.23.0 正式版、torch-npu=2.10.0.post4）。

**P16 工程坑集合（六要素合并陈述——每条=一次真实踩坑+修正）**
- 引擎正本日志=容器直写共享盘 `04_stack_logs/n{49,151,175}_n{mp,md}.log`；**docker logs 为空 ≠ 无故障**（10.20 曾据 docker logs 误报 TRANSFER_FAIL=0，作废）。
- NM 重拉用 `>` 重定向 → **截断原日志**：重拉前必先备份（P11 已执行）。
- `setproctitle` 改名子进程持有监听 fd：kill 后端口仍占，须 **inode 反查**杀（10.19 拉起期）。
- kill 脚本 KEEP 'mooncake' 模式会误保活引擎（argv 含 backend=mooncake）。
- awk 断言字段号写错会把全对数据判 FAIL——验收输出 `verify_out.txt` 必须亲自看原文（E0 第五轮教训）。
- `.216` 有 docker、控制机没有；`.216` 无跨节点 ssh → 跨节点取证一律 `ssh_exec.py --nodes <ip> --cmd`（e2_run.sh 内嵌抓取空即此因，缓存态改由控制机补采）。
- `.49` 有「删无容器引用镜像」GC 机制（journalctl/events 实证）→ **新 tag 必须跟随 imgkeep 占位**（r1 早期 ID 已被 GC）。
- `pgrep -f` 自匹配（脚本名含模式时误杀/误计数）。
- 宿主 `ps lstart` 是宿主本地时区（UTC+8）——勿误判「神秘重拉」（10-21 06:04 核实 P 进程年龄时澄清）。
- 宿主 /tmp 与容器 /tmp 不同：base64 载荷须 docker cp 进容器再用。
- bash -c 里中文括号 `(` 裸词会语法错；`ssh_exec.py` 零输出要打 `(no output)` 占位（曾误读为失败）。
- 取证 P 用 nmp.log、D 用 nmd.log 勿混（曾误判 flashcomm 缺失）。
- 提前发现检查：全部吸收进 §9 五段检查流程。

**P17 abort +2/请求口径**：正常完成路径=release_native+release_fg 各 1 次；P/D attempt 清理路径各发 1 次 abort（幂等 suppress 空操作）→ metrics.abort ≈ 2×请求数。d6 探针定量验证。非故障信号；分析时按口径扣除。【运行实证】

**P18 路由粘性**：低并发档（B1/B3）流量落单 P/D 实例（如 n175 主导）=fgjsq 按 score 排序的粘性，2026-10-09 用户与同事已定性为**正常现象**；B16 档自然多实例。B 档分析注明实例覆盖即可。

**P19 同 seed 缓存污染 TTFT 口径**：warmup（6 条）与 job 同 seed 同前缀 → P 本地 prefix cache 命中 → 前序流量后的 TTFT 不可比（E1 单流 ttft 3.3s 即命中例；TPOT 不受影响）。跨 run 比 TTFT 必须注明冷热态；warmup md5 序（`309c68de4aed/36e5cf2859a6/97fdb3844852/02216d35047d/5dcf2ee8a3e7/f17656b7ebdd`）三处一致锁定客户端口径。【运行实证】

**P20 cp-kv-cache-interleave-size=1 no-op**：g5 注入、g4 无此参数。该参数仅 Context-Parallelism 路径（mla_cp/sfa_cp）消费；两栈引擎均未传 `--context-parallel-size`（=1）→ CP 路径不激活；platform 校验仅 cp_size>1 触发。**结论=no-op**（配置审计〔C〕项关闭）。【源码确认】

---

## 4. 最终运行架构与完整配置

### 4.1 部署表与请求时序

| 节点 | 容器 | 进程 | 端口 | 设备 |
|---|---|---|---|---|
| 7.193.130.49 | motor3p3d-zxy | mooncake master；Coordinator（推理/管理/观测）；Controller（API/观测）；P NM + P 引擎；D NM + D 引擎 | 50089；18080/18081/18082；18083/18084；1026→:10000；1027→:10002 | 8×910B2（P 卡 0-3，D 卡 4-7） |
| 7.193.130.151 | motor3p3d-zxy | P NM + P 引擎；D NM + D 引擎 | 1026→:10000；1027→:10002 | 同上 |
| 7.193.130.175 | motor3p3d-zxy | P NM + P 引擎；D NM + D 引擎 | 1026→:10000；1027→:10002 | 同上 |
| 7.193.130.216 | agent_1017_aisbench | AISBench 客户端（压测发压机） | — | — |

请求时序（P 侧标出 FGJSQ 关键位置；D 侧纯原生 vllm-ascend，无任何 slo_patch 代码）：

```
客户端(.216)
  → POST :18080/v1/chat/completions (stream)
    → Coordinator UnifiedPDRouter（.49）
        [FGJSQ-1] allocate(P) → Mgmt FgjsqService._reserve：
                   rank(P 候选) → 选实例 → native CAS-add + FG loads[count+1, +estimated_tokens]
        attach_request：P body kv_transfer_params.fgjsq = {reservation_id, coordinator_epoch,
                   attempt_seq, instance_id, endpoint_id, generation, event_url}
        [FGJSQ-2] allocate(D) → 原生 CAS（D 不走 FGJSQ 账本）
    → P 引擎(:10000, SchedulerWithPredictorAsync, SLO=0 → 行为=AsyncRecomputeScheduler+打点)
        waiting(FCFS) → admission（running-first + 共享 token budget 8192）
        每 step：freeze_snapshot → [FGJSQ-3] 批事件 POST :18081/fgjsq/v1/events
                 （num_prompt/num_scheduled/num_remaining tokens + predicted_exec_ms）
        HANDOFF 完成 → _release_attempt → [FGJSQ-4] release_native（幂等 RPC，native 账本扣减）
    → KV 交接：P(kv_producer) → mooncake master(.49:50089) → D(kv_consumer)
              （MultiConnector=[MooncakeConnectorV1 + AscendStoreConnector(backend=mooncake)]）
    → Coordinator 转发 D(:10002)
        [FGJSQ-5] D 首个非空 body bytes → FirstBodyObserver → release_fg（FG 账本扣减）
    → 流式返回客户端（delta.reasoning/content 字段）
    → D 完成 → Release release_d_tokens（D 原生 CAS）
    → 请求收尾 finish_request：兜底 abort（幂等；口径见 P17）
```

### 4.2 P/D 实例运行时对照（值=non-default args + additional_config 实测；CLI 未出现 ≠ 未启用，均标注运行时实际值）

| 项 | P（每节点 1 实例，:10000） | D（每节点 1 实例，:10002） | 证据 |
|---|---|---|---|
| scheduler class | `slo_patch.slo.scheduler_with_predictor.SchedulerWithPredictorAsync` | `vllm_ascend.core.recompute_scheduler.AsyncRecomputeScheduler` | 【运行实证】`[slo_patch] scheduler_cls -> SchedulerWithPredictorAsync (async_scheduling=true)` |
| scheduler MRO（P） | `SchedulerWithPredictorAsync → SchedulerWithPredictor → AsyncRecomputeScheduler → AsyncScheduler → RecomputeScheduler → Scheduler` | — | 【源码确认】§6.B.1 |
| async_scheduling | **true（config 未写，运行时实际 true）** | true（config 显式） | 【运行实证】 |
| max_num_seqs / max_num_batched_tokens / max_model_len | 24 / 8192 / 131072 | 同 | non-default args |
| chunked prefill | enabled（8192 budget） | enabled | 【运行实证】 |
| long_prefill_token_threshold | **未出现在 non-default args → 引擎默认值生效（vllm 默认 0=不启用单请求截断；日志未显式 dump）**【未完全验证，标注】 | 同 | 【推断】 |
| prefix caching | True | **False**（`--no-enable-prefix-caching`，P02） | non-default args |
| enforce_eager | True | False（cudagraph FULL_DECODE_ONLY，capture sizes [1,4,…,64] 步长 4 共 17 项） | non-default args |
| MTP speculative | num_speculative_tokens=3, method=mtp, enforce_eager=true | 同 | non-default args |
| KV connector | MultiConnector=[MooncakeConnectorV1(kv_port=30000, use_ascend_direct) + AscendStoreConnector(backend=mooncake, lookup_rpc_port=实例号)]；kv_role=**kv_producer** | 同构；kv_role=**kv_consumer**，Mooncake kv_port=30004（实例分位） | non-default args（全文 §4.4） |
| predictor/reporter env | SLO_PATCH_ROLE=prefill、ENABLE_BATCH_REPORTER=1、ENABLE_VLLM_TTFT_SLO_MS=**0**（SLO 硬关）、SLO_PREDICTOR_MODEL_PATH=model.pkl（NM env 命令前缀注入，仅 P） | **无**（D 纯净：无 SLO_*，activate 对 role!=prefill 空转） | 【运行实证】environ 断言 |
| additional_config | enable_cpu_binding、enable_flashcomm1、scheduler_with_predictor_enable=true、api_server_host/port（P07 占位） | recompute_scheduler_enable、enable_cpu_binding | config_sample.json |
| cp-kv-cache-interleave-size | 1（注入，no-op 见 P20） | 1（同） | /proc cmdline |
| 采样参数（业务） | temperature=0.01、top_k=20、top_p=0.95（AISBench 模型配置渲染） | 同（D 执行采样） | 10.21 短核查实测 |

### 4.3 编排层配置全文（config_sample.json，来源 EXP_10.20_MOTOR/03_stack/；注意 image_name 字段仍是 rc1 旧值——实际容器镜像由 e0_stop_and_switch.sh 以固化 tag 决定，此字段在本裸 docker 编排中不被消费，仅记录）

```json
{
  "version": "v2.0",
  "motor_deploy_config": {
    "deploy_mode": "single_container",
    "p_instances_num": 1, "d_instances_num": 1,
    "single_p_instance_pod_num": 1, "single_d_instance_pod_num": 1,
    "p_pod_npu_num": 4, "d_pod_npu_num": 4,
    "image_name": "vllm-ascend:v0.23.0rc1-mindie-motor-3.1.0-main-0917",
    "job_id": "motor3p3d-zxy",
    "hardware_type": "910B",
    "weight_mount_path": "/mnt/esfs"
  },
  "motor_engine_prefill_config": {
    "engine_type": "vllm",
    "model_config": {
      "model_path": "/mnt/esfs/Qwen3.6-27B-w8a8", "model_name": "Qwen3.6-27B",
      "npu_mem_utils": 0.9,
      "parallel_config": { "dp_size": 1, "tp_size": 4, "pp_size": 1, "dp_rpc_port": 13300 }
    },
    "engine_config": {
      "max_model_len": 131072, "max_num_batched_tokens": 8192, "max_num_seqs": 24,
      "trust_remote_code": true, "seed": 1024,
      "tool_call_parser": "qwen3_coder", "enable_auto_tool_choice": true,
      "reasoning_parser": "qwen3", "quantization": "ascend",
      "api_server_count": 1, "distributed_executor_backend": "mp",
      "enable_prompt_tokens_details": true,
      "enable_prefix_caching": true,
      "enforce_eager": true,
      "speculative_config": { "num_speculative_tokens": 3, "method": "mtp", "enforce_eager": true },
      "additional_config": {
        "enable_cpu_binding": true, "enable_flashcomm1": true,
        "scheduler_with_predictor_enable": true,
        "api_server_host": "motor3p3d-zxy-p", "api_server_port": 10000
      },
      "kv_transfer_config": {
        "kv_connector": "MultiConnector",
        "kv_connector_extra_config": {
          "connectors": [
            { "kv_connector": "MooncakeConnectorV1", "kv_port": "30000",
              "kv_connector_extra_config": { "use_ascend_direct": true } },
            { "kv_connector": "AscendStoreConnector",
              "kv_connector_extra_config": { "backend": "mooncake", "lookup_rpc_port": "0" } }
          ]
        }
      }
    }
  },
  "motor_engine_decode_config": {
    "engine_type": "vllm",
    "model_config": {
      "model_path": "/mnt/esfs/Qwen3.6-27B-w8a8", "model_name": "Qwen3.6-27B",
      "npu_mem_utils": 0.9,
      "parallel_config": { "dp_size": 1, "tp_size": 4, "pp_size": 1, "dp_rpc_port": 13300 }
    },
    "engine_config": {
      "max_model_len": 131072, "max_num_batched_tokens": 8192, "max_num_seqs": 24,
      "trust_remote_code": true, "seed": 1024,
      "tool_call_parser": "qwen3_coder", "enable_auto_tool_choice": true,
      "reasoning_parser": "qwen3", "quantization": "ascend",
      "api_server_count": 1, "distributed_executor_backend": "mp",
      "enable_prompt_tokens_details": true,
      "async_scheduling": true,
      "compilation_config": {
        "cudagraph_mode": "FULL_DECODE_ONLY",
        "cudagraph_capture_sizes": [1,4,8,12,16,20,24,28,32,36,40,44,48,52,56,60,64]
      },
      "speculative_config": { "num_speculative_tokens": 3, "method": "mtp", "enforce_eager": true },
      "additional_config": { "recompute_scheduler_enable": true, "enable_cpu_binding": true },
      "kv_transfer_config": {
        "kv_connector": "MultiConnector",
        "kv_connector_extra_config": {
          "connectors": [
            { "kv_connector": "MooncakeConnectorV1", "kv_port": "30000",
              "kv_connector_extra_config": { "use_ascend_direct": true } },
            { "kv_connector": "AscendStoreConnector",
              "kv_connector_extra_config": { "backend": "mooncake", "lookup_rpc_port": "0" } }
          ]
        }
      },
      "no_enable_prefix_caching": true
    }
  },
  "motor_nodemanger_config": {
    "api_config": { "pod_ip": "127.0.0.1", "node_manager_port": 1026 },
    "endpoint_config": { "endpoint_num": 1, "base_port": 13700, "service_ports": [], "bootstrap_port": null },
    "basic_config": {
      "model_name": "Qwen3.6-27B", "engine_type": "vllm", "hardware_type": "910B",
      "device_num": 4,
      "parallel_config": { "dp_size": 1, "tp_size": 4, "pp_size": 1, "world_size": 4, "local_world_size": 4 },
      "enable_multi_endpoints": true, "nnodes": 1
    },
    "fault_tolerance_config": { "enable_fault_tolerance": false, "enable_engine_relaunch": false },
    "kv_cache_store_config": { "enable": false, "backend": "memcache", "mode": "combined" }
  },
  "motor_coordinator_config": {
    "api_config": {
      "coordinator_api_infer_port": 18080,
      "coordinator_api_mgmt_port": 18081,
      "coordinator_obs_port": 18082
    },
    "scheduler_config": { "scheduler_type": "unified_pd", "enable_pd_separation_fallback_to_hybrid": false },
    "context_budget_mode": "off",
    "deploy_config": { "p_instances_num": 1, "d_instances_num": 1 }
  },
  "motor_controller_config": {
    "api_config": { "controller_api_dns": "7.193.130.49", "controller_api_port": 18083, "observability_api_port": 18084 },
    "instance_config": { "instance_assemble_timeout": 300 },
    "fault_tolerance_config": { "enable_fault_tolerance": false },
    "logging_config": { "log_level": "INFO" }
  }
}
```

要点：`deploy_mode=single_container`+裸 docker（NM 的 k8s 健康自愈失效即 P11 灾难链根源）；`fault_tolerance_config.enable_fault_tolerance=false`（引擎死不自动重拉）；D 侧 `no_enable_prefix_caching=true`（fix2 否定式键）；`context_budget_mode=off`（Coordinator 不做上下文预算干预，路由完全由 unified_pd + FGJSQ score 决定）。

### 4.4 fgjsq.json 全文（FGJSQ 账本参数，来源同上）

```json
{
  "enabled": true,
  "event_url": "http://7.193.130.49:18081/fgjsq/v1/events",
  "max_num_seqs": 24,
  "retention": 0.05,
  "reserve_window_s": 30,
  "tombstone_s": 3600,
  "max_records": 100000,
  "rpc_attempts": 3
}
```

语义：`reserve_window_s=30` 预留窗（FGJSQ-1 处 score 衰减的参考节拍，见 §6.A）；`retention=0.05` 保留因子；事件全部打向 Coordinator mgmt 口 18081（与实例 API 同口不同路径）。

### 4.5 NM 拉起脚本全文（nm_launch_pd_hccl.sh，唯一正本；来源 EXP_10.21_MOTOR/06_g5_candidate/launch/）

```bash
#!/bin/bash
# g5 最终启动脚本（EXP_10.21 基线版）：单节点拉起本节点 P NM + D NM（双侧对称 HCCL env）。
# 结构 = 正本 steps/s4_1_launch/nm_launch_one.sh（P/D 双段）+ g4 setup_env 等价段（EXP_10.14
# run_2p2d_exp.sh:208-228 逐字，HCCL_IF_IP=$IP、NIC=enp67s0f5 三节点统一）。
# SLO_*/predictor 四变量仅以命令前缀进 P NM（非 export，不泄给 D）；D 保持纯净。
# TAG/IP 双替换（由 apply 脚本 sed）。
set -e
TAG=__TAG__; IP=__IP__
NAME=motor3p3d-zxy
LOGD=/mnt/esfs/zhangxiyue/qwen3.6-27b/FGJSQ_3P3D/EXP_10.20_MOTOR/04_stack_logs
CFG=/mnt/esfs/zhangxiyue/qwen3.6-27b/FGJSQ_3P3D/EXP_10.20_MOTOR/03_stack/config_sample.json
MC=/mnt/esfs/zhangxiyue/qwen3.6-27b/mooncake_exp_cluster49.json
MODEL=/mnt/esfs/zhangxiyue/qwen3.6-27b/FGJSQ_3P3D/code/predictor_pretrained/model.pkl
NIC=enp67s0f5
cat > /tmp/inside_nm_pd.sh <<I2
set -e
cd $LOGD
# ===== g4 setup_env 等价段（P/D 双侧对称）=====
export PYTHONHASHSEED=0
export HCCL_INTRA_ROCE_ENABLE=1
export HCCL_RDMA_TIMEOUT=17
export ASCEND_CONNECT_TIMEOUT=10000
export ASCEND_TRANSFER_TIMEOUT=10000
export VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=12000
export PYTORCH_NPU_ALLOC_CONF="expandable_segments:True"
export HCCL_OP_EXPANSION_MODE="AIV"
export HCCL_BUFFSIZE=1024
export TASK_QUEUE_ENABLE=1
export HCCL_IF_IP="$IP"
export GLOO_SOCKET_IFNAME="$NIC"
export TP_SOCKET_IFNAME="$NIC"
export HCCL_SOCKET_IFNAME="$NIC"
export OMP_PROC_BIND=false
export OMP_NUM_THREADS=10
# ===== P NM（fgjsq/predictor env 以命令前缀注入，仅 P）=====
ROLE=prefill INDEX=0 POD_IP=$IP JOB_NAME=motor3p3d-zxy-p__TAG__ USER_CONFIG_PATH=$CFG \
MOONCAKE_CONFIG_PATH=$MC \
SLO_PATCH_ROLE=prefill ENABLE_BATCH_REPORTER=1 ENABLE_VLLM_TTFT_SLO_MS=0 \
SLO_PREDICTOR_MODEL_PATH=$MODEL \
  nohup python3 -m motor.node_manager.main > $LOGD/n${TAG}_nmp.log 2>&1 &
echo nmp_pid=\$!
sleep 8
# ===== D NM（无 fgjsq/predictor env）=====
ROLE=decode INDEX=0 POD_IP=$IP JOB_NAME=motor3p3d-zxy-d__TAG__ USER_CONFIG_PATH=$CFG \
MOONCAKE_CONFIG_PATH=$MC \
  nohup python3 -m motor.node_manager.main > $LOGD/n${TAG}_nmd.log 2>&1 &
echo nmd_pid=\$!
sleep 8
pgrep -f 'motor.node_manager.main' | wc -l
I2
docker cp /tmp/inside_nm_pd.sh $NAME:/tmp/inside_nm_pd.sh
docker exec $NAME bash /tmp/inside_nm_pd.sh
echo NODE_PD_DONE
```

这就是 P10 根因（g4 setup_env 15 项）与 P11 根因（P/D 对称）的**修复载体本体**——外网如需复现环境，这 15 个 export 与 P/D 对称性是硬前提。`SLO_PREDICTOR_MODEL_PATH` 指向预训练 model.pkl（sha256=142f3364…），在线训练 warm start 语义见 §6.C。

### 4.6 engine_files.json 全文（slo_patch 完整性锚）

```json
{
  "vllm.v1.engine.core": "cf9cbde601afb80925254aae814033abeab3817f9c4fe7bf01ca92edc9d10c2d",
  "vllm.v1.core.sched.async_scheduler": "0022e12f356fd46406f6a6d3c82755daf7287ca2d86e2000c27b05bb8d9621cc",
  "vllm_ascend.core.recompute_scheduler": "38111806d9434e4267482a63a453f6f4328a5d0bf9ae931fa17ad38208d79202"
}
```

三个 key 是 slo_patch activate 时校验的目标引擎文件 sha256 白名单（compatibility.py 逐项 raise 硬失败、无豁免）。固化值 = g4 底座实际文件 hash：两栈 vllm 同 commit 0fc695fc → 前两锚与 rc1 时代相同；第三锚 38111806（g4 版 recompute_scheduler，含 failed_kv 扣减顺序 bugfix）替换 rc1 锚 23abae3c——这是"改 hash 白名单适配新底座"，**不是修改引擎文件**（引擎文件三组件对交付包零修改）。外网复现须知：若底座 vllm/vllm-ascend 版本不同，三锚必须按新底座重算（sha256sum 目标文件后回填），否则 P 引擎启动即 compatibility raise。

### 4.7 镜像 Dockerfile 全文（来源 10_g4base_motor/01_artifacts/build/；构建上下文=01_artifacts/ 下 g5_export/）

```dockerfile
# 方案 E 候选镜像 r2：g4 完整引擎底座 + 当前已跑通的 Motor/FGJSQ/predictor 集成
# 底座 = quay.io/ascend/vllm-ascend:v0.23.0 (660ce23a8357)：vllm 0.23.0+empty@0fc695fc、
#        vllm_ascend 0.23.0@5cb98caa、torch_npu 2.10.0.post4 —— 全部保留不动。
# 增量 = g5 运行容器导出（三节点 md5 一致验证）：
#        motor 3.1.0（含 8 文件现场修复 fix1-8）、slo_patch 0.2.0（含 engine_files.json
#        g4 锚适配版 + fgjsq 七文件适配 + predictor/reporter）、fgjsq、lightgbm 4.7.0。
# r2 修订（2026-10-21 E0 第三轮教训）：r1 只带 docker diff 增量，漏掉两类依赖——
#   (a) rc1 镜像层预装而 g4 底座没有的（docker diff 不可见）：OpenSSL/pyopenssl 26.4.0
#       （motor.common.http.cert_util 必需；g4 自带 cryptography 50.0.0 满足 >=49,<51，
#       零升级）、kubernetes+durationpy+oauthlib+requests_oauthlib+websocket(client)
#       （motor 2 文件引用 kubernetes）、watchdog（1 文件引用）；
#   (b) diff 增量中误判可省的：motor_adapter（FGJSQ 源码补丁的 P 侧集成入口，必需）、
#       sklearn 1.9.1+libs+joblib+threadpoolctl（predictor 侧依赖）。
#   依赖集为证据法选定：grep motor/slo_patch/motor_adapter/fgjsq 源码 import 引用计数>0
#   或 import 链直接命中；0 引用且非传递依赖者不带。仍不触碰底座任何已有路径。
FROM quay.io/ascend/vllm-ascend:v0.23.0
ARG SP=/usr/local/python3.12.13/lib/python3.12/site-packages
COPY g5_export/motor/ ${SP}/motor/
COPY g5_export/motor-3.1.0.dist-info/ ${SP}/motor-3.1.0.dist-info/
COPY g5_export/slo_patch/ ${SP}/slo_patch/
COPY g5_export/slo_patch-0.2.0.dist-info/ ${SP}/slo_patch-0.2.0.dist-info/
COPY g5_export/fgjsq/ ${SP}/fgjsq/
COPY g5_export/lightgbm/ ${SP}/lightgbm/
COPY g5_export/lightgbm-4.7.0.dist-info/ ${SP}/lightgbm-4.7.0.dist-info/
COPY g5_export/narwhals/ ${SP}/narwhals/
COPY g5_export/narwhals-2.26.0.dist-info/ ${SP}/narwhals-2.26.0.dist-info/
COPY g5_export/motor_adapter/ ${SP}/motor_adapter/
COPY g5_export/OpenSSL/ ${SP}/OpenSSL/
COPY g5_export/pyopenssl-26.4.0.dist-info/ ${SP}/pyopenssl-26.4.0.dist-info/
COPY g5_export/sklearn/ ${SP}/sklearn/
COPY g5_export/scikit_learn.libs/ ${SP}/scikit_learn.libs/
COPY g5_export/scikit_learn-1.9.1.dist-info/ ${SP}/scikit_learn-1.9.1.dist-info/
COPY g5_export/joblib/ ${SP}/joblib/
COPY g5_export/joblib-1.6.0.dist-info/ ${SP}/joblib-1.6.0.dist-info/
COPY g5_export/threadpoolctl.py ${SP}/threadpoolctl.py
COPY g5_export/threadpoolctl-3.7.0.dist-info/ ${SP}/threadpoolctl-3.7.0.dist-info/
COPY g5_export/kubernetes/ ${SP}/kubernetes/
COPY g5_export/kubernetes-35.0.0.dist-info/ ${SP}/kubernetes-35.0.0.dist-info/
COPY g5_export/durationpy/ ${SP}/durationpy/
COPY g5_export/durationpy-0.11.dist-info/ ${SP}/durationpy-0.11.dist-info/
COPY g5_export/oauthlib/ ${SP}/oauthlib/
COPY g5_export/oauthlib-3.3.1.dist-info/ ${SP}/oauthlib-3.3.1.dist-info/
COPY g5_export/requests_oauthlib/ ${SP}/requests_oauthlib/
COPY g5_export/requests_oauthlib-2.0.0.dist-info/ ${SP}/requests_oauthlib-2.0.0.dist-info/
COPY g5_export/websocket/ ${SP}/websocket/
COPY g5_export/websocket_client-1.9.2.dist-info/ ${SP}/websocket_client-1.9.2.dist-info/
COPY g5_export/watchdog/ ${SP}/watchdog/
COPY g5_export/watchdog-6.0.0.dist-info/ ${SP}/watchdog-6.0.0.dist-info/
```

三条铁律：①绝不能带 rc1 的 `__editable___vllm_ascend_0_23_0rc1_finder.py` 与 `__editable__.vllm_ascend-0.23.0rc1.pth`（劫持 vllm_ascend import 回 rc1 树）；②纯 COPY 不删不改底座任何已有路径；③构建后必检 import_battery.py（三服务入口+插件链+predictor 依赖 14 模块+底座版本断言）三节点 BATTERY_PASS。防 GC：新 tag 落三节点后立即起 `motor3p3d-zxy-imgkeep` 占位容器。

### 4.8 启动序（唯一正本；错序=故障）

1. 容器就位：`10_g4base_motor/02_e0/e0_stop_and_switch.sh <IP>`（幂等；已跑同版本容器→改 `e0_soft_reset.sh <IP>` 软复位：杀进程+NPU 释放验证，不重切容器）
2. mooncake master：`EXP_10.20_MOTOR/steps/s4_1_launch/mooncake_start.sh`（**仅 .49** 容器内 :50089）——**漏启=全引擎 Worker `Initialize mooncake failed ret=-600`**（P06②）
3. coord/ctrl：`EXP_10.20_MOTOR/steps/s4_1_launch/{coord_restart,ctrl_restart}.sh`（仅 .49）
4. NM：§4.5 脚本三节点各跑一次（sed 替换 __TAG__/__IP__）
5. 验收：`curl :18081/instances` → count=6、decode=3；三节点 :10000/:10002 health；env 断言（P 有 SLO_*、D 无）；link_check；深度项（1024 token 守恒 / finish_reason=length / D External prefix hit ~100% / P 插件事件出现 / 错误窗 0）

一键编排 `10_g4base_motor/02_e0/e0_orchestrate.sh`（含全部+活性断言）。冷启动耗时参考：NM 拉起→实例 Ready ≈3-5 分钟/节点（含 W8A8 权载与 MTP 图构）。

### 4.9 运行时生命周期语义

- **predictor 状态**：随 P NM 进程存活；NM 重启=清零冷启（从 SLO_PREDICTOR_MODEL_PATH 预训练权重 warm start，10:45:39 loaded 行）；**跨压测轮继承**（E2 r01→r02 零重启，r02 无漂移；十档九档同生命周期）。在线训练节奏实证（2026-10-21）：n49 loaded 10:45:39 → v1@11:10:10（r2=0.0691, mae=813）→ v24@12:47:23（r2=0.0467, mae=193）；n151 v1@11:11:28（r2=0.4794）→ v19@12:48:39；n175 v1@11:12:53 → v16@12:02:40。产物落 `04_stack_logs/predictor_results_*/model.pkl`。**注意 r2 普遍很低**（§0.4 残留 3）：模型当前解释力弱，打点/试探用途为主，勿当可靠预测器。
- **mooncake master**：单点 .49:50089，P(kv_producer)→D(kv_consumer) 传输经其寻址；引擎侧 92 条 segment 终身复用（g4 setup_env 在位时）。
- **Coordinatorepoch/reservation**：Coordinator 重启则 coordinator_epoch 递增、旧 reservation 失配；fgjsq.json 的 tombstone_s=3600 控制墓碑清理。

---
## 5. 修改清单（两视角）

外网恢复本基线需要两份"改动账"：相对 g4 底座（镜像内容视角）与相对原始交付物（源码视角）。两账合起来=可完整重建。

### 5.1 视角一：相对 g4 底座镜像 660ce23a8357（=固化镜像的全部内容差异）

**全部为纯新增，零删除零修改**。22 组 COPY 清单见 §4.7 Dockerfile 全文（motor 3.1.0 含现场修复 / slo_patch 0.2.0 / fgjsq / motor_adapter / lightgbm 4.7.0 / narwhals 2.26.0 / OpenSSL+pyopenssl 26.4.0 / sklearn 1.9.1+libs / joblib 1.6.0 / threadpoolctl 3.7.0 / kubernetes 35.0.0 / durationpy / oauthlib / requests_oauthlib / websocket client 1.9.2 / watchdog 6.0.0 + 各 dist-info）。底座组件（vllm 0.23.0+empty@0fc695fc、vllm-ascend 0.23.0@5cb98caa、torch-npu 2.10.0.post4、CANN 9.0.1、mooncake 0.3.11.post1）一字未动。

**内容保真三件套**（复现校验用）：
1. motor 8 修复文件聚合 md5 = `fcce4957d1fa5a22a844b338521916ee`（三节点一致实测）
2. import_battery.py 三节点 BATTERY_PASS（14 模块：三服务入口 motor.node_manager/coord/ctrl、插件链 fgjsq+motor_adapter+slo_patch.activate、predictor 依赖 lightgbm/sklearn/joblib、底座版本断言 vllm_ascend==0.23.0 正式、torch_npu==2.10.0.post4）
3. engine_files.json 三锚（§4.6）= 底座实际文件 sha256

### 5.2 视角二：相对原始 Motor 交付物（用户 2026-10-19 交付包 fgjsq-motor-p-0.2.0-20261019.tar.gz）

交付包内容=三合一 wheel（fgjsq+motor_adapter+slo_patch 0.2.0，单 entrypoint `slo_patch`）+ Motor 七文件 patch（锚 f203263d）。实际改动分三层：

**(a) Motor 源码七文件 patch**（用户交付原样、已 apply 进镜像 motor/ 树；全文如下——这是 FGJSQ 接入 Motor 的全部 Coordinator 侧改动）：

```diff
diff --git a/motor/coordinator/api_server/management_server.py b/motor/coordinator/api_server/management_server.py
--- a/motor/coordinator/api_server/management_server.py
+++ b/motor/coordinator/api_server/management_server.py
@@ -49,6 +49,9 @@
+from motor_adapter import bindings as fgjsq_hooks
+from motor_adapter.config import enabled as fgjsq_enabled
@@ -382,6 +385,7 @@ class ManagementServer(BaseCoordinatorServer):
     def _register_routes(self) -> None:
+        fgjsq_hooks.register_routes(self)          # ← /fgjsq/v1/events 路由注册（事件入口）
         @self.management_app.get("/startup")

diff --git a/motor/coordinator/domain/scheduling.py b/motor/coordinator/domain/scheduling.py
@@ -142,6 +142,8 @@ class UpdateWorkloadParams:
     operation_id: str | None = None
+    fgjsq_reservation_id: str | None = None
+    fgjsq_coordinator_epoch: str | None = None
@@ -156,6 +158,7 @@ class SchedulingFacade(Protocol):
         *,
+        attempt_seq: int | None = None,             # select_and_allocate 签名扩展（P 侧透传）
         target_instance_id: int | None = None,

diff --git a/motor/coordinator/models/request.py b/motor/coordinator/models/request.py
@@ -99,6 +99,7 @@ class RequestInfo(BaseModel):
+    _fgjsq_state: dict = PrivateAttr(default_factory=dict)   # 每请求 FGJSQ 私有态（reservation 元数据挂点）

diff --git a/motor/coordinator/router/strategies/base.py b/motor/coordinator/router/strategies/base.py
@@ -59,6 +59,9 @@
+from motor_adapter import bindings as fgjsq_hooks
+from motor_adapter.config import enabled as fgjsq_enabled
@@ -245,12 +248,16 @@ class BaseRouter(ABC):        # _request_lifecycle：请求生命周期壳
+        fgjsq_hooks.validate_router(self)           # 启动期断言 router 具备所需属性
         await self._request_manager.add_req_info(self.req_info)
         finally:
-                await self._reclaim_residual_workloads()
+                try:
+                    await self._reclaim_residual_workloads()
+                finally:
+                    await fgjsq_hooks.finish_request(self)   # ← 兜底释放（正常/异常路径都走；abort 幂等）
@@ -553,6 +560,7 @@（streaming forward）
+        req_data, fg_observer = fgjsq_hooks.prepare_forward(self, req_data)   # D 侧生成 FirstBodyObserver
@@ -603,6 +611,8 @@（chunk 循环）
                 async for chunk in response.aiter_bytes():
+                    if fg_observer is not None:
+                        fg_observer.observe(chunk)   # ← D 首个非空 body bytes → release_fg 触发点
@@ -647,6 +657,7 @@（非流式 forward）
+        req_data, fg_observer = fgjsq_hooks.prepare_forward(self, req_data)
@@ -695,7 +706,16 @@（非流式响应体观察）
+                if fg_observer is not None:
+                    if response.is_stream_consumed:
+                        fg_observer.observe(response.content)
+                    else:
+                        from motor_adapter.body_observer import ObservedStream
+                        response.stream = ObservedStream(response.stream, fg_observer)
+            elif fg_observer is not None:
+                fg_observer.observe(response.content)

diff --git a/motor/coordinator/router/strategies/unified_pd.py b/motor/coordinator/router/strategies/unified_pd.py
@@ -96,6 +96,9 @@
+from motor_adapter import bindings as fgjsq_hooks
+from motor_adapter.config import enabled as fgjsq_enabled
@@ -501,6 +504,7 @@ / @@ -575,6 +579,7 @@（两处 attempt 循环）
                         coordination_mode = self._select_coordination_mode(attempt)
+                        fgjsq_hooks.validate_mode(coordination_mode)   # 仅支持 CONCURRENT_ENGINE 同步模式
@@ -1968,7 +1973,7 @@（build leg request）
-        return engine_request.body, engine_request.api
+        return fgjsq_hooks.attach_request(self, attempt, role, engine_request.body), engine_request.api
         # ↑ P 侧把 kv_transfer_params.fgjsq={reservation_id, coordinator_epoch, attempt_seq,
         #   instance_id, endpoint_id, generation, event_url} 注入请求体（仅 P；D 原样）
@@ -2113,6 +2118,8 @@（_schedule_leg）
         scheduler_kwargs = {"target_instance_id": target_instance_id}
+        if fgjsq_enabled() and role == PDRole.ROLE_P:
+            scheduler_kwargs["attempt_seq"] = attempt_seq
@@ -2156,6 +2163,7 @@（_release_attempt）
     async def _release_attempt(self, attempt, *, wait=True):
+        await fgjsq_hooks.finish_attempt(self, attempt)   # ← P HANDOFF 完成后 release_native 触发点
@@ -2337,6 +2345,10 @@（UpdateWorkloadParams 构造）
+            fgjsq_reservation_id=(fgjsq_hooks.metadata(self.req_info, attempt_seq) or {}).get('reservation_id')
+                if role == PDRole.ROLE_P and fgjsq_enabled() else None,
+            fgjsq_coordinator_epoch=(fgjsq_hooks.metadata(self.req_info, attempt_seq) or {}).get('coordinator_epoch')
+                if role == PDRole.ROLE_P and fgjsq_enabled() else None,

diff --git a/motor/coordinator/scheduler/runtime/scheduler_client.py b/motor/coordinator/scheduler/runtime/scheduler_client.py
@@ -69,6 +69,9 @@
+from motor_adapter import bindings as fgjsq_hooks
+from motor_adapter.config import enabled as fgjsq_enabled
@@ -961,11 +964,18 @@ class AsyncSchedulerClient:（select_and_allocate）
-        """Select locally, then CAS-commit on schema-4 SHM (no ALLOCATE_ONLY ZMQ)."""
+        """P FGJSQ uses Mgmt; disabled and D allocation retain native CAS."""
+        if fgjsq_enabled() and role == PDRole.ROLE_P:
+            return await fgjsq_hooks.allocate(   # ← FGJSQ-1 入场分流：P 走 Mgmt 账本，D 保留原生 CAS
+                self, role, req_info, attempt_seq, target_instance_id=target_instance_id,
+                required_engine_type=required_engine_type,
+                required_dispatch_capability=required_dispatch_capability)
@@ -1394,7 +1404,10 @@（update_workload）
-        """Release path: CAS-sub floor 0 on schema-4 SHM (no UPDATE_WORKLOAD ZMQ)."""
+        """FGJSQ P release is idempotent; D/disabled retain CAS-sub."""
+        if fgjsq_enabled() and params.role == PDRole.ROLE_P:
+            return await fgjsq_hooks.native_release(self, params)   # ← FGJSQ-4 幂等 native 释放

diff --git a/motor/coordinator/scheduler/runtime/scheduler_server.py b/motor/coordinator/scheduler/runtime/scheduler_server.py
@@ -49,6 +49,9 @@
+from motor_adapter import bindings as fgjsq_hooks
+from motor_adapter.config import enabled as fgjsq_enabled
@@ -118,9 +121,12 @@ class _SchedulerRequestDispatcher:
+        fgjsq_hooks.init_dispatcher(self)
     async def dispatch(self, request: SchedulerRequest) -> SchedulerResponse:
+        if request.request_type == fgjsq_hooks.WIRE_TYPE:
+            return await fgjsq_hooks.dispatch(self, request)   # 事件 RPC 进入 mgmt server 的传输挂钩
```

（完整 hunk 上下文见交付包 patches/motor/f203263d-p-fgjsq.patch，270 行；上文为逐 hunk 全量 diff 行+注释说明。）

**(b) Motor 现场修复 fix1-fix8**（拉起期排障产生，已含在镜像 motor/ 树内；逐条六要素见 §3.2，此处只列文件级账目）：

| fix | 文件 | 改动 |
|---|---|---|
| fix1 | `motor/config/node_manager.py` | lookup_rpc_port 位置冲突修复（8 行 diff 见 §3.2 P01；唯一算法外源码补丁） |
| fix2 | config（非源码） | D `no_enable_prefix_caching` 否定式键 |
| fix3 | config/编排 | P/D 分 JOB_NAME（p49/p151/p175+d49/d151/d175） |
| fix4 | 编排 | NM 串行拉起（P sleep 8 → D） |
| fix5 | 运维 | 清 10.16 遗留 24 卡占卡 |
| fix6 | 编排 | mooncake master 自持拉起（漏启=ret=-600） |
| fix7 | config | P api_server_host/port 占位过 0.2.0 硬校验 |
| fix8 | 运维/逻辑 | Coordinator 池按 (role, job_name) 去重 → 1P1D/节点 |

**(c) slo_patch/fgjsq/motor_adapter 对交付包的改动 = 零**。diff 仅两处且均非代码语义：`slo_patch/.gitkeep`（导出携带）与 `slo_patch/engine_files.json`（三锚适配：第三锚 23abae3c→38111806，§4.6 依据）。predictor 三件（predictor_impl.py/predictor.py/batch_reporter.py）与 g4 逐字节一致（94 文件 sha256 全过，2026-10-20 CHECK_REPORT）。冒烟脚本 smoke.py 有 EXP 副本（随实验目录走，不在镜像内）。

### 5.3 三节点一致性

同 Dockerfile+同 esfs 构建上下文，三节点本地 build（镜像 ID 异=层时间戳，内容同源：.49=9ff2237f0ebe/.151=c590300504b9/.175=fb149ce8f7d2，r1 固化 tag 与 r2 同镜像双 tag）；motor 8 文件聚合 md5 三节点一致（§5.1）。

### 5.4 运行时 monkey patch 清单（非文件态修改，每次引擎启动时由 slo_patch entrypoint 施加）

| 目标 | 位置 | 作用 | 门控 |
|---|---|---|---|
| `EngineCore.step` / `step_with_batch_queue` | slo_patch/patch_core.py | 打点版 step（批事件采集→batch_event_reporter；SLO=0 时不干预调度决策） | SLO_PATCH_ROLE=prefill（仅 P） |
| `NPUPlatform.check_and_update_config` | slo_patch/patch_runtime.py（classmethod 包装） | 挂 scheduler_cls 重指 + additional_config 校验钩 | 同上 |
| chat_utils tool_args / kv debug / multi-connector kv events | patch_runtime 内 | **env 门控未启用**（当前全关；P3D_KV_EVENTS_FIX/P3D_KV_DEBUG 两开关存在但未开） | 各自 env，默认 off |

关键语义：`scheduler_with_predictor_enable=true`（config）+ activate 重指 = P 引擎 scheduler 类换成 SchedulerWithPredictorAsync；**ENABLE_VLLM_TTFT_SLO_MS=0 → SLO 干预硬关**，SchedulerWithPredictorAsync 退化为 AsyncRecomputeScheduler 行为+每步打点。这是"接入零行为变更"验证（Phase 2 A/B 四轮全指标 <1%）的机制基础。

### 5.5 回退

- 回 rc1 旧栈：三节点 `docker rm -f motor3p3d-zxy && docker start motor3p3d-zxy-rc1-keep && docker rename motor3p3d-zxy-rc1-keep motor3p3d-zxy` → 按 §4.8 重拉（10.20 日志已备份 02_e0/prelogs/）
- 回 g4 原生栈：停本栈，g4 runbook（EXP_10.14，镜像 660ce23a8357 底座原 tag）
- 本版本内部重置：e0_soft_reset.sh（不重切容器）

---

## 6. 关键源码（外网离线正本；冻结镜像内路径 /usr/local/python3.12.13/lib/python3.12/site-packages/）

### 6.A 入场与路由（Coordinator 侧，fgjsq+motor_adapter 两包）

#### A.1 fgjsq/policy.py 全文（负载账本数学核心，97 行）

```python
"""Deterministic G4 formulas; no routing transport or engine dependencies."""
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True)
class Progress:
    prompt: int
    scheduled: int
    remaining: int
    predicted_ms: float


@dataclass
class Reservation:
    instance: str
    original: int
    committed: int
    received_ms: int = 0
    progress: Progress | None = None


class FineGrainedPolicy:
    def __init__(self, max_seqs: int = 24, retention: float = 0.05, clock=None):
        if max_seqs <= 0 or not 0 <= retention < 1:
            raise ValueError("invalid FGJSQ parameters")
        self.max_seqs = max_seqs
        self.retention = retention
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.requests: dict[str, Reservation] = {}
        self.loads: dict[str, list[int]] = {}
        self.limits: dict[str, int] = {}

    def add_instance(self, instance: str, max_seqs: int | None = None) -> None:
        self.loads.setdefault(instance, [0, 0])
        self.limits[instance] = max_seqs or self.max_seqs

    def actual(self, request: Reservation, now_ms: int) -> int:
        p = request.progress
        if p is None or p.prompt <= 0:
            return request.original
        waiting = request.original * p.remaining / p.prompt
        running = request.original * p.scheduled / p.prompt
        elapsed = now_ms - request.received_ms
        progress = min(elapsed / p.predicted_ms, 1 - self.retention) if p.predicted_ms > 0 and elapsed > 0 else 0
        return int(round(waiting + running * (1 - progress)))

    def recompute(self) -> None:
        now = self.clock()
        for request in self.requests.values():
            if request.progress is not None:
                value = self.actual(request, now)
                self.loads[request.instance][1] += value - request.committed
                request.committed = value

    def score(self, instance: str) -> float:
        count, load = self.loads[instance]
        return float(load) * (math.ceil(count / self.limits[instance]) + 1) / 2

    def rank(self, eligible: list[str]) -> list[str]:
        for instance in eligible:
            self.add_instance(instance, self.limits.get(instance))
        self.recompute()
        allowed = set(eligible)
        return sorted((i for i in self.loads if i in allowed), key=self.score)

    def reserve(self, key: str, instance: str, estimated_tokens: int) -> None:
        if key in self.requests:
            raise ValueError("duplicate reservation")
        self.add_instance(instance, self.limits.get(instance))
        self.loads[instance][0] += 1
        self.loads[instance][1] += estimated_tokens
        self.requests[key] = Reservation(instance, estimated_tokens, estimated_tokens)

    def event(self, key: str, progress: Progress) -> None:
        request = self.requests[key]
        if request.progress is None and progress.prompt > 0 and progress.prompt != request.original:
            delta = progress.prompt - request.original
            self.loads[request.instance][1] += delta
            request.original = progress.prompt
            request.committed += delta
        request.progress = progress
        request.received_ms = self.clock()

    def release(self, key: str) -> bool:
        request = self.requests.pop(key, None)
        if request is None:
            return False
        self.loads[request.instance][0] -= 1
        self.loads[request.instance][1] -= request.committed
        return True

    def snapshot(self) -> dict:
        self.recompute()
        return {i: {"requests": n, "committed_tokens": w, "score": self.score(i),
                    "max_num_seqs": self.limits[i]} for i, (n, w) in self.loads.items()}
```

语义要点（外网设计入场/让行策略必须知道的账本行为）：
- **score = load×(ceil(count/limit)+1)/2**：count 过 limit 翻倍惩罚——超编实例被指数级降权，这是粘性（P18）来源也是天然的"让行"杠杆。
- **estimated_tokens = max(1, req_len//4)**（bindings.allocate 内，req_len=Coordinator 侧请求长度口径）：入场即全额记账；**之后只靠批事件衰减**（actual() 线性衰减，基准=事件到达时刻与 predicted_ms；无事件则永不衰减）。
- **事件驱动衰减的反馈含义**：一个请求已被 P 引擎 admission 前，FGJSQ 看到的是满额 estimated_tokens；衰减只反映已调度进度（scheduled/prompt），waiting 排队时间不衰减剩余额度（remaining 部分）。→ 延迟入场的请求持续占用账面 load，会持续压低该实例 score，从而把后续请求导向其它实例——**这是现成的"入场延迟→路由反馈"闭环**（§7 利用点）。
- event() 首事件若 prompt 与 original 不符会**修正 original**（token 数校正），账面随之调平。

#### A.2 motor_adapter/bindings.py 关键段（Coordinator 子进程内 hook 实现，全文 249 行在镜像；此处嵌入入场/释放/元数据三核心）

```python
# —— 入场分流核心（scheduler_client.select_and_allocate 调用）——
async def allocate(client, role, req_info, attempt_seq, **constraints):
    ...
    if attempt_seq is None:
        raise ValueError("FGJSQ only supports UnifiedPD attempts")
    prompt = req_info.req_data.get("prompt")
    if isinstance(prompt, list) and (not prompt or not isinstance(prompt[0], int)):
        raise ValueError("FGJSQ v1 does not support batched prompts")
    if int(req_info.req_data.get("n", 1)) != 1:
        raise ValueError("FGJSQ v1 requires n=1")
    state = request_state(req_info)          # _fgjsq_state: {nonce, attempts{seq:record}, tasks}
    record = state["attempts"].setdefault(attempt_seq, {})
    try:
        if "command" not in record:
            hello = await _rpc(client, {"op": "hello"})
            command = {"op": "reserve", "coordinator_epoch": hello["coordinator_epoch"],
                       "key": state["nonce"] + ":" + str(attempt_seq),   # 幂等 key = nonce:attempt_seq
                       "req_id": req_info.req_id,
                       "attempt_seq": attempt_seq,
                       "reserve_deadline": time.time() + get_config().reserve_window_s,
                       "estimated_tokens": max(1, req_info.req_len // 4),
                       "native_tokens": float(calculate_demand_workload(role, req_info).active_tokens),
                       **constraints}
            record["command"] = command
        ack = await _rpc(client, record["command"])        # 重试同 key → 幂等返回同 reservation
        if ack.get("unavailable"):
            return None                                    # 全实例拒收 → Motor 重试 attempt
        if ack["native_released"] or ack["fg_released"]:
            raise RuntimeError("attempt already closed; cannot resend")
        record["ack"] = ack
        return (Instance.model_validate(ack["instance"]), Endpoint.model_validate(ack["endpoint"]),
                Workload(active_tokens=ack["native_tokens"]))
    except BaseException:
        with CancelScope(shield=True):
            await release_record(client, record, "abort", suppress=True)   # 失败即兜底 abort
        raise
```

```python
# —— 请求体注入（unified_pd.attach_request 调用）——
def attach_request(router, attempt, role, body: dict) -> dict:
    if not enabled():
        return body
    meta = metadata(router.req_info, attempt.attempt_seq)
    if not meta:
        raise RuntimeError("FGJSQ reservation missing for native leg")
    body = copy.deepcopy(body)
    body.pop(BODY_MARKER, None)
    kv = body.get("kv_transfer_params")
    if isinstance(kv, dict):
        kv.pop("fgjsq", None)
    if getattr(role, "value", role) == "prefill":
        body.setdefault("kv_transfer_params", {})["fgjsq"] = meta
        # meta = {schema_version, coordinator_epoch, reservation_id, attempt_seq,
        #         instance_id, endpoint_id, generation, event_url}
    else:
        # Consumed at Coordinator HTTP boundary; never sent to D.
        body[BODY_MARKER] = {"attempt_seq": attempt.attempt_seq, "reservation_id": meta["reservation_id"]}
    return body
```

```python
# —— 两释放点与兜底 ——
async def native_release(client, params) -> bool:          # update_workload 分流（P 侧）
    if not params.fgjsq_reservation_id or not params.fgjsq_coordinator_epoch:
        logger.error("P native release lacks FGJSQ identity req_id=%s; final abort will reconcile", params.req_id)
        return False
    return bool((await _rpc(client, {"op": "release_native",
                "coordinator_epoch": params.fgjsq_coordinator_epoch,
                "reservation_id": params.fgjsq_reservation_id})).get("ok"))

def prepare_forward(router, body: dict):                    # D 转发前：marker → FirstBodyObserver
    ...
    return body, FirstBodyObserver(lambda: release_record(router._scheduler, record, "release_fg"),
                                   state["tasks"])

async def finish_attempt(router, attempt) -> None:          # _release_attempt 头部（HANDOFF 后）
    if enabled():
        await release_record(router._scheduler, record_for(router.req_info, attempt.attempt_seq), "abort", suppress=True)

async def finish_request(router) -> None:                   # 生命周期壳兜底（每 record abort）
    ...
    for record in state["attempts"].values():
        await release_record(router._scheduler, record, "abort", suppress=True)
```

`validate_router` 启动期硬校验：仅 UnifiedPDRouter、仅 v1/chat/completions 与 v1/completions、必须原生 OpenAI transport（tokenized 禁用）；`validate_mode` 仅 handoff 模式。config.py 的 `validate_motor` 拒绝主备/Render/token 混淆/hybrid 回退四配置——外网打开 FGJSQ 前必须关这四项。

#### A.3 motor_adapter/body_observer.py 全文（D 首输出→release_fg 机制，42 行）

```python
"""Observe the first nonempty D body bytes without changing the byte stream."""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)


class FirstBodyObserver:
    def __init__(self, release, tasks: set):
        self.release = release
        self.tasks = tasks
        self.seen = False

    def observe(self, chunk: bytes) -> None:
        if not chunk or self.seen:
            return
        self.seen = True
        task = asyncio.create_task(self.release())
        self.tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("P FG release failed; request finalizer will retry: %s", task.exception())


class ObservedStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, observer: FirstBodyObserver):
        self.stream = stream
        self.observer = observer

    async def __aiter__(self):
        async for chunk in self.stream:
            self.observer.observe(chunk)
            yield chunk

    async def aclose(self) -> None:
        await self.stream.aclose()
```

关键：**release_fg 的触发不是"D 完成首 token 计算"，而是"Coordinator 收到 D 首个非空 body bytes"**——含 SSE 注释行/padding 在内的一切非空字节。FG 账本释放早于 native（HANDOFF）还是晚于，取决于流时序；两 flag 独立、abort 双收。

#### A.4 motor_adapter/service.py 核心段（Mgmt 侧账本服务，全文 187 行在镜像）

```python
# —— command 分发（asyncio.Lock 全程串行；epoch 校验防跨代操作）——
async def command(self, data: dict) -> dict:
    async with self.lock:
        self._prune()
        op = data.get("op")
        if op == "hello":
            return {"schema_version": 1, "coordinator_epoch": self.epoch}
        if data.get("coordinator_epoch") != self.epoch:
            raise ValueError("coordinator epoch changed; drain/reconcile before retry")
        if op == "reserve":
            return self._reserve(data)
        rid = data.get("reservation_id") or self.keys.get(data.get("key"))
        r = self.records.get(rid)
        if op == "query":
            return {"found": r is not None, "record": self._ack(r) if r else None}
        if r is None:
            if op == "abort" and data.get("key"):
                self.cancelled[data["key"]] = self.clock() + self.config.tombstone_s
                return {"ok": True, "reason": "cancelled_before_reserve"}
            # Never subtract native tokens from a caller-supplied delta.
            return {"ok": False, "reason": "unknown_reservation"}
        if op not in ("release_native", "release_fg", "abort"):
            raise ValueError("unknown operation")
        if op in ("release_native", "abort") and not r.native_released:
            if not self.backend.release(r.candidate, r.native_tokens):   # Motor SHM CAS-sub floor0
                return {"ok": False, "reason": "native_release_unconfirmed"}
            r.native_released = True
        if op in ("release_fg", "abort") and not r.fg_released:
            self.policy.release(r.reservation_id)                        # FG 账本扣减
            r.fg_released = True
        if r.native_released and r.fg_released and r.closed_at is None:
            r.closed_at = self.clock()
        self.metrics[op] += 1
        return {"ok": True, "record": self._ack(r)}
```

```python
# —— _reserve：rank 顺序试 Native CAS，全拒才 unavailable ——
def _reserve(self, data: dict) -> dict:
    key = data["key"]
    if key in self.cancelled:
        raise ValueError("attempt cancelled before reserve")
    if key in self.keys:                                  # 幂等重发
        r = self.records[self.keys[key]]
        if r.request != data:
            raise ValueError("idempotency key reused with different reserve parameters")
        return self._ack(r)
    deadline = float(data["reserve_deadline"])            # 超窗拒收
    ...
    candidates = self.backend.candidates(data)            # Motor 实例快照 → P 候选
    by_instance = {str(c["instance_id"]): c for c in candidates}
    if len(by_instance) != len(candidates):
        raise ValueError("FGJSQ v1 requires one endpoint per P instance")
    for instance in self.policy.rank(list(by_instance)):  # ← FGJSQ score 排序（入场决策点）
        c = by_instance[instance]
        if not self.backend.reserve(c, native):           # Motor 原生 CAS-add 二道闸
            continue
        rid = uuid.uuid4().hex
        r = Record(key, rid, c, native, dict(data))
        try:
            self.policy.reserve(rid, instance, tokens)
            self.records[rid] = r
            self.keys[key] = rid
        except BaseException:
            ...  # 全回滚
        self.metrics["reserved"] += 1
        return self._ack(r)
    return {"unavailable": True}
```

```python
# —— events：批事件校验链（身份五元组+epoch+batch_seq 单调）——
async def events(self, payload: dict) -> dict:
    async with self.lock:
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported event schema")
        counts = Counter()
        for item in payload.get("requests", []):
            counts["received"] += 1
            r = self.records.get(item.get("reservation_id"))
            if r is None or r.fg_released:
                counts["unknown_or_released"] += 1
                continue
            if (item.get("coordinator_epoch") != self.epoch or
                    item.get("instance_id") != r.candidate["instance_id"] or
                    item.get("endpoint_id") != r.candidate["endpoint_id"] or
                    item.get("generation") != r.candidate["generation"] or
                    item.get("attempt_seq") != r.request["attempt_seq"]):
                counts["wrong_identity"] += 1
                continue
            seq, epoch = payload.get("batch_seq"), payload.get("engine_epoch")
            ...
            if r.engine_epoch is not None and r.engine_epoch != epoch:
                counts["wrong_engine_epoch"] += 1     # P 引擎重启检测
                continue
            if seq <= r.batch_seq:
                counts["stale"] += 1                  # 乱序/重放防护
                continue
            ...
            self.policy.event(r.reservation_id, p)    # → Progress → actual() 衰减
            r.engine_epoch, r.batch_seq = epoch, seq
            counts["matched"] += 1
        self.metrics.update(counts)
        return dict(counts)
```

snapshot()（GET /fgjsq/v1/loads）：返回 policy.snapshot()（每实例 requests/committed_tokens/score/max_num_seqs）+ metrics + open_native/open_fg/records/tombstones——**外网监控入场压力的第一现场接口**。

#### A.5 请求生命周期字段演变（脱敏示例，保留字段结构与单位）

一个请求经三层时携带的 FGJSQ 相关字段（值全为示例）：

```
① 客户端 → Coordinator(:18080)
POST /v1/chat/completions
{ "model": "Qwen3.6-27B", "stream": true,
  "messages": [{"role":"user","content":"<业务文本约126k token>"}],
  "max_tokens": 1024, "temperature": 0.01, "top_k": 20, "top_p": 0.95 }
  —— 此时无任何 FGJSQ 字段

② Coordinator 内部（router attempt_seq=0）
req_info._fgjsq_state = { "nonce": "a1b2c3d4…(32hex)",
                          "attempts": { 0: { "command": {"op":"reserve", "key":"a1b2c3d4…:0",
                                       "estimated_tokens": 31500, "native_tokens": 131072.0, …},
                                       "ack": {"reservation_id":"e5f6…(32hex)",
                                               "coordinator_epoch":"9a8b…(32hex)",
                                               "instance_id":1, "endpoint_id":101,
                                               "generation":3,
                                               "event_url":"http://7.193.130.49:18081/fgjsq/v1/events"} } } }
  —— estimated_tokens=req_len//4（无量纲 token 数）；native_tokens=Motor workload 口径 token 数

③ Coordinator → P 引擎(:10000)
body.kv_transfer_params.fgjsq = { "schema_version":1, "coordinator_epoch":"9a8b…",
  "reservation_id":"e5f6…", "attempt_seq":0, "instance_id":1, "endpoint_id":101,
  "generation":3, "event_url":"http://7.193.130.49:18081/fgjsq/v1/events" }
  —— P 引擎从 request.kv_transfer_params['fgjsq'] 读身份（snapshot.py:21）

④ P 引擎批事件 POST（由 freeze_snapshot 构造，json）
{ "schema_version":1, "engine_epoch":"c3d4…(32hex)", "batch_seq":1207,
  "captured_at":1761028000.123, "requests":[ { "reservation_id":"e5f6…",
  "coordinator_epoch":"9a8b…", "attempt_seq":0, "instance_id":1, "endpoint_id":101,
  "generation":3, "engine_request_id":"req-abc123…",
  "num_prompt_tokens":126000, "num_computed_tokens":8192,
  "num_scheduled_tokens":8192, "num_remaining_tokens":117808,
  "predicted_exec_ms":813.4 } ] }
  —— 全 token 数整数；predicted_exec_ms 毫秒三位小数；batch_seq 引擎内单调

⑤ Coordinator → D 引擎(:10002)：marker 剥离后纯原生请求（D 不感知 FGJSQ）
```

### 6.B P 引擎调度链路与 chunked prefill（外网设计入场/让行策略的引擎侧正本）

#### B.1 调用链与 scheduler MRO

```
HTTP :18080 (Coordinator) → P 引擎 APIServer :10000
  → EngineCore.add_request → SchedulerWithPredictor.add_request（warmup 2 个跳过计数后透传）
  → RecomputeScheduler.add_request（MTP consumer 占位 token 注入 + _enqueue_waiting_request）
      → waiting: FCFSRequestQueue(deque)   [blocked 状态入 skipped_waiting]
  → EngineCore.step_with_batch_queue（patch_core 打点版）
      → SchedulerWithPredictor.schedule()（waiting<=1 直通；SLO 关 → prefilter 返回空，等价直通）
        → RecomputeScheduler.schedule()  [= vllm Scheduler.schedule 的 ascend 改造版]
            ① RUNNING 循环（token budget 先耗）
            ② WAITING admission 循环（peek→校验→allocate_slots→入 running）
      → execute_model(non_block) → batch_queue（深度流水）
  → update_from_output（predictor 异步 update + 事件 emit 队列批）
```

MRO（P）：`SchedulerWithPredictorAsync → SchedulerWithPredictor → AsyncRecomputeScheduler → AsyncScheduler → RecomputeScheduler → vllm Scheduler`。**fix-async 教训（源码注释实证）**：async 实例若丢 AsyncScheduler 契约（MTP spec-token 记账）→ SWA in_flight=负 → recompute_scheduler assert → EngineDead。**任何新 scheduler 插件必须保留 MRO 中的 Async 基类**。

#### B.2 SchedulerWithPredictor 关键源码（SLO 关闭态=冻结行为）

```python
# __init__：SLO 硬关 + reporter 装配（scheduler_with_predictor.py:60-101 摘录）
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    ttft_slo_ms = int(os.getenv(_ENV_ENABLE_SLO_MS, "0") or 0)
    batch_reporter_flag = int(os.getenv(_ENV_ENABLE_BATCH_REPORTER, "0") or 0)
    if ttft_slo_ms != 0:
        raise ValueError("Admission scheduling is outside the FGJSQ baseline")  # ← 非零直接拒启
    self._slo_enabled = False
    self._batch_reporter_enabled = bool(batch_reporter_flag)
    if self._slo_enabled or self._batch_reporter_enabled:
        self._init_predictor()
    ...
    if self._batch_reporter_enabled:
        self.batch_reporter = BatchReporter()
        additional_config = getattr(self.vllm_config, 'additional_config', None) or {}
        addr = additional_config.get("api_server_host", "")
        port = additional_config.get("api_server_port", 0)
        if addr and port:
            self._batch_event_reporter = BatchEventReporter(addr=addr, port=port)
        else:
            raise RuntimeError("P reporter requires api_server_host and api_server_port")
```

```python
# schedule()：SLO 关时 prefilter 直通（213-229）
def schedule(self):
    if len(self.waiting) <= 1:
        return super().schedule()
    deferred = self._slo_prefilter_waiting()   # SLO 关 → 立即 return None（309-311）
    result = super().schedule()
    if deferred:
        for r in deferred:
            self.waiting.add_request(r)
    ...
    return result

# _slo_prefilter_waiting 开关闸（309-311）——双队列现成骨架（dead code）：
def _slo_prefilter_waiting(self):
    if not self._slo_enabled or self.predictor is None:
        return None
    ...
    all_requests = []
    while self.waiting:
        all_requests.append(self.waiting.pop_request())   # pop 全部
    ...
    slo_requests.sort(key=lambda r: getattr(r, 'slo_priority', float('inf')))
    H = slo_requests[0]                                    # 最紧迫者
    batch = [H] + no_slo_requests
    deferred = []
    for r in slo_requests[1:]:
        ...
        predicted_ttft = self.predictor.predict(batch_size=..., avg_prompt_length=..., cache_hit_rate=...) / 1000.0
        if predicted_ttft <= T_remain:
            batch.append(r)
        else:
            deferred.append(r)                             # 让行集合
    for r in batch:
        self.waiting.add_request(r)
    return deferred                                        # super().schedule() 后回队
```

**这是冻结基线中唯一现成的"入场前分类+延迟"机制**：pop 全部→分类→批回队/延迟回队，全程不触碰 admission 循环本体。当前因 `_slo_enabled=False` 为 dead code；激活需 ENABLE_VLLM_TTFT_SLO_MS≠0——但 __init__ 的 raise 拦死了这条路（Admission scheduling is outside the FGJSQ baseline）。**外网启用=必须改 scheduler_with_predictor.py 本体（去掉 raise）或换独立子类**——前者触碰交付包纪律，后者是推荐路径（§6.E.4）。

#### B.3 原生 waiting admission 循环（vllm 0fc695fc，容器路径 /vllm-workspace/vllm/vllm/v1/core/sched/scheduler.py；RecomputeScheduler.schedule 为同构复制+preempt/recompute 扩展）

```python
# L340  def schedule(self) -> SchedulerOutput:
#   ……（token_budget = max_num_batched_tokens = 8192）
# L373  # First, schedule the RUNNING requests.（running-first：先耗尽 budget）
        req_index = 0
        while req_index < len(self.running) and token_budget > 0:
            request = self.running[req_index]
            #   ……（async/spec 占位跳过、long_prefill_token_threshold 截断、encoder 预算）
            num_new_tokens = min(num_new_tokens, token_budget)      # 共享 token budget
            with record_function_or_nullcontext("schedule: allocate_slots"):
                while True:
                    new_blocks = self.kv_cache_manager.allocate_slots(request, num_new_tokens, …)
                    if new_blocks is not None:
                        break
                    # KV 不足 → 抢占最低优先级 running（FCFS 时 pop 尾部=最新入场者）
            scheduled_running_reqs.append(request); token_budget -= num_new_tokens; req_index += 1

# L560  # Next, schedule the WAITING requests.
        if not preempted_reqs and self._pause_state == PauseState.UNPAUSED:
            step_skipped_waiting = create_request_queue(self.policy)
            while (self.waiting or self.skipped_waiting) and token_budget > 0:
                if len(self.running) == self.max_num_running_reqs:
                    break
                request_queue = self._select_waiting_queue_for_scheduling()   # FCFS: skipped 优先
                request = request_queue.peek_request()                        # 队首候选
                # blocked 状态（WAITING_FOR_REMOTE_KV 等）→ pop → step_skipped 队首，continue（跳过）
                # lora 超限 → 同上跳过
                if request.num_computed_tokens == 0:
                    new_computed_blocks, num_new_local_computed_tokens = (
                        self.kv_cache_manager.get_computed_blocks(request))    # ← P 本地 prefix hit（有副作用）
                    if self.connector is not None:
                        ext_tokens, load_kv_async = self.connector.get_num_new_matched_tokens(
                            request, num_new_local_computed_tokens)           # ← external KV 查询
                        if ext_tokens is None:
                            request_queue.pop_request(); step_skipped_waiting.prepend_request(request); continue
                    num_computed_tokens = num_new_local_computed_tokens + num_external_computed_tokens
                num_new_tokens = request.num_tokens - num_computed_tokens
                if 0 < threshold < num_new_tokens: num_new_tokens = threshold # long_prefill 截断
                if (not self.scheduler_config.enable_chunked_prefill
                        and num_new_tokens > token_budget):
                    break                                  # 非分块：预算不足→停止整轮 admission
                num_new_tokens = min(num_new_tokens, token_budget)
                new_blocks = self.kv_cache_manager.allocate_slots(request, num_new_tokens, …)
                if new_blocks is None:
                    break                                  # ← 队首放不下：停止整个 waiting 循环（不跳过）
                request = request_queue.pop_request()
                if load_kv_async:
                    request.status = RequestStatus.WAITING_FOR_REMOTE_KVS
                    step_skipped_waiting.prepend_request(request); continue
                self.running.append(request)               # ← 首次 admission 完成
                # token_budget -= num_new_tokens ……
            if step_skipped_waiting:
                self.skipped_waiting.prepend_requests(step_skipped_waiting)
```

要点（入场/让行策略必须遵守的引擎语义）：
- **FCFS + running-first**；waiting 只处理队首；**队首放不下=break 停止整轮**（队首阻塞），跳过仅限 blocked/lora/connector 未定三种。
- chunked prefill enabled（本基线）：首 admission 的请求以 `min(剩余, token_budget, long_prefill_threshold)` 入场，未完部分留在 running 下轮续推（RUNNING 循环），**不回 waiting**。
- 抢占：allocate_slots 失败时对 running 触发；FCFS 抢队尾（最新入场者）；prefix_caching=True → 重算式抢占（释放全部块回 waiting）。冻结验证期未观察到抢占【未验证高压行为，B16 高压基线待十档数据回溯】。

#### B.4 waiting 队列类型与操作接口（request_queue.py 摘录）

```python
class SchedulingPolicy(Enum): FCFS = "fcfs"; PRIORITY = "priority"
# Scheduler.__init__：self.policy = SchedulingPolicy(self.scheduler_config.policy)  → 本基线 P = FCFS
#                    self.waiting = create_request_queue(self.policy)
class FCFSRequestQueue(deque[Request], RequestQueue):
    add_request → append          # 尾入
    pop_request → popleft         # 首出
    peek_request → self[0]
    prepend_request → appendleft
    prepend_requests(q) → extendleft(q)
    remove_request / remove_requests / __iter__ / __bool__ / __len__
class PriorityRequestQueue(RequestQueue):   # heap，序 = (priority, arrival_time)，小者先
    add_request → heapq.heappush …（prepend 语义=重新入堆，无真"插队首"）
def create_request_queue(policy) → FCFSRequestQueue() | PriorityRequestQueue()
# 队列选择：_select_waiting_queue_for_scheduling（FCFS: skipped_waiting or waiting）
```

#### B.5 异步调度提前推进（async 计数≠计算完成）

async 路径下 `step_with_batch_queue` 在上一批 future 未完成时即调度下一批：`scheduled_new_reqs/num_scheduled_tokens`="已提交计算"；num_computed_tokens 在 update_from_output 才前进。因此：
- fgjsq 事件快照的 num_scheduled_tokens = **已提交**，不是已完成；
- `actual_batch_exec_time` 在 async 队非空时是**占位间隔**（标签噪声来源，§6.C.6）；
- MTP spec token in-flight 记账由 AsyncScheduler 契约维护（B.1 fix-async 教训）。

### 6.C predictor（P 侧在线时延模型：特征、训练、标签——chunk size 寻优的关键接口）

#### C.1 特征集与特征函数（predictor_impl.py，FEATURE_COLS + compute_features 全文）

```python
FEATURE_COLS = [
    "N_uncached",            # B*L_avg - B*L_avg*hit（未命中 token 数）
    "B",                      # 批内请求数
    "L_avg",                  # 批平均 prompt 长度
    "cache_hit_rate",         # 批级"剩余率"（见 D.2——不是命中率的直觉语义）
    "prefill_intensity",      # N_uncached / B
    "N_cached",
    "Cross_Attention_Proxy",  # N_uncached*N_cached / B
    "Self_Attention_Proxy",   # N_uncached^2 / B
]

def compute_features(batch_size, avg_prompt_length, cache_hit_rate,
                     total_scheduled_tokens=None, total_cached_tokens=None):
    B = float(batch_size); L_avg = float(avg_prompt_length)
    cache_hit_rate = float(np.clip(cache_hit_rate, 0.0, 1.0))
    if total_cached_tokens is None:
        total_cached_tokens = int(B * L_avg * cache_hit_rate)
    if total_scheduled_tokens is None:
        total_scheduled_tokens = int(B * L_avg - total_cached_tokens)
    N_uncached = float(total_scheduled_tokens); N_cached = float(total_cached_tokens)
    prefill_intensity = N_uncached / (B + 1e-6)
    safe_b = max(B, 1.0)
    Cross_Attention_Proxy = (N_uncached * N_cached) / safe_b
    Self_Attention_Proxy = (N_uncached ** 2) / safe_b
    return {"N_uncached": N_uncached, "B": B, "L_avg": L_avg,
            "cache_hit_rate": cache_hit_rate, "prefill_intensity": prefill_intensity,
            "N_cached": N_cached, "Cross_Attention_Proxy": Cross_Attention_Proxy,
            "Self_Attention_Proxy": Self_Attention_Proxy, ...}
```

**特征全部是批级聚合**（B、L_avg、批级 hit rate）——无单请求粒度特征，无 chunk size 特征。

#### C.2 predict（纯函数、无副作用、sub-ms）

```python
def predict(self, batch_size, avg_prompt_length, cache_hit_rate) -> float:   # 返回毫秒
    if not self._model_ready or self._snapshot is None:
        N_uncached = batch_size * avg_prompt_length * (1 - cache_hit_rate)
        return N_uncached * 0.01                      # 冷启启发式
    snap = self._snapshot
    B = float(batch_size); L_avg = float(avg_prompt_length)
    chr_ = min(max(float(cache_hit_rate), 0.0), 1.0)
    cached_int = int(B * L_avg * chr_); uncached_int = int(B * L_avg - cached_int)
    ...（内联 compute_features，纯 numpy）
    X = np.array([[N_uncached_f, B, L_avg, chr_, prefill_intensity,
                   N_cached_f, cross_ap, self_ap]], dtype=np.float64)
    X_s = (X - snap.scaler_mean) / snap.scaler_scale
    pred_ms = float(snap.gbr.predict(X_s)[0])         # LGBMRegressor
    return pred_ms                                     # 负值→0.001；>60000 截断
```

**外网试探接口**：`predictor.predict(batch_size=任意, avg_prompt_length=任意, cache_hit_rate=任意)` 是纯函数——传假想 (B, L_avg, hit) 组合即可无副作用地查询"假想批的预测执行毫秒"。chunk size 寻优策略可用它做 cost model 的一个组件（语义限制见 C.6）。

#### C.3 训练触发与在线生命周期

```python
# update（由 scheduler_with_predictor._update_worker 后台线程调用，入队点 update_from_output）：
def update(self, actual_ttft, predicted_ttft, batch_size, avg_prompt_length, cache_hit_rate):
    self.batch_count += 1; self.batches_since_update += 1
    features = compute_features(batch_size, avg_prompt_length, cache_hit_rate)
    sample = {**features, self.config.target_col: actual_ttft, "batch_id": self.batch_count}
    self.buffer.add_sample(sample)                    # BucketedSlidingWindow：(L桶1000, H桶0.2) maxlen=100
    if ((not self.warmup_done and self.batch_count >= self.config.warmup_batches)   # warmup_batches=2
            or self.batches_since_update >= self.config.update_interval_batches):   # 100 批一训
        self._train_model()

# 超参（PurePythonPredictorConfig）：n_estimators=300, max_depth=5, lr=0.05,
#   min_child_samples=5, subsample=0.85, min_total_train_samples=50,
#   length_bucket_size=1000, cache_bucket_size=0.2, bucket_maxlen=100
# 预训练加载：SLO_PREDICTOR_MODEL_PATH env → pickle{scaler,gbr} → warmup_done=True 即刻可用
# 训练重入保护：_training_event + 60s timeout force-reset；后台 daemon 线程
```

#### C.4 标签时序（标签从哪来——patch_core 打点链）

```python
# patch_core._predict_batch_exec_time（EngineCore.step 打点版内调用）：
total_prompt_tokens   = sum(r.num_prompt_tokens for r in scheduled_reqs)
total_computed_tokens = sum(r.num_computed_tokens for r in scheduled_reqs)
total_cache_hit_rate  = (total_prompt_tokens - total_computed_tokens) / total_prompt_tokens
exec_batch_size       = len(scheduled_reqs)
avg_prompt_length     = total_prompt_tokens / exec_batch_size
scheduler_output.total_cache_hit_rate/… = …          # 挂到 scheduler_output
predicted_batch_exec_time = predictor.predict(exec_batch_size, avg_prompt_length, total_cache_hit_rate)
scheduler_output.predicted_batch_exec_time = predicted_batch_exec_time
# actual 标签 = scheduler_output.actual_batch_exec_time（vllm-ascend 侧产生；async 队非空时=占位间隔）

# update 入队（scheduler_with_predictor.update_from_output）：
_update_queue.put((predictor,
    {"actual_ttft": scheduler_output.actual_batch_exec_time,      # ← 标签
     "predicted_ttft": scheduler_output.predicted_batch_exec_time,
     "batch_size": scheduler_output.exec_batch_size,
     "avg_prompt_length": scheduler_output.avg_prompt_length,
     "cache_hit_rate": scheduler_output.total_cache_hit_rate},
    {"total_prompt_tokens": …, "total_computed_tokens": …}))
```

#### C.5 批事件快照构造（fgjsq/snapshot.py 全文已在 §6.A 结构中给出要点；此处补 freeze 调用点）

```python
# patch_core._capture_batch_event（EngineCore.step 每步）：
seq = getattr(self, "_fgjsq_batch_seq", 0); self._fgjsq_batch_seq = seq + 1
scheduler_output._fgjsq_snapshot = freeze_snapshot(
    scheduler_output, self.scheduler.requests, _ENGINE_EPOCH, seq)   # _ENGINE_EPOCH=进程级 uuid
# emit：BatchEventReporter.emit 从 _fgjsq_snapshot 取 frozen payloads → 4 线程 httpx 队列(1024) POST event_url
```

BatchEventReporter（全文在镜像 slo_patch/slo/batch_event_reporter.py，85 行）：4 daemon 线程、queue 1024 满则丢弃并计 dropped、每 POST 3 次重试、回读 matched/stale/unmatched 计数——**事件链丢批有界且可观测（metrics 计数）**。

#### C.6 "能否区分同请求不同 chunk size"——诚实回答

- **接口层：能**。predict(batch_size, avg_prompt_length, cache_hit_rate) 接受任意假想组合——把"同一请求按不同 chunk 切法"折算成不同 (B, L_avg, hit) 试探是纯函数调用，无副作用，sub-ms。
- **特征层：不区分**。特征是批级聚合；chunk size 本身不是特征；同一 (B, L_avg, hit) 下不同单请求 chunk 分配不可分。
- **标签层：有噪声**。actual_batch_exec_time 在 async 队非空时是占位间隔（B.5）——训练标签含流水线效应，r2 普遍 <0.5（§4.9 实证）与此直接相关。
- 结论：**predictor 可作为 chunk size 寻优的候选成本估计器之一，但不是可靠的单请求级 oracle**；寻优策略的 ground truth 应来自十档式对照实验，predictor 仅做在线快速试探/粗筛。此判断与 §0.4 残留 3 一致。

### 6.D KV 可见性（三类"命中"严格区分——分析缓存收益时必须分口径）

#### D.1 三命中对照

| 名称 | 发生侧 | 机制 | 观测接口 | 冻结期量级 |
|---|---|---|---|---|
| P 本地 prefix hit | P 引擎 | 块缓存 get_computed_blocks（admission 循环内、有副作用） | P nmp.log prefix cache 命中行 | E1 单流命中例（P19） |
| P→D external KV hit | D 引擎 | AscendStoreConnector 收 KV 后 external prefix cache | D nmd.log `External prefix cache hit rate` | E0/E1/E2 请求窗 ~100% |
| predictor cache_hit_rate | P 进程 | (prompt−computed)/prompt 批级剩余率 | [slo] 行 total_cache_hit_rate | 批级量、与单请求命中无关 |

三者数值互不可比；引用时必须注明口径。

#### D.2 cache_hit_rate 计算代码（patch_core L43-46）

```python
total_cache_hit_rate = (
    (total_prompt_tokens - total_computed_tokens) / total_prompt_tokens
    if total_prompt_tokens != 0 else 0
)
```

注意方向：这是**剩余率**（未算部分占比），命名为 hit_rate 是历史遗留——外网读 [slo] 日志时方向别读反。

#### D.3 首次 admission 前可用信息表（入场/让行策略设计的关键约束）

| 字段 | 首次可获得阶段 | 访问接口 | 只读？ | 限制 |
|---|---|---|---|---|
| prompt 长度（token） | add_request 时 | `request.num_prompt_tokens` | 是 | O(1) |
| 到达时间 | Request 构造 | `request.arrival_time` | 是 | O(1) |
| 等待时长 | 入队后 | `time.time()-arrival_time` | 是 | O(1) |
| 请求状态 | 入队后 | `request.status` | 是 | O(1) |
| SLO/长度档 | — | **本基线无**（SLO 关、无分级字段、FCFS 不读 priority） | — | — |
| **P 本地 prefix hit** | **仅 admission 循环内** | `kv_cache_manager.get_computed_blocks(request)` | **否——有副作用**（touch/占块）且只对队首执行 | waiting 中段无法免费探得 |
| P→D external KV 状态 | admission 循环内 | `connector.get_num_new_matched_tokens` | 否 | P 是 producer，语义="已算完可传输" |
| predictor legacy cache_hit_rate | 任意时刻 | `scheduler._last_cache_hit_rate`（上步批级剩余率） | 是 | 与单请求真实命中无关 |
| 剩余计算量 | 批事件后 | `request.num_computed_tokens` | 是（快照值） | 反映"截至上一步" |
| 可用 KV | 任意时刻 | `kv_cache_manager` 聚合统计 | 部分 | 精确"能否容纳 X"需 allocate 试探 |
| running/批状态 | 任意时刻 | `scheduler.running`、上步 scheduler_output | 是 | async 下"已提交未完成" |
| FG reservation 身份 | 入队后 | `request.kv_transfer_params['fgjsq']` | 是 | D 请求无此字段（marker 在 Coordinator 剥离） |

**入场策略的硬约束**：waiting 阶段可免费拿到的只有长度/时间/状态/身份四类；"真实 prefix hit"必须等 admission（且有副作用）——任何"入场前按命中预判分流"的设计只能用 predictor 剩余率或历史统计近似，拿不到免费真值。

#### D.4 未启用的 KV 观察能力（存在但关）

patch_runtime 内 env 门控：`P3D_KV_EVENTS_FIX`、`P3D_KV_DEBUG`（multi-connector kv 事件/调试行）——默认关，冻结基线未启用；外网需要 KV 逐事件可见性时可开（属打点类，非调度行为）。

### 6.E 插件接入与关闭（外网加载新策略的工程边界）

#### E.1 slo_patch 装配链（activate.py 全文，29 行）

```python
"""P-only general plugin; preserve the existing optional D chat compatibility hook."""
import os

_applied = False


def activate() -> None:
    global _applied
    if _applied:
        return
    role = os.getenv("SLO_PATCH_ROLE", "").lower()
    if role not in ("", "prefill", "decode"):
        raise ValueError("SLO_PATCH_ROLE must be prefill or decode")
    if role != "prefill":
        if os.getenv("P3D_TOLERATE_BAD_TOOL_ARGS", "0") == "1":
            from slo_patch.patch_runtime import _patch_chat_utils_tool_args
            _patch_chat_utils_tool_args()
        _applied = True
        return                            # D：可选 chat 兼容补丁后立即返回（纯净）
    if int(os.getenv("ENABLE_VLLM_TTFT_SLO_MS", "0")) != 0:
        raise ValueError("This baseline requires SLO=0; admission mechanisms are pending")
    if os.getenv("ENABLE_BATCH_REPORTER", "0") != "1":
        raise ValueError("P baseline requires ENABLE_BATCH_REPORTER=1")
    from slo_patch.compatibility import verify_engine()
    verify_engine()                       # engine_files.json 三锚 sha256 硬校验
    from slo_patch.patch_runtime import apply_all
    apply_all()                           # scheduler 重指 + EngineCore.step 打点 + NPUPlatform 包装
    _applied = True
```

要点：**角色门控**（非 prefill 空转）；P 侧两个 raise 把"SLO≠0"与"无 reporter"拦死在启动期——**SLO 类入场策略不能靠改 env 打开，必须走新代码**；`_applied` 进程级单次（重复调用幂等）；关闭=去 env/去插件重启进程（无热卸载）。

#### E.2 compatibility.verify_engine 全文（21 行）

```python
"""Refuse to replace EngineCore methods on an unverified runtime."""
import hashlib, importlib.util, json
from pathlib import Path

def verify_engine() -> dict:
    expected = json.loads(Path(__file__).with_name("engine_files.json").read_text())
    observed = {}
    for module, digest in expected.items():
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None:
            raise RuntimeError("Missing engine module: " + module)
        actual = hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest()
        observed[module] = actual
        if actual != digest:
            raise RuntimeError("Engine compatibility mismatch for " + module +
                               "; collect runtime evidence and port/revalidate the overlay before launch")
    return observed
```

锁三文件：vllm.v1.engine.core / vllm.v1.core.sched.async_scheduler / vllm_ascend.core.recompute_scheduler。**新 scheduler 子类不改这三文件则不触发校验**；直接改任一文件必须同步 bump engine_files.json（sha256sum 新文件回填）——这是"改哪个文件就要动哪个锚"的一一对应。

#### E.3 加载机制与关闭语义

- 加载：镜像内 general_plugins 机制（底座自带 general plugin 装载点）+ slo_patch 单 entrypoint `slo_patch:activate`；P NM env 四变量（§4.5）是唯一开关面。
- 关闭：P 侧去掉 `SLO_PATCH_ROLE=prefill`（或 ENABLE_BATCH_REPORTER=0 → raise 拒启，等于强制显式选择）→ 重启 P NM 进程；**没有运行时关闭**。
- D 侧：从无 FGJSQ 代码路径（marker 剥离），无需任何操作。

#### E.4 新策略插件的冲突面清单（外网新增入场/让行/chunk 策略时逐项检查）

| 冲突面 | 现状 | 新插件注意事项 |
|---|---|---|
| engine_files.json 三锚 | 锁 3 文件 | 新独立子类不触发；改 3 文件本体必 bump 锚 |
| patch_core EngineCore.step 打点 | 常驻（P） | 打点读 `scheduler.predictor` 属性，缺失早退——兼容无 predictor 的自定义 scheduler |
| fix-async MRO 契约 | AsyncScheduler spec 记账 | 新 scheduler 类 MRO 必须含 AsyncRecomputeScheduler/AsyncScheduler（B.1） |
| `_slo_prefilter_waiting` dead code | 存在未激活 | 复用骨架 vs 独立实现二选一；激活需改 scheduler_with_predictor.py（触碰交付包）或独立子类（推荐） |
| FGJSQ 账本反馈 | 事件链常驻 | 引擎侧任何延迟入场都会放大账面 load（A.1）——策略设计必须考虑路由反馈耦合 |
| predictor 在线训练 | 常驻 | 打点数据分布变了（chunk size 改变）会改变训练样本分布；model_version 波动属预期 |
| activate raise 链 | SLO≠0 拒启 | 新策略若沿用 slo_patch 包必须绕开/修改 activate——修改=改交付包版本纪律；独立包+独立 entrypoint 无此问题 |
| Mooncake/KV connector | MultiConnector 常驻 | chunk size 改变 → KV 传输分片节奏变化 → HcclBatchPut 行为需回归观察（P10 敏感区） |

---
## 7. 接口地图（外网策略设计接入面——只述工程边界，不实现算法；双队列放 GF 还是 P 不代做决定）

### 7.1 入场/让行策略候选接入位置

| # | 候选接入位置 | 当前真实函数/对象 | 可用字段（此刻可读） | 可执行动作 | 状态更新责任 | 约束与风险 | 稳定性 |
|---|---|---|---|---|---|---|---|
| 1 | **Coordinator 路由层**：P 入场前 | `FgjsqService._reserve` → `policy.rank()`（score 排序，§6.A.4） | 每实例 requests/committed_tokens/score/limit；请求 req_len | 改 rank 序、改 score 权重、拒绝（unavailable）、附加延迟（reserve 窗内 hold） | rank/拒绝结果自身维护；若 hold 需自管超时与 Motor attempt 语义 | Motor select_and_allocate 期待即时返回；长 hold 会顶到 Motor 重试/超时；改 score 公式=改 FGJSQ 数学（历史红线：需用户批准） | **稳定**（自家代码） |
| 2 | **P 引擎 add_request 点** | `SchedulerWithPredictor.add_request`（warmup 计数后透传，§6.B.2） | num_prompt_tokens/arrival_time/status/kv_transfer_params.fgjsq | 分类标记（Request 挂属性）、重定向到自建第二队列、（激进）拒绝 | 分类属性由入场策略维护；重排必须遵守 FCFS deque 语义 | 不改 admission 循环则只能影响"谁在队里/什么序"，不能改"队首阻塞"语义；需独立子类（E.4） | 稳定（覆写点现成） |
| 3 | **P 引擎 schedule() 覆写**（入场前分类+让行） | `_slo_prefilter_waiting`（dead code 骨架，§6.B.2） | 全 waiting 请求的长度/时间/身份 + scheduler.running + 上步批统计 | pop 全部→分类→batch 回队 / deferred 延迟回队（现成模式） | deferred 集合策略自管；防饥饿（现版 _max_deferred_per_step=999 不设限=反例警示） | **激活需改 scheduler_with_predictor.py 本体或独立子类**；async 契约不可破坏；延迟期间 FGJSQ 账面 load 不衰减（A.1）→ 路由反馈放大 | 骨架稳定；激活路径有纪律约束 |
| 4 | **P 引擎 admission 循环本体** | vllm/RecomputeScheduler.schedule L560+（§6.B.3） | 队首请求全字段；token_budget；KV 聚合 | 把"队首放不下=break"改为跳过、双队列预算、入场顺序重写 | 完全自管 | **必 bump engine_files.json 锚**（改 recompute_scheduler.py）+ vllm 升级重基线成本 + fix-async 崩溃敏感区 | 版本耦合最强，代价最大 |
| 5 | **Coordinator 转发/释放层**（让行信号外显） | bindings.finish_attempt/native_release/release_fg（§6.A.2） | reservation 状态（native/fg released）、attempt_seq | 提前/延后释放、附加释放信号 | 与两 flag 幂等协议一致 | 释放语义已被幂等协议锁定（双 flag+abort 口径 P17）；乱序释放会被 events 校验拒（stale） | 协议稳定 |

**明确句**（任务要求）：
- **可延迟首次派发的位置**：#3（引擎侧让行）与 #1（Coordinator 侧 hold）两处——#3 粒度到单请求、在引擎内；#1 粒度到实例选择、在引擎外。#2 只能标记不能延迟。
- **已进引擎请求 GF 无法撤回**：请求一旦经 attach_request 进 P 引擎（add_request 入 waiting），FGJSQ 无法取消它——引擎 abort 与 Mgmt 账本无逐事件同步（§6.B 抢占节）；账本只能经批事件感知（remaining 回升）。让行决策必须在 attach 之前（#1）或引擎内自管（#2/#3）。
- **延迟请求已计入 FGJSQ 预留且不衰减**：waiting 阶段无批事件 → estimated_tokens 全额挂账 → score 持续被压 → 后续请求被导向其它实例。这是自动路由反馈（可用），也是让行策略的隐性代价（需评估：让行越久，该实例越"冷"）。
- **信号不混用**：P scheduled（事件 num_scheduled_tokens=已提交，B.5）、P 完成（HANDOFF→release_native）、D 首输出（release_fg）、E2E 完成（finish_request 兜底）四个时点语义互不可替换——让行/调度信号取哪个时点必须显式声明。
- 双队列（GF 队 vs P 队）放哪一层：#3（引擎内 prefilter 骨架）与 #4（admission 本体）是引擎侧方案；#1/#5 是 Coordinator 侧方案——本文档不代做决定，边界已全部给出。

### 7.2 chunk size 寻优策略候选接入位置

chunk size 在本基线由三个量共同决定：`max_num_batched_tokens=8192`（共享 token budget）、`long_prefill_token_threshold`（单请求截断，本基线默认值生效）、admission 循环的 budget 分配顺序（running-first）。

| # | 候选接入位置 | 当前真实函数/对象 | 可用字段 | 可执行动作 | 状态更新责任 | 约束与风险 | 稳定性 |
|---|---|---|---|---|---|---|---|
| 1 | **admission/截断参数面**（不改编码） | 引擎 config：max_num_batched_tokens、long_prefill_token_threshold、enable_chunked_prefill | — | 改 config 值重启（行为性变更） | config 即状态 | 最粗粒度（全局静态）；改后必须新版本重跑受影响实验（用户红线） | 稳定（原生参数） |
| 2 | **RUNNING 循环截断点** | scheduler.py L373+（num_new_tokens=min(剩余,threshold,budget)，§6.B.3） | 每请求 num_computed/num_tokens、budget 余量 | 按请求动态 threshold（需 #4 级侵入或子类覆写困难——截断在循环内联） | 自管 | 同 #4 侵入级 | 版本耦合 |
| 3 | **WAITING admission 首块大小** | scheduler.py L560+（num_new_tokens 计算） | 队首全字段、get_computed_blocks 结果（此时已知本地 hit） | 首块大小策略化 | 自管 | 同 #4；且 prefix hit 副作用已发生 | 版本耦合 |
| 4 | **调度器子类覆写 schedule()** | SchedulerWithPredictor.schedule（覆写点现成，§6.B.2） | 同上+predictor | 在 super().schedule() 前后调整请求的"入场单元"（如控制 waiting 供给来间接控制批构成） | 自管 | 只能间接影响 chunk（预算在基类循环内分配）；直接控制需 #2/#3 | 覆写点稳定 |
| 5 | **Coordinator 侧请求整形**（间接） | attach_request 前 body（§6.A.2） | req_len | 理论上可改写请求体（如分段）——**本基线语义禁止**（FG marker 只注入不动业务字段；改 prompt=改变业务语义） | — | 红线：不改业务正文；改写请求体等同新语义系统 | 不推荐 |
| 6 | **成本预测组件**（寻优的 oracle 之一） | `predictor.predict(B, L_avg, hit)`（§6.C.2，纯函数） | 任意假想组合 | 无副作用试探假想批执行毫秒 | 无状态 | 批级聚合特征、无 chunk size 特征、标签含 async 占位噪声（C.6）——粗筛可用非 oracle | 稳定 |

**明确句**：候选 chunk 成本预测可无副作用调 predictor.predict——但特征是 (B, L_avg, hit) 三元组的批级聚合，不含 chunk size 本身；预测的是"假想批执行时间"，把它映射到 chunk 决策是策略自身的建模责任，且 r2<0.5 的现状（§0.4 残留 3）决定它只配做粗筛。
**改 chunk size 时的一致性**：scheduler 预算状态（token_budget 消耗序）、KV 块分配（allocate_slots/preempt）、async 占位记账（MTP spec in-flight）、Mooncake 传输分片节奏（P10 敏感区）四处联动——任何动态 chunk 策略必须同时回归验证这四处的稳定性证据（引擎不崩、TRANSFER_FAIL 不回升、TPOT 不劣化）。
**接口稳定性总结**：Coordinator 侧 FGJSQ 接口（#7.1 的 1/5、#7.2 的 6）为自家代码=稳定；引擎侧覆写点（schedule/add_request）跨小版本通常稳定；admission 循环本体与 RUNNING 截断（#7.2 的 2/3、#7.1 的 4）与 vllm commit 0fc695fc 强耦合——vllm 升级即重基线。

---

## 8. 实验证据（数字均为落盘 extract/judge 原文口径）

### 8.1 四版本对照总表（同 seed 同客户端同口径：128k×B16×PT900、seed 20261014、prefix 0.5）

| 版本 | run_id/出处 | n（成功/总） | TPOT mean/P90 (ms) | TTFT mean/P90 (s) | QPS | 时间窗（UTC） | 判定 |
|---|---|---|---|---|---|---|---|
| **A g4 基线** | T128kB16 r01/r02（EXP_10.14 csv） | — | 12.228 / 12.181 | 40.70 | 0.2812/0.2834 | （历史） | 参照 |
| **B rc1 初始** | 128kB16_g5_p01（EXP_10.20 07_bench） | 120/120 | 17.2 / 18.5 | 110.1 / 127.1 | 0.115 | 10-20 03:21-03:42 | TTFT 2.7×、QPS 减半（P10 链） |
| **C rc1 修复后** | S2 双轮（EXP_10.21 09_tpot_attribution） | 293 / 283 | 16.8 / 16.7 | 33.0 / 34.8 | 0.3072 / 0.2979 | 10-21 晨 | TPOT 超 13.42 阈不达标 → 方案 E |
| **D 方案 E（=g5 冻结）** | E2_128kB16 r01/r02（10_g4base_motor/04_e2） | 284/284、283/283 | 13.2/14.2、13.1/14.2 | 38.18/43.84、38.49/43.76 | 0.298、0.2973 | r01 11:21:19-11:39:49、r02 11:45:01-12:03:30 | **双轮全项 PASS → 固化** |

- rc1 S2 的 QPS 以 S2_VERDICT_TPOT_ATTRIBUTION.md 权威值为准（0.3072/0.2979；E2_SUMMARY.md 三方对比表中 0.261-0.262 为笔误，不采用——两文书矛盾以专用判定文书为准）。
- D 对 A：TPOT +7.5%（±10% 工程容忍内）、TTFT −6%、QPS +5%；D 对 C：TPOT −21%。+7.5% 残差未做单变量分解（§0.4 残留 1）。

### 8.2 E2 双轮独立性声明

两轮连续服务生命周期、轮间零重启（predictor 状态跨轮继承——r02 与 r01 全指标差异 <1%，无漂移）；每轮独立 warmup 6 + drain 60 + PT900 job；extract/judge 逐轮独立落盘（runs/E2_128kB16_{r01,r02}/，aisbench 原始 csv/json + marks）。判定=两轮各自对阈值全过才 PASS（非取均值）。

### 8.3 沿途关键实验

| 实验 | 内容 | 关键结果 | 出处 |
|---|---|---|---|
| E0 五轮 | 容器切换/编排/深度验收（1024 守恒、finish_reason、external hit ~100%、插件事件、错误窗 0） | 编排 PASS（第三轮 OpenSSL 缺失→r2 教训 P15） | 10_g4base_motor/02_e0 |
| E1 单流+ B4 | TPOT 恢复验证 | 单流 12.137/12.509/14.380ms 回 g4 水平（rc1 15.6-16.2）；B4 TPOT 16.3→13.2（-19%）；单流 ttft 3.3s=前缀污染例（P19） | 03_e1/E1_SUMMARY.md |
| Phase 2 A/B | FGJSQ 开/关 ×2 双臂四轮 | 全指标 <1% → FGJSQ 接入零行为变更 | 06_5_regression_debug/phase02_ab |
| E2 (定位期) | TRANSFER_FAIL 请求级关联 | 失败链画像（P10）；修复前后 110s→33s | phase02_ab/e2_transfer_fail |
| S0/S1 | 客户端管道冒烟 3×40k / 固化前确认 | all_ok；分辨率检查 10 包全中 | 05_small_comparison |

### 8.4 十档进度（截至 13:09 UTC；判定归后续独立验收报告 G5_G4BASE_MOTOR_ACCEPTANCE.md，本文只忠实记录）

已完成的 3 档 extract+judge JSON 原文（progress log 逐档落盘；128kB16 档=§8.1 D 行）：

```json
E2_128kB1（12:11:43-12:29:23，max_concurrency=1）：
"metrics": {"ttft_mean": 11423.7, "ttft_p90": 13107.7, "tpot_mean": 12.9, "tpot_p90": 13.8,
            "e2e_mean": 24610.2, "qps": 0.0406, "failed_requests": 0, "total_requests": 37,
            "success_requests": 37, "benchmark_duration_ms": 911172.457}
"judge": {"ttft_mean_thr_ms": 13233.0, "ttft_mean_pass": true, "ttft_p90_thr": 14505.87, "ttft_p90_pass": true,
          "tpot_mean_thr": 12.89, "tpot_mean_pass": false, "tpot_p90_thr": 13.61, "tpot_p90_pass": false,
          "qps_thr": 0.0378, "qps_pass": true, "zero_tol_fail": 0, "zero_tol_pass": true}
—— TPOT mean 12.9 vs 12.89 阈差 0.01ms、TPOT P90 13.8 vs 13.61：两项 TPOT 未过（边缘量级）；
   TTFT/QPS/零容忍过。是否边缘豁免由验收报告裁定，本文不判。

E3_128kB2（12:34:15-12:51:51，max_concurrency=2）：
"metrics": {"ttft_mean": 10601.9, "ttft_p90": 13450.5, "tpot_mean": 12.6, "tpot_p90": 13.5,
            "e2e_mean": 23464.1, "qps": 0.0848, "failed_requests": 0, "total_requests": 77,
            "success_requests": 77, "benchmark_duration_ms": 908120.9762}
"judge": 全项 pass（tpot_mean_thr 12.9/tpot_p90_thr 13.94/qps_thr 0.0702/ttft 阈 14817/15378）
```

E4_128kB4 job 12:56:43 起（job end 时 extract+judge 自动落盘）；E5-E10 待跑；档间零重启。warmup md5 序 309c68de4aed/36e5cf2859a6/97fdb3844852/02216d35047d/5dcf2ee8a3e7/f17656b7ebdd 各档一致（客户端口径锁定，P19）。

g4 对照值（EXP_10.20_MOTOR/03_plan/PLAN_FOR_APPROVAL.md 十档表，TTFT mean s / TPOT mean ms / QPS）：
128kB1 12.03/11.72/0.042；128kB2 13.47/11.73/0.078；128kB4 13.60/11.79/0.153；128kB8 17.15/12.10/0.261；
（128kB16 见 §8.1 A 行）；66kB1 4.33/12.40/0.061；66kB2 5.39/12.08/0.115；66kB4 6.56/12.03/0.209；
66kB8 7.08/12.48/0.395；66kB16 11.02/12.63/0.650。（阈值口径=各指标 ≤g4 均值×1.10、QPS ≥×0.90——如 128kB1 TPOT 阈 12.89=11.72×1.10，与 judge JSON 一致。）

### 8.5 AISBench 客户端口径（读数必读）

- **并发语义**：B=在途信号量（asyncio.Semaphore(num_workers)+TCPConnector(limit=B+1)）；压力模式完成一条立即预取下一条，**无整轮 barrier**；pressure_time 到点后在途请求继续等完成。
- **TTFT/TPOT**：客户端流式口径（VLLMCustomAPIChatStream 逐 SSE 时间戳）；SSE 到达时间≠设备计算时间（含 Coordinator 两跳转发）。
- **QPS 双分母口径**：success_requests/benchmark_duration（本次 extract 采用）；另有按 job 墙钟口径——跨文档比较必须对齐分母。
- 采样：temperature=0.01/top_k=20/top_p=0.95（业务侧固定）。
- 失败统计独立列示；成功延迟只覆盖成功请求。

### 8.6 两个判断分离（任务要求明确）

1. **恢复 g4 对照**（工程判断）：TPOT +7.5% 在 ±10% 容忍内、TTFT/QPS 优于 g4 → 达成。
2. **业务 SLO 达标**（业务判断）：对照 SLO 标准（128K P90 TTFT≤30s/P90 TPOT≤45ms 等）——**TTFT P90 43.8s 超业务 128K 阈**；该判断属业务方职权，本基线只承诺"恢复 g4 水平"，不承诺业务 SLO 达标。两判断不可互相替代。

---

## 9. 外网复现检查流程与收尾状态

### 9.1 环境复现五段检查（按序；每段失败先修复再进下一段）

**段一：镜像身份**（对应 §4.7/§5.1）
1. 底座 quay.io/ascend/vllm-ascend:v0.23.0 在位，ID 660ce23a8357
2. 22 组 COPY 全部落位；**确认无 `__editable___vllm_ascend*rc1*` finder/.pth**（有=构建污染，重来）
3. import_battery 14 模块 BATTERY_PASS（含底座版本断言）
4. motor 8 修复文件聚合 md5 == fcce4957d1fa5a22a844b338521916ee

**段二：编排配置**（§4.3-4.5）
5. config_sample.json/fgjsq.json/mooncake 配置就位；fault_tolerance=false（裸 docker 语义）
6. fgjsq.json enabled=true 且 event_url 指向 Coordinator mgmt 口
7. NM 脚本 sed __TAG__/__IP__ 完成；g4 setup_env 15 项 P/D 双侧对称（§4.5 是本体）

**段三：启动序**（§4.8，错序=故障）
8. 容器→mooncake master(.49:50089)→coord/ctrl→NM×3（漏 mooncake=ret=-600 全灭）
9. count=6、decode=3；三节点 health 200；P env 断言（有 SLO_*）、D env 断言（无 SLO_*）
10. P nmp.log 见 `[slo_patch] scheduler_cls -> SchedulerWithPredictorAsync (async_scheduling=true)` 与 predictor loaded 行；D nmd.log 无任何 slo_patch 行

**段四：链路验收**
11. 单请求 1024 token 守恒、finish_reason=length
12. D nmd.log External prefix cache hit rate ~100%
13. P 侧插件事件出现（Coordinator metrics received/matched 增长）；GET /fgjsq/v1/loads 返回实例快照
14. 错误窗：TRANSFER_FAIL=0（g4 setup_env 生效的直接判据；非零=段二第 7 步失败）
15. abort 探针：metrics.abort ≈ 2×请求数（口径 P17，非故障）

**段五：行为基线**（性能实验前）
16. warmup 6 条 md5 序与 309c68de4aed…f17656b7ebdd 一致（客户端口径锁定）
17. 单流 128k 冒烟：TPOT ~12-13ms 量级（对齐 E1）
18. 首档正式压测前确认 predictor loaded 后已有 v1 训练行（在线训练启动）

### 9.2 收尾四项

**① 可靠结论**（证据强度已达标）：
- g5 冻结版在 128k×B16 双轮全项过阈，TPOT 恢复 g4 ±10% 容忍内、TTFT/QPS 优于 g4（【实验对照支持】双轮+零重启可重复性）
- FGJSQ/适配层接入零行为变更（Phase 2 A/B 四轮 <1%，【实验对照支持】）
- TRANSFER_FAIL 根因=缺 g4 setup_env（前后对照 110s→33s，【运行实证】）；P/D HCCL env 必须对称（【运行实证】P11）
- r1→r2 构建方法论（101 项缺失集证据法+import_battery，【运行实证】）

**② 不阻碍算法开发但未解决**（如实列出，非阻塞）：
- TPOT +7.5% 残差未分解（候选方向=rc1 vs 正式版 435 文件 diff、AscendC sampler 算子、编排层；均为【推断】，未做单变量实验）
- predictor 在线训练 r2 普遍 <0.5（标签含 async 占位噪声；打点/粗筛可用，非可靠 oracle）
- errmsg 空的 Transfer failed 新类（10-20 Phase 4 后）未复现、量级 ~5.7/请求、请求全成功
- Motor attempt/reserve 超时语义（reserve_window_s=30 窗外行为）未实测
- B16 高压下 admission 行为基线（waiting 深度/budget 用满率/抢占是否出现）待十档数据回溯

**③ 外网基线契约**（本文档自足性声明）：外网机器凭本文档+esfs 导出的构建上下文（g5_export/ + Dockerfile）即可重建镜像；源码关键文件全文/关键段已嵌入 §4-§6（policy/snapshot/bindings/service/body_observer/config/activate/compatibility/scheduler_with_predictor/predictor 特征与训练段/patch_core 打点段/admission 循环/request_queue）；配置三份全文（config_sample/fgjsq/engine_files）+NM 脚本全文在 §4；接口地图 §7 直接给出两类策略的接入边界。内网路径仅作来源索引（§0.1 组成表）。

**④ 待人工验收**：十档余档汇总与 G5_G4BASE_MOTOR_ACCEPTANCE.md（独立任务，含 128kB1 TPOT 边缘项裁定）；业务 SLO 判断（§8.6 判断 2）归业务方。

---

## 10. 自检（任务验收问题逐条回答）

**Q1 只看本文档能否解释故障与解决办法？**
能。§3.1 总表 20 问题+证据分级；四大重点链（P10 TRANSFER_FAIL 含日志原文、P11 灾难链、P13 版本倒挂、P15 r1→r2）六要素详述在 §3.2-3.4；每条根因都带"发现证据→实际修复→验证"闭环与证据等级。

**Q2 能否识别版本？**
能。§0.1/§2 四版本演进表（A g4/B rc1 初始/C rc1 修复/D 方案 E=g5 冻结）+D 版内部 r1→r2；版本身份五件套（tag/三节点镜像 ID/底座组件 commit/22 组增量/md5）在 §0.1 与 §5.1；rc1 finder 禁带红线条目可直接鉴别构建污染。

**Q3 能否恢复全部修改？**
能。两视角账目：相对 g4 底座=22 组 COPY（§4.7 Dockerfile 全文）+三件套校验值；相对交付包=七文件 patch 全文（§5.2a）+fix1-8 文件级账目（§5.2b）+slo_patch 零修改声明+运行时 monkey patch 清单（§5.4）；锚适配（engine_files.json 第三锚）依据在 §4.6。

**Q4 能否找到两类策略的接入边界？**
能。入场/让行五位置+chunk size 六位置两表（§7.1/§7.2），每行含当前真实函数、可用字段、可执行动作、状态责任、约束风险、稳定性；四条明确句（可延迟位置/已进引擎不可撤回/延迟请求的账本反馈/信号不混用）；引擎侧正本源码（admission 循环/prefilter 骨架/队列接口/async 语义）在 §6.B；插件加载与冲突面在 §6.E。双队列放 GF 还是 P 未代做决定——边界已给全。

**Q5 脱敏是否达标？**
达标。正文无凭据/token/业务文本；§6.A.5 字段示例全为结构示例（nonce/reservation_id 等以省略号示长，跨事件 ID 对应关系保留：nonce:attempt_seq→reservation_id→事件五元组→批事件 reservation_id 闭环可追）。

---

*文档完。生成：Claude Code（EXP_10.21_MOTOR 会话）；落盘：EXP_10.21_MOTOR/11_handover/G5_FROZEN_BASELINE_HANDOVER.md；对应固化版本 g5-g4base-motor-20261021-r1；数据截至 2026-10-21 13:09 UTC。*