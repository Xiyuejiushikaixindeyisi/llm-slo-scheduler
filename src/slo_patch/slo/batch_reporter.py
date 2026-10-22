# 来源：260807 dev 仓 ascend_vllm/patch/slo/batch_reporter.py —— 逐行原样复制（无 ascend_vllm 依赖）
"""Batch info reporter — sends batch data to external service via async HTTP."""

from vllm.logger import logger
import threading

import requests



class BatchReporter:
    """Asynchronously reports batch scheduling info to an external service.
    """

    def __init__(self, endpoint: str = "http://localhost:9900/batch"):
        self.endpoint = endpoint
        self._session = requests.Session()

    def report_batch(self, batch_info: dict) -> None:
        """Fire-and-forget: spawn a daemon thread to POST batch_info."""
        thread = threading.Thread(
            target=self._send_async,
            args=(batch_info,),
            daemon=True,
        )
        thread.start()

    def _send_async(self, batch_info: dict) -> None:
        """Send HTTP POST in background thread. Log warning on failure."""
        try:
            self._session.post(
                self.endpoint,
                json=batch_info,
                timeout=2.0,
            )
        except Exception as e:
            logger.warning("[slo] batch report failed: %s", e)