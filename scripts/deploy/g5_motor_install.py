#!/usr/bin/env python3
"""Install missing exact Motor patches; rollback owns only this transaction."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PATCHES = {
    "fgjsq": ("f203263d-files.json", "f203263d-p-fgjsq.patch"),
    "node-manager": ("f203263d-g5-node-manager-files.json", "f203263d-g5-node-manager-lookup.patch"),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_target(root, components):
    result = {}
    for component in components:
        manifest_name, patch_name = PATCHES[component]
        files = json.loads((ROOT / "patches/motor" / manifest_name).read_text())
        states = {}
        for name, hashes in files.items():
            path = root / name
            sha = digest(path) if path.is_file() else None
            states[name] = {"sha256": sha, "state": next(
                (s for s in ("before", "after") if sha == hashes[s]), "unknown")}
        values = {v["state"] for v in states.values()}
        state = next(iter(values)) if len(values) == 1 else "mixed"
        result[component] = {"state": state, "files": files, "observed": states,
                             "patch": ROOT / "patches/motor" / patch_name}
    return result


def git_apply(root, patch, check=False):
    env = dict(os.environ)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    env["GIT_CEILING_DIRECTORIES"] = str(root.parent)
    subprocess.run(["git", "apply", *(["--check"] if check else []), str(patch)],
                   cwd=root, env=env, check=True)


def revert(root, state_dir):
    saved = json.loads((state_dir / "manifest.json").read_text())
    if saved["motor_root"] != str(root):
        raise ValueError("Backup belongs to another Motor root")
    files = saved["files"]
    for name, hashes in files.items():
        if digest(state_dir / name) != hashes["before"]:
            raise ValueError("Backup integrity mismatch: " + name)
        if digest(root / name) != hashes["after"]:
            raise ValueError("Target changed since installation: " + name)
    for name in files:
        shutil.copy2(state_dir / name, root / name)
    print(json.dumps({"status": "reverted", "files": list(files)}))


def install(root, state_dir, target="g5", action="check"):
    if action == "revert":
        if state_dir is None:
            raise ValueError("--state-dir is required for revert")
        return revert(root, state_dir)
    components = ["fgjsq", "node-manager"] if target == "g5" else ["fgjsq"]
    inspected = inspect_target(root, components)
    states = {k: v["state"] for k, v in inspected.items()}
    unknown = [k for k, v in inspected.items() if v["state"] not in ("before", "after")]
    if unknown:
        raise ValueError("Version mismatch; no files changed: " + ", ".join(unknown) +
                         ". Collect the full file/diff; never replace a different onsite fix automatically.")
    missing = [v for v in inspected.values() if v["state"] == "before"]
    for component in missing:
        git_apply(root, component["patch"], check=True)
    if action == "check" or not missing:
        print(json.dumps({"status": "already_aligned" if not missing else "applicable", "components": states}))
        return
    if state_dir is None or state_dir.exists():
        raise ValueError("A new --state-dir is required; do not overwrite rollback evidence")
    state_dir.mkdir(parents=True)
    changed = {name: hashes for component in missing for name, hashes in component["files"].items()}
    for name in changed:
        backup = state_dir / name
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, backup)
    record = {"schema_version": 2, "motor_root": str(root), "files": changed,
              "initial_states": states, "status": "prepared"}
    manifest_path = state_dir / "manifest.json"
    manifest_path.write_text(json.dumps(record, indent=2) + "\n")
    try:
        for component in missing:
            git_apply(root, component["patch"])
        if any(digest(root / name) != hashes["after"] for name, hashes in changed.items()):
            raise ValueError("Post-apply hash mismatch")
    except BaseException:
        for name in changed:
            shutil.copy2(state_dir / name, root / name)
        record["status"] = "rolled_back_after_error"
        manifest_path.write_text(json.dumps(record, indent=2) + "\n")
        raise
    record["status"] = "applied"
    manifest_path.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"status": "applied", "files": list(changed), "initial_states": states}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motor-root", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--target", choices=("g5", "fgjsq"), default="g5")
    parser.add_argument("--action", choices=("check", "apply", "revert"), default="check")
    args = parser.parse_args()
    try:
        install(args.motor_root.resolve(), args.state_dir.resolve() if args.state_dir else None,
                args.target, args.action)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
