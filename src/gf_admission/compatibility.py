"""Enabled-mode source contract. Off mode never imports this module."""

import hashlib
import importlib.util
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def validate_runtime():
    contract = json.loads(Path(__file__).with_name("runtime_contract.json").read_text())
    roots = {}
    for name, package in (("motor", "motor"), ("adapter", "motor_adapter")):
        spec = importlib.util.find_spec(package)
        if spec is None or not spec.submodule_search_locations:
            raise RuntimeError("admission requires installed " + package)
        roots[name] = Path(next(iter(spec.submodule_search_locations))).parent
    for name, item in {**contract["protected"], **contract["changes"]}.items():
        if item.get("observe_only"):
            continue
        path = roots[item["root"]] / item["relative"]
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = item.get("after", item.get("sha256"))
        if observed != expected:
            raise RuntimeError("admission source contract mismatch: " + name)
    return contract["version"]
