#!/usr/bin/env python3
"""Read-only, selected-source inventory for the target container; never loads weights."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import platform
from pathlib import Path
import shutil
import subprocess


def package_root(name):
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    return Path(next(iter(spec.submodule_search_locations))).resolve()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-archive", help="Actual archive name if known; no inferred default")
    parser.add_argument("--image", help="Actual running image identity if known")
    parser.add_argument("--include-source", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    release = Path(__file__).resolve().parents[2]
    manifest = json.loads((release / "patches/motor/f203263d-files.json").read_text())
    manifest.update(json.loads((release / "patches/motor/f203263d-g5-node-manager-files.json").read_text()))
    engine = json.loads((release / "src/slo_patch/engine_files.json").read_text())
    info = {"image_archive_reported": args.image_archive, "image_reported": args.image,
            "baseline_reference": json.loads((release / "env/delivery-target.json").read_text())["effective_image"],
            "node_manager_hash_note": "Local reconstruction hash; a different onsite fix is not proof of a semantic regression.",
            "python": platform.python_version(),
            "machine": platform.machine(), "platform": platform.platform(), "packages": {}, "files": {}}
    for name in ("motor", "vllm", "vllm-ascend", "torch", "torch-npu", "mooncake-transfer-engine",
                 "numpy", "pandas", "scipy", "lightgbm", "scikit-learn", "httpx", "pyOpenSSL", "kubernetes", "watchdog"):
        try:
            info["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            info["packages"][name] = None
    targets = {path: ("motor", path.removeprefix("motor/"), value["before"], value["after"])
               for path, value in manifest.items()}
    for name, sha in json.loads((release / "env/g5-baseline-files.json").read_text())["core_files"].items():
        top, relative = name.removeprefix("src/").split("/", 1)
        targets[name] = (top, relative, sha, sha)
    for module, sha in engine.items():
        top, rest = module.split(".", 1)
        targets[module.replace(".", "/") + ".py"] = (top, rest.replace(".", "/") + ".py", sha, sha)
    for label, (top, relative, before, after) in targets.items():
        root = package_root(top)
        path = root / relative if root else None
        if path is None or not path.is_file():
            info["files"][label] = {"status": "missing", "path": str(path)}
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        info["files"][label] = {"path": str(path), "sha256": digest,
                               "status": "baseline" if digest == before else "patched" if digest == after else "mismatch"}
        if args.include_source:
            dest = args.output / "selected_sources" / label
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
    for name in ("motor", "vllm", "vllm_ascend"):
        root = package_root(name)
        if root and shutil.which("git"):
            result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
            info.setdefault("git_commits", {})[name] = result.stdout.strip() if result.returncode == 0 else None
    (args.output / "runtime.json").write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "status_counts":
                     {s: sum(x["status"] == s for x in info["files"].values())
                      for s in ("baseline", "patched", "mismatch", "missing")}}, indent=2))


if __name__ == "__main__":
    main()
