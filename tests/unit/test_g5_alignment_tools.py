"""Protect G5 overlay ownership, refusal on drift, and reasoning-only smoke responses."""
import asyncio
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load_tool(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load_tool("g5_installer", "scripts/deploy/g5_motor_install.py")
smoke = load_tool("g5_smoke", "scripts/validate/smoke.py")


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "motor"
    for manifest, _ in installer.PATCHES.values():
        for name in json.loads((ROOT / "patches/motor" / manifest).read_text()):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "upstream/motor" / name, target)
    return root


def states(root):
    return {k: v["state"] for k, v in installer.inspect_target(root, installer.PATCHES).items()}


@pytest.mark.parametrize("existing", [None, "fgjsq", "node-manager"])
def test_apply_idempotence_and_revert_own_only_new_changes(source, tmp_path, existing):
    if existing:
        installer.git_apply(source, ROOT / "patches/motor" / installer.PATCHES[existing][1])
    initial = states(source)
    backup = tmp_path / "backup"
    installer.install(source, backup, action="apply")
    assert set(states(source).values()) == {"after"}
    saved = (backup / "manifest.json").read_bytes()
    installer.install(source, backup, action="apply")
    assert (backup / "manifest.json").read_bytes() == saved
    installer.install(source, backup, action="revert")
    assert states(source) == initial


def test_unknown_file_refuses_all_mutation(source, tmp_path):
    (source / "motor/config/node_manager.py").write_text("onsite custom fix\n")
    initial = {p: p.read_bytes() for p in source.rglob("*.py")}
    with pytest.raises(ValueError, match="Version mismatch"):
        installer.install(source, tmp_path / "backup", action="apply")
    assert not (tmp_path / "backup").exists()
    assert all(p.read_bytes() == data for p, data in initial.items())


def test_failed_second_patch_rolls_back_first(source, tmp_path, monkeypatch):
    original = installer.git_apply
    def injected(root, patch, check=False):
        if not check and "lookup" in patch.name:
            raise RuntimeError("injected second patch failure")
        return original(root, patch, check)
    monkeypatch.setattr(installer, "git_apply", injected)
    with pytest.raises(RuntimeError, match="injected"):
        installer.install(source, tmp_path / "backup", action="apply")
    assert set(states(source).values()) == {"before"}


def test_revert_refuses_to_destroy_later_research_edit(source, tmp_path):
    backup = tmp_path / "backup"
    installer.install(source, backup, action="apply")
    changed = source / "motor/config/node_manager.py"
    changed.write_bytes(changed.read_bytes() + b"\n# subsequent research edit\n")
    initial = {p: p.read_bytes() for p in source.rglob("*.py")}
    with pytest.raises(ValueError, match="Target changed"):
        installer.install(source, backup, action="revert")
    assert all(p.read_bytes() == data for p, data in initial.items())


@pytest.mark.parametrize("field", ["content", "reasoning", "reasoning_content"])
def test_smoke_accepts_each_output_field_and_checks_release(field, tmp_path, monkeypatch):
    polls = 0
    def handler(request):
        nonlocal polls
        if request.method == "GET":
            polls += 1
            return httpx.Response(200, json={"open_fg": 0, "open_native": 0, "metrics": {"matched": polls - 1}})
        packet = {"choices": [{"delta": {field: "hello"}}]}
        return httpx.Response(200, text="data: " + json.dumps(packet) + "\n\ndata: [DONE]\n\n")
    original_client = httpx.AsyncClient
    monkeypatch.setattr(smoke.httpx, "AsyncClient", lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    args = SimpleNamespace(mgmt="http://mgmt", url="http://coordinator", model="test", prompt="test",
                           concurrency=1, output=tmp_path / "smoke.json")
    assert asyncio.run(smoke.run(args)) == 0
    report = json.loads(args.output.read_text())
    assert report["requests"][0]["output_chars"] == 5
    assert report["requests"][0]["first_content_s"] is not None
