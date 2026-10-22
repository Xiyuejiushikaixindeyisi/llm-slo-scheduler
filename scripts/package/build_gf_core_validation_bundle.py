#!/usr/bin/env python3
"""Package the CPU-only milestone and its verification prompt; never deploy it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
NAME = "gf-admission-core-0.1.0.dev1-20261022"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New WSL build directory")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    build = output / "wheel-build"
    subprocess.run([sys.executable, str(ROOT / "scripts/package/build_gf_admission_core.py"),
                    "--output", str(build)], check=True)
    bundle = output / NAME
    bundle.mkdir()
    paths = list((ROOT / "src/gf_admission").glob("*.py"))
    paths += list((ROOT / "tests/fixtures/admission").glob("*"))
    paths += [ROOT / p for p in (
        "tests/unit/test_admission_core.py",
        "scripts/validate/verify_gf_core_bundle.py",
        "scripts/validate/benchmark_admission_containers.py",
        "docs/engineering/HUAWEI_AGENT_PROMPT_GF_CORE_20261022.md",
        "docs/engineering/GF_ADMISSION_IMPLEMENTATION_STATUS.md",
        "evidence/manifests/gf_admission_core_20261022.json")]
    for path in paths:
        target = bundle / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(build / "source/pyproject.toml", bundle / "pyproject.toml")
    shutil.copy2(ROOT / "packages/gf_admission/README.md", bundle / "README.md")
    (bundle / "wheels").mkdir()
    for wheel in (build / "wheels").glob("*.whl"):
        shutil.copy2(wheel, bundle / "wheels" / wheel.name)
    source_commit = subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", "src/gf_admission"], cwd=ROOT, text=True).strip()
    manifest = {"schema_version": 1, "name": NAME, "source_commit": source_commit,
                "scope": "offline CPU core validation only; no Motor activation",
                "tool_identity": "per-file SHA256; packaging tools may follow source commit",
                "files": {str(p.relative_to(bundle)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(bundle.rglob("*")) if p.is_file()}}
    (bundle / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    archive = output / (NAME + ".tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(bundle, arcname=NAME)
    # Test the extracted archive, not the source checkout or original stage.
    extracted = output / "extracted"
    extracted.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(extracted, filter="data")
    subprocess.run([sys.executable, str(extracted / NAME / "scripts/validate/verify_gf_core_bundle.py")],
                   cwd=extracted, check=True)
    print(json.dumps({"archive": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                      "extracted_validation": "passed"}, indent=2))


if __name__ == "__main__":
    main()
