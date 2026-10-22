#!/usr/bin/env python3
"""Verify an extracted gf-admission CORE bundle without changing installed packages."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "MANIFEST.json").read_text())
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise SystemExit("Missing or invalid bundle path: " + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit("SHA256 mismatch: " + name)
    result = {"python": platform.python_version(), "machine": platform.machine(),
              "source_commit": manifest["source_commit"], "integrity": "passed",
              "runtime_admission": "not implemented", "npu_performance": "not tested"}
    out = root / "validation-output"
    out.mkdir(exist_ok=True)
    wheel, = (root / "wheels").glob("*.whl")
    code = """import sys
sys.path.insert(0, sys.argv[1])
import gf_admission
from gf_admission.queue import DualQueueStore
from gf_admission.config import QueueLimits
q = DualQueueStore(QueueLimits(2, 2, 10, 10, 2, 8), lambda: 0)
q.add('one', 1, tail=True)
q.add('two', 2, tail=True)
assert q.candidates()[0].key == 'two'
assert q.promote(max_items=1, force=True) == ('one',)
assert q.candidates()[0].protected
assert not any(k in sys.modules for k in ('motor', 'torch', 'vllm', 'httpx'))
print(gf_admission.__version__, gf_admission.__file__)
"""
    smoke = subprocess.run([sys.executable, "-I", "-S", "-c", code, str(wheel)],
                           capture_output=True, text=True)
    (out / "wheel-smoke.log").write_text(smoke.stdout + smoke.stderr)
    result["wheel_smoke"] = "passed" if smoke.returncode == 0 else "failed"
    env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    test = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/unit/test_admission_core.py",
                           "--junitxml=" + str(out / "core.xml")], cwd=root,
                          env=env, capture_output=True, text=True)
    (out / "core-tests.log").write_text(test.stdout + test.stderr)
    result["tests_exit_code"] = test.returncode
    result["tests"] = "passed" if test.returncode == 0 else "failed_or_dependency_missing"
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(test.stdout + test.stderr)
    print(json.dumps(result, indent=2))
    return int(smoke.returncode != 0 or test.returncode != 0)


if __name__ == "__main__":
    raise SystemExit(main())
