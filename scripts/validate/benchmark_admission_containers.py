#!/usr/bin/env python3
"""Compare container-only cancellation/promotion/dispatch traces on CPU.

This does not measure Motor IPC, lock contention, event-loop latency or NPU gain.
All containers replay exactly the same keys and operations, including cancellation
of 25% and promotion of 25% of initially queued entries before full draining.
"""
import argparse
from collections import OrderedDict, deque
import heapq
import json
from pathlib import Path
import platform
import random
import statistics
import time
import tracemalloc


class Ordered:
    def __init__(self):
        self.q = [OrderedDict(), OrderedDict()]
        self.live = {}

    def add(self, key, tail):
        self.q[tail][key] = None
        self.live[key] = tail

    def remove(self, key):
        tail = self.live.pop(key)
        del self.q[tail][key]

    def pop(self):
        tail = not bool(self.q[0])
        key, _ = self.q[tail].popitem(last=tail)
        del self.live[key]
        return key


class Deque:
    def __init__(self):
        self.q = [deque(), deque()]
        self.live = {}

    def add(self, key, tail):
        self.q[tail].append(key)
        self.live[key] = tail

    def remove(self, key):
        tail = self.live.pop(key)
        self.q[tail].remove(key)

    def pop(self):
        tail = not bool(self.q[0])
        key = self.q[tail].pop() if tail else self.q[0].popleft()
        del self.live[key]
        return key


class Heap:
    def __init__(self):
        self.q = [[], []]
        self.live = {}
        self.seq = 0

    def add(self, key, tail):
        self.seq += 1
        self.live[key] = self.seq
        heapq.heappush(self.q[tail], (-self.seq if tail else self.seq, key, self.seq))

    def remove(self, key):
        del self.live[key]

    def pop(self):
        for queue in self.q:
            while queue:
                _, key, revision = heapq.heappop(queue)
                if self.live.get(key) == revision:
                    del self.live[key]
                    return key
        raise RuntimeError("no live entry")


def replay(kind, size, cancelled, promoted):
    queue = kind()
    for key in range(size):
        queue.add(key, True)
    for key in cancelled:
        queue.remove(key)
    for key in promoted:
        queue.remove(key)
        queue.add(key, False)
    return [queue.pop() for _ in range(size - len(cancelled))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=100)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be >=2")
    result = {"python": platform.python_version(), "platform": platform.platform(),
              "seed": 20261022, "repeats": args.repeats, "results": [],
              "scope": "container-only CPU batches; not whole policy/IPC/NPU performance"}
    for size in (16, 256, 4096):
        keys = list(range(size))
        random.Random(20261022).shuffle(keys)
        cancelled, promoted = keys[:size // 4], keys[size // 4:size // 2]
        reference = replay(Ordered, size, cancelled, promoted)
        for kind in (Ordered, Deque, Heap):
            samples = []
            for _ in range(args.repeats):
                start = time.perf_counter_ns()
                observed = replay(kind, size, cancelled, promoted)
                samples.append((time.perf_counter_ns() - start) / 1000)
                assert observed == reference
            tracemalloc.start()
            replay(kind, size, cancelled, promoted)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            result["results"].append(dict(container=kind.__name__, initial_items=size,
                                         batch_p50_us=statistics.median(samples),
                                         batch_p99_us=sorted(samples)[int(.99 * (len(samples) - 1))],
                                         peak_python_bytes=peak))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
