"""Whole-delta refusal, exact rollback and protected onsite adaptation checks."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "gf_installer", ROOT / "scripts/deploy/gf_admission_install.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


@pytest.fixture
def prepared(tmp_path):
    contract = json.loads((ROOT / "src/gf_admission/runtime_contract.json").read_text())
    motor = ROOT / "reference-motor"
    if not motor.exists():
        motor = ROOT / "artifacts/build/motor-g5"
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "runtime-manifest.json").write_text(json.dumps(contract))
    target = tmp_path / "target"
    roots = {"motor": target, "adapter": target / "src"}
    for name, item in {**contract["changes"], **contract["protected"]}.items():
        source = (ROOT / "src" if item["root"] == "adapter" else motor) / item[
            "relative"
        ]
        dest = roots[item["root"]] / item["relative"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        if name in contract["changes"]:
            dest = bundle / "payload" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    for folder in ("motor", "gf_admission"):
        subprocess.run(
            [
                "git",
                "apply",
                "--reverse",
                str(ROOT / "patches" / folder / "g5-gf-admission-0.1.0rc1.patch"),
            ],
            cwd=target,
            check=True,
        )
    # Deliberately different field adaptations must survive byte-for-byte.
    for name, item in contract["protected"].items():
        if item.get("observe_only"):
            (roots[item["root"]] / item["relative"]).write_bytes(
                b"onsite-specific-preserve\n"
            )
    return bundle, roots, tmp_path / "state", contract


def test_installer_apply_twice_rollback_twice_preserves_field_adaptations(prepared):
    bundle, roots, state, contract = prepared
    before = {
        str(p): p.read_bytes()
        for root in [roots["motor"]]
        for p in root.rglob("*")
        if p.is_file()
    }
    installer.install(bundle, roots, state, "check")
    installer.install(bundle, roots, state, "apply")
    installer.install(bundle, roots, state, "apply")
    for item in contract["changes"].values():
        assert (
            installer.sha((roots[item["root"]] / item["relative"]).read_bytes())
            == item["after"]
        )
    installer.install(bundle, roots, state, "rollback")
    installer.install(bundle, roots, state, "rollback")
    assert {
        str(p): p.read_bytes() for p in roots["motor"].rglob("*") if p.is_file()
    } == before


def test_installer_unknown_bytes_refuses_entire_delta(prepared):
    bundle, roots, state, contract = prepared
    _name, item = next(iter(contract["changes"].items()))
    (roots[item["root"]] / item["relative"]).write_bytes(b"field edit")
    before = {str(p): p.read_bytes() for p in roots["motor"].rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="unknown target"):
        installer.install(bundle, roots, state, "apply")
    assert {
        str(p): p.read_bytes() for p in roots["motor"].rglob("*") if p.is_file()
    } == before
    assert not state.exists()


def test_off_does_not_import_optional_admission_package():
    import os

    script = """import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,*args):
        if fullname.startswith('gf_admission'):
            raise AssertionError('optional admission imported in off mode')
sys.meta_path.insert(0,Block())
from motor_adapter.bindings import admission_mode
assert admission_mode()=='off'
"""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    env.pop("GF_ADMISSION_CONFIG", None)
    subprocess.run([sys.executable, "-c", script], env=env, check=True)


def test_enabled_runtime_contract_checks_all_hook_and_protected_sources():
    from gf_admission.compatibility import validate_runtime

    validate_runtime.cache_clear()
    assert validate_runtime() == "0.1.0rc1"
    validate_runtime.cache_clear()
