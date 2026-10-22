"""Validated policy parameters. No uncalibrated production defaults."""

from dataclasses import dataclass
from math import isfinite


def finite(name: str, value: float, *, positive: bool = False) -> None:
    try:
        valid = (
            not isinstance(value, bool)
            and isinstance(value, (int, float))
            and isfinite(value)
            and (value > 0 if positive else value >= 0)
        )
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(
            f"{name} must be finite and {'positive' if positive else 'nonnegative'}"
        )


def integer(name: str, value: int, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True, slots=True)
class ClassifierConfig:
    quota_every: int
    quota_amount: int
    threshold_ratio: float
    long_request_ratio: float
    credit_cap: int

    def __post_init__(self) -> None:
        integer("quota_every", self.quota_every, minimum=1)
        integer("quota_amount", self.quota_amount)
        integer("credit_cap", self.credit_cap)
        finite("threshold_ratio", self.threshold_ratio, positive=True)
        if self.threshold_ratio > 1:
            raise ValueError("threshold_ratio must be <= 1")
        finite("long_request_ratio", self.long_request_ratio, positive=True)
        if self.long_request_ratio <= 1:
            raise ValueError(
                "long_request_ratio must be > 1 (homogeneous requests remain normal)"
            )


@dataclass(frozen=True, slots=True)
class QueueLimits:
    max_pending: int
    max_tail_requests: int
    max_tail_cost: float
    max_tail_wait_ms: float
    scan_limit: int
    max_key_bytes: int

    def __post_init__(self) -> None:
        integer("max_pending", self.max_pending, minimum=1)
        integer("max_tail_requests", self.max_tail_requests)
        if self.max_tail_requests > self.max_pending:
            raise ValueError("max_tail_requests exceeds max_pending")
        finite("max_tail_cost", self.max_tail_cost)
        finite("max_tail_wait_ms", self.max_tail_wait_ms, positive=True)
        integer("scan_limit", self.scan_limit, minimum=1)
        integer("max_key_bytes", self.max_key_bytes, minimum=1)
