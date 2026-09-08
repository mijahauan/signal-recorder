"""End-to-end behaviour on synthetic witnesses.

The synthetic station has a ruler running a chosen number of parts per
million and a witness that reports the true UTC of a named sample with a
chosen sigma. Everything the estimator learns, it learns from those reports.
"""

import math

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
    """The POSITIVE half of the step rule, asserted on the plane itself.

    A verdict of ``publish`` and an unchanged rate say only that nothing
    broke. Delete the ``reseed_phase`` call in ``_settle_step`` and both
    still hold, because a quorum that never ripens publishes an untouched
    plane at an untouched rate. What separates the two is where the plane
    ENDS UP, so this measures it against the offset the quorum injected.
    """
    st = Station(ppm=-20.0)
    est = StationTimingEstimator(f_nom=F_NOM)
    for rtp in minute_marks(8):
        est.observe(st.phase(rtp, tier="T3"))
        est.advance(rtp)
    eighth = minute_marks(8)[-1]
    settled = est.solve(eighth)
    # Before the quorum speaks the plane sits on the truth.
    assert settled.utc_ns_at(eighth) - st.true_utc_ns(eighth) == pytest.approx(
        0.0, abs=0.5 * MS
    )

    # Two tiers now agree that the plane sits 40 ms out, for five minutes.
    for rtp in minute_marks(14)[8:]:
        for tier in ("T3", "T5"):
            est.observe(st.phase(rtp, tier=tier, error_ns=40.0 * MS))
        est.advance(rtp)
    last = minute_marks(14)[-1]
    after = est.solve(last)

    assert after.verdict == VERDICT_PUBLISH
    # The plane MOVED, by what the quorum said and not by rather less.
    assert after.utc_ns_at(last) - st.true_utc_ns(last) == pytest.approx(
        40.0 * MS, abs=0.5 * MS
    )
    # And the rate learned nothing from the step.
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


def test_a_quiet_ruler_cannot_be_told_from_its_witnesses_and_says_so():
    """Was ``..._turns_measured_once_the_span_allows``.

    Span is not what gates the label; the witnesses are. A governed ruler's
    own deviation sits below half-millisecond witnesses at every tau this
    project can supply -- separating 0.01 ppm from them needs a tau near
    86,400 s -- so the honest answer is the stand-in, and it stays the
    stand-in however long the run (controller ruling R36, 2026-09-08).
    """
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="observed")
    rng = np.random.default_rng(11)
    early = est.solve(st.rtp0)
    assert early.q_source == "standin"
    for rtp in minute_marks(90):
        est.observe(st.phase(rtp, sigma_ns=0.5 * MS, rng=rng))
        est.advance(rtp)
    sol = est.solve(minute_marks(90)[-1])
    assert sol.q_source == "standin"
    assert est._noise is est._standin


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


def test_a_host_plane_rate_witness_reaches_nothing_at_all():
    """Spec section 3, and the path that helped walk ND on 2026-09-07.

    The judge's offset-slope witness rides on whichever bench the judge
    selected; on the host bench it imports host error as ruler rate. No
    other test builds a host-plane ``RateObservation``, so deleting the
    guard in ``_observe_rate`` left the whole suite green.

    Two things must not happen, and each is asserted separately. It must
    not reach the filter or its tally -- so its tier appears nowhere in the
    published witnesses -- and it must not reach the rate-spread gate
    either, so a label-plane witness disagreeing with it by 50 ppm still
    raises no ``rate_disagreement``.
    """
    st, est, rtp = settled()
    before = est.solve(rtp)

    verdict = est.observe(
        rate_obs(
            ppm=+50.0,
            sigma_ppm=0.2,
            tier="T4",
            plane=PLANE_HOST,
            source="judge-offset-slope",
        )
    )
    est.observe(
        rate_obs(ppm=0.0, sigma_ppm=0.2, tier="T6", source="t6-residual")
    )
    after = est.solve(rtp)

    assert verdict.accepted is False
    assert verdict.reason == "host_plane"
    assert "T4" not in after.witnesses
    assert after.refusal is None
    assert after.witnesses["T6"]["accepted"] == 1
    assert abs(after.rate_ppm - before.rate_ppm) < 1.0


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
    # And fitting still runs after the deque has wrapped: the counter resets
    # on every attempted fit, so a small value proves one was attempted
    # within the last ``adev_refit_every`` accepted witnesses.
    assert est._since_refit < est.config.adev_refit_every
    # This ruler is quiet, so the honest label is the stand-in.
    assert est.solve(marks[-1]).q_source == "standin"


# ---- ruling R33: an ambiguous counter delta latches, never passes -------

WRAP = 2**32
HOUR = 3600 * F_NOM


def test_a_gap_past_half_a_wrap_latches_ambiguous_instead_of_publishing():
    """The resuming-daemon fault: 30 hours aliased to a backward step."""
    st, est, rtp = settled()
    far = (rtp + 30 * HOUR) % WRAP
    est.advance(far)
    sol = est.solve(far)

    assert sol.verdict == VERDICT_WITHHOLD
    assert sol.refusal == "counter_ambiguous"
    # And it stays latched: a later, perfectly ordinary sample does not
    # forgive it, because nothing but a fresh seed re-establishes the plane.
    assert est.solve(rtp).refusal == "counter_ambiguous"


def test_a_gap_inside_half_a_wrap_still_advances():
    st, est, rtp = settled()
    far = (rtp + 20 * HOUR) % WRAP
    est.advance(far)
    sol = est.solve(far)

    assert sol.refusal == "stale_phase"
    assert sol.rtp_ref == far
    assert sol.span_s == pytest.approx(20 * 3600 + 600, abs=1.0)


def test_an_announced_epoch_change_clears_the_ambiguity():
    st, est, rtp = settled()
    est.advance((rtp + 30 * HOUR) % WRAP)
    assert est.solve(rtp).refusal == "counter_ambiguous"

    est.note_counter_epoch_change("recorder announced a new counter space")
    st2 = Station(ppm=0.0, rtp0=5_000_000)
    est.observe(st2.phase(st2.rtp0))
    assert est.solve(st2.rtp0).refusal is None


# ---- an out-of-order arrival is not an aliased gap ----------------------
#
# The two arrive as the same SIGN and differ only in MAGNITUDE, by roughly
# three hundred to one. Latching on both took one witness reporting a sample
# index behind the last -- ordinary integration with two tiers on different
# cadences -- and withheld every later solution, permanently.


def test_an_out_of_order_witness_is_refused_without_latching():
    st, est, rtp = settled()
    before = est.solve(rtp)
    assert before.refusal is None

    # A second tier reports the sample one second behind the newest one.
    verdict = est.observe(st.phase(rtp - F_NOM, tier="T5"))

    assert verdict.accepted is False
    assert verdict.reason == "out_of_order"
    # The state did not move, and nothing latched.
    still = est.solve(rtp)
    assert still.refusal is None
    assert still.utc_ns_at(st.rtp0) == before.utc_ns_at(st.rtp0)
    assert still.rtp_ref == before.rtp_ref
    # The refusal is counted against the tier that arrived late.
    assert still.witnesses["T5"] == {"accepted": 0, "rejected": 1}


def test_later_solves_still_publish_after_an_out_of_order_witness():
    """The regression: one stale arrival used to end the timing product."""
    st, est, rtp = settled()
    est.observe(st.phase(rtp - F_NOM, tier="T5"))

    last = rtp
    for minute in range(11, 16):
        last = minute_marks(minute + 1)[-1]
        est.observe(st.phase(last))
        est.advance(last)
    after = est.solve(last)

    assert after.verdict == VERDICT_PUBLISH
    assert after.refusal is None


def test_a_host_plane_witness_never_advances_the_ruler_clock():
    """The plane is read BEFORE the clock moves (spec section 3)."""
    st, est, rtp = settled()
    before = est.solve(rtp)

    far = rtp + 600 * F_NOM
    est.observe(
        PhaseObservation(
            tier="T2",
            rtp=far,
            utc_ns=st.true_utc_ns(far),
            sigma_ns=25.0 * MS,
            plane=PLANE_HOST,
            source="ntp-pool",
        )
    )
    after = est.solve(rtp)

    assert after.rtp_ref == before.rtp_ref
    assert after.span_s == pytest.approx(before.span_s, abs=1e-9)
    assert after.refusal is None


def test_a_witness_a_wrap_behind_the_plane_still_latches_ambiguous():
    """Magnitude is the discriminant, so the aliased gap must still latch."""
    st, est, rtp = settled()
    far = (rtp + 30 * HOUR) % WRAP

    verdict = est.observe(st.phase(far))

    assert verdict.accepted is False
    assert verdict.reason == "counter_ambiguous"
    assert est.solve(rtp).refusal == "counter_ambiguous"


def test_an_epoch_change_clears_a_latch_set_by_an_observation():
    st, est, rtp = settled()
    est.observe(st.phase((rtp + 30 * HOUR) % WRAP))
    assert est.solve(rtp).refusal == "counter_ambiguous"

    est.note_counter_epoch_change("recorder announced a new counter space")
    st2 = Station(ppm=0.0, rtp0=5_000_000)
    est.observe(st2.phase(st2.rtp0))
    assert est.solve(st2.rtp0).refusal is None


# ---- ruling R35: a dead witness stops voting ----------------------------


def age_out(st, est, from_minute: int, to_minute: int) -> int:
    """Keep the phase witness fresh while older claims expire."""
    for rtp in minute_marks(to_minute)[from_minute:]:
        est.observe(st.phase(rtp))
        est.advance(rtp)
    return minute_marks(to_minute)[-1]


def test_a_stale_rate_disagreement_expires_and_publishing_resumes():
    st, est, rtp = settled(n_minutes=6)
    for ppm, source in ((+0.0, "t6-residual"), (+5.0, "fold-drift")):
        est.observe(rate_obs(ppm=ppm, sigma_ppm=0.1, source=source))
    assert est.solve(rtp).refusal == "rate_disagreement"

    last = age_out(st, est, 6, 12)
    sol = est.solve(last)
    assert sol.refusal is None
    assert sol.verdict == VERDICT_PUBLISH


def test_a_stale_coarse_disagreement_expires_and_publishing_resumes():
    st, est, rtp = settled(n_minutes=6)
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
    assert est.solve(rtp).refusal == "coarse_disagreement"

    last = age_out(st, est, 6, 12)
    sol = est.solve(last)
    assert sol.refusal is None
    assert sol.verdict == VERDICT_PUBLISH


# ---- rulings R34/R36/R38: the fit, and what it may call measured -------


class WanderingRuler:
    """A ruler whose frequency random-walks, with honest witnesses.

    ``ppm_per_hour`` is the standard deviation of the rate after one hour of
    walking, so the per-step kick is that divided by the square root of the
    steps in an hour. 3.5 ppm/hr is the wander this pair is built on: it
    clears the witness floor by more than an order of magnitude at ten hours
    of minute-marks, and it stays inside what the innovation gate will admit
    for a ruler DECLARED undisciplined. Both halves of that matter. Declare
    the same ruler ``observed`` and its 0.01 ppm stand-in keeps the gate so
    tight that 522 of 599 witnesses are rejected and the series never grows;
    push the wander to 12 ppm/hr and even ``assumed`` locks out. An
    undisciplined ruler is the only case where adaptive process noise earns
    its place, and this is the shape of that case.
    """

    def __init__(
        self,
        rng,
        ppm_per_hour: float,
        spacing_s: int = 60,
        rtp0: int = 1_000_000,
    ):
        self.rng = rng
        self.step_ppm = ppm_per_hour / math.sqrt(3600.0 / spacing_s)
        self.spacing_s, self.rtp0 = spacing_s, rtp0
        self.utc: dict[int, int] = {}
        self._rate_ppm = 0.0
        self._phase_ns = 0.0

    def marks(self, n: int, skip_after: int = -1, skip_s: int = 0):
        out, extra = [], 0
        for m in range(n):
            if m == skip_after + 1:
                extra = skip_s
            offset_s = m * self.spacing_s + extra
            rtp = self.rtp0 + offset_s * F_NOM
            if m:
                self._rate_ppm += float(self.rng.normal(0.0, self.step_ppm))
                self._phase_ns += self._rate_ppm * 1000.0 * self.spacing_s
            self.utc[rtp] = T0_NS + round(offset_s * 1e9 + self._phase_ns)
            out.append(rtp)
        return out

    def phase(self, rtp: int, sigma_ns: float, rng=None) -> PhaseObservation:
        noise = 0.0 if rng is None else float(rng.normal(0.0, sigma_ns))
        return PhaseObservation(
            tier="T6",
            rtp=int(rtp),
            utc_ns=self.utc[rtp] + round(noise),
            sigma_ns=sigma_ns,
            plane=PLANE_LABEL,
            source="wandering",
        )


def drive_wandering(marks, ruler, est, sigma_ns=0.5 * MS, seed=1023):
    rng = np.random.default_rng(seed)
    for rtp in marks:
        est.observe(ruler.phase(rtp, sigma_ns, rng=rng))
        est.advance(rtp)
    return est.solve(marks[-1])


def test_a_wandering_ruler_announces_itself_and_the_fit_takes_q2_only():
    ruler = WanderingRuler(np.random.default_rng(41), ppm_per_hour=3.5)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    sol = drive_wandering(ruler.marks(900), ruler, est)

    assert sol.q_source == "measured"
    # Above the declared stand-in, or the label would report that the ruler
    # was measured and returned its own fallback. All seven seeds tried
    # clear it, by between 1.05 and 16 times.
    assert est._noise.q2 > est._standin.q2
    # q1 is the witnesses' noise, never the ruler's, so it stays at the floor.
    assert est._noise.q1 == est._standin.q1


def test_a_holed_series_refuses_to_fit_even_when_the_ruler_is_wandering():
    """The hole, not the quiet, is what refuses this one.

    Built on the same wandering ruler that reads "measured" above, so the
    only difference is a three-hour hole among sixty-second spacings.
    ``compute_phase_adev`` assumes uniform spacing and a median gap is
    hole-blind, which is what the guard is for.

    The hole sits before the first refit deliberately. Put it later and the
    guard still refuses every fit that straddles it, but a clean fit taken
    earlier has already set the label -- correctly, since the guard exists to
    stop a bad fit overwriting, not to revoke a good one.
    """
    ruler = WanderingRuler(np.random.default_rng(41), ppm_per_hour=3.5)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="assumed")
    marks = ruler.marks(900, skip_after=30, skip_s=3 * 3600)
    sol = drive_wandering(marks, ruler, est)

    assert sol.q_source == "standin"
    assert est._noise is est._standin


def test_a_quiet_ruler_with_fine_witnesses_is_not_flattered_by_the_floor():
    """Fine witnesses must not flatter the stand-in into a false label.

    ``noise_from_adev`` floors q2 at the stand-in and still stamps it
    "measured". Judging the fit by the deviation that STORED q2 implies then
    asks a question about the stand-in rather than about the ruler: fine
    witnesses have a low floor, so the "observed" stand-in read 5.51 times
    its own noise and passed, with no measurement in it anywhere.

    Two guards stand between that and the label -- comparing the MEASURED
    deviation instead of the stored one, and requiring the fit to have moved
    off the floor -- and they overlap. Whenever the floor wins, the second
    refuses first, so no test can separate them: the loophole is unreachable
    while the off-the-floor check stands. Mutating either alone leaves this
    suite green; mutating BOTH turns this test and the wandering-ruler test
    red. They are jointly load-bearing, and the first is defence in depth.
    """
    st = Station(ppm=0.0)
    est = StationTimingEstimator(f_nom=F_NOM, ruler_provenance="observed")
    rng = np.random.default_rng(29)
    for rtp in minute_marks(160):
        est.observe(st.phase(rtp, sigma_ns=300.0, rng=rng))
        est.advance(rtp)

    assert est.solve(minute_marks(160)[-1]).q_source == "standin"
    assert est._noise is est._standin
