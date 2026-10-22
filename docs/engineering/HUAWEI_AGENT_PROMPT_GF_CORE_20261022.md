# 华为 agent prompt：gf_admission 纯核心离线验证

你收到的是 `gf-admission-core-0.1.0.dev1-20261022`，算法源码 commit
`7055b220c6ac640ef32837e4bbe0ff50b22bbf19`，g5 起点为
`3b63b00546e7a6ffb2526dafc341969cebe22359`。
本包只验证 CPU 分类、队列、预算及跨解释器兼容性，**不是已接通 Motor 的入场插件**。
没有 broker/WaitHub/原子预留 hooks/在线 KV provider，不支持 shadow/enforce。
不得把本包安装后无报错解释为 gf_admission 已启用，不能用它做 TTFT/TPOT/吞吐收益实验。

## 执行范围

沿用当前现场 g5 `vllm-ascend:g5-g4base-motor-20261021-r1` 作为后续集成背景。
本轮不修改该运行服务，不停止/重启 Coordinator、P/D 或压测服务，不替换 site-packages，
不执行 pip install 到运行环境，不修改 FGJSQ/predictor、NodeManager fix1、engine_files.json、权重或配置。
使用一个全新独立工作目录解包。Python 3.10+；优先用现场 Python 3.12 的解释器，
具备 pytest 即可。不需要 Motor、torch、Ascend、HTTP、模型或 NPU。

## 操作命令

先对压缩包及本 prompt 计算 SHA256，与用户同时带入的交付说明核对。
下面路径是占位，替换为实际新目录和解释器；目录存在则换一个新目录，不覆盖旧结果。

```sh
mkdir /YOUR/NEW/gf-core-validation
tar -xzf /YOUR/TRANSFER/gf-admission-core-0.1.0.dev1-20261022.tar.gz -C /YOUR/NEW/gf-core-validation
cd /YOUR/NEW/gf-core-validation/gf-admission-core-0.1.0.dev1-20261022
/YOUR/PYTHON3.12 scripts/validate/verify_gf_core_bundle.py
```

验证器先核对包内逐文件 SHA256，再从 wheel 隔离导入，最后运行纯核心 22 项测试。
它只在解包目录的 `validation-output/` 写结果；不安装任何包，不查询在线服务。
如果 pytest 缺失，记录依赖缺失；可在专用离线测试虚拟环境使用现场已有 wheel 补齐，
不可擅自联网安装或改生产 Python。若无法获得依赖，回报未执行，不宣称通过。
如果 SHA 不符或测试失败，停止后续验证，保留日志；可在独立副本修改纯核心/测试工具，
必须回传完整 diff，不能修改 oracle 夹具使测试变绿。

可选的容器 CPU 微基准（不作为算法收益验收）：

```sh
/YOUR/PYTHON3.12 scripts/validate/benchmark_admission_containers.py \
  --repeats 100 --output validation-output/container-benchmark.json
```

其单位是整条容器操作轨迹的微秒，不能称为每请求附加时延、NPU 吞吐或生产收益。
可选离线重建 wheel：在专用构建环境中，从包根运行
`python -m pip wheel --no-deps --no-build-isolation --no-index . --wheel-dir validation-output/rebuilt`。
需要本地已有 pip/setuptools/wheel；无依赖则记未执行。当前包为 pure Python，未携带本机原生二进制。

## 本轮验收

1. 包与文件完整性核验通过，解释器和加载路径明确。
2. wheel 隔离导入成功，未加载 Motor/torch/vLLM/HTTP 客户端。
3. 22 项纯核心测试通过；失败、未运行或依赖缺失分别记录。
4. 当前现场服务与配置未变。没有安装到服务，因此没有服务逆补丁；结束测试进程即可。

本轮不能验收：至多一次真实 reservation、多 worker/IPC、取消与 claim 竞态、真实 KV、
READY 租约/清理、off/shadow/enforce 接入、NPU 输出正确性、延迟和吞吐。
业务 64K 27s/30ms、128K 30s/40ms 为后续全体请求 P90 TTFT/TPOT 的约束，
不是本包测试阈值。禁止沿用历史 ±10% 工程容忍度宣称新算法有效。

## 回传一份自包含 Markdown

文件名 `GF_ADMISSION_CORE_VALIDATION_REPORT_20261022.md`，必须正文嵌入：

- 原始包 SHA、MANIFEST 的 source_commit、Python 完整版本/架构、实际执行命令。
- `validation-output/summary.json` 全文、wheel-smoke.log、pytest 汇总及失败堆栈。
- 是否重建、是否修改源码；修改前后 SHA 及可应用的完整 diff，无修改则明确写无。
- 可选微基准 JSON 与解释，不把容器结果写成 NPU 收益。
- 已通过/未运行/失败项目，服务未变的操作记录，下一阶段待验证项。

关键证据直接嵌入正文，内网路径仅作索引，不要求外传完整目录或原始业务数据。
如无运行环境条件，直接报告阻碍与已完成的完整性检查，不追加全栈环境复刻。
