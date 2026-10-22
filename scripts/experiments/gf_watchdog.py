#!/usr/bin/env python3
"""Supervise one owned benchmark process; notify only on completion/failure.

Commands are JSON argv arrays, never shell strings. Site health/agent notification
adapters are mandatory and must be rehearsed. This tool never restarts engines,
changes code, hides failed runs, or retries an experiment automatically.
"""

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path


def argv_file(path):
    args = json.loads(path.read_text())
    if (
        not isinstance(args, list)
        or not args
        or any(not isinstance(x, str) for x in args)
    ):
        raise ValueError("command must be a nonempty JSON string array")
    return args


def stop_owned(process):
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def supervise(command, health, notify, output, interval=15, failures=3):
    if interval <= 0 or failures < 1:
        raise ValueError("positive watchdog interval/failure count required")
    output.mkdir(parents=True, exist_ok=False)

    def interrupted(signum, frame):
        raise KeyboardInterrupt("watchdog signal")

    previous_handlers = {
        sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGINT)
    }
    started = time.time()
    process = None
    reason, streak, returncode = "watchdog_error", 0, None
    with (
        (output / "benchmark.log").open("wb") as log,
        (output / "health.log").open("wb") as health_log,
    ):
        try:
            process = subprocess.Popen(
                command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
            )
            (output / "pid.json").write_text(
                json.dumps({"pid": process.pid, "started_s": started})
            )
            while True:
                returncode = process.poll()
                if returncode is not None:
                    reason = "complete" if returncode == 0 else "benchmark_failed"
                    break
                try:
                    result = subprocess.run(
                        health,
                        stdout=health_log,
                        stderr=subprocess.STDOUT,
                        timeout=10,
                        check=False,
                    )
                    streak = streak + 1 if result.returncode else 0
                except subprocess.TimeoutExpired:
                    streak += 1
                state = {
                    "wall_time_s": time.time(),
                    "pid": process.pid,
                    "unhealthy_streak": streak,
                }
                temp = output / "status.tmp"
                temp.write_text(json.dumps(state))
                temp.replace(output / "status.json")
                if streak >= failures:
                    reason = "health_failed"
                    break
                time.sleep(interval)
        except BaseException as error:  # noqa: BLE001 - preserve terminal evidence and stop owned child
            reason = "watchdog_" + type(error).__name__
        finally:
            if process is not None:
                stop_owned(process)
                returncode = process.returncode
    event = {
        "reason": reason,
        "started_s": started,
        "ended_s": time.time(),
        "returncode": returncode,
        "output": str(output.resolve()),
        "restart_performed": False,
    }
    event_path = output / "event.json"
    event_path.write_text(json.dumps(event, indent=2))
    # Durable event remains even when the notification adapter fails.
    try:
        result = subprocess.run(
            notify + [str(event_path.resolve())],
            timeout=15,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        notified = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        notified = False
    (output / "notification.json").write_text(
        json.dumps(
            {
                "adapter_accepted": notified,
                "note": "adapter success alone does not prove agent consumption; rehearse end-to-end",
            }
        )
    )
    for sig, handler in previous_handlers.items():
        signal.signal(sig, handler)
    return 0 if reason == "complete" and notified else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("command", "health", "notify", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--interval", type=float, default=15)
    parser.add_argument("--failures", type=int, default=3)
    args = parser.parse_args()
    raise SystemExit(
        supervise(
            argv_file(args.command),
            argv_file(args.health),
            argv_file(args.notify),
            args.output,
            args.interval,
            args.failures,
        )
    )


if __name__ == "__main__":
    main()
