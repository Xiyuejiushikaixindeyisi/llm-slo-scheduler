#!/usr/bin/env python3
"""Build a source/patch/prompt bundle and pure Python wheel, never native Motor binaries."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
NAME = "fgjsq-motor-p-0.2.0-20261019"


def copy_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main():
    out = ROOT / "artifacts/releases"
    out.mkdir(parents=True, exist_ok=True)
    destination = out / NAME
    if destination.exists():
        raise SystemExit("Release directory exists; use a new release version rather than merge stale files")
    manifest = json.loads((ROOT / "evidence/manifests/g4_source_intake_20261019.json").read_text())
    for item in manifest["files"]:
        if hashlib.sha256((ROOT/item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit("Raw input changed: " + item["path"])
    with tempfile.TemporaryDirectory(prefix="release-stage-", dir=ROOT / "artifacts/build") as temporary:
        stage = Path(temporary) / NAME
        stage.mkdir()
        for folder in ("src", "tests", "patches/motor", "configs/baseline", "scripts/collect",
                       "scripts/deploy", "scripts/validate", "evidence/source_drops/proxy/g4-20261015",
                       "evidence/source_drops/slo_patch/g4-20261015"):
            for f in (ROOT/folder).rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                    copy_file(f, stage/f.relative_to(ROOT))
        for f in ("pyproject.toml", "THIRD_PARTY_NOTICES.md", "env/sources.lock.json", "env/delivery-target.json",
                  "env/onsite-g4-reported.json", "evidence/manifests/g4_source_intake_20261019.json",
                  "docs/engineering/FGJSQ_MOTOR_DELIVERY.md", "docs/engineering/FGJSQ_MOTOR_ADAPTATION_REVIEW.md",
                  "docs/engineering/HUAWEI_AGENT_PROMPT_FGJSQ_MOTOR.md"):
            copy_file(ROOT/f, stage/f)
        (stage/"README.md").write_text("# FGJSQ + predictor + Motor P-only release 0.2.0\n\n"
                                      "Read [delivery notes](docs/engineering/FGJSQ_MOTOR_DELIVERY.md) and "
                                      "[onsite agent prompt](docs/engineering/HUAWEI_AGENT_PROMPT_FGJSQ_MOTOR.md).\n\n"
                                      "Run sha256sum -c MANIFEST.sha256 before installation. "
                                      "The rc1 image and NPU chain have not been verified locally.\n")
        # Minimal pinned references for source porting and original-vs-patched CPU tests.
        motor_files = json.loads((ROOT/"patches/motor/f203263d-files.json").read_text())
        for f in motor_files:
            copy_file(ROOT/"upstream/motor"/f, stage/"upstream/motor"/f)
        for repo, relative in (("vllm-v0.23.0", "vllm/v1/engine/core.py"),
                               ("vllm-v0.23.0", "vllm/v1/core/sched/async_scheduler.py"),
                               ("vllm-ascend-v0.23.0", "vllm_ascend/core/recompute_scheduler.py")):
            copy_file(ROOT/"upstream"/repo/relative, stage/"upstream"/repo/relative)
        for repo in ("motor", "vllm-v0.23.0", "vllm-ascend-v0.23.0"):
            for f in (ROOT/"upstream"/repo).glob("LICENSE*"):
                if f.is_file():
                    copy_file(f, stage/"licenses"/(repo+"-"+f.name))
        notes = ROOT/"artifacts/build/motor/.agents/skills/motor-dev"
        for f in ("references/coordinator.md", "bug-fix-history/INDEX.md",
                  "bug-fix-history/coordinator/fgjsq-buffered-response-release.md"):
            copy_file(notes/f, stage/"development-notes"/f)
        for f in ("local-test-report.json", "fgjsq-tests.xml", "motor-regression.xml", "package-verification.json"):
            copy_file(ROOT/"artifacts"/f, stage/"validation"/f)
        (stage/"dist").mkdir()
        with (ROOT/"artifacts/wheel-build.log").open("w") as log:
            subprocess.run([sys.executable,"-m","pip","wheel",str(stage),"--no-deps","--no-build-isolation",
                            "--wheel-dir",str(stage/"dist")],stdout=log,stderr=subprocess.STDOUT,check=True)
        wheel = next((stage/"dist").glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            for f in ("fgjsq/policy.py", "motor_adapter/bindings.py", "slo_patch/engine_files.json"):
                assert f in names, f
            assert not any(n.endswith((".so", ".pyd")) for n in names)
            entry = next(n for n in names if n.endswith("entry_points.txt"))
            assert b"slo_patch = slo_patch.activate:activate" in archive.read(entry)
        # Remove wheel build intermediates, never mix them into the release.
        for f in (stage/"build", stage/"src/slo_patch.egg-info"):
            if f.exists():
                shutil.rmtree(f)
        metadata = {"name":NAME,"version":"0.2.0","target":json.loads((ROOT/"env/delivery-target.json").read_text()),
                    "local_validation":"validation/local-test-report.json","onsite_chain_passed":False,
                    "upstream_reference_scope":"selected source files only, not complete repositories"}
        (stage/"RELEASE.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n")
        contents = sorted(f for f in stage.rglob("*") if f.is_file())
        (stage/"MANIFEST.sha256").write_text("".join(hashlib.sha256(f.read_bytes()).hexdigest()+"  "+str(f.relative_to(stage))+"\n" for f in contents))
        shutil.move(stage, destination)
    archive = out/(NAME+".tar.gz")
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(destination, arcname=NAME)
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (out/(archive.name+".sha256")).write_text(digest+"  "+archive.name+"\n")
    print(json.dumps({"archive":str(archive),"bytes":archive.stat().st_size,"sha256":digest},indent=2))


if __name__ == "__main__":
    main()
