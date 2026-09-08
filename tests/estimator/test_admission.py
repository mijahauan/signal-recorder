import pytest

from hf_timestd.estimator.admission import AdmissionPolicy, Admitter
from hf_timestd.estimator.observations import (
    PLANE_HOST,
    PLANE_LABEL,
    PhaseObservation,
)

MS = 1_000_000.0


def obs(tier: str, plane: str = PLANE_LABEL, sigma_ns: float = 1.0 * MS):
    return PhaseObservation(
        tier=tier,
        rtp=1,
        utc_ns=2,
        sigma_ns=sigma_ns,
        plane=plane,
        source="test",
    )


def test_an_observation_inside_three_sigmas_is_accepted():
    a = Admitter(AdmissionPolicy())
    v = a.judge(nu=2.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    assert v.accepted is True
    assert v.reason == "accepted"


def test_an_observation_beyond_three_sigmas_is_rejected():
    a = Admitter(AdmissionPolicy())
    v = a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    assert v.accepted is False
    assert v.reason == "outlier"


def test_a_host_plane_observation_never_reaches_the_filter():
    a = Admitter(AdmissionPolicy())
    v = a.judge(
        nu=0.0,
        s=1.0,
        obs=obs("T2", plane=PLANE_HOST, sigma_ns=25 * MS),
        now_s=0.0,
    )
    assert v.accepted is False
    assert v.reason == "host_plane"


def test_counts_are_kept_per_tier():
    a = Admitter(AdmissionPolicy())
    a.judge(nu=0.0, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=1.0)
    a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T6"), now_s=1.0)
    counts = a.counts()
    assert counts["T3"] == {"accepted": 1, "rejected": 1}
    assert counts["T6"] == {"accepted": 0, "rejected": 1}


def test_one_tier_alone_never_proposes_a_step_however_often_it_repeats():
    """Spec section 4: a single tier may never move the plane."""
    a = Admitter(AdmissionPolicy())
    for i in range(1000):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=float(i))
        assert a.step(now_s=float(i)) is None


def test_a_concordant_quorum_proposes_a_step_only_after_the_dwell():
    a = Admitter(AdmissionPolicy(dwell_s=120.0))
    for tier in ("T3", "T5"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs(tier), now_s=0.0)
    assert a.step(now_s=0.0) is None
    assert a.step(now_s=119.0) is None
    proposal = a.step(now_s=121.0)
    assert proposal is not None
    assert proposal.implied_error_ns == pytest.approx(50.0 * MS)
    assert set(proposal.tiers) == {"T3", "T5"}


def test_tiers_disagreeing_with_each_other_prove_nothing():
    a = Admitter(AdmissionPolicy(dwell_s=0.0))
    a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    a.judge(nu=500.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T5"), now_s=0.0)
    assert a.step(now_s=10.0) is None


def test_opposite_directions_prove_nothing():
    a = Admitter(AdmissionPolicy(dwell_s=0.0))
    a.judge(nu=+50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=0.0)
    a.judge(nu=-50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T5"), now_s=0.0)
    assert a.step(now_s=10.0) is None


def test_the_sign_test_refuses_a_pair_the_spread_test_would_have_passed():
    """Isolates the sign check, which nothing else reaches.

    The test above pairs +50 ms with -50 ms against 1 ms sigmas. That
    spread of 100 ms runs sixteen times the concordance tolerance, so
    ``_concordant`` refuses on spread and returns before it ever looks at
    the signs: delete the sign test and that test still passes.

    Here the two dissents sit 4 ms apart against 10 ms sigmas -- well
    inside a tolerance of 60 ms -- so the spread test passes them and only
    their opposite directions stand between the pair and a step. The second
    half proves the tolerance really was generous enough, by pushing the
    same two magnitudes into the same direction and watching a proposal
    ripen.
    """
    opposed = Admitter(AdmissionPolicy(dwell_s=0.0))
    for tier, nu in (("T3", +2.0 * MS), ("T5", -2.0 * MS)):
        opposed.judge(
            nu=nu,
            s=(0.1 * MS) ** 2,
            obs=obs(tier, sigma_ns=10.0 * MS),
            now_s=0.0,
        )
    assert opposed.step(now_s=10.0) is None

    agreed = Admitter(AdmissionPolicy(dwell_s=0.0))
    for tier, nu in (("T3", +2.0 * MS), ("T5", +6.0 * MS)):
        agreed.judge(
            nu=nu,
            s=(0.1 * MS) ** 2,
            obs=obs(tier, sigma_ns=10.0 * MS),
            now_s=0.0,
        )
    assert agreed.step(now_s=10.0) is not None


def test_a_dissolved_quorum_expires_and_moves_nothing():
    a = Admitter(AdmissionPolicy(dwell_s=120.0, freshness_s=60.0))
    for tier in ("T3", "T5"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs(tier), now_s=0.0)
    # One tier comes good again while the other's dissent goes stale.
    a.judge(nu=0.0, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=30.0)
    assert a.step(now_s=200.0) is None


def test_an_accepted_observation_clears_that_tier_from_the_candidate():
    a = Admitter(AdmissionPolicy(dwell_s=0.0))
    for tier in ("T3", "T5"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs(tier), now_s=0.0)
    a.judge(nu=0.0, s=(1.0 * MS) ** 2, obs=obs("T5"), now_s=1.0)
    assert a.step(now_s=10.0) is None


def test_clear_step_forgets_the_candidate():
    a = Admitter(AdmissionPolicy(dwell_s=0.0))
    for tier in ("T3", "T5"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs(tier), now_s=0.0)
    assert a.step(now_s=10.0) is not None
    a.clear_step()
    assert a.step(now_s=10.0) is None


def test_a_backward_judge_raises():
    a = Admitter(AdmissionPolicy())
    a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T3"), now_s=100.0)
    with pytest.raises(ValueError, match="went backwards in ruler time"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs("T5"), now_s=10.0)


def test_reset_clears_a_dwelling_candidate():
    a = Admitter(AdmissionPolicy(dwell_s=0.0))
    for tier in ("T3", "T5"):
        a.judge(nu=50.0 * MS, s=(1.0 * MS) ** 2, obs=obs(tier), now_s=0.0)
    assert a.step(now_s=10.0) is not None
    a.reset("timeline restarted")
    assert a.step(now_s=10.0) is None


def test_a_dwelling_candidate_announces_itself_before_it_ripens():
    """The estimator publishes ``step_pending`` while a quorum dwells."""
    adm = Admitter(AdmissionPolicy())
    assert adm.dwelling is False
    for tier in ("T3", "T5"):
        adm.judge(
            50.0e6,
            1.0e12,
            PhaseObservation(
                tier=tier,
                rtp=1_000_000,
                utc_ns=1_788_729_000_000_000_000,
                sigma_ns=1.0e6,
                plane=PLANE_LABEL,
                source="synthetic",
            ),
            now_s=10.0,
        )
    assert adm.dwelling is True
    assert adm.step(now_s=60.0) is None
    # Past the dwell but still inside the freshness window.
    assert adm.step(now_s=140.0) is not None
    adm.clear_step()
    assert adm.dwelling is False
