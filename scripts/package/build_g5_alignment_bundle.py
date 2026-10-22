#!/usr/bin/env python3
"""Prepare a versioned source/reference bundle without rebuilding wheels or NPU dependencies."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
NAME = "g5-baseline-alignment-0.1.0-20261022"


def inventory():
    anchor = json.loads((ROOT / "env/g5-baseline-files.json").read_text())
    files = set(anchor["core_files"])
    files.update(anchor["engine_files"])
    files.add(anchor["evidence"]["path"])
    for name in {**anchor["motor_patch_files"], **anchor["node_manager_fix"]}:
        files.add("upstream/motor/" + name)
    for folder in ("configs/baseline/g5-frozen", "env", "patches/motor"):
        files.update(str(p.relative_to(ROOT)) for p in (ROOT / folder).rglob("*") if p.is_file())
    files.update(("docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md",
                  "docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_REVIEW.md",
                  "evidence/manifests/g5_local_alignment_audit_20261022.json",
                  "scripts/deploy/g5_motor_install.py", "scripts/validate/verify_g5_baseline.py",
                  "scripts/validate/preflight.py", "scripts/validate/smoke.py", "scripts/collect/collect_runtime.py",
                  "tests/unit/test_g5_alignment_tools.py"))
    for name in ("node-manager-red.log", "node-manager-green.log", "motor-config-regression.log",
                 "project-tests.log", "fingerprint-check.json"):
        files.add("artifacts/g5-alignment/" + name)
    for repo in ("motor", "vllm-v0.23.0", "vllm-ascend-v0.23.0"):
        files.update(str(p.relative_to(ROOT)) for p in (ROOT / "upstream" / repo).glob("LICENSE*") if p.is_file())
    for name, sha in {**anchor["core_files"], **anchor["engine_files"], anchor["evidence"]["path"]: anchor["evidence"]["sha256"]}.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha:
            raise ValueError("Frozen source drift: " + name)
    for name in files:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(name)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, help="New staging directory; omission only validates the inventory")
    args = parser.parse_args()
    files = inventory()
    if args.stage:
        args.stage.mkdir(parents=True, exist_ok=False)
        for name in files:
            dest = args.stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, dest)
        metadata = {"name": NAME, "algorithm_version": "0.2.0 unchanged",
                    "purpose": "Incremental baseline tooling; do not reinstall frozen onsite algorithms",
                    "sources": "Selected files only; not complete upstream repos or an environment replica"}
        (args.stage / "RELEASE.json").write_text(json.dumps(metadata, indent=2) + "\n")
        (args.stage / "README.md").write_text(
            "# G5 baseline alignment 0.1.0\n\nRead docs/engineering/G5_LOCAL_BASELINE_ALIGNMENT_RESULT.md and "
            "patches/motor/G5_ALIGNMENT.md first. This bundle does not start services, rebuild dependencies or "
            "reinstall the existing 0.2.0 wheel. Use runtime fingerprint collection against the actual environment; "
            "the local checkout is not included.\n")
        contents = sorted(p for p in args.stage.rglob("*") if p.is_file())
        (args.stage / "MANIFEST.sha256").write_text("".join(
            hashlib.sha256(p.read_bytes()).hexdigest() + "  " + str(p.relative_to(args.stage)) + "\n" for p in contents))
    print(json.dumps({"name": NAME, "files": len(files), "stage": str(args.stage), "archive_created": False}))


if __name__ == "__main__":
    main()
