#!/usr/bin/env python3
"""Bounded read-only FG sampling, window summaries and explicit parameter freeze.

No automatic threshold tuning. Window labels must come from independent waiting
records; TTFT residuals are not engine queue time. No credentials are persisted.
"""

import argparse
import hashlib
import json
import math
import os
import ssl
import time
import urllib.request
from pathlib import Path


def quantiles(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    result = {"n": len(values), "min": values[0], "max": values[-1]}
    for q in (25, 50, 75, 90, 99):
        pos = (len(values) - 1) * q / 100
        lo = math.floor(pos)
        result["p" + str(q)] = values[lo] + (values[math.ceil(pos)] - values[lo]) * (
            pos - lo
        )
    return result


def collect(args):
    if not 0.1 <= args.interval <= 60 or not 0 < args.duration <= 3600:
        raise ValueError("probe interval .1..60s and duration (0,3600]s required")
    context = ssl.create_default_context(cafile=args.ca_file)
    key = os.environ.get(args.key_env)
    headers = {"X-Motor-Management-Key": key} if key else {}
    urls = {"loads": args.url.rstrip("/") + "/fgjsq/v1/loads"}
    if args.admission:
        urls["admission"] = args.url.rstrip("/") + "/admission/v1/state"
    stop = time.monotonic() + args.duration
    with args.output.open("x", encoding="utf-8") as out:
        while time.monotonic() < stop:
            row = {
                "run_id": args.run_id,
                "wall_time_s": time.time(),
                "input_tokens": args.input_tokens,
                "concurrency": args.concurrency,
                "instances": args.instances.split(","),
                "samples": {},
            }
            for name, url in urls.items():
                started = time.time()
                try:
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(
                        req, timeout=min(3, args.duration), context=context
                    ) as response:
                        raw = response.read(2097153)
                    if len(raw) > 2097152:
                        raise ValueError("oversized management response")
                    row["samples"][name] = {
                        "start_s": started,
                        "end_s": time.time(),
                        "data": json.loads(raw),
                    }
                except (OSError, ValueError) as error:
                    row["samples"][name] = {
                        "start_s": started,
                        "end_s": time.time(),
                        "error": type(error).__name__,
                    }
            out.write(json.dumps(row, allow_nan=False) + "\n")
            out.flush()
            time.sleep(min(args.interval, max(0, stop - time.monotonic())))


def summarize(source, windows):
    groups, rejected, rows = {}, 0, 0
    identities = set()
    with source.open() as stream:
        for line in stream:
            row = json.loads(line)
            rows += 1
            identities.add((row["run_id"], row["input_tokens"], row["concurrency"]))
            sample = row.get("samples", {}).get("loads", {})
            policy = sample.get("data", {}).get("policy", {})
            ids = row["instances"]
            if not ids or any(i not in policy for i in ids) or "error" in sample:
                rejected += 1
                continue
            labels = {
                w["label"]
                for w in windows
                if w["start_s"] <= sample["start_s"] and sample["end_s"] <= w["end_s"]
            }
            labels.add("all")
            for label in labels:
                group = groups.setdefault(label, {"minimum_score": [], "per_p": {}})
                group["minimum_score"].append(min(policy[i]["score"] for i in ids))
                for i in ids:
                    target = group["per_p"].setdefault(
                        i, {k: [] for k in ("score", "committed_tokens", "requests")}
                    )
                    for k in target:
                        value = policy[i][k]
                        if (
                            not isinstance(value, (int, float))
                            or not math.isfinite(value)
                            or value < 0
                        ):
                            raise ValueError("invalid FG sample")
                        target[k].append(value)
    return {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "rows": rows,
        "rejected_missing_p_or_error": rejected,
        "identities": sorted(identities),
        "unit": "fg_score; committed_tokens are FG estimates, not engine waiting tokens",
        "windows": windows,
        "groups": {
            label: {
                "minimum_score": quantiles(g["minimum_score"]),
                "per_p": {
                    i: {k: quantiles(v) for k, v in fields.items()}
                    for i, fields in g["per_p"].items()
                },
            }
            for label, g in groups.items()
        },
        "thresholds": "choose explicitly; no automatic fitting",
    }


def freeze(args):
    from gf_admission.runtime_config import load_config

    report = json.loads(args.evidence.read_text())
    if not report.get("groups", {}).get("all", {}).get("minimum_score", {}).get("n"):
        raise ValueError("probe evidence has no complete pressure samples")
    raw = json.loads(args.template.read_text())
    raw.update(
        mode="enforce",
        cluster_uuid=args.cluster_uuid,
        model_spec=args.model_spec,
        release_threshold=args.low,
        high_pressure_threshold=args.high,
        parameter_source="probe-sha256:"
        + hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
    )
    if args.event_fresh_ms is not None:
        raw["event_fresh_ms"] = args.event_fresh_ms
    if args.tail_wait_ms is not None:
        raw["limits"]["max_tail_wait_ms"] = args.tail_wait_ms
    # Validate in memory before creating the final file; no invalid leftovers.
    from gf_admission.config import ClassifierConfig, QueueLimits
    from gf_admission.runtime_config import RuntimeConfig

    checked = dict(
        raw,
        classifier=ClassifierConfig(**raw["classifier"]),
        limits=QueueLimits(**raw["limits"]),
    )
    RuntimeConfig(**checked)
    with args.output.open("x") as out:
        out.write(json.dumps(raw, indent=2) + "\n")
    print(
        json.dumps(
            {
                "config": str(args.output),
                "digest": load_config(args.output).digest,
                "evidence": str(args.evidence),
                "rationale": args.rationale,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="op", required=True)
    p = sub.add_parser("collect")
    p.add_argument("--url", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--input-tokens", type=int, required=True)
    p.add_argument("--concurrency", type=int, default=16)
    p.add_argument(
        "--instances", required=True, help="comma-separated actual P instance IDs"
    )
    p.add_argument("--duration", type=float, default=600)
    p.add_argument("--interval", type=float, default=0.5)
    p.add_argument("--key-env", default="GF_MGMT_KEY")
    p.add_argument("--ca-file")
    p.add_argument("--admission", action="store_true")
    p = sub.add_parser("summarize")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument(
        "--windows",
        type=Path,
        help="JSON array: start_s/end_s/label from waiting evidence",
    )
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("freeze")
    p.add_argument("--template", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cluster-uuid", required=True)
    p.add_argument("--model-spec", required=True)
    p.add_argument("--high", type=float, required=True)
    p.add_argument("--low", type=float, required=True)
    p.add_argument("--rationale", required=True)
    p.add_argument("--event-fresh-ms", type=float)
    p.add_argument("--tail-wait-ms", type=float)
    args = parser.parse_args()
    if args.op == "collect":
        collect(args)
    elif args.op == "summarize":
        windows = json.loads(args.windows.read_text()) if args.windows else []
        with args.output.open("x") as out:
            json.dump(summarize(args.input, windows), out, indent=2)
    else:
        freeze(args)


if __name__ == "__main__":
    main()
