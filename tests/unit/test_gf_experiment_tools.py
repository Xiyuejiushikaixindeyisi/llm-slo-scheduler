"""Local supervision and probe contracts, without AISBench/NPU claims."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def tool(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts/experiments" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_keeps_per_p_units_and_rejects_missing_candidates(tmp_path):
    probe = tool("gf_pressure_probe")
    source = tmp_path / "samples.jsonl"
    rows = []
    for n in (1, 2):
        policy = {
            str(i): {"score": i * n * 10, "committed_tokens": i * n * 8, "requests": n}
            for i in (1, 2)
        }
        rows.append(
            {
                "run_id": "test",
                "input_tokens": 66158,
                "concurrency": 16,
                "instances": ["1", "2"],
                "samples": {
                    "loads": {
                        "start_s": n,
                        "end_s": n + 0.1,
                        "data": {"policy": policy},
                    }
                },
            }
        )
    rows.append(dict(rows[0], instances=["1", "2", "3"]))
    source.write_text("\n".join(json.dumps(x) for x in rows))
    report = probe.summarize(source, [{"start_s": 2, "end_s": 3, "label": "long_wait"}])
    assert report["rejected_missing_p_or_error"] == 1
    assert report["groups"]["long_wait"]["minimum_score"]["p50"] == 20
    evidence = tmp_path / "report.json"
    evidence.write_text(json.dumps(report))
    args = SimpleNamespace(
        template=ROOT / "configs/gf_admission/enforce.example.json",
        evidence=evidence,
        output=tmp_path / "frozen.json",
        low=5,
        high=20,
        event_fresh_ms=None,
        tail_wait_ms=None,
        cluster_uuid="test",
        model_spec="66k",
        rationale="test fixture",
    )
    probe.freeze(args)
    assert json.loads(args.output.read_text())["high_pressure_threshold"] == 20
    args.output = tmp_path / "invalid.json"
    args.low = 30
    with pytest.raises(ValueError, match="release_threshold"):
        probe.freeze(args)
    assert not args.output.exists()


@pytest.mark.parametrize("failed", [False, True])
def test_watchdog_notifies_terminal_event_and_stops_only_owned_child(tmp_path, failed):
    watchdog = tool("gf_watchdog")
    notify = [
        sys.executable,
        "-c",
        "import pathlib,sys;pathlib.Path(sys.argv[1]+'.received').write_text('ok')",
    ]
    health = [sys.executable, "-c", "raise SystemExit(" + str(int(failed)) + ")"]
    command = [
        sys.executable,
        "-c",
        "import time;time.sleep(" + ("30" if failed else ".05") + ")",
    ]
    output = tmp_path / "run"
    code = watchdog.supervise(
        command, health, notify, output, interval=0.02, failures=1
    )
    event = json.loads((output / "event.json").read_text())
    assert code == int(failed)
    assert event["reason"] == ("health_failed" if failed else "complete")
    assert not event["restart_performed"]
    assert (output / "event.json.received").is_file()
    assert json.loads((output / "notification.json").read_text())["adapter_accepted"]
