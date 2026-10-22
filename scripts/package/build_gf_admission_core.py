#!/usr/bin/env python3
"""Build an isolated, reproducible-source development wheel, not a runtime release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    (source / "src/gf_admission").mkdir(parents=True)
    for path in sorted((ROOT / "src/gf_admission").glob("*.py")):
        shutil.copy2(path, source / "src/gf_admission" / path.name)
    config = (ROOT / "packages/gf_admission/pyproject.toml").read_text()
    (source / "pyproject.toml").write_text(config.replace('"../../src"', '"src"'))
    shutil.copy2(ROOT / "packages/gf_admission/README.md", source / "README.md")
    # The stage is standalone; no absolute imports or source paths are embedded.
    env = dict(os.environ, PIP_NO_INDEX="1", SOURCE_DATE_EPOCH="1792627200")
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
                    "--no-index", str(source), "--wheel-dir", str(output / "wheels")], env=env, check=True)
    wheel, = (output / "wheels").glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        unexpected = [n for n in archive.namelist()
                      if not (n.startswith("gf_admission/") or n.startswith("gf_admission-"))]
        if unexpected or any(n.endswith("entry_points.txt") for n in archive.namelist()):
            raise RuntimeError("unexpected wheel contents or plugin entrypoint")
    check = """import sys
sys.path.insert(0, sys.argv[1])
import gf_admission
from gf_admission.queue import DualQueueStore
from gf_admission.config import QueueLimits
q = DualQueueStore(QueueLimits(1, 1, 1, 1, 1, 8), lambda: 0)
q.add('x', 1, tail=True)
assert q.remove('x').key == 'x'
assert not any(x in sys.modules for x in ('motor', 'torch', 'vllm', 'httpx'))
print(gf_admission.__version__, gf_admission.__file__)
"""
    subprocess.run([sys.executable, "-I", "-S", "-c", check, str(wheel)], cwd=output, check=True)
    files = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(output.rglob("*")) if p.is_file() and "/build/" not in str(p)
             and ".egg-info/" not in str(p)}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = {"schema_version": 1, "kind": "development_core_only", "source_base_commit": commit,
                "source_identity": "file SHA256 (includes uncommitted source)", "files": files,
                "runtime_activation": False, "npu_tested": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(output / "manifest.json")


if __name__ == "__main__":
    main()
