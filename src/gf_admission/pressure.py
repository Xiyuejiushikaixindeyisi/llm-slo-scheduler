"""Read FG scores without converting them into uncalibrated milliseconds."""
from dataclasses import dataclass

from .config import finite


@dataclass(frozen=True, slots=True)
class Pressure:
    value: float | None
    valid: bool
    reason: str
    unit: str = "fg_score"
    model_version: str = "g5_score_v1"


@dataclass(frozen=True, slots=True)
class ScoreThreshold:
    release_threshold: float

    def __post_init__(self) -> None:
        finite("release_threshold", self.release_threshold)

    def allows(self, pressure: Pressure) -> bool:
        if pressure.unit != "fg_score" or pressure.model_version != "g5_score_v1":
            raise ValueError("pressure unit/model mismatch")
        if not pressure.valid or pressure.value is None:
            return False
        finite("pressure", pressure.value)
        return pressure.value <= self.release_threshold
