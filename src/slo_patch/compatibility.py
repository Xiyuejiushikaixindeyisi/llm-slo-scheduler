"""Refuse to replace EngineCore methods on an unverified runtime."""
import hashlib
import importlib.util
import json
from pathlib import Path


def verify_engine() -> dict:
    expected = json.loads(Path(__file__).with_name("engine_files.json").read_text())
    observed = {}
    for module, digest in expected.items():
        spec = importlib.util.find_spec(module)
        if spec is None or spec.origin is None:
            raise RuntimeError("Missing engine module: " + module)
        actual = hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest()
        observed[module] = actual
        if actual != digest:
            raise RuntimeError("Engine compatibility mismatch for " + module +
                               "; collect runtime evidence and port/revalidate the overlay before launch")
    return observed
