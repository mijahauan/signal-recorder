"""End-to-end behaviour on synthetic witnesses.

The synthetic station has a ruler running a chosen number of parts per
million and a witness that reports the true UTC of a named sample with a
chosen sigma. Everything the estimator learns, it learns from those reports.
"""

import numpy as np
import pytest

from hf_timestd.estimator.estimator import (
    RESIDUAL_CAP,
    StationTimingEstimator,
)
from hf_timestd.estimator.observations import (
    PLANE_HOST,
    PLANE_LABEL,
    PhaseObservation,
    RateObservation,
)
from hf_timestd.estimator.solution import VERDICT_PUBLISH, VERDICT_WITHHOLD

F_NOM = 24000
MS = 1_000_000.0
T0_NS = 1_788_729_000_000_000_000


class Station:
    """A ruler running ``ppm`` fast, and truthful witnesses on it."""

    def __init__(self, ppm: float, rtp0: int = 1_000_000):
        self.ppm = float(ppm)
        self.rtp0 = int(rtp0)

    def true_utc_ns(self, rtp: int) -> int:
        f_true = F_NOM * (1.0 + self.ppm * 1e-6)
        return T0_NS + round(1e9 * (rtp - self.rtp0) / f_true)

    def phase(
        self,
        rtp: int,
        tier: str = "T3",
        sigma_ns: float = 1.0 * MS,
        error_ns: float = 0.0,
        rng=None,
    ) -> PhaseObservation:
        noise = 0.0 if rng is None else float(rng.normal(0.0, sigma_ns))
        return PhaseObservation(
            tier=tier,
            rtp=int(rtp),
            utc_ns=self.true_utc_ns(rtp) + round(error_ns + noise),
            sigma_ns=sigma_ns,
            plane=PLANE_LABEL,
            source="synthetic",
        )


def minute_marks(n_minutes: int, rtp0: int = 1_000_000):
    return [rtp0 + m * 60 * F_NOM for m in range(n_minutes)]


def test_a_fresh_estimator_refuses_for_want_of_a_witness():
    est = StationTimingEstimator(f_nom=F_NOM)
    sol = est.solve(1_000_000)
    assert sol.verdict == VERDICT_WITHHOLD
    assert sol.refusal == "no_phase_witness"


def test_the_first_witness_seeds_the_plane_exactly():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    obs = st.phase(st.rtp0)
    est.observe(obs)
    sol = est.solve(st.rtp0)
    assert sol.utc_ns_at(st.rtp0) == obs.utc_ns


def test_it_recovers_a_sixty_ppm_ruler_from_ten_minutes_of_witnesses():
    """The headline capability: rate from phase drift alone."""
    st = Station(ppm=-60.0)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp, sigma_ns=1.0 * MS))
        est.advance(rtp)
    sol = est.solve(minute_marks(11)[-1])
    assert sol.rate_ppm == pytest.approx(-60.0, abs=1.0)


def test_it_recovers_a_governed_ruler_as_near_zero():
    st = Station(ppm=+0.03)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="observed")
    rng = np.random.default_rng(3)
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp, sigma_ns=0.15 * MS, rng=rng))
        est.advance(rtp)
    sol = est.solve(minute_marks(11)[-1])
    assert abs(sol.rate_ppm) < 0.5


def test_the_published_rate_and_the_projection_agree():
    st = Station(ppm=-60.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    sol = est.solve(minute_marks(11)[-1])
    implied = (sol.rate_samples_per_utc_sec / F_NOM - 1.0) * 1e6
    assert implied == pytest.approx(sol.rate_ppm, rel=1e-6)


def test_a_lone_tier_repeating_a_fifty_millisecond_error_moves_nothing():
    """The regression test for 2026-09-07 (spec section 4)."""
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp, tier="T3", sigma_ns=1.0 * MS))
        est.advance(rtp)
    before = est.solve(minute_marks(6)[-1])

    liar = minute_marks(30)[6:]
    for rtp in liar:
        est.observe(
            st.phase(rtp, tier="T3", sigma_ns=1.0 * MS, error_ns=50.0 * MS)
        )
        est.advance(rtp)
    after = est.solve(liar[-1])

    assert abs(after.rate_ppm - before.rate_ppm) < 0.1
    assert after.witnesses["T3"]["rejected"] >= 20


@pytest.mark.parametrize("lattice_ms", [18.7, 34.0, 50.0])
def test_no_lattice_confusion_from_one_tier_moves_the_plane(lattice_ms):
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp, tier="T3"))
        est.advance(rtp)
    settled = est.solve(minute_marks(6)[-1])

    for rtp in minute_marks(20)[6:]:
        est.observe(st.phase(rtp, tier="T3", error_ns=lattice_ms * MS))
        est.advance(rtp)
    after = est.solve(minute_marks(20)[-1])

    assert abs(after.utc_ns_at(st.rtp0) - settled.utc_ns_at(st.rtp0)) < 5 * MS


def test_a_concordant_quorum_moves_the_plane_and_spares_the_rate():
    st = Station(ppm=-20.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(8):
        est.observe(st.phase(rtp, tier="T3"))
        est.advance(rtp)
    settled = est.solve(minute_marks(8)[-1])

    # Two tiers now agree that the plane sits 40 ms out, for five minutes.
    for rtp in minute_marks(14)[8:]:
        for tier in ("T3", "T5"):
            est.observe(st.phase(rtp, tier=tier, error_ns=40.0 * MS))
        est.advance(rtp)
    after = est.solve(minute_marks(14)[-1])

    assert after.verdict == VERDICT_PUBLISH
    assert abs(after.rate_ppm - settled.rate_ppm) < 0.1


def test_a_host_plane_witness_never_enters_the_state():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    before = est.solve(minute_marks(6)[-1])

    verdict = est.observe(
        PhaseObservation(
            tier="T2",
            rtp=minute_marks(6)[-1],
            utc_ns=st.true_utc_ns(minute_marks(6)[-1]) + round(20.0 * MS),
            sigma_ns=25.0 * MS,
            plane=PLANE_HOST,
            source="ntp-pool",
        )
    )
    after = est.solve(minute_marks(6)[-1])

    assert verdict.accepted is False
    assert verdict.reason == "host_plane"
    assert after.phase_ns == pytest.approx(before.phase_ns, abs=1.0)


def test_a_wildly_disagreeing_coarse_witness_withdraws_the_solution():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    rtp = minute_marks(6)[-1]
    est.observe(
        PhaseObservation(
            tier="T2",
            rtp=rtp,
            utc_ns=st.true_utc_ns(rtp) + round(400.0 * MS),
            sigma_ns=25.0 * MS,
            plane=PLANE_HOST,
            source="ntp-pool",
        )
    )
    sol = est.solve(rtp)
    assert sol.verdict == VERDICT_WITHHOLD
    assert sol.refusal == "coarse_disagreement"


def test_two_rate_witnesses_that_disagree_withdraw_the_solution():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(6):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    for ppm, source in ((+0.0, "t6-residual"), (+5.0, "fold-drift")):
        est.observe(
            RateObservation(
                tier="T6",
                ppm=ppm,
                sigma_ppm=0.1,
                span_s=900.0,
                n=900,
                plane=PLANE_LABEL,
                source=source,
            )
        )
    sol = est.solve(minute_marks(6)[-1])
    assert sol.verdict == VERDICT_WITHHOLD
    assert sol.refusal == "rate_disagreement"


def test_a_stale_witness_withdraws_the_solution():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(3):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    far = minute_marks(3)[-1] + 400 * F_NOM  # more than 300 s of samples later
    est.advance(far)
    sol = est.solve(far)
    assert sol.verdict == VERDICT_WITHHOLD
    assert sol.refusal == "stale_phase"


def test_a_counter_epoch_change_drops_phase_and_keeps_rate():
    st = Station(ppm=-30.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    before = est.solve(minute_marks(11)[-1])

    est.note_counter_epoch_change("recorder announced a new counter space")
    assert est.generation == before.generation + 1
    assert est.solve(minute_marks(11)[-1]).refusal == "no_phase_witness"

    st2 = Station(ppm=-30.0, rtp0=5_000_000)
    est.observe(st2.phase(st2.rtp0))
    after = est.solve(st2.rtp0)
    assert after.rate_ppm == pytest.approx(before.rate_ppm, abs=0.5)


def test_the_a_level_describes_the_ruler_and_nothing_branches_on_it():
    st = Station(ppm=-60.0)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    for rtp in minute_marks(11):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    assert est.solve(minute_marks(11)[-1]).a_level == "A0"

    governed = Station(ppm=0.0)
    est2 = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="observed")
    for rtp in minute_marks(31):
        est2.observe(governed.phase(rtp, sigma_ns=0.1 * MS))
        est2.advance(rtp)
    assert est2.solve(minute_marks(31)[-1]).a_level == "A1"


def test_the_process_noise_source_turns_measured_once_the_span_allows():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="observed")
    rng = np.random.default_rng(11)
    early = est.solve(st.rtp0)
    assert early.q_source == "standin"
    for rtp in minute_marks(90):
        est.observe(st.phase(rtp, sigma_ns=0.5 * MS, rng=rng))
        est.advance(rtp)
    assert est.solve(minute_marks(90)[-1]).q_source == "measured"


# ---- ruling R31: the rate path carries the same innovation test ----------


def settled(ppm: float = 0.0, n_minutes: int = 11):
    """A station and an estimator that has watched it for ``n_minutes``."""
    st = Station(ppm=ppm)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(n_minutes):
        est.observe(st.phase(rtp))
        est.advance(rtp)
    return st, est, minute_marks(n_minutes)[-1]


def rate_obs(ppm: float, sigma_ppm: float, tier: str = "T6", **kw):
    args = dict(
        tier=tier,
        ppm=ppm,
        sigma_ppm=sigma_ppm,
        span_s=900.0,
        n=900,
        plane=PLANE_LABEL,
        source=f"{tier}-witness",
    )
    args.update(kw)
    return RateObservation(**args)  # type: ignore[arg-type]


def test_a_wild_rate_witness_is_rejected_and_moves_the_rate_not_at_all():
    st, est, rtp = settled()
    before = est.solve(rtp)

    verdict = est.observe(rate_obs(ppm=+50.0, sigma_ppm=0.01))
    after = est.solve(rtp)

    assert verdict.accepted is False
    assert verdict.reason == "outlier"
    assert after.rate_ppm == pytest.approx(before.rate_ppm, abs=1e-9)
    assert after.witnesses["T6"]["rejected"] == 1


def test_a_reasonable_rate_witness_is_accepted_and_moves_the_rate():
    st, est, rtp = settled()
    before = est.solve(rtp)

    verdict = est.observe(rate_obs(ppm=+0.5, sigma_ppm=0.2))
    after = est.solve(rtp)

    assert verdict.accepted is True
    assert verdict.reason == "accepted"
    assert after.witnesses["T6"]["accepted"] == 1
    assert after.rate_ppm > before.rate_ppm


def test_rejected_rate_witnesses_never_license_a_step_of_the_plane():
    """A rate dissent is not a phase step, however concordant it looks."""
    st, est, rtp = settled()
    before = est.solve(rtp)

    for minute in range(11, 20):
        far = minute_marks(minute + 1)[-1]
        for tier in ("T6", "T5"):
            est.observe(rate_obs(ppm=+50.0, sigma_ppm=0.01, tier=tier))
        est.observe(st.phase(far))
        est.advance(far)
    after = est.solve(minute_marks(20)[-1])

    assert after.refusal != "step_pending"
    assert after.utc_ns_at(st.rtp0) == pytest.approx(
        before.utc_ns_at(st.rtp0), abs=1.0 * MS
    )
    assert after.witnesses["T5"]["rejected"] == 9
    assert after.witnesses["T5"]["accepted"] == 0


# ---- ruling R32: the residual series is bounded -------------------------


def ten_second_marks(n: int, rtp0: int = 1_000_000):
    """Marks close enough together that ``n`` of them clear no wrap."""
    return [rtp0 + m * 10 * F_NOM for m in range(n)]


def test_the_residual_series_stops_at_its_cap_and_still_fits_after():
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="observed")
    rng = np.random.default_rng(7)
    marks = ten_second_marks(RESIDUAL_CAP + 300)
    for rtp in marks:
        est.observe(st.phase(rtp, sigma_ns=0.5 * MS, rng=rng))
        est.advance(rtp)

    # Reaching past the public surface on purpose: the cap exists to stop
    # unbounded growth, and only the length can witness that.
    assert len(est._residuals) == RESIDUAL_CAP
    assert est.solve(marks[-1]).q_source == "measured"
