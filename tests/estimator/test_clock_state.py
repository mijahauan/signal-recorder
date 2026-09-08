import numpy as np
import pytest

from hf_timestd.estimator.clock_state import PHASE, RATE, ClockState
from hf_timestd.estimator.process_noise import RulerNoise

F_NOM = 24000
QUIET = RulerNoise(q1=0.0, q2=0.0, source="standin")


def fresh(**kw) -> ClockState:
    args = dict(
        f_nom=F_NOM,
        rtp_ref=1_000_000,
        utc_ref_ns=1_788_729_000_000_000_000,
    )
    args.update(kw)
    return ClockState(**args)


def test_a_fresh_state_projects_its_own_reference_exactly():
    st = fresh()
    assert st.utc_ns_at(1_000_000) == 1_788_729_000_000_000_000


def test_one_second_of_samples_advances_utc_by_one_second():
    st = fresh()
    elapsed = st.utc_ns_at(1_000_000 + F_NOM) - st.utc_ns_at(1_000_000)
    assert elapsed == 1_000_000_000


def test_a_fast_converter_makes_a_second_of_samples_arrive_early():
    """+10ppm converter: 24000 samples take LESS than 1 s to arrive."""
    st = fresh(rate_ns_per_s=-10.0 * 1000.0)  # -y*1e9 with y = +10 ppm
    assert st.rate_ppm == pytest.approx(+10.0)
    span = st.utc_ns_at(1_000_000 + F_NOM) - st.utc_ns_at(1_000_000)
    assert span == pytest.approx(1_000_000_000 * (1 - 10e-6), rel=1e-9)


def test_the_counter_wrap_is_signed():
    st = fresh(rtp_ref=2**32 - 100)
    ahead = st.utc_ns_at(50)  # 150 samples past the reference, across the wrap
    expected = pytest.approx(150 * 1e9 / F_NOM, abs=2)
    assert ahead - st.utc_ns_at(2**32 - 100) == expected


def test_the_projection_stays_exact_just_inside_the_wrap_horizon():
    """Just under half a wrap (2**31 samples), the signed delta is exact."""
    st = fresh(rate_ns_per_s=0.0)
    delta = 2**31 - 1
    rtp = 1_000_000 + delta
    analytic = 1_788_729_000_000_000_000 + round(1e9 * delta / F_NOM)
    assert st.utc_ns_at(rtp) == pytest.approx(analytic, abs=1)


def test_predict_walks_phase_by_the_rate():
    st = fresh(rate_ns_per_s=-1000.0)
    st.predict(10.0, QUIET)
    assert st.phase_ns == pytest.approx(-10_000.0)


def test_predict_grows_the_covariance_and_couples_phase_to_rate():
    st = fresh(p=np.diag([100.0, 4.0]))
    st.predict(3.0, QUIET)
    # F P F' with F = [[1, tau], [0, 1]]
    assert st.p[PHASE, PHASE] == pytest.approx(100.0 + 9.0 * 4.0)
    assert st.p[PHASE, RATE] == pytest.approx(3.0 * 4.0)
    assert st.p[RATE, RATE] == pytest.approx(4.0)


def test_process_noise_widens_a_quiet_state():
    st = fresh(p=np.zeros((2, 2)))
    st.predict(10.0, RulerNoise(q1=0.0, q2=2.0, source="standin"))
    assert st.p[RATE, RATE] == pytest.approx(20.0)
    assert st.p[PHASE, PHASE] == pytest.approx(2.0 * 1000.0 / 3.0)


def test_a_perfect_phase_observation_pulls_phase_to_it():
    st = fresh(p=np.diag([1.0e6, 1.0]))
    nu = st.update(z=500.0, index=PHASE, r=1.0e-6)
    assert nu == pytest.approx(500.0)
    assert st.phase_ns == pytest.approx(500.0, rel=1e-3)
    assert st.p[PHASE, PHASE] < 1.0


def test_a_rate_observation_moves_rate_and_leaves_phase_near_where_it_was():
    st = fresh(p=np.diag([1.0, 1.0e6]))
    st.update(z=-60_000.0, index=RATE, r=1.0)
    assert st.rate_ppm == pytest.approx(+60.0, rel=1e-3)
    assert abs(st.phase_ns) < 1.0


def test_the_covariance_stays_symmetric_and_positive_through_many_updates():
    rng = np.random.default_rng(7)
    st = fresh(p=np.diag([1.0e8, 1.0e4]))
    for _ in range(500):
        st.predict(1.0, RulerNoise(q1=1.0, q2=1e-3, source="standin"))
        st.update(z=float(rng.normal(0.0, 1000.0)), index=PHASE, r=1.0e6)
    assert st.p[PHASE, RATE] == pytest.approx(st.p[RATE, PHASE])
    assert np.all(np.linalg.eigvals(st.p) > 0)


def test_innovation_does_not_mutate_the_state():
    st = fresh(p=np.diag([100.0, 1.0]))
    before = (st.phase_ns, st.rate_ns_per_s, st.p.copy())
    nu, s = st.innovation(z=1234.0, index=PHASE, r=25.0)
    assert nu == pytest.approx(1234.0)
    assert s == pytest.approx(125.0)
    assert (st.phase_ns, st.rate_ns_per_s) == before[:2]
    assert np.allclose(st.p, before[2])


def test_a_hundred_thousand_rebases_lose_no_nanoseconds():
    """The reference plane must survive rebasing exactly (spec section 2)."""
    st = fresh(rate_ns_per_s=-1234.5)
    control = fresh(rate_ns_per_s=-1234.5)

    rtp = 1_000_000
    # Not a whole second of samples, so the fractional-nanosecond carry bites.
    # And small enough that 100,000 of them stay inside HALF a counter wrap:
    # the control never rebases, so its own signed delta must remain
    # unambiguous. 100,000 x 24,007 = 2.4007e9 samples exceeds 2**31 and
    # aliases by exactly one wrap period (controller ruling R11, 2026-09-08).
    step = 12_007
    for _ in range(100_000):
        rtp += step
        st.rebase(rtp)

    # One nanosecond, not zero: the control's single projection is a float at
    # ~1e14 ns, where float64 resolves near 0.015 ns, so it need not round
    # identically to a sum of integers. A biased half-nanosecond error per
    # rebase would reach 50 microseconds here, so 1 ns still proves no
    # accumulation (controller ruling R4, 2026-09-08).
    assert abs(st.utc_ns_at(rtp) - control.utc_ns_at(rtp)) <= 1


def test_a_rebase_changes_no_belief():
    st = fresh(p=np.array([[100.0, 5.0], [5.0, 2.0]]))
    before = st.p.copy()
    st.rebase(1_000_000 + 5 * F_NOM)
    assert np.allclose(st.p, before)


def test_reseeding_phase_leaves_rate_and_its_variance_alone():
    """Spec section 4: a step never becomes a rate."""
    st = fresh(rate_ns_per_s=-750.0, p=np.array([[10.0, 3.0], [3.0, 9.0]]))
    st.reseed_phase(
        utc_ns=st.utc_ns_at(1_000_000) + 50_000_000,
        rtp=1_000_000,
        sigma_ns=2.0e6,
    )
    assert st.rate_ns_per_s == pytest.approx(-750.0)
    assert st.p[RATE, RATE] == pytest.approx(9.0)
    assert st.p[PHASE, RATE] == 0.0
    assert st.p[PHASE, PHASE] == pytest.approx((2.0e6) ** 2)
    assert st.phase_ns == pytest.approx(50_000_000.0, abs=1.0)
