#!/usr/bin/env python3
"""Rebuild local G5 Motor source without resetting other agents' work."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/build/motor-g5")
    parser.add_argument("--with-tests", action="store_true", help="Also apply regression tests and development notes")
    args = parser.parse_args()
    output = args.output.resolve()
    pin = next(r for r in json.loads((ROOT / "env/sources.lock.json").read_text())["repositories"]
               if r["id"] == "motor")["commit"]
    if not output.exists():
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--no-hardlinks", str(ROOT / "upstream/motor"), str(output)], check=True)
    observed = subprocess.check_output(["git", "-C", str(output), "rev-parse", "HEAD"], text=True).strip()
    if observed != pin:
        raise SystemExit("Motor HEAD differs; refusing to reset an existing checkout")
    subprocess.run([sys.executable, str(ROOT / "scripts/deploy/g5_motor_install.py"),
                    "--motor-root", str(output), "--target", "g5", "--action", "apply",
                    "--state-dir", str(output.parent / (output.name + "-install-state"))], check=True)
    if args.with_tests:
        for filename in ("f203263d-g5-tests.patch", "f203263d-g5-development-notes.patch"):
            patch = ROOT / "patches/motor" / filename
            reverse = subprocess.run(["git", "apply", "--reverse", "--check", str(patch)],
                                     cwd=output, capture_output=True)
            if reverse.returncode == 0:
                continue
            subprocess.run(["git", "apply", "--check", str(patch)], cwd=output, check=True)
            subprocess.run(["git", "apply", str(patch)], cwd=output, check=True)
    print(json.dumps({"motor_root": str(output), "base_commit": pin,
                      "scope": "CPU development source; not an onsite image replica"}))


if __name__ == "__main__":
    main()
