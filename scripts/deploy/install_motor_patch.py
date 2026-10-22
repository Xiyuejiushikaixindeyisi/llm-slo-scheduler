#!/usr/bin/env python3
"""Check/apply/revert exact Motor files, preserving a verified backup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--motor-root", type=Path, required=True, help="directory containing motor/")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--action", choices=("check", "apply", "revert"), default="check")
    args = parser.parse_args()
    root = args.motor_root.resolve()
    # An installed package can sit inside an unrelated parent Git workspace.
    # Prevent git apply from silently skipping patches outside that repo's cwd prefix.
    git_env = dict(os.environ)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        git_env.pop(key, None)
    git_env["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    release = Path(__file__).resolve().parents[2]
    manifest = json.loads((release / "patches/motor/f203263d-files.json").read_text())
    expected_key = "after" if args.action == "revert" else "before"
    mismatches = [p for p, value in manifest.items() if not (root/p).is_file() or digest(root/p) != value[expected_key]]
    if mismatches:
        raise SystemExit("Version mismatch; no files changed: " + ", ".join(mismatches))
    patch = release / "patches/motor/f203263d-p-fgjsq.patch"
    if args.action == "check":
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=root, env=git_env, check=True)
        print("Exact Motor target files match; patch check passed.")
        return
    if args.action == "apply":
        if args.state_dir.exists():
            raise SystemExit("State directory exists; choose a new directory, do not overwrite rollback evidence")
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=root, env=git_env, check=True)
        args.state_dir.mkdir(parents=True)
        for p in manifest:
            target = args.state_dir / p
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / p, target)
        (args.state_dir / "manifest.json").write_text(json.dumps({"motor_root": str(root), "files": manifest}, indent=2))
        subprocess.run(["git", "apply", str(patch)], cwd=root, env=git_env, check=True)
        if any(digest(root / p) != entry["after"] for p, entry in manifest.items()):
            raise SystemExit("Post-apply hash mismatch; restore backup before launching")
        print("Applied and verified Motor patch; install the Python package before starting Coordinator.")
    else:
        backup = json.loads((args.state_dir / "manifest.json").read_text())
        if backup["motor_root"] != str(root):
            raise SystemExit("Backup belongs to another Motor root")
        if any(not (args.state_dir / p).is_file() or digest(args.state_dir / p) != entry["before"]
               for p, entry in manifest.items()):
            raise SystemExit("Backup integrity mismatch")
        for p in manifest:
            shutil.copy2(args.state_dir / p, root / p)
        print("Restored exact baseline Motor files. Restart drained experimental processes.")


if __name__ == "__main__":
    main()
