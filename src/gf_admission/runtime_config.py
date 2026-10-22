"""Versioned runtime settings, separate from FGJSQ_CONFIG."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import ClassifierConfig, QueueLimits, finite, integer


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    schema_version: int
    mode: str
    cluster_uuid: str
    model_spec: str
    parameter_source: str
    classifier: ClassifierConfig
    limits: QueueLimits
    release_threshold: float
    tick_ms: float
    wait_ms: float
    worker_lease_ms: float
    ready_lease_ms: float
    request_wait_ms: float
    tombstone_ms: float
    max_records: int
    max_workers: int
    max_payload_bytes: int
    changes_batch: int
    pump_items: int
    pump_ms: float
    cleanup_retries: int
    event_fresh_ms: float
    feature_timeout_ms: float
    feature_max_inflight: int
    beta_cpu: float
    beta_disk: float
    feature_kind: str
    high_pressure_threshold: float

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 2:
            raise ValueError("unsupported admission schema")
        if self.mode not in ("off", "shadow", "enforce"):
            raise ValueError("invalid admission mode")
        for value in (self.cluster_uuid, self.model_spec, self.parameter_source):
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError(
                    "explicit bounded pool identity/parameter source required"
                )
        for name in (
            "tick_ms",
            "wait_ms",
            "worker_lease_ms",
            "ready_lease_ms",
            "request_wait_ms",
            "tombstone_ms",
            "pump_ms",
            "event_fresh_ms",
            "feature_timeout_ms",
        ):
            finite(name, getattr(self, name), positive=True)
        for name in (
            "release_threshold",
            "high_pressure_threshold",
            "beta_cpu",
            "beta_disk",
        ):
            finite(name, getattr(self, name))
        if not 0 < self.release_threshold < self.high_pressure_threshold:
            raise ValueError("require 0 < release_threshold < high_pressure_threshold")
        for name in (
            "max_records",
            "max_workers",
            "max_payload_bytes",
            "changes_batch",
            "pump_items",
            "cleanup_retries",
            "feature_max_inflight",
        ):
            integer(name, getattr(self, name), minimum=1)
        if not self.wait_ms + 500 < 5000:
            raise ValueError("wait_ms plus 500ms dispatch headroom must be < 5s")
        if (
            self.worker_lease_ms < 3 * self.wait_ms
            or self.ready_lease_ms <= self.tick_ms
        ):
            raise ValueError("worker/READY lease too short for configured polling")
        if self.tombstone_ms <= self.request_wait_ms + self.worker_lease_ms:
            raise ValueError("tombstones must outlive request wait and worker lease")
        if (
            self.max_records < self.limits.max_pending
            or self.changes_batch > self.max_records
        ):
            raise ValueError("invalid record/notification capacity")
        if self.feature_kind not in ("unknown", "motor_conductor"):
            raise ValueError("unsupported feature provider")

    @property
    def digest(self):
        raw = json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return hashlib.sha256(raw.encode()).hexdigest()


def load_config(path: str) -> RuntimeConfig:
    with Path(path).open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("admission config exceeds 64KiB")
    values = json.loads(raw)
    values["classifier"] = ClassifierConfig(**values["classifier"])
    values["limits"] = QueueLimits(**values["limits"])
    return RuntimeConfig(**values)
