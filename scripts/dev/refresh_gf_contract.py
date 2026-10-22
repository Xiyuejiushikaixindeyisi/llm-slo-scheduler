#!/usr/bin/env python3
"""Generate the explicit four-file delta against frozen g5, never reset source."""

import difflib
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "3b63b00546e7a6ffb2526dafc341969cebe22359"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    baseline = json.loads((ROOT / "env/g5-baseline-files.json").read_text())
    motor = ROOT / baseline["motor_checkout"]
    contract = {
        "schema_version": 1,
        "version": "0.1.0rc2",
        "baseline_commit": BASE,
        "changes": {},
        "protected": {},
    }
    patches = {"motor": [], "adapter": []}
    for relative in ("motor_adapter/bindings.py", "motor_adapter/service.py"):
        name = "src/" + relative
        before = subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT)
        after = (ROOT / name).read_bytes()
        assert sha(before) == baseline["core_files"][name]
        contract["changes"][name] = {
            "root": "adapter",
            "relative": relative,
            "before": sha(before),
            "after": sha(after),
        }
        patches["adapter"].extend(
            difflib.unified_diff(
                before.decode().splitlines(True),
                after.decode().splitlines(True),
                fromfile="a/" + name,
                tofile="b/" + name,
            )
        )
    for relative, removals in {
        "motor/coordinator/scheduler/runtime/scheduler_client.py": [
            "            await fgjsq_hooks.start_admission_client(self)\n",
            "        await fgjsq_hooks.close_admission_client(self)\n",
        ],
        "motor/coordinator/scheduler/runtime/scheduler_server.py": [
            "        if self._dispatcher is not None:\n            await fgjsq_hooks.close_admission_dispatcher(self._dispatcher)\n"
        ],
    }.items():
        after = (motor / relative).read_bytes()
        before = after.decode()
        for line in removals:
            assert before.count(line) == 1, relative
            before = before.replace(line, "", 1)
        before = before.encode()
        assert sha(before) == baseline["motor_patch_files"][relative]["after"], relative
        contract["changes"][relative] = {
            "root": "motor",
            "relative": relative,
            "before": sha(before),
            "after": sha(after),
        }
        patches["motor"].extend(
            difflib.unified_diff(
                before.decode().splitlines(True),
                after.decode().splitlines(True),
                fromfile="a/" + relative,
                tofile="b/" + relative,
            )
        )
    for name, expected in baseline["core_files"].items():
        if name not in contract["changes"]:
            contract["protected"][name] = {
                "root": "adapter",
                "relative": name.removeprefix("src/"),
                "sha256": expected,
                "observe_only": name.endswith("engine_files.json"),
            }
    for name, item in {
        **baseline["motor_patch_files"],
        **baseline["node_manager_fix"],
    }.items():
        if name not in contract["changes"]:
            contract["protected"][name] = {
                "root": "motor",
                "relative": name,
                "sha256": item["after"],
                "observe_only": name in baseline["node_manager_fix"],
            }
    (ROOT / "src/gf_admission/runtime_contract.json").write_text(
        json.dumps(contract, indent=2) + "\n"
    )
    for kind, lines in patches.items():
        target = ROOT / "patches" / ("motor" if kind == "motor" else "gf_admission")
        target.mkdir(parents=True, exist_ok=True)
        (target / "g5-gf-admission-0.1.0rc2.patch").write_text("".join(lines))
    print("Four-file runtime contract refreshed; protected baselines remain immutable.")


if __name__ == "__main__":
    main()
