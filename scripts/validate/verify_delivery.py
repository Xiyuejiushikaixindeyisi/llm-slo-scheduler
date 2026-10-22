#!/usr/bin/env python3
"""CPU-only package checks and Motor apply/revert round trip in an isolated directory."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root/"patches/motor/f203263d-files.json").read_text())
    parsed = 0
    for folder in ("src", "scripts", "tests"):
        for p in (root/folder).rglob("*.py"):
            ast.parse(p.read_text(), filename=str(p))
            parsed += 1
    build = root/"artifacts/build"
    build.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-roundtrip-", dir=build) as directory:
        work=Path(directory)/"motor-parent"
        for relative in manifest:
            p=work/relative
            p.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(root/"upstream/motor"/relative,p)
        command=[sys.executable,str(root/"scripts/deploy/install_motor_patch.py"),"--motor-root",str(work),
                 "--state-dir",str(Path(directory)/"backup")]
        for action in ("check","apply","revert"):
            result=subprocess.run(command+["--action",action],capture_output=True,text=True)
            if result.returncode:
                raise RuntimeError(result.stdout+result.stderr)
        for relative,entry in manifest.items():
            assert hashlib.sha256((work/relative).read_bytes()).hexdigest()==entry["before"]
        first=work/next(iter(manifest))
        first.write_bytes(first.read_bytes()+b"\n# deliberate mismatch\n")
        original={relative:(work/relative).read_bytes() for relative in manifest}
        result=subprocess.run(command+["--action","apply"],capture_output=True,text=True)
        assert result.returncode != 0 and "Version mismatch" in result.stdout+result.stderr
        assert all((work/relative).read_bytes()==data for relative,data in original.items())
    legacy=root/"evidence/source_drops/slo_patch/g4-20261015/slo_patch/slo"
    unchanged=[]
    for name in ("predictor.py","predictor_impl.py","batch_reporter.py"):
        assert (legacy/name).read_bytes()==(root/"src/slo_patch/slo"/name).read_bytes()
        unchanged.append(name)
    result={"syntax_files":parsed,"motor_install_apply_revert":"passed outside Git repository",
            "unknown_source_rejection":"passed without modifying files","legacy_bytes_preserved":unchanged,
            "native_npu_validation":False}
    (root/"artifacts/package-verification.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
