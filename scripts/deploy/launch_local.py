#!/usr/bin/env python3
"""Execute a reviewed, explicit per-node command; no guessed engine or KV CLI."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--role", choices=("P", "D", "coordinator"), required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    spec = plan["nodes"][args.node][args.role]
    command = spec["command"]
    env = dict(spec.get("env", {}))
    if not isinstance(command, list) or not command or any(not isinstance(v,str) for v in command):
        raise SystemExit("command must be a nonempty argv list")
    if any("REQUIRED_" in v for v in command + list(env.values())):
        raise SystemExit("Replace required site-specific values before launch")
    if args.role == "P":
        env.update(SLO_PATCH_ROLE="prefill", ENABLE_BATCH_REPORTER="1", ENABLE_VLLM_TTFT_SLO_MS="0")
    elif args.role == "D" and (env.get("SLO_PATCH_ROLE") == "prefill" or env.get("ENABLE_BATCH_REPORTER") == "1"):
        raise SystemExit("P-only environment present in D specification")
    if not args.execute:
        print(json.dumps({"node":args.node,"role":args.role,"command":command,"env_overrides":env},ensure_ascii=False,indent=2))
        return
    merged = dict(os.environ)
    # Experiment launcher separates P switches from the D/Coordinator environment.
    if args.role != "P":
        for key in ("SLO_PATCH_ROLE","ENABLE_BATCH_REPORTER","ENABLE_VLLM_TTFT_SLO_MS","SLO_PREDICTOR_MODEL_PATH"):
            merged.pop(key,None)
    merged.update(env)
    if spec.get("cwd"):
        os.chdir(spec["cwd"])
    os.execvpe(command[0], command, merged)


if __name__ == "__main__":
    main()
