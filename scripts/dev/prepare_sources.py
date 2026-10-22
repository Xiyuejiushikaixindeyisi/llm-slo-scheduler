#!/usr/bin/env python3
"""Check pinned upstreams; --fetch retrieves only missing repositories, never resets existing work."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def verify(path, commit):
    actual = git(path, "rev-parse", "HEAD")
    if actual != commit:
        raise ValueError(f"{path}: expected {commit}, observed {actual}; existing checkout preserved")
    if git(path, "status", "--porcelain"):
        raise ValueError(f"{path}: local changes found; existing checkout preserved")


def prepare(repo, fetch=False, root=ROOT):
    path = (root / repo["path"]).resolve()
    upstream = (root / "upstream").resolve()
    if not path.is_relative_to(upstream) or path == upstream:
        raise ValueError("Source path must be below upstream/")
    if not path.exists():
        if not fetch:
            raise ValueError(f"Missing {path}; use --fetch to retrieve its pinned public commit")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".fetch-", dir=path.parent) as tmp:
            staged = Path(tmp) / "repo"
            subprocess.run(["git", "init", "--quiet", str(staged)], check=True)
            git(staged, "remote", "add", "origin", repo["url"])
            git(staged, "fetch", "--depth=1", "origin", repo["commit"])
            git(staged, "checkout", "--detach", "FETCH_HEAD")
            verify(staged, repo["commit"])
            staged.rename(path)
    verify(path, repo["commit"])
    return {"id": repo["id"], "path": str(path), "commit": repo["commit"], "clean": True}


def main():
    repos = json.loads((ROOT / "env/sources.lock.json").read_text())["repositories"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", action="append", choices=[r["id"] for r in repos],
                        help="Repeat to select sources; defaults to Motor, vLLM and Ascend")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    selected = args.repo or ["motor", "vllm", "vllm-ascend"]
    try:
        results = [prepare(r, args.fetch) for r in repos if r["id"] in selected]
    except (ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
