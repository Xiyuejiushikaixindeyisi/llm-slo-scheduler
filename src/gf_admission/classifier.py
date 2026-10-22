"""super-p95 arrival classification, separate from instantaneous S/V budgets.

The owner calls decide exactly once per logical nonce, after capacity and identity
validation. Transport retries and new attempts reuse the owner's saved decision.
"""

from dataclasses import dataclass
from enum import Enum

from .config import ClassifierConfig, finite


class Reason(str, Enum):
    TAIL = "tail"
    PRESSURE = "pressure"
    BOTH = "cost_and_pressure"
    UNKNOWN = "unknown_cost"
    ZERO = "zero_cost"
    NOT_LONG = "not_long"
    NO_CREDIT = "no_credit"
    BUDGET = "tail_budget"
    PRESSURE_UNKNOWN = "pressure_unknown"
    PROTECTED = "protected"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class Decision:
    tail: bool
    reason: Reason
    cost: float | None


class Classifier:
    def __init__(self, config: ClassifierConfig):
        self.config = config
        self.arrivals = 0
        self.credit = 0
        self.consumed = 0
        self.refilled = 0
        self.discarded = 0
        self.minimum: float | None = None
        self.maximum: float | None = None

    def decide(
        self,
        cost: float | None,
        *,
        budget_allows: bool,
        pressure_valid: bool,
        protected: bool = False,
        supported: bool = True,
        high_pressure: bool = False,
    ) -> Decision:
        # Validate before changing any accounting, including arrival credit.
        if cost is not None:
            finite("cost", cost)
        self.arrivals += 1
        cfg = self.config
        if self.arrivals % cfg.quota_every == 0:
            self.refilled += cfg.quota_amount
            available = self.credit + cfg.quota_amount
            self.credit = min(available, cfg.credit_cap)
            self.discarded += available - self.credit
        if cost is not None and cost > 0:
            self.minimum = cost if self.minimum is None else min(self.minimum, cost)
            self.maximum = cost if self.maximum is None else max(self.maximum, cost)
        reason = self._reason(
            cost, budget_allows, pressure_valid, protected, supported, high_pressure
        )
        tail = reason in (Reason.TAIL, Reason.PRESSURE, Reason.BOTH)
        if tail:
            self.credit -= 1
            self.consumed += 1
        return Decision(tail, reason, cost)

    def _reason(
        self, cost, budget_allows, pressure_valid, protected, supported, high_pressure
    ) -> Reason:
        if not supported:
            return Reason.UNSUPPORTED
        if protected:
            return Reason.PROTECTED
        if cost is None:
            return Reason.UNKNOWN
        if cost == 0:
            return Reason.ZERO
        if not pressure_valid:
            return Reason.PRESSURE_UNKNOWN
        long_cost = (
            cost >= self.config.threshold_ratio * self.maximum
            and cost >= self.config.long_request_ratio * self.minimum
        )
        if not long_cost and not high_pressure:
            return Reason.NOT_LONG
        if self.credit == 0:
            return Reason.NO_CREDIT
        if not budget_allows:
            return Reason.BUDGET
        return (
            Reason.BOTH
            if long_cost and high_pressure
            else (Reason.TAIL if long_cost else Reason.PRESSURE)
        )
