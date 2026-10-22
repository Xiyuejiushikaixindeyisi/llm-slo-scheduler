#!/usr/bin/env python3
"""Read-only, standard-library analysis of the nine-field cluster request CSV."""
import argparse
import bisect
import csv
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.0"
FIELDS = (
    "instance_uuid", "hash_id", "appid", "model_handle_start_time",
    "prompt_tokens", "completion_tokens", "cached_tokens", "model_ttft",
    "model_tpot",
)
UNIT_SCALE = {"s": 1.0, "ms": .001, "us": .000001, "unknown": None}
UNIT_NAMES = {"秒": "s", "毫秒": "ms", "微秒": "us",
              "s": "s", "ms": "ms", "us": "us"}


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def number(value, integer=False):
    try:
        n = float(str(value).strip())
    except (ValueError, TypeError):
        return None
    if not math.isfinite(n) or n < 0 or (integer and not n.is_integer()):
        return None
    return int(n) if integer else n


def timestamp(value):
    """Naive model_handle_start_time is UTC, as specified by the data owner."""
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        width = len(text.split(".")[0])
        scales = {10: 1, 13: 1e3, 16: 1e6, 19: 1e9}
        if width not in scales:
            raise ValueError("Unrecognized epoch timestamp precision")
        result = float(text) / scales[width]
        datetime.fromtimestamp(result, timezone.utc)
        return result
    text = re.sub(r"\s+UTC$", "+00:00", text, flags=re.I)
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def quantile(values, q):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def describe(values):
    values = [v for v in values if v is not None]
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "p50": quantile(values, .5), "p90": quantile(values, .9),
        "p95": quantile(values, .95), "p99": quantile(values, .99),
        "max": max(values) if values else None,
    }


def columns(headers):
    if not headers or len(headers) != len(set(headers)):
        raise ValueError("Missing or duplicate CSV headers")
    mapping = {}
    for field in FIELDS:
        pattern = re.compile(
            re.escape(field)
            + (r"(?:\s*[\[(]\s*(s|ms|us|秒|毫秒|微秒)\s*[\])]|_(s|ms|us))?"
               if field.startswith("model_t") else "")
            + r"$", re.I)
        hits = [h for h in headers if pattern.fullmatch(h.strip())]
        if len(hits) != 1:
            raise ValueError(f"Need exactly one column for {field}; found {hits}")
        mapping[field] = hits[0]
    return mapping


def resolve_unit(header, requested):
    suffix = re.search(r"(?:[\[(]\s*(s|ms|us|秒|毫秒|微秒)\s*[\])]|_(s|ms|us))$",
                       header.strip(), re.I)
    explicit = UNIT_NAMES[(suffix.group(1) or suffix.group(2)).lower()] if suffix else None
    if requested == "auto":
        if not explicit:
            raise ValueError(
                f"No explicit unit in {header!r}. Verify its source and pass s/ms/us, "
                "or pass unknown for traffic/token-only analysis. Never infer from magnitude.")
        return explicit
    if explicit and requested not in (explicit, "unknown"):
        raise ValueError(f"Unit conflict: header={explicit}, option={requested}")
    return requested


def read_input(args):
    quality = Counter()
    rows, identities, clusters = [], {}, set()
    with args.input.open(encoding=args.encoding, newline="") as f:
        sample = f.read(32768)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        mapping = columns(reader.fieldnames)
        units = {
            "ttft": resolve_unit(mapping["model_ttft"], args.ttft_unit),
            "tpot": resolve_unit(mapping["model_tpot"], args.tpot_unit),
        }
        for raw in reader:
            quality["csv_rows"] += 1
            if None in raw or any(raw.get(mapping[k]) is None for k in FIELDS):
                quality["malformed_rows_excluded"] += 1
                continue
            row = {k: raw[mapping[k]].strip() for k in FIELDS}
            if args.instance_uuid and row["instance_uuid"] != args.instance_uuid:
                quality["other_cluster_rows_excluded"] += 1
                continue
            if not row["instance_uuid"] or not row["hash_id"]:
                quality["missing_identity_rows_excluded"] += 1
                continue
            clusters.add(row["instance_uuid"])
            identity = (row["instance_uuid"], row["hash_id"])
            signature = tuple(row[k] for k in FIELDS)
            if identity in identities:
                if identities[identity] != signature:
                    raise ValueError(f"Conflicting rows for one hash_id in cluster {identity[0]}; "
                                     "resolve retry/update semantics before analysis.")
                quality["identical_duplicate_rows_excluded"] += 1
                continue
            identities[identity] = signature
            try:
                start = timestamp(row["model_handle_start_time"])
            except (ValueError, OverflowError, OSError):
                quality["invalid_start_rows_excluded"] += 1
                continue
            item = {"start": start, "cluster": row["instance_uuid"]}
            item["tenant"] = (
                "tenant_" + hashlib.sha256(row["appid"].encode()).hexdigest()[:12]
                if row["appid"] else "unknown_tenant")
            for name in ("prompt_tokens", "completion_tokens", "cached_tokens"):
                item[name] = number(row[name], integer=True)
                if item[name] is None:
                    quality[f"invalid_or_missing_{name}"] += 1
            p, total, hit = (item[k] for k in
                             ("prompt_tokens", "completion_tokens", "cached_tokens"))
            item["output_tokens"] = total - p if p is not None and total is not None and total >= p else None
            if p is not None and total is not None and total < p:
                quality["completion_less_than_prompt"] += 1
            valid_hit = p is not None and hit is not None and hit <= p
            if p is not None and hit is not None and hit > p:
                quality["cached_greater_than_prompt"] += 1
            item["uncached_tokens"] = p - hit if valid_hit else None
            item["cache_hit_ratio"] = hit / p if valid_hit and p > 0 else None
            for metric in ("ttft", "tpot"):
                value = number(row["model_" + metric])
                if value is None:
                    quality[f"invalid_or_missing_{metric}"] += 1
                scale = UNIT_SCALE[units[metric]]
                item[metric + "_s"] = value * scale if value is not None and scale is not None else None
            rows.append(item)
    if len(clusters) != 1:
        raise ValueError(f"Need one cluster; found {len(clusters)}. Use --instance-uuid.")
    if not rows:
        raise ValueError("No requests with usable identity and start timestamp")
    rows.sort(key=lambda r: r["start"])
    quality["parsed_unique_rows"] = len(rows)
    return rows, dict(quality), mapping, units


def length_bin(row):
    p = row["prompt_tokens"]
    if p is None:
        return "unknown"
    edges = [0, 8192, 16384, 32768, 49152, 65536]
    for lo, hi in zip(edges, edges[1:]):
        if lo <= p < hi:
            return f"[{lo},{hi})"
    return "[65536,+inf)"


def cache_bin(row):
    h = row["cache_hit_ratio"]
    if h is None:
        return "unknown"
    if h == 0:
        return "0"
    if h < .5:
        return "(0,0.5)"
    if h < .9:
        return "[0.5,0.9)"
    return "[0.9,1]"


def row_stats(rows, args, tail_threshold):
    ttft = describe([r["ttft_s"] for r in rows])
    tpot = describe([r["tpot_s"] * 1000 if r["tpot_s"] is not None else None for r in rows])
    result = {"requests": len(rows), "small_group": len(rows) < args.min_group_size}
    result.update({"ttft_s_" + k: v for k, v in ttft.items()})
    result.update({"tpot_ms_" + k: v for k, v in tpot.items()})
    for key in ("prompt_tokens", "output_tokens", "uncached_tokens"):
        valid = [r[key] for r in rows if r[key] is not None]
        result[key + "_known_n"] = len(valid)
        result[key + "_sum"] = sum(valid)
        result[key + "_mean"] = statistics.fmean(valid) if valid else None
    pairs = [r for r in rows if r["cache_hit_ratio"] is not None]
    denom = sum(r["prompt_tokens"] for r in pairs)
    result["cache_hit_known_n"] = len(pairs)
    result["cache_hit_token_weighted"] = sum(r["cached_tokens"] for r in pairs) / denom if denom else None
    result["ttft_slo_violation_n"] = sum(
        r["ttft_s"] is not None and r["ttft_s"] >= args.ttft_slo_s for r in rows)
    result["tpot_slo_violation_n"] = sum(
        r["tpot_s"] is not None and r["tpot_s"] * 1000 >= args.tpot_slo_ms for r in rows)
    result["ttft_tail_n"] = sum(
        r["ttft_s"] is not None and tail_threshold is not None and r["ttft_s"] >= tail_threshold
        for r in rows)
    return result


def group_stats(rows, args, threshold, key):
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return [{"group": name, **row_stats(group, args, threshold)}
            for name, group in sorted(groups.items())]


def window_stats(rows, start, end, width, args, threshold):
    count = math.ceil((end - start) / width)
    if count > 1_000_000:
        raise ValueError("Analysis span exceeds one million windows; specify a shorter interval.")
    buckets = defaultdict(list)
    for row in rows:
        buckets[int((row["start"] - start) // width)].append(row)
    output = []
    for index in range(count):
        left, right = start + index * width, min(end, start + (index + 1) * width)
        entry = row_stats(buckets[index], args, threshold)
        entry.update(start_utc=iso(left), end_utc=iso(right),
                     duration_s=right-left, full_window=right-left == width)
        entry["recorded_start_rps"] = entry["requests"] / (right-left)
        output.append(entry)
    counts = [r["requests"] for r in output if r["full_window"]]
    avg = statistics.fmean(counts) if counts else None
    overview = {
        "window_s": width, "full_windows": len(counts),
        "zero_window_fraction": counts.count(0) / len(counts) if counts else None,
        "count_mean": avg, "count_p90": quantile(counts, .9),
        "count_max": max(counts) if counts else None,
        "count_fano": statistics.pvariance(counts) / avg if avg else None,
    }
    return output, overview


def preceding_work(rows, analysis_start, threshold):
    """Use [t-10,t), excluding all same-timestamp arrivals and the current row."""
    times = [r["start"] for r in rows]
    prefix = {k: [0] for k in ("prompt_tokens", "uncached_tokens")}
    missing = {k: [0] for k in prefix}
    for row in rows:
        for k in prefix:
            prefix[k].append(prefix[k][-1] + (row[k] or 0))
            missing[k].append(missing[k][-1] + (row[k] is None))
    groups = defaultdict(list)
    for row in rows:
        if row["start"] < analysis_start + 10 or row["ttft_s"] is None or threshold is None:
            continue
        lo = bisect.bisect_left(times, row["start"] - 10)
        hi = bisect.bisect_left(times, row["start"])
        record = {"prior_10s_count": hi-lo}
        for k in prefix:
            record["prior_10s_" + k] = (
                prefix[k][hi] - prefix[k][lo] if missing[k][hi] == missing[k][lo] else None)
        groups["ttft_at_or_above_p90" if row["ttft_s"] >= threshold else "below_p90"].append(record)
    return {group: {key: describe([r[key] for r in values])
                    for key in ("prior_10s_count", "prior_10s_prompt_tokens", "prior_10s_uncached_tokens")}
            for group, values in groups.items()}


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fmt(value):
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value).replace("|", "/").replace("\n", " ")


def markdown_table(rows, fields):
    return "\n".join(
        ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
        + ["| " + " | ".join(fmt(row.get(k)) for k in fields) + " |" for row in rows])


def make_report(summary):
    meta, overall = summary["metadata"], summary["overall"]
    text = [
        "# CLUSTER_FLOW_PROFILE_REPORT",
        "",
        "本报告为九字段日志的描述性分析，未连接服务、查询数据库或改变调度。",
        "请求时间轴使用 model_handle_start_time（UTC，模型处理起点），不是已验证的GF接收时刻。",
        "request_time虽为到达时间，但不在本CSV九字段中；不还原两个时间点之间的等待。",
        "",
        "## 来源与口径",
        "",
        "```json", json.dumps(meta, ensure_ascii=False, indent=2), "```",
        "",
        "## 数据质量",
        "",
        "```json", json.dumps(summary["quality"], ensure_ascii=False, indent=2), "```",
        "",
        "completion_tokens按用户口径为输入＋输出；output_tokens=completion_tokens-prompt_tokens。",
        "uncached_tokens=prompt_tokens-cached_tokens仅是工作量代理，不等于精确服务时间。",
        "命中为事后记录，未证明入场前可见。缺失/异常字段不补0，不影响其他有效字段的独立统计。",
        "",
        "## 总体结果",
        "",
        markdown_table([overall], ["requests", "ttft_s_n", "ttft_s_p50", "ttft_s_p90",
                                  "ttft_s_p95", "ttft_s_p99", "tpot_ms_n", "tpot_ms_p90",
                                  "ttft_slo_violation_n", "tpot_slo_violation_n"]),
        "",
        "分位数为线性插值经验分位数。SLO违约按TTFT≥阈值/TPOT≥阈值计，分母分别是有效指标数。",
        "TTFT尾部定义为≥本样本P90，存在并列时占比可能超过10%；小组标记不构成置信区间。",
        "未提供失败/取消/未完成标记，结果仅代表CSV中已记录且该指标有效的请求，不能宣称覆盖所有发起请求。",
        "",
        "## 请求工作量分布",
        "",
        markdown_table(
            [{"field": key, **value} for key, value in summary["workload_distributions"].items()],
            ["field", "n", "mean", "p50", "p90", "p95", "p99", "max"]),
        "",
        "长度单位为token；cache_hit_ratio是逐请求比值，其均值不同于sum(cached)/sum(prompt)。",
        "命中及输出均为事后观测，不自动成为入场时可知的特征。",
        "",
        "## 时间节奏与工作量",
        "",
        "```json", json.dumps(summary["interarrival_s"], ensure_ascii=False, indent=2), "```",
        "",
        markdown_table(summary["window_overview"], ["window_s", "full_windows",
                       "zero_window_fraction", "count_mean", "count_p90", "count_max", "count_fano"]),
        "",
        "窗口包含零请求窗，Fano仅使用完整窗。上述指标描述模型处理起点的节奏，"
        "不据此判定泊松/独立到达、容量饱和或突发因果。",
        "各窗口CSV的token总量按请求起点归属，是该群体输入工作量，不是期间实际处理token量。",
        "",
    ]
    for name, title in (("length", "输入长度分组"), ("cache", "命中分组"),
                        ("length_cache", "长度×命中联合分组"), ("tenant", "租户分组（最多20组）")):
        data = summary["groups"][name]
        if name == "tenant":
            data = sorted(data, key=lambda r: -r["requests"])[:20]
        text.extend(["## " + title, "", markdown_table(data, [
            "group", "requests", "small_group", "ttft_s_n", "ttft_s_p90", "tpot_ms_p90",
            "uncached_tokens_mean", "cache_hit_token_weighted", "ttft_tail_n",
            "ttft_slo_violation_n"]), ""])
    text.extend([
        "## TTFT尾部与前10秒工作量的描述性对照",
        "",
        "```json", json.dumps(summary["preceding_10s_comparison"], ensure_ascii=False, indent=2), "```",
        "",
        "回看区间为[t−10s,t)，不包含当前请求和同时间戳请求；跳过分析窗口开头10s。",
        "这种对照不能排除更早积压、批干扰、传输或调度影响，不能把低于突发阈值解释为容量已满。",
        "",
        "## 可以支持的下一步讨论",
        "",
        "- 描述同一64K集群的长度/实际命中差异、尾部请求构成及其与时间窗口工作量的关联。",
        "- 选择值得验证的流量片段与候选分类特征；租户标签仅用于分组，不自动用作低优先级。",
        "- 结合已有引擎聚合实验提出GF/P入场策略假设，不能由本CSV单独决定队列位置或预算阈值。",
        "",
        "## 本数据不能证明",
        "",
        "- 不能计算真实逐请求入场等待、P队列深度、P间负载差异或每轮可执行候选。",
        "- 不输出TTFT减下包络作为真实等待；不将不同样本的分位数相减作阶段分解。",
        "- 不据本CSV宣称ρ≈1、吞吐达到容量，或预测双队列会带来多少收益。",
        "- 缺少完成时刻/状态，不计算真实完成吞吐和总在途并发；到达率及群体token量不冒充吞吐。",
        "- 未给定另一策略下的缓存/批服务演化，不作调度反事实性能估计。",
        "",
        "请实验机agent在下方补充实际执行命令、单位来源、SQL窗口语义、异常处理和已有实验对照；"
        "新增判断需区分记录事实与假设。只回传本Markdown即可，其余JSON/CSV留在内网。",
    ])
    return "\n".join(text) + "\n"


def analyze(args):
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise ValueError("Output directory is nonempty; choose a new directory.")
    input_hash = digest_file(args.input)
    rows, quality, mapping, units = read_input(args)
    if digest_file(args.input) != input_hash:
        raise ValueError("Input CSV changed during reading; use a completed, static export.")
    if bool(args.window_start) != bool(args.window_end):
        raise ValueError("Specify both --window-start and --window-end, or neither.")
    if args.window_start:
        start, end = timestamp(args.window_start), timestamp(args.window_end)
        boundary_source = "explicit UTC model_handle_start_time interval"
    else:
        start, end = math.floor(rows[0]["start"]), math.floor(rows[-1]["start"]) + 1
        boundary_source = "inferred observed span; not the full SQL arrival window"
    if end <= start:
        raise ValueError("Window end must exceed start")
    selected = [r for r in rows if start <= r["start"] < end]
    quality["outside_analysis_window"] = len(rows) - len(selected)
    rows = selected
    if not rows:
        raise ValueError("No requests in analysis window")
    threshold = quantile([r["ttft_s"] for r in rows], .9)
    gaps = [b["start"] - a["start"] for a, b in zip(rows, rows[1:])]
    gaps_summary = describe(gaps)
    gaps_summary["cv"] = statistics.pstdev(gaps) / statistics.fmean(gaps) if gaps and statistics.fmean(gaps) else None
    groups = {
        "length": group_stats(rows, args, threshold, length_bin),
        "cache": group_stats(rows, args, threshold, cache_bin),
        "length_cache": group_stats(rows, args, threshold, lambda r: length_bin(r) + " / " + cache_bin(r)),
        "tenant": group_stats(rows, args, threshold, lambda r: r["tenant"]),
    }
    windows, overviews = {}, []
    for width in (1, 10, 60):
        windows[width], overview = window_stats(rows, start, end, width, args, threshold)
        overviews.append(overview)
    summary = {
        "metadata": {
            "tool_version": VERSION, "script_sha256": digest_file(__file__),
            "python_version": sys.version.split()[0],
            "input_path": str(args.input.resolve()), "input_sha256": input_hash,
            "instance_uuid": rows[0]["cluster"], "workload_type": args.workload_type,
            "label": args.label, "routing_label": args.routing_label,
            "reported_environment": "64K; 3P3D; TP4; 24x910B2; Qwen3.6-27B W8A8; v0.23.0",
            "reported_token_budget": 8192, "reported_max_num_seqs": 16,
            "environment_evidence": "user-provided context, not detected from CSV",
            "column_mapping": mapping, "resolved_input_units": units,
            "window_start_utc": iso(start), "window_end_utc": iso(end),
            "window_boundary_source": boundary_source,
            "recorded_start_rps": len(rows) / (end-start),
            "metric_units": "TTFT seconds; TPOT milliseconds",
            "ttft_slo_s": args.ttft_slo_s, "tpot_slo_ms": args.tpot_slo_ms,
            "small_group_threshold": args.min_group_size,
            "quantile_method": "linear interpolation, (n-1)*q",
        },
        "quality": quality, "overall": row_stats(rows, args, threshold),
        "workload_distributions": {
            key: describe([r[key] for r in rows])
            for key in ("prompt_tokens", "output_tokens", "uncached_tokens", "cache_hit_ratio")
        },
        "interarrival_s": gaps_summary, "window_overview": overviews,
        "groups": groups, "preceding_10s_comparison": preceding_work(rows, start, threshold),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for width, records in windows.items():
        write_csv(args.output_dir / f"windows_{width}s.csv", records)
    for name, records in groups.items():
        write_csv(args.output_dir / f"groups_{name}.csv", records)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    (args.output_dir / "CLUSTER_FLOW_PROFILE_REPORT.md").write_text(make_report(summary), encoding="utf-8")
    return summary


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--instance-uuid")
    p.add_argument("--encoding", default="utf-8-sig")
    for name in ("ttft", "tpot"):
        p.add_argument("--" + name + "-unit", choices=["auto", "s", "ms", "us", "unknown"], default="auto")
    p.add_argument("--window-start", help="Optional UTC interval on model_handle_start_time")
    p.add_argument("--window-end")
    p.add_argument("--workload-type", choices=["production", "open_replay", "closed"], default="production")
    p.add_argument("--label", default="production_64k")
    p.add_argument("--routing-label", default="native_proxy_unspecified_policy")
    p.add_argument("--ttft-slo-s", type=float, default=27)
    p.add_argument("--tpot-slo-ms", type=float, default=30)
    p.add_argument("--min-group-size", type=int, default=20)
    return p


def main():
    args = parser().parse_args()
    try:
        if (args.min_group_size < 1 or not math.isfinite(args.ttft_slo_s)
                or not math.isfinite(args.tpot_slo_ms)
                or args.ttft_slo_s <= 0 or args.tpot_slo_ms <= 0):
            raise ValueError("SLOs and minimum group size must be positive and finite")
        result = analyze(args)
    except (ValueError, OSError, UnicodeError, csv.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"report": str(args.output_dir / "CLUSTER_FLOW_PROFILE_REPORT.md"),
                      "requests": result["overall"]["requests"],
                      "units": result["metadata"]["resolved_input_units"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
