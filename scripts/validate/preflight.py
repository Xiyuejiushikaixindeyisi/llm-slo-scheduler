#!/usr/bin/env python3
"""Static launch checks; execute inside the target image before starting services."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("coordinator", "prefill", "decode"), required=True)
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    if args.role == "coordinator":
        from motor_adapter.config import get_config
        config = get_config()
        if not config.enabled:
            raise SystemExit("FGJSQ_CONFIG is not enabled")
        from motor.coordinator.scheduler.runtime.scheduler_client import AsyncSchedulerClient
        import inspect
        if "attempt_seq" not in inspect.signature(AsyncSchedulerClient.select_and_allocate).parameters:
            raise SystemExit("Motor source patch not loaded")
        print(json.dumps({"role": args.role, "event_url": config.event_url, "max_num_seqs": config.max_num_seqs}))
    elif args.role == "prefill":
        from slo_patch.compatibility import verify_engine
        observed = verify_engine()
        if os.getenv("SLO_PATCH_ROLE") != "prefill" or os.getenv("ENABLE_BATCH_REPORTER") != "1":
            raise SystemExit("Missing P-only plugin environment")
        if int(os.getenv("ENABLE_VLLM_TTFT_SLO_MS", "0")) != 0:
            raise SystemExit("SLO batching must remain off")
        for name in ("numpy", "pandas", "sklearn", "lightgbm", "httpx"):
            if importlib.util.find_spec(name) is None:
                raise SystemExit("Missing predictor dependency: " + name)
        model = args.model or (Path(os.environ["SLO_PREDICTOR_MODEL_PATH"]) if os.getenv("SLO_PREDICTOR_MODEL_PATH") else None)
        if model is not None and not model.is_file():
            raise SystemExit("Missing predictor model: " + str(model))
        print(json.dumps({"role": args.role, "engine_files": observed, "model": str(model),
                          "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest() if model else None,
                          "mode": "warm" if model else "cold_smoke_only"}, indent=2))
    else:
        if os.getenv("SLO_PATCH_ROLE") == "prefill" or os.getenv("ENABLE_BATCH_REPORTER") == "1":
            raise SystemExit("P predictor environment leaked into D")
        print("D: no P-only predictor environment; compare remaining settings to captured baseline.")


if __name__ == "__main__":
    main()
