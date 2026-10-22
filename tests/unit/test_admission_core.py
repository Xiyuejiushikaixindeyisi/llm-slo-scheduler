"""Pure CPU policy checks. These do not claim RPC or native CAS coverage."""
from dataclasses import replace
import hashlib
import heapq
import json
from pathlib import Path
import random
from types import SimpleNamespace
import textwrap

import pytest

from gf_admission.classifier import Classifier, Reason
from gf_admission.config import ClassifierConfig, QueueLimits
from gf_admission.features import CostModel, FeatureSnapshot, TierCoverage
from gf_admission.pressure import Pressure, ScoreThreshold
from gf_admission.queue import CapacityError, DualQueueStore

ROOT = Path(__file__).resolve().parents[2]


def classifier(**changes):
    return Classifier(replace(ClassifierConfig(20, 1, .8, 1.5, 1000), **changes))


def decide(c, cost, **changes):
    return c.decide(cost, **dict(budget_allows=True, pressure_valid=True, **changes))


class FakeClock:
    now = 0.0

    def __call__(self):
        return self.now


def store(**changes):
    clock = FakeClock()
    limits = replace(QueueLimits(100, 100, 1e6, 100, 3, 128), **changes)
    return DualQueueStore(limits, clock), clock


def oracle():
    """Execute verbatim pinned prototype statements, with no backend imports."""
    fixtures = ROOT / "tests/fixtures/admission"
    manifest = json.loads((fixtures / "provenance.json").read_text())
    blocks = []
    for item in manifest["excerpts"]:
        raw = (fixtures / item["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        blocks.append(textwrap.dedent(raw.decode()))
    namespace = {}
    exec(blocks[1], namespace)
    state = SimpleNamespace(arrival_counter=0, credits=0, quota_every=20, quota_amount=1,
                            quota_refills=0, quota_credits_added=0, global_min_service_s=None,
                            global_max_service_s=0, threshold_ratio=.8, long_request_ratio=1.5,
                            tail_admitted_count=0, sacrificial_dispatches=0,
                            quota_credits_consumed=0, normal_dispatches=0)
    state._is_sacrificial_candidate = lambda cost: namespace["_is_sacrificial_candidate"](state, cost)

    def observe(cost):
        local = {"self": state, "estimated_service_s": cost}
        exec(blocks[0], {}, local)
        return local["is_sacrificial"]
    return state, observe


def test_classifier_against_pinned_prototype():
    original, observe = oracle()
    candidate = classifier()
    rng = random.Random(20261022)
    costs = [10.] * 40 + [15., 12., 80., 100.] + [rng.uniform(1, 100) for _ in range(3000)]
    for cost in costs:
        assert decide(candidate, cost).tail == observe(cost)
        assert candidate.credit == original.credits
        assert candidate.consumed == original.quota_credits_consumed
        assert candidate.minimum == original.global_min_service_s
        assert candidate.maximum == original.global_max_service_s
        assert candidate.credit + candidate.consumed + candidate.discarded == candidate.refilled


def test_unknown_zero_homogeneous_credit_and_boundary():
    c = classifier()
    for _ in range(19):
        assert decide(c, None).reason is Reason.UNKNOWN
    assert c.minimum is None and c.credit == 0
    assert not decide(c, 10).tail
    assert c.credit == 1
    assert not decide(c, 0).tail and c.minimum == 10
    assert not decide(c, 14.999).tail
    assert decide(c, 15).tail
    assert c.credit == 0
    assert not decide(c, 100).tail
    # Both thresholds must hold. 80% equality is inclusive.
    c = classifier(quota_every=1)
    decide(c, 1)
    decide(c, 100)
    assert not decide(c, 79.999).tail
    assert decide(c, 80).tail


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "10"])
def test_invalid_cost_rejected_without_mutation(value):
    c = classifier()
    with pytest.raises(ValueError):
        decide(c, value)
    assert c.arrivals == c.credit == c.consumed == 0


def test_credit_cap_and_gates_do_not_consume_or_refund():
    c = classifier(quota_every=1, credit_cap=2)
    for _ in range(10):
        decide(c, 10)
    assert (c.credit, c.refilled, c.discarded) == (2, 10, 8)
    assert c.decide(100, budget_allows=False, pressure_valid=True).reason is Reason.BUDGET
    assert c.decide(100, budget_allows=True, pressure_valid=False).reason is Reason.PRESSURE_UNKNOWN
    assert decide(c, 100, protected=True).reason is Reason.PROTECTED
    assert decide(c, 100, supported=False).reason is Reason.UNSUPPORTED
    assert c.credit == 2 and c.consumed == 0
    assert decide(c, 100).tail
    q, _ = store()
    q.add("tail", 100, tail=True)
    q.remove("tail")
    q.remove("tail")
    assert c.credit == 1 and c.consumed == 1


def test_fifo_lifo_budget_promotion_and_cancel():
    q, clock = store(max_tail_requests=2, max_tail_cost=30)
    q.add("n0", None, tail=False)
    q.add("t0", 10, tail=True)
    clock.now = 5
    q.add("t1", 20, tail=True)
    assert not q.tail_allows(1)
    assert q.candidates()[0].key == "n0"
    q.remove("n0")
    assert [e.key for e in q.candidates()] == ["t1", "t0"]
    clock.now = 100
    assert q.promote(max_items=1) == ("t0",)
    assert q.tail_cost == 20 and q.next_promotion_ms() == 105
    q.add("new_normal", 1, tail=False)
    assert q.candidates()[0].key == "t0"
    assert q.normal["t0"].protected
    assert q.promote(max_items=1) == ()
    clock.now = 105
    assert q.promote(max_items=1) == ("t1",)
    assert list(q.normal) == ["t0", "new_normal", "t1"]
    assert q.tail_cost == 0 and q.next_promotion_ms() is None
    assert q.remove("t0") is not None
    assert q.remove("t0") is None


def test_capacity_duplicate_oversize_budget_and_clock_fail_closed():
    q, clock = store(max_pending=2, max_tail_requests=1, max_tail_cost=5, max_key_bytes=4)
    with pytest.raises(ValueError):
        q.add("large", 1, tail=False)
    q.add("a", 5, tail=True)
    with pytest.raises(ValueError):
        q.add("a", 5, tail=True)
    with pytest.raises(ValueError):
        q.add("b", 1, tail=True)
    with pytest.raises(ValueError):
        q.add("b", None, tail=True)
    with pytest.raises(ValueError):
        q.add("b", 1, tail=True, protected=True)
    q.add("b", None, tail=False)
    with pytest.raises(CapacityError):
        q.add("c", 0, tail=False)
    assert len(q) == 2 and q.tail_cost == 5
    q.remove("a")
    clock.now = -1
    with pytest.raises(ValueError):
        q.add("c", 1, tail=False)
    assert len(q) == 1


def test_bounded_scan_and_force_promotion():
    q, _ = store(scan_limit=2)
    for i in range(5):
        q.add(str(i), i + 1, tail=True)
    assert [e.key for e in q.candidates()] == ["4", "3"]
    assert q.promote(max_items=2, force=True) == ("0", "1")
    assert len(q.tail) == 3 and q.tail_cost == 12
    assert [e.key for e in q.candidates()] == ["0"]


def test_cancel_large_cost_preserves_small_remaining_work():
    q, _ = store(max_tail_cost=1e17)
    q.add("large", 1e16, tail=True)
    q.add("small", 1, tail=True)
    q.remove("large")
    assert q.tail_cost == 1
    q.remove("small")
    assert q.tail_cost == 0


def test_seeded_queue_replay_against_heap_oracle():
    q, clock = store()
    rng = random.Random(10922)
    live = {}
    normal, tail = [], []
    seq = 0
    for step in range(5000):
        op = rng.randrange(3)
        if op == 0 and len(live) < 100:
            seq += 1
            key = str(seq)
            is_tail = bool(rng.randrange(2))
            cost = rng.uniform(.1, 100)
            q.add(key, cost, tail=is_tail)
            live[key] = (is_tail, cost)
            heapq.heappush(tail if is_tail else normal, (-seq if is_tail else seq, key))
        elif op == 1 and live:
            key = rng.choice(list(live))
            q.remove(key)
            del live[key]
        else:
            expected = None
            for heap in (normal, tail):
                while heap and heap[0][1] not in live:
                    heapq.heappop(heap)
                if heap:
                    expected = heap[0][1]
                    break
            selected = q.candidates()
            assert (selected[0].key if selected else None) == expected
            if expected is not None:
                q.remove(expected)
                del live[expected]
        assert len(q) == len(live)
        assert set(q.normal).isdisjoint(q.tail)
        assert q.tail_cost == pytest.approx(sum(c for t, c in live.values() if t))
    for key in list(live):
        q.remove(key)
    assert len(q) == 0 and q.tail_cost == 0


def snapshot():
    return FeatureSnapshot(100, (TierCoverage(1, 0, 1, 20, 30, 10),), "test-v1", 10, True, "known")


def test_feature_tiers_unknown_age_and_generation():
    model = CostModel(.5, 2, "experiment-v1")
    s = snapshot()
    assert model.estimate(s, ((1, 0, 1),), now_ms=20, max_age_ms=10) == (75, (75,))
    for changed, candidates, now in [(replace(s, trusted=False), ((1, 0, 1),), 20),
                                     (s, ((1, 0, 2),), 20), (s, ((1, 0, 1),), 21),
                                     (s, ((1, 0, 1),), 9), (s, (), 20),
                                     (s, ((1, 0, 1), (2, 0, 1)), 20)]:
        assert model.estimate(changed, candidates, now_ms=now, max_age_ms=10) == (None, ())
    with pytest.raises(ValueError):
        replace(s, prompt_tokens=50)
    with pytest.raises(ValueError):
        replace(s, coverage=s.coverage * 2)
    with pytest.raises(ValueError):
        CostModel(float("nan"), 0, "bad")


def test_min_cost_does_not_select_route():
    s = replace(snapshot(), coverage=(TierCoverage(1, 0, 1, 100, 0, 0), TierCoverage(2, 0, 1, 0, 0, 0)))
    assert CostModel(1, 1, "test").estimate(s, ((1, 0, 1), (2, 0, 1)), now_ms=10, max_age_ms=1) == (0, (0, 100))


def test_pressure_units_unknown_and_inclusive_boundary():
    gate = ScoreThreshold(10)
    assert gate.allows(Pressure(10, True, "known"))
    assert not gate.allows(Pressure(10.01, True, "known"))
    assert not gate.allows(Pressure(0, False, "stale"))
    assert not gate.allows(Pressure(None, False, "unknown"))
    with pytest.raises(ValueError):
        gate.allows(Pressure(1, True, "known", unit="ms"))
    with pytest.raises(ValueError):
        gate.allows(Pressure(float("nan"), True, "known"))


@pytest.mark.parametrize("changes", [dict(quota_every=0), dict(quota_every=True), dict(credit_cap=-1),
                                       dict(threshold_ratio=1.1), dict(long_request_ratio=1),
                                       dict(threshold_ratio=float("nan"))])
def test_classifier_config_rejects_invalid(changes):
    with pytest.raises(ValueError):
        classifier(**changes)


@pytest.mark.parametrize("cost, pressure, expected", [(10, True, Reason.PRESSURE),
    (15, True, Reason.BOTH), (15, False, Reason.TAIL), (10, False, Reason.NOT_LONG)])
def test_unified_cost_or_pressure_uses_one_credit(cost, pressure, expected):
    c = classifier(quota_every=1, credit_cap=2)
    decide(c, 10)
    before = c.consumed
    result = decide(c, cost, high_pressure=pressure)
    assert result.reason is expected
    assert c.consumed - before == int(result.tail)
    assert not c.decide(None, budget_allows=True, pressure_valid=True, high_pressure=True).tail
    assert not c.decide(10, budget_allows=True, pressure_valid=False, high_pressure=True).tail
