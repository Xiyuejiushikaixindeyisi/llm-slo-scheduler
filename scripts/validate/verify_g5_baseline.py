#!/usr/bin/env python3
"""Read-only G5 fingerprint check; local source checks do not validate NPU runtime."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
IMPORTS = ("motor.coordinator.main", "motor.controller.main", "motor.node_manager.main",
           "motor_adapter.bindings", "slo_patch.activate", "lightgbm", "sklearn",
           "joblib", "httpx", "OpenSSL", "kubernetes", "watchdog")


def installed_path(relative):
    top, *rest = relative.split("/")
    spec = importlib.util.find_spec(top)
    if not spec or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations))).joinpath(*rest).resolve()


def check_file(path, expected):
    observed = hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None
    return {"path": str(path) if path else None, "sha256": observed, "expected": expected,
            "status": "match" if observed == expected else "missing" if observed is None else "mismatch"}


def verify(root=ROOT, motor_root=None, scope="local", imports=False):
    manifest = json.loads((root / "env/g5-baseline-files.json").read_text())
    files = {}
    for name, sha in {**manifest["core_files"], **manifest["engine_files"]}.items():
        relative = name.removeprefix("src/") if name.startswith("src/") else name.split("/", 2)[2]
        path = root / name if scope == "local" else installed_path(relative)
        files[name] = check_file(path, sha)
    motor_root = motor_root or root / manifest["motor_checkout"]
    for name, hashes in {**manifest["motor_patch_files"], **manifest["node_manager_fix"]}.items():
        path = motor_root / name if scope == "local" else installed_path(name)
        files[name] = check_file(path, hashes["after"])
    if scope == "local":
        evidence = manifest["evidence"]
        files[evidence["path"]] = check_file(root / evidence["path"], evidence["sha256"])
    versions = {}
    for name in ("motor", "vllm", "vllm-ascend", "torch", "torch-npu", "mooncake-transfer-engine",
                 "lightgbm", "scikit-learn", "httpx", "pyOpenSSL", "kubernetes", "watchdog"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    import_results = {}
    if imports:
        for name in IMPORTS:
            try:
                run = subprocess.run([sys.executable, "-c",
                    "import importlib; m=importlib.import_module(" + repr(name) + "); print(getattr(m, '__file__', None))"],
                    capture_output=True, text=True, timeout=30)
                import_results[name] = {"passed": run.returncode == 0, "returncode": run.returncode,
                                        "output": run.stdout[-2000:], "error": run.stderr[-2000:]}
            except subprocess.TimeoutExpired:
                import_results[name] = {"passed": False, "error": "import timed out after 30 s"}
    return {"schema_version": 1, "baseline": manifest["baseline"], "scope": scope,
            "passed": all(f["status"] == "match" for f in files.values()) and
                      all(v["passed"] for v in import_results.values()),
            "python": platform.python_version(), "machine": platform.machine(), "files": files,
            "package_versions_observed_only": versions, "imports": import_results,
            "limits": ["No NPU or performance validation; dependency versions are observations, not local requirements.",
                       "NodeManager after hash identifies the local semantic reconstruction, not the unprovided onsite file.",
                       "A different onsite fix must be reviewed; this tool never installs or replaces files."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("local", "runtime"), default="local")
    parser.add_argument("--motor-root", type=Path)
    parser.add_argument("--imports", action="store_true", help="Optional runtime import battery, isolated processes")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.imports and args.scope != "runtime":
        parser.error("--imports belongs to --scope runtime; local source alignment needs no NPU packages")
    result = verify(motor_root=args.motor_root, scope=args.scope, imports=args.imports)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "scope": args.scope,
                      "matched": sum(f["status"] == "match" for f in result["files"].values()),
                      "issues": {k: v for k, v in result["files"].items() if v["status"] != "match"},
                      "output": str(args.output)}, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
