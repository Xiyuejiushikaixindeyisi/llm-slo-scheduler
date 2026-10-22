# CLUSTER_FLOW_PROFILE_REPORT

本报告为九字段日志的描述性分析，未连接服务、查询数据库或改变调度。
请求时间轴使用 model_handle_start_time（UTC，模型处理起点），不是已验证的GF接收时刻。
request_time虽为到达时间，但不在本CSV九字段中；不还原两个时间点之间的等待。

## 来源与口径

```
{
  "tool_version": "0.1.0",
  "script_sha256": "07c0870f58c7da27b9105868b48af34a15e79b1340efab06fd6c00d4110c6f73",
  "python_version": "3.12.13",
  "input_path": "/mnt/esfs/zhangxiyue/qwen3.6-27b/FGJSQ_3P3D/TRACR_9.24_GF/TRACE_9.24_GF.csv",
  "input_sha256": "89c3b69274d7b7923b43da1a607382f713321ce4082e67de19a1dfd989a3a8b3",
  "instance_uuid": "9a1c5866-aab8-4229-ae4c-51686b863d6e",
  "workload_type": "production",
  "label": "production_64k_20260924",
  "routing_label": "native_proxy_unspecified_policy",
  "reported_environment": "64K; 3P3D; TP4; 24x910B2; Qwen3.6-27B W8A8; v0.23.0",
  "reported_token_budget": 8192,
  "reported_max_num_seqs": 16,
  "environment_evidence": "user-provided context, not detected from CSV",
  "column_mapping": {
    "instance_uuid": "instance_uuid",
    "hash_id": "hash_id",
    "appid": "appid",
    "model_handle_start_time": "model_handle_start_time",
    "prompt_tokens": "prompt_tokens",
    "completion_tokens": "completion_tokens",
    "cached_tokens": "cached_tokens",
    "model_ttft": "model_ttft",
    "model_tpot": "model_tpot"
  },
  "resolved_input_units": {
    "ttft": "unknown",
    "tpot": "unknown"
  },
  "window_start_utc": "2026-09-24T07:00:02+00:00",
  "window_end_utc": "2026-09-24T08:59:57+00:00",
  "window_boundary_source": "inferred observed span; not the full SQL arrival window",
  "recorded_start_rps": 0.771230020847811,
  "metric_units": "TTFT seconds; TPOT milliseconds",
  "ttft_slo_s": 27,
  "tpot_slo_ms": 30,
  "small_group_threshold": 20,
  "quantile_method": "linear interpolation, (n-1)*q"
}
```

## 数据质量

```
{
  "csv_rows": 55166,
  "other_cluster_rows_excluded": 49617,
  "completion_less_than_prompt": 5548,
  "parsed_unique_rows": 5549,
  "outside_analysis_window": 0
}
```

completion_tokens按用户口径为输入＋输出；output_tokens=completion_tokens-prompt_tokens。
uncached_tokens=prompt_tokens-cached_tokens仅是工作量代理，不等于精确服务时间。
命中为事后记录，未证明入场前可见。缺失/异常字段不补0，不影响其他有效字段的独立统计。

## 总体结果

| requests | ttft_s_n | ttft_s_p50 | ttft_s_p90 | ttft_s_p95 | ttft_s_p99 | tpot_ms_n | tpot_ms_p90 | ttft_slo_violation_n | tpot_slo_violation_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5549 | 0 | NA | NA | NA | NA | 0 | NA | 0 | 0 |
| 分位数为线性插值经验分位数。SLO违约按TTFT≥阈值/TPOT≥阈值计，分母分别是有效指标数。 |  |  |  |  |  |  |  |  |  |
| TTFT尾部定义为≥本样本P90，存在并列时占比可能超过10%；小组标记不构成置信区间。 |  |  |  |  |  |  |  |  |  |
| 未提供失败/取消/未完成标记，结果仅代表CSV中已记录且该指标有效的请求，不能宣称覆盖所有发起请求。 |  |  |  |  |  |  |  |  |  |

## 请求工作量分布

| field | n | mean | p50 | p90 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| prompt_tokens | 5549 | 3.741e+04 | 4.166e+04 | 5.989e+04 | 6.29e+04 | 6.832e+04 | 103562 |
| output_tokens | 1 | 1566 | 1566 | 1566 | 1566 | 1566 | 1566 |
| uncached_tokens | 5549 | 2.235e+04 | 1.957e+04 | 4.981e+04 | 5.666e+04 | 6.391e+04 | 103562 |
| cache_hit_ratio | 5549 | 0.3165 | 0.1129 | 0.915 | 0.9386 | 0.958 | 0.9903 |
| 长度单位为token；cache_hit_ratio是逐请求比值，其均值不同于sum(cached)/sum(prompt)。 |  |  |  |  |  |  |  |
| 命中及输出均为事后观测，不自动成为入场时可知的特征。 |  |  |  |  |  |  |  |

## 时间节奏与工作量

```
{
  "n": 5548,
  "mean": 1.2965940865322076,
  "p50": 0.7818170785903931,
  "p90": 3.2536608457565306,
  "p95": 4.371426212787627,
  "p99": 7.020830569267267,
  "max": 17.782660007476807,
  "cv": 1.1603349424764169
}
```

| window_s | full_windows | zero_window_fraction | count_mean | count_p90 | count_max | count_fano |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 7195 | 0.4959 | 0.7712 | 2 | 7 | 1.218 |
| 10 | 719 | 0.004172 | 7.708 | 12 | 22 | 1.281 |
| 60 | 119 | 0 | 46.17 | 62.2 | 96 | 3.122 |
| 窗口包含零请求窗，Fano仅使用完整窗。上述指标描述模型处理起点的节奏，不据此判定泊松/独立到达、容量饱和或突发因果。 |  |  |  |  |  |  |
| 各窗口CSV的token总量按请求起点归属，是该群体输入工作量，不是期间实际处理token量。 |  |  |  |  |  |  |

## 输入长度分组

| group | requests | small_group | ttft_s_n | ttft_s_p90 | tpot_ms_p90 | uncached_tokens_mean | cache_hit_token_weighted | ttft_tail_n | ttft_slo_violation_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [0,8192) | 1128 | False | 0 | NA | NA | 1595 | 0.004252 | 0 | 0 |
| [16384,32768) | 362 | False | 0 | NA | NA | 2.165e+04 | 0.2601 | 0 | 0 |
| [32768,49152) | 2213 | False | 0 | NA | NA | 2.446e+04 | 0.3983 | 0 | 0 |
| [49152,65536) | 1709 | False | 0 | NA | NA | 3.205e+04 | 0.4316 | 0 | 0 |
| [65536,+inf) | 124 | False | 0 | NA | NA | 4.282e+04 | 0.3885 | 0 | 0 |
| [8192,16384) | 13 | True | 0 | NA | NA | 1.087e+04 | 0.2204 | 0 | 0 |

## 命中分组

| group | requests | small_group | ttft_s_n | ttft_s_p90 | tpot_ms_p90 | uncached_tokens_mean | cache_hit_token_weighted | ttft_tail_n | ttft_slo_violation_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| (0,0.5) | 1335 | False | 0 | NA | NA | 3.395e+04 | 0.2639 | 0 | 0 |
| 0 | 2525 | False | 0 | NA | NA | 2.576e+04 | 0 | 0 | 0 |
| [0.5,0.9) | 991 | False | 0 | NA | NA | 1.151e+04 | 0.7599 | 0 | 0 |
| [0.9,1] | 698 | False | 0 | NA | NA | 3182 | 0.9337 | 0 | 0 |

## 长度×命中联合分组

| group | requests | small_group | ttft_s_n | ttft_s_p90 | tpot_ms_p90 | uncached_tokens_mean | cache_hit_token_weighted | ttft_tail_n | ttft_slo_violation_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [0,8192) / 0 | 1123 | False | 0 | NA | NA | 1602 | 0 | 0 | 0 |
| [0,8192) / [0.9,1] | 5 | True | 0 | NA | NA | 31.2 | 0.9801 | 0 | 0 |
| [16384,32768) / (0,0.5) | 150 | False | 0 | NA | NA | 2.238e+04 | 0.2114 | 0 | 0 |
| [16384,32768) / 0 | 130 | False | 0 | NA | NA | 3.081e+04 | 0 | 0 | 0 |
| [16384,32768) / [0.5,0.9) | 60 | False | 0 | NA | NA | 6968 | 0.7462 | 0 | 0 |
| [16384,32768) / [0.9,1] | 22 | False | 0 | NA | NA | 2452 | 0.9206 | 0 | 0 |
| [32768,49152) / (0,0.5) | 613 | False | 0 | NA | NA | 2.972e+04 | 0.2659 | 0 | 0 |
| [32768,49152) / 0 | 769 | False | 0 | NA | NA | 3.976e+04 | 0 | 0 | 0 |
| [32768,49152) / [0.5,0.9) | 477 | False | 0 | NA | NA | 9038 | 0.7834 | 0 | 0 |
| [32768,49152) / [0.9,1] | 354 | False | 0 | NA | NA | 2920 | 0.9296 | 0 | 0 |
| [49152,65536) / (0,0.5) | 520 | False | 0 | NA | NA | 4.09e+04 | 0.2735 | 0 | 0 |
| [49152,65536) / 0 | 466 | False | 0 | NA | NA | 5.64e+04 | 0 | 0 | 0 |
| [49152,65536) / [0.5,0.9) | 425 | False | 0 | NA | NA | 1.452e+04 | 0.743 | 0 | 0 |
| [49152,65536) / [0.9,1] | 298 | False | 0 | NA | NA | 3533 | 0.9374 | 0 | 0 |
| [65536,+inf) / (0,0.5) | 44 | False | 0 | NA | NA | 5.453e+04 | 0.229 | 0 | 0 |
| [65536,+inf) / 0 | 33 | False | 0 | NA | NA | 7.061e+04 | 0 | 0 | 0 |
| [65536,+inf) / [0.5,0.9) | 28 | False | 0 | NA | NA | 1.786e+04 | 0.7414 | 0 | 0 |
| [65536,+inf) / [0.9,1] | 19 | True | 0 | NA | NA | 4224 | 0.9386 | 0 | 0 |
| [8192,16384) / (0,0.5) | 8 | True | 0 | NA | NA | 1.039e+04 | 0.2699 | 0 | 0 |
| [8192,16384) / 0 | 4 | True | 0 | NA | NA | 1.322e+04 | 0 | 0 | 0 |
| [8192,16384) / [0.5,0.9) | 1 | True | 0 | NA | NA | 5290 | 0.6353 | 0 | 0 |

## 租户分组（最多20组）

| group | requests | small_group | ttft_s_n | ttft_s_p90 | tpot_ms_p90 | uncached_tokens_mean | cache_hit_token_weighted | ttft_tail_n | ttft_slo_violation_n |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| tenant_11084483a919 | 3561 | False | 0 | NA | NA | 2.889e+04 | 0.3993 | 0 | 0 |
| tenant_2ae913d44c3b | 1133 | False | 0 | NA | NA | 1650 | 0.04624 | 0 | 0 |
| tenant_43325774110a | 319 | False | 0 | NA | NA | 1.871e+04 | 0.47 | 0 | 0 |
| tenant_60407d162828 | 309 | False | 0 | NA | NA | 2.215e+04 | 0.5041 | 0 | 0 |
| tenant_db12d2db9fd9 | 148 | False | 0 | NA | NA | 2.472e+04 | 0.3607 | 0 | 0 |
| tenant_ac0dcffae03c | 32 | False | 0 | NA | NA | 3.193e+04 | 0.3065 | 0 | 0 |
| tenant_7031da787b5e | 10 | True | 0 | NA | NA | 3.26e+04 | 0.3181 | 0 | 0 |
| tenant_2ad80d16c7c9 | 8 | True | 0 | NA | NA | 3.151e+04 | 0.1086 | 0 | 0 |
| tenant_8de9b57b1148 | 8 | True | 0 | NA | NA | 4.349e+04 | 0.1338 | 0 | 0 |
| tenant_df19b9c86690 | 6 | True | 0 | NA | NA | 1.657e+04 | 0.5559 | 0 | 0 |
| tenant_14b0709a9965 | 3 | True | 0 | NA | NA | 3.052e+04 | 0 | 0 | 0 |
| tenant_1a0184abbfad | 3 | True | 0 | NA | NA | 4.221e+04 | 0 | 0 | 0 |
| tenant_19d18d2e9599 | 2 | True | 0 | NA | NA | 5.454e+04 | 0 | 0 | 0 |
| tenant_3c6b8451c5bc | 2 | True | 0 | NA | NA | 1.026e+05 | 0 | 0 | 0 |
| tenant_129eabe5ebb7 | 1 | True | 0 | NA | NA | 3.886e+04 | 0.03802 | 0 | 0 |
| tenant_76ab5112d0d1 | 1 | True | 0 | NA | NA | 7093 | 0 | 0 | 0 |
| tenant_bb8214d01235 | 1 | True | 0 | NA | NA | 4.393e+04 | 0 | 0 | 0 |
| tenant_d2dfa2252c78 | 1 | True | 0 | NA | NA | 6.742e+04 | 0 | 0 | 0 |
| tenant_f666f827f9b8 | 1 | True | 0 | NA | NA | 3.922e+04 | 0 | 0 | 0 |

## TTFT尾部与前10秒工作量的描述性对照

```
{}
```

回看区间为[t−10s,t)，不包含当前请求和同时间戳请求；跳过分析窗口开头10s。
这种对照不能排除更早积压、批干扰、传输或调度影响，不能把低于突发阈值解释为容量已满。

## 可以支持的下一步讨论

- 描述同一64K集群的长度/实际命中差异、尾部请求构成及其与时间窗口工作量的关联。
- 选择值得验证的流量片段与候选分类特征；租户标签仅用于分组，不自动用作低优先级。
- 结合已有引擎聚合实验提出GF/P入场策略假设，不能由本CSV单独决定队列位置或预算阈值。

## 本数据不能证明

- 不能计算真实逐请求入场等待、P队列深度、P间负载差异或每轮可执行候选。
- 不输出TTFT减下包络作为真实等待；不将不同样本的分位数相减作阶段分解。
- 不据本CSV宣称ρ≈1、吞吐达到容量，或预测双队列会带来多少收益。
- 缺少完成时刻/状态，不计算真实完成吞吐和总在途并发；到达率及群体token量不冒充吞吐。
- 未给定另一策略下的缓存/批服务演化，不作调度反事实性能估计。
请实验机agent在下方补充实际执行命令、单位来源、SQL窗口语义、异常处理和已有实验对照；新增判断需区分记录事实与假设。只回传本Markdown即可，其余JSON/CSV留在内网。

---

# 执行补充（实验机agent，2026-10-21）

## A. 输入来源与口径确认

| 项 | 记录 |
| --- | --- |
| 输入文件 | `/mnt/esfs/zhangxiyue/qwen3.6-27b/FGJSQ_3P3D/TRACR_9.24_GF/TRACE_9.24_GF.csv`（注意：实际目录名为 `TRACR_9.24_GF`，任务描述写作 `TRACE_9.24_GF`，已按实际路径执行） |
| 输入 sha256 | `89c3b69274d7b7923b43da1a607382f713321ce4082e67de19a1dfd989a3a8b3` |
| 文件规模 | 55,166 数据行 + 1 表头行；9 列与约定字段完全一致（带引号 CSV，UTF-8 无 BOM 问题） |
| 数据日期 | model_handle_start_time 观测跨度 2026-09-24 07:00:02 – 08:59:57 UTC（目标 UUID） |
| 原 SQL | **现场未获得 SQL 文件**。已搜索：包内文档、`DATA_9.24_Qwen-3.6-27b/`、`EXP_10.9/`、`EXP_10.12/`、`EXP_10.17_TOKENS/`、`manifest.md`、`HANDOFF_PROMPT.md`、`3P3D服务拉起手册.md`、`RESULT_9.24_Qwen-3.6-27b/`，均无导出 SQL 或表定义。request_time 的时区无法在本机核对，按用户说明记录为"到达时间、时区未确认" |
| 时间窗处理 | 未套用 SQL 的 07:00–09:00 字面窗口（它作用于 request_time 到达轴，本 CSV 无该列）。脚本默认按模型处理起点观测跨度取窗，`outside_analysis_window=0`，未删除任何目标 UUID 记录 |
| 时间格式 | 全部 55,166 行均为 `24/9/2026 07:00:01.348439` 形态（日/月/年）。日位恒为 24、月位恒为 9、年恒为 2026，与 SQL 窗口 2026-09-24 及既有文档先例（`EXP_10.9/DATA_instance/README_DATA_instance.md` §2.1："生产处理开始时刻（UTC，`24/9/2026 07:00:02.080857` 格式）"）一致，按 **D/M/Y + UTC** 解析（需脚本补丁，见 B 节） |
| 选定 UUID | `9a1c5866-aab8-4229-ae4c-51686b863d6e`（5,549 行）。依据：① 同批 9.24 先前导出 `Qwen3.6-9.24-2h.csv`（16336 行、3 实例）中该 UUID 行数同为 5549，两份独立导出同源一致；② EXP_10.9 单实例原速重放选定实例即它（`inst_dataset_summary.json`：avg_qps 0.7714，与本 CSV 实测 0.7712 一致），有跨实验可比性；③ 本 CSV 中它是第 4 大 UUID。**任务未指定具体 UUID 值，此选择为执行侧裁定，见 C-3** |
| 配置依据 | "64K；3P3D；TP4；24×910B2；Qwen3.6-27B W8A8；v0.23.0；原生 proxy；token 预算 8192；最大运行序列 16"全部为**用户口述背景**，本机无可读记录可证实或证伪，未从 CSV 检测，未改写为 FGJSQ/g5，未与 EXP_10.9/10.12 混合 |

## B. 执行记录与脚本修改

**校验与测试**（Python 3.12.13，`/usr/local/python3.12.13/bin/python3`）：

```
cd pkg/cluster-flow-profile-0.1.0-20261020
sha256sum -c MANIFEST.sha256        # 5 文件全部 OK，exit 0
python3 -m unittest discover -s tests/unit -p test_profile_cluster_csv.py -v
                                     # 8 tests OK，exit 0
```

**脚本修改（独立副本，原包未动）**：`run/profile_cluster_csv_patched.py`

- 原因：`timestamp()` 只支持 ISO/epoch，本 CSV 的 `24/9/2026 07:00:01.348439`（D/M/Y）会全部落入 `invalid_start_rows_excluded`，无法分析。
- 修改：仅新增日先格式解析，插在 UTC 后缀清洗与 `fromisoformat` 之间；未支持月先格式（如 `2026/09/24` 仍报错，防止歧义日期静静翻转）。

```
     text = re.sub(r"\s+UTC$", "+00:00", text, flags=re.I)
+    for fmt in ("%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S"):
+        try:
+            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc).timestamp()
+        except ValueError:
+            pass
     dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
```

- hash：原脚本 `22a049696339cd691332213b47a00d27a2cdb37a8c174dcd5a79c6669456f2e4` → 补丁后 `07c0870f58c7da27b9105868b48af34a15e79b1340efab06fd6c00d4110c6f73`（与上方自动报告 metadata.script_sha256 一致）。
- 重新测试：将补丁副本放入镜像目录 `run/testpkg/` 后原 8 项单测对其运行 **8/8 OK，exit 0**；另做函数级断言：新格式两例往返正确、ISO/epoch 回归不变、不支持格式仍 loud-fail——全部通过。
**实际执行命令**（exit 0）：

```
python3 run/profile_cluster_csv_patched.py \
  --input TRACE_9.24_GF.csv \
  --output-dir profile_out_9a1c5866 \
  --instance-uuid 9a1c5866-aab8-4229-ae4c-51686b863d6e \
  --ttft-unit unknown --tpot-unit unknown \
  --workload-type production \
  --label production_64k_20260924 \
  --routing-label native_proxy_unspecified_policy
# {"report": ".../profile_out_9a1c5866/CLUSTER_FLOW_PROFILE_REPORT.md",
#  "requests": 5549, "units": {"ttft": "unknown", "tpot": "unknown"}}
```

**单位取证结论：ttft=unknown、tpot=unknown。**

- 表头无单位后缀（`model_ttft`、`model_tpot`），`auto` 会按规则拒绝。
- 已搜索可能定义单位的现场文档：包内两份文档、`DATA_9.24_Qwen-3.6-27b/` 全部 README 与转换脚本、`EXP_10.9/`（计划/runbook/trace 说明/报告）、`EXP_10.12/`、`EXP_10.17_TOKENS/`、`EXP_10.20_MOTOR/`、`manifest.md`、`HANDOFF_PROMPT.md`、`3P3D服务拉起手册.md`、`RESULT_9.24_Qwen-3.6-27b/`——**均未定义平台库这两个导出字段的单位**。
- `3P3D服务拉起手册.md` 的 `vllm:time_to_first_token_seconds` 是引擎侧指标名，不是本 DB 导出口径，不能移用。
- 旁证（独立来源、不同总体，**不作为单位证据**）：EXP_10.17_TOKENS 记录测试栈 66k 输入 B=1 基线 TTFT 5947/5965ms、TPOT 11.916/11.835ms。
- 按规则未做量级猜单位。字段**原始取值范围核对**（仅为格式核对与后续单位裁定材料，**不是延迟结论，不输出该字段分位数，不作任何 SLO 判断**）：目标 UUID model_ttft 整数 1194–35489；model_tpot 整数 2–31。若外网侧有 DB 文档可据此裁定单位后重跑（命令同上，改 `--ttft-unit/--tpot-unit` 即可）。

## C. 数据质量与不能解释的异常

1. **completion_tokens 语义与用户口径冲突（最重要）**。用户口径=输入＋输出（输出=completion−prompt），但目标 UUID 5,548/5,549 行、全量 55,156/55,166 行 completion<prompt，按该口径输出几乎全为负、不可能成立。两种解读并列如下，**本报告不裁定**，自动报告按用户口径将 output_tokens 置为 NA（仅 1 行可算）：
   - 解读甲（用户口径）：则本导出字段已被改写或口径不适用本表，真实输出未知；
   - 解读乙（completion=实际输出）：则列分布为 p50=182 / p90=629 / max=16384（目标 UUID）。支持乙的形状证据：p50 量级与典型输出一致；反证：与用户明确说明矛盾。
   - 另有硬异常：目标 UUID 26 行 completion≥8192（其中 6 行恰=16384），全量 246 行≥8192、max 86679——**两种解读下都与"token 预算 8192"冲突**（16384/32000 恰为该业务常见 max_tokens 预设值，见 DATA_9.24/dataset_summary.json 的 max_tokens_req p50=16384/p90=32000，疑有记录混入，无法从 9 字段判定）。全量 10 行 completion>prompt（如 2220→3786、110→745），语义同样未定。
2. **3,143 行空 instance_uuid 骨架行**：prompt/completion/cached/ttft/tpot 全空，仅身份+时间+appid；appid 全部为 `com.huawei.ltc.cnbg`；时间聚成 7 个分钟：07:53(70)、07:55(162)、07:56(23)、08:48(590)、08:55(893)、08:57(166)、08:58(1239)。与全 trace 繁忙分钟（08:57/08:48 等）重叠，疑似高负载时段实例字段缺失。另有 21 行带 UUID 的同形态骨架行（981dd673×8、a907f20f×10、484ef606/881108ef/aa195c59 各 1），**目标 UUID 无此类行**。两类合计 3,164 行被计入 `other_cluster_rows_excluded`（=49,617 中的非完整部分；49,617 = 其余 8 个 UUID 完整行 46,453 + 3,164）。
3. **UUID 拓扑与"instance_uuid=整个集群"口径不符**：本 CSV 有 9 个非空 UUID（5,133–7,123 行/个，合计 52,002 完整行、聚合 7.22 起点rps），画像高度同质（见 D-F3）。若按用户口径每个 UUID=一个集群，则本导出跨 9 个集群而非用户描述的单 64K 集群；或该字段粒度与用户理解不同（如 serving 实例）。本报告只分析选定的 1 个 UUID，此矛盾留待外网裁定。
4. **覆盖性声明**：无状态/完成字段，本报告仅覆盖 CSV 中已记录请求；3,164 行骨架记录仅有身份与时间。未发现重复行、(uuid,hash_id) 内容冲突、hash_id 跨 UUID 重叠、cached>prompt。
5. 守恒核对：55,166 = 49,617（其他/空 UUID）+ 5,549（目标，解析后全部有效）；目标内 `completion_less_than_prompt`=5,548、无效 token=0、无效时间=0、窗口排除=0。

## D. 发现（均有上方表格/数字来源）

- **F1 输入长度与命中强异质，prefill 工作量高度集中**：prompt p50=41,655 但 20.3% 请求 ≤8K（1,128 行，几乎全部来自一个租户）；45.5% 请求零命中（2,525 行），token 加权命中率 40.3%（12,400 万 uncached 中零命中组占 52.5%）；≥32K 且零命中的 1,235 行贡献 47.7% 的 uncached token（[32768,49152)/0：769 行×39.8K；[49152,65536)/0：466 行×56.4K）。平均未命中输入 22,346 tok/请求 × 0.7712 rps ≈ **17.2K uncached tok/s** 的持续 prefill 工作量（按起点归属，非执行吞吐）。来源：命中分组/联合分组表、总体表。
- **F2 时间节奏多尺度结构**：1s Fano=1.22、10s=1.28、60s=**3.12**——秒级近泊松、分钟级显著成簇；49.6% 的 1s 窗为零。计数峰 08:57 分钟（n=96）与独立来源（DATA_9.24/dataset_summary busiest_minutes 第 1 位 08:57）一致；工作量峰 07:25 分钟（1.475M uncached tok，≈24.6K tok/s 均值）由 S000…0773 租户驱动（31/40 条）。"前 10s 工作量 vs TTFT 尾部"对照因单位 unknown **未产出**（自动报告该节为空）。
- **F3 两份独立导出同源互证**：本 CSV 的 9a1c5866 与 2026-09-28 首次导出（Qwen3.6-9.24-2h.csv→DATA_9.24 链路）行数同为 5,549、qps 0.7712 vs 0.7714、prompt p50 41,655 vs est_tokens p50 40,849（DB 记录 vs 本地模板分词估计，差 2%，合理）。独立来源已注明。
- **F4 租户集中**：top1 租户 64.2%（3,561 行，uncached 均值 28.9K，token 加权命中 39.9%）；第 2 租户 20.4%（1,133 行，uncached 均值仅 1,650、命中 4.6%）——两租户 prefill 贡献相差一个量级。哈希标签与 appid 对应关系由行数唯一匹配得出：tenant_11084483a919↔S000…0773(3561)、tenant_2ae913d44c3b↔com.huawei.ltc.cnbg(1133)、tenant_43325774110a↔datalinkpro(319)、tenant_60407d162828↔aizhushou(309)、tenant_db12d2db9fd9↔ags(148)。
- **F5 延迟字段零结论**：单位未确认（B 节），无 TTFT/TPOT 分位数、无 SLO 判断、无尾部归因；这是本报告相对任务清单的唯一功能缺失。

## E. 研究假设（明确标注：以下为假设，非结论，均需下一轮数据/实验验证）

- **H1**：分钟级成簇（60s Fano 3.12）主要由 top1 租户会话式用法（相邻分钟重复发送长 prompt）驱动；可用同租户相邻请求的 prompt 相似度/命中演化验证。
- **H2**：零命中长 prompt 组（≥32K/零命中，1,235 行、47.7% uncached）是排队压力的主体；若"长度档+租户+零命中历史"在入场前可预测，它们是双队列分类的候选特征。注意：命中是事后记录，**未证明入场前可见**，预测特征必须另行验证。
- **H3**：ltc.cnbg 骨架行分钟聚块（C-2）是高负载期记录退化，导致该租户真实请求占比被低估；可用其他 UUID 同分钟 ltc.cnbg 计数缺口验证。
- **H4**：completion_tokens 在本导出中实为输出 token（解读乙）；可由外网查表定义或与带输出计数的日志 join 裁定。

## F. 对"双队列分类与让行预算"最有价值的片段/分组，及仍无法确定的事项

最有价值输入（本 CSV 可直接支撑的部分）：

1. **联合分组表**（长度×命中）：最大 uncached 贡献组 = [32768,49152)/0 与 [49152,65536)/0；对照 [0.9,1] 高命中组（698 行、uncached 均值仅 3,182）——让行预算若按 uncached 工作量思考，这两个极端组就是分档边界样本。
2. **租户维度的双峰**：top1（长输入、中等命中、28.9K uncached/条）vs top2（短输入、近零命中、1.65K/条、高频）——两类租户对 P 池的占用模式完全不同，是分类讨论的天然对照。
3. **时间片段**：07:25（工作量峰）、08:57（计数峰）、以及骨架行 7 分钟（数据质量 watch，分析该租户时须剔除或单列）。
4. 节奏基准：0.77 rps、17.2K uncached tok/s、60s Fano 3.12，可作为重放或策略仿真的输入画像参数（按起点口径）。
仍无法确定（不由本 9 字段给出，已按规则不填补）：model_ttft/model_tpot 单位及全部延迟/SLO 结论；completion_tokens 语义（含 ≥8192 异常行）；request_time 到达轴与 GF 接收时刻、逐请求入场等待、排队深度、P ID/batch/真实吞吐；空 UUID 骨架行的归属；9 UUID 拓扑与用户"单集群"口径的关系；任何双队列反事实收益。
**交接**：本 MD 为唯一回传文件；`profile_out_9a1c5866/`（summary.json、windows_*.csv、groups_*.csv）、补丁副本 `run/profile_cluster_csv_patched.py`（07c0870f…）及输入 CSV 均留在内网 `TRACR_9.24_GF/` 下。