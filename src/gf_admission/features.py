"""Immutable, exclusive tier coverage. Unknown is never a zero-hit estimate."""

from dataclasses import dataclass

from .config import finite, integer


@dataclass(frozen=True, slots=True)
class TierCoverage:
    instance_id: int
    endpoint_id: int
    generation: int
    npu_tokens: int
    cpu_tokens: int
    disk_tokens: int

    def __post_init__(self) -> None:
        for name in (
            "instance_id",
            "endpoint_id",
            "generation",
            "npu_tokens",
            "cpu_tokens",
            "disk_tokens",
        ):
            integer(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    prompt_tokens: int | None
    coverage: tuple[TierCoverage, ...]
    source_version: str
    observed_ms: float
    trusted: bool
    reason: str

    def __post_init__(self) -> None:
        finite("observed_ms", self.observed_ms)
        if self.prompt_tokens is not None:
            integer("prompt_tokens", self.prompt_tokens, minimum=1)
        if not isinstance(self.coverage, tuple) or not all(
            isinstance(c, TierCoverage) for c in self.coverage
        ):
            raise ValueError("coverage must be an immutable tuple of TierCoverage")
        if len({c.instance_id for c in self.coverage}) != len(self.coverage):
            raise ValueError("one endpoint per P instance is required")
        if type(self.trusted) is not bool:
            raise ValueError("trusted must be a boolean")
        if not self.source_version or not self.reason:
            raise ValueError("feature provenance and reason are required")
        if self.coverage and self.prompt_tokens is None:
            raise ValueError("coverage requires prompt_tokens")
        for c in self.coverage:
            if c.npu_tokens + c.cpu_tokens + c.disk_tokens > self.prompt_tokens:
                raise ValueError("exclusive coverage exceeds prompt length")


@dataclass(frozen=True, slots=True)
class CostModel:
    beta_cpu: float
    beta_disk: float
    version: str

    def __post_init__(self) -> None:
        finite("beta_cpu", self.beta_cpu)
        finite("beta_disk", self.beta_disk)
        if not self.version:
            raise ValueError("explicit cost model version required")

    def estimate(
        self,
        snapshot: FeatureSnapshot,
        candidates: tuple[tuple[int, int, int], ...],
        *,
        now_ms: float,
        max_age_ms: float,
    ) -> tuple[float | None, tuple[float, ...]]:
        """Return min and per-candidate costs; missing eligible coverage is unknown.

        Timestamps belong to the caller's monotonic clock domain, never to a
        different host. The frozen costs are not FG reservation accounting.
        """
        finite("now_ms", now_ms)
        finite("max_age_ms", max_age_ms, positive=True)
        if (
            not snapshot.trusted
            or snapshot.prompt_tokens is None
            or not candidates
            or not 0 <= now_ms - snapshot.observed_ms <= max_age_ms
        ):
            return None, ()
        by_identity = {
            (c.instance_id, c.endpoint_id, c.generation): c for c in snapshot.coverage
        }
        costs = []
        for identity in candidates:
            c = by_identity.get(identity)
            if c is None:
                return None, ()
            uncached = (
                snapshot.prompt_tokens - c.npu_tokens - c.cpu_tokens - c.disk_tokens
            )
            value = (
                uncached + self.beta_cpu * c.cpu_tokens + self.beta_disk * c.disk_tokens
            )
            finite("estimated cost", value)
            costs.append(value)
        return min(costs), tuple(costs)
