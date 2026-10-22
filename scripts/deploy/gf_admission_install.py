#!/usr/bin/env python3
"""Exact-file incremental installer. Run only against a stopped/drained target.

check is read-only; apply/rollback preserve a per-target journal and preimages.
Neither the plugin wheel nor engines/NodeManager are installed by this tool.
"""

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temp = tempfile.mkstemp(prefix=".gf-admission-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def plan(bundle, roots, action, state):
    manifest = json.loads((bundle / "runtime-manifest.json").read_text())
    changes = []
    for name, spec in manifest["changes"].items():
        root = roots[spec["root"]].resolve()
        path = (root / spec["relative"]).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("target path escapes root: " + name)
        current = path.read_bytes()
        observed = sha(current)
        if observed not in (spec["before"], spec["after"]):
            raise ValueError(
                "unknown target bytes; preserve onsite fix and review: " + str(path)
            )
        after = (bundle / "payload" / name).read_bytes()
        if sha(after) != spec["after"]:
            raise ValueError("payload checksum mismatch: " + name)
        compile(after, str(path), "exec")
        backup = state / "preimages" / name
        if action == "rollback":
            before = backup.read_bytes()
            if sha(before) != spec["before"]:
                raise ValueError("backup mismatch: " + name)
            desired = before
        else:
            desired = after
        changes.append((name, path, current, desired, backup, spec))
    observations = {}
    for name, spec in manifest["protected"].items():
        path = roots[spec["root"]] / spec["relative"]
        observed = sha(path.read_bytes())
        observations[name] = observed
        if not spec.get("observe_only") and observed != spec["sha256"]:
            raise ValueError("protected g5 dependency differs: " + str(path))
    return manifest, changes, observations


def install(bundle, roots, state, action):
    bundle, state = bundle.resolve(), state.resolve()
    manifest, changes, observations = plan(bundle, roots, action, state)
    identity = {name: str(path) for name, path, *_ in changes}
    report = {
        "version": manifest["version"],
        "action": action,
        "targets": identity,
        "files": {name: sha(current) for name, _, current, *_ in changes},
        "protected_observed": observations,
    }
    if action == "check":
        return report
    state.mkdir(parents=True, exist_ok=True)
    lock = state / "install.lock"
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    try:
        journal = state / "journal.json"
        if journal.exists():
            old = json.loads(journal.read_text())
            if old["targets"] != identity or old["version"] != manifest["version"]:
                raise ValueError("state directory belongs to another target/version")
        elif action == "rollback":
            raise ValueError("rollback requires original installation journal")
        # Prepare every backup before changing any live file.
        for name, path, current, desired, backup, spec in changes:
            if backup.exists():
                if sha(backup.read_bytes()) != spec["before"]:
                    raise ValueError("backup mismatch: " + name)
            elif sha(current) == spec["before"] and action == "apply":
                backup.parent.mkdir(parents=True, exist_ok=True)
                atomic(backup, current)
            else:
                raise ValueError(
                    "missing preimage; refusing untracked applied files: " + name
                )
        report["status"] = "prepared"
        atomic(journal, (json.dumps(report, indent=2) + "\n").encode())
        # Recheck all files after locking/preparing; no overwrite of concurrent edits.
        for name, path, current, *_ in changes:
            if path.read_bytes() != current:
                raise ValueError("concurrent target edit: " + name)
        for name, path, current, desired, *_ in changes:
            if current != desired:
                atomic(path, desired)
        report["status"] = "complete"
        report["files"] = {name: sha(path.read_bytes()) for name, path, *_ in changes}
        atomic(journal, (json.dumps(report, indent=2) + "\n").encode())
        return report
    finally:
        lock.unlink()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument(
        "--motor-root", type=Path, required=True, help="directory containing motor/"
    )
    p.add_argument(
        "--adapter-root",
        type=Path,
        required=True,
        help="directory containing motor_adapter/, fgjsq/, slo_patch/",
    )
    p.add_argument("--state-dir", type=Path, required=True)
    p.add_argument("--action", choices=["check", "apply", "rollback"], default="check")
    args = p.parse_args()
    print(
        json.dumps(
            install(
                args.bundle,
                {"motor": args.motor_root, "adapter": args.adapter_root},
                args.state_dir,
                args.action,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
