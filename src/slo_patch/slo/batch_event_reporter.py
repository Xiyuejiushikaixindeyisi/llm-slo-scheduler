"""Bounded asynchronous transport for immutable, explicitly correlated P batch events."""
from collections import Counter
import os
from pathlib import Path
import logging
import queue
import threading

import httpx

logger = logging.getLogger("vllm")


class BatchEventReporter:
    def __init__(self, max_workers: int = 4, addr: str = "", port: int = 0, capacity: int = 1024):
        self.metrics = Counter()
        self._queue = queue.Queue(maxsize=capacity)
        self._closed = threading.Event()
        headers = {"content-type": "application/json"}
        key_path = os.getenv("FGJSQ_MGMT_API_KEY_FILE")
        if key_path:
            key = Path(key_path).read_text().strip()
            if not key:
                raise ValueError("FGJSQ_MGMT_API_KEY_FILE is empty")
            headers["X-Motor-Management-Key"] = key
        self._client = httpx.Client(timeout=5.0, headers=headers,
                                    limits=httpx.Limits(max_connections=max_workers))
        self._threads = [threading.Thread(target=self._run, name="fgjsq-reporter", daemon=True)
                         for _ in range(max_workers)]
        for thread in self._threads:
            thread.start()

    def emit(self, scheduler_output, requests=None) -> None:
        if self._closed.is_set():
            return
        snapshot = getattr(scheduler_output, "_fgjsq_snapshot", None)
        if snapshot is None:
            if scheduler_output.num_scheduled_tokens:
                self.metrics["missing_snapshot"] += 1
                logger.error("FGJSQ missing frozen batch snapshot")
            return
        for url, body in snapshot.payloads:
            try:
                self._queue.put_nowait((url, body))
                self.metrics["queued"] += 1
            except queue.Full:
                self.metrics["dropped"] += 1
                logger.error("FGJSQ reporter queue full; dropped batch_seq=%s", snapshot.batch_seq)

    def _run(self) -> None:
        while not self._closed.is_set() or not self._queue.empty():
            try:
                url, body = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                for retry in range(3):
                    try:
                        response = self._client.post(url, content=body)
                        response.raise_for_status()
                        result = response.json()
                        self.metrics["sent"] += 1
                        self.metrics["matched"] += int(result.get("matched", 0))
                        self.metrics["stale"] += int(result.get("stale", 0))
                        unmatched = int(result.get("unknown_or_released", 0)) + int(result.get("wrong_identity", 0))
                        self.metrics["unmatched"] += unmatched
                        if unmatched:
                            logger.warning("FGJSQ event unmatched count=%s result=%s", unmatched, result)
                        break
                    except (httpx.HTTPError, ValueError, TypeError) as error:
                        if retry == 2:
                            self.metrics["send_failed"] += 1
                            logger.error("FGJSQ event send failed: %s", error)
                        elif self._closed.wait(0.05 * (retry + 1)):
                            break
            finally:
                self._queue.task_done()

    def close(self, wait: bool = True) -> None:
        self._closed.set()
        if wait:
            for thread in self._threads:
                thread.join()
            self._client.close()
