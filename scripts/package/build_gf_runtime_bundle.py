#!/usr/bin/env python3
"""Build a source-audited runtime candidate; no native library or engine wheel."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copytree(source, target):
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.so",
            ".pytest_cache",
            ".git",
            "*.egg-info",
            "target",
            "lib",
        ),
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stage = out / "gf-admission-0.1.0rc2"
    stage.mkdir()
    contract = json.loads((ROOT / "src/gf_admission/runtime_contract.json").read_text())
    (stage / "runtime-manifest.json").write_text(json.dumps(contract, indent=2) + "\n")
    motor = ROOT / "artifacts/build/motor-g5"
    for name, item in contract["changes"].items():
        source = (ROOT / "src" if item["root"] == "adapter" else motor) / item[
            "relative"
        ]
        if digest(source) != item["after"]:
            raise RuntimeError("contract stale: " + name)
        dest = stage / "payload" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    for name in (
        "src/gf_admission",
        "src/fgjsq",
        "src/motor_adapter",
        "src/slo_patch",
        "tests",
        "configs/gf_admission",
        "patches/motor",
        "patches/gf_admission",
        "scripts/experiments",
    ):
        copytree(ROOT / name, stage / name)
    copytree(
        motor / ".agents/skills/motor-dev",
        stage / "reference-motor/.agents/skills/motor-dev",
    )
    shutil.copy2(motor / "AGENTS.md", stage / "reference-motor/AGENTS.md")
    for name in ("motor", "tests", "scripts"):
        copytree(motor / name, stage / "reference-motor" / name)
    for name in ("requirements.txt", "pyproject.toml", "setup.cfg"):
        if (motor / name).is_file():
            shutil.copy2(motor / name, stage / "reference-motor" / name)
    files = (
        "scripts/deploy/gf_admission_install.py",
        "scripts/validate/verify_gf_runtime_bundle.py",
        "scripts/validate/run_gf_runtime_tests.sh",
        "scripts/validate/smoke.py",
        "docs/engineering/GF_ADMISSION_RUNTIME_GUIDE.md",
        "docs/engineering/GF_ADMISSION_IMPLEMENTATION_STATUS.md",
        "docs/engineering/GF_ADMISSION_RC2_REPAIR_REPORT_20261022.md",
        "docs/admission/GF_PRESSURE_ADMISSION_REVISION_20261022.md",
        "experiments/plans/GF_ADMISSION_RC2_AISBENCH_20261022.json",
        "packages/gf_admission/pyproject.toml",
        "scripts/package/build_gf_runtime_bundle.py",
        "scripts/dev/refresh_gf_contract.py",
        "docs/engineering/HUAWEI_AGENT_PROMPT_GF_RUNTIME.md",
        "docs/admission/G5_GF_DUAL_QUEUE_IMPLEMENTATION_DESIGN.md",
        "docs/admission/GF_SUPER_P95_DESIGN_DISCUSSION.md",
        "env/g5-baseline-files.json",
        "pyproject.toml",
    )
    for name in files:
        source = ROOT / name
        if not source.is_file():
            if name.endswith("GF_SUPER_P95_REFERENCE_REPRODUCTION.md"):
                continue
            raise FileNotFoundError(source)
        dest = stage / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    for name in (
        "project.xml",
        "motor.xml",
        "project-tests.log",
        "motor-tests.log",
        "ruff.log",
        "extracted-tests.log",
        "extracted-initial-failure.log",
        "wheel-check.log",
        "control_microbench.py",
        "control_microbench.json",
    ):
        source = ROOT / "artifacts/gf-admission-rc2" / name
        dest = stage / "evidence/local" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    source = ROOT / "evidence/manifests/gf_admission_rc2_20261022.json"
    shutil.copy2(source, stage / "evidence/local/summary.json")
    # Source-delta evidence records the working checkout without staging others' edits.
    (stage / "evidence/local/working-tree-status.txt").write_bytes(
        subprocess.check_output(["git", "status", "--short"], cwd=ROOT)
    )
    (stage / "evidence/local/rc1-to-rc2.patch").write_bytes(
        subprocess.check_output(
            [
                "git",
                "diff",
                "0bb3e40",
                "--",
                "src/gf_admission",
                "src/motor_adapter/bindings.py",
                "configs/gf_admission",
                "packages/gf_admission",
                "tests/unit/test_admission_broker.py",
                "tests/unit/test_admission_core.py",
                "tests/integration/test_admission_runtime.py",
            ],
            cwd=ROOT,
        )
    )
    # Include tool fixtures needed by existing project regression tests.
    for folder in ("scripts/deploy", "scripts/collect", "scripts/validate"):
        for source in (ROOT / folder).glob("*.py"):
            dest = stage / folder / source.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    source = out / "wheel-source"
    copytree(ROOT / "src/gf_admission", source / "src/gf_admission")
    (source / "pyproject.toml").write_text(
        (ROOT / "packages/gf_admission/pyproject.toml")
        .read_text()
        .replace('"../../src"', '"src"')
    )
    (stage / "wheels").mkdir()
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            str(source),
            "--wheel-dir",
            str(stage / "wheels"),
        ],
        check=True,
        env=dict(os.environ, PIP_NO_INDEX="1", SOURCE_DATE_EPOCH="1792627200"),
    )
    (wheel,) = list((stage / "wheels").glob("*.whl"))
    with zipfile.ZipFile(wheel) as z:
        assert "gf_admission/runtime_contract.json" in z.namelist()
        assert all(
            n.startswith(("gf_admission/", "gf_admission-")) for n in z.namelist()
        )
        assert not any(n.endswith(("entry_points.txt", ".so")) for n in z.namelist())
    names = {
        str(p.relative_to(stage)): digest(p)
        for p in sorted(stage.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "schema_version": 1,
        "version": contract["version"],
        "files": names,
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_identity": "SHA256 is authoritative; includes current working source",
        "npu_tested": False,
        "aisbench_tested": False,
        "session2_review_pending": True,
    }
    (stage / "SHA256.json").write_text(json.dumps(manifest, indent=2) + "\n")
    subprocess.run(
        [
            sys.executable,
            str(stage / "scripts/validate/verify_gf_runtime_bundle.py"),
            str(stage),
        ],
        check=True,
    )
    archive = out / "gf-admission-0.1.0rc2-20261022.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(stage, arcname=stage.name)
    print(
        json.dumps(
            {"archive": str(archive), "sha256": digest(archive), "files": len(names)}
        )
    )


if __name__ == "__main__":
    main()
