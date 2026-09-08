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
    # The exact definition reads 10.000100 where the linear one read
    # 10.0 (controller ruling R29).
    assert st.rate_ppm == pytest.approx(+10.0, abs=1e-3)
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


def test_advance_folds_the_rate_into_the_plane():
    """The rate's effect on phase is folded into the plane at fold time.

    Replaces test_predict_walks_phase_by_the_rate: there is no longer a
    standalone phase-only extrapolation step (controller ruling, Task 4
    fix round 1, 2026-09-08) -- advance_to folds the whole offset, rate
    included, into the integer reference in one motion.
    """
    st = fresh(rate_ns_per_s=-1000.0)
    before_utc_ref = st.utc_ref_ns
    tau = st.advance_to(1_000_000 + 10 * F_NOM, QUIET)
    assert tau == pytest.approx(10.0)
    assert st.utc_ref_ns - before_utc_ref == 9_999_990_000
    assert st.phase_ns == pytest.approx(0.0, abs=1e-6)
    assert st.rate_ns_per_s == pytest.approx(-1000.0)


def test_advance_grows_the_covariance_and_couples_phase_to_rate():
    st = fresh(p=np.diag([100.0, 4.0]))
    st.advance_to(1_000_000 + 3 * F_NOM, QUIET)
    # F P F' with F = [[1, tau], [0, 1]]
    assert st.p[PHASE, PHASE] == pytest.approx(100.0 + 9.0 * 4.0)
    assert st.p[PHASE, RATE] == pytest.approx(3.0 * 4.0)
    assert st.p[RATE, RATE] == pytest.approx(4.0)


def test_process_noise_widens_a_quiet_state():
    st = fresh(p=np.zeros((2, 2)))
    noise = RulerNoise(q1=0.0, q2=2.0, source="standin")
    st.advance_to(1_000_000 + 10 * F_NOM, noise)
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
    noise = RulerNoise(q1=1.0, q2=1e-3, source="standin")
    rtp = 1_000_000
    for _ in range(500):
        rtp += F_NOM
        st.advance_to(rtp, noise)
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


def test_many_small_advances_equal_one_big_advance():
    """The no-double-count property. Nothing may extrapolate twice.

    Detects path-dependence (a fold losing or gaining ns across many small
    steps). Blind to a rate*tau double count: that defect is linear, so it
    scales identically whether folded once or many times, and this test
    cannot see it.
    """
    # 100 ppm: a double count would be loud.
    stepwise = fresh(rate_ns_per_s=-100_000.0)
    single = fresh(rate_ns_per_s=-100_000.0)
    end = 1_000_000 + 3600 * F_NOM
    for k in range(1, 3601):
        stepwise.advance_to(1_000_000 + k * F_NOM, QUIET)
    single.advance_to(end, QUIET)
    assert abs(stepwise.utc_ns_at(end) - single.utc_ns_at(end)) <= 1


def test_a_consumer_dividing_by_the_published_rate_agrees_exactly():
    """One arithmetic. The published rate must reproduce our own projection.

    Detects f_meas and utc_ns_at disagreeing with EACH OTHER. Blind to both
    being wrong the same way: it compares the module against itself, so a
    build that applies the rate twice in both places still agrees with
    itself.
    """
    st = fresh(rate_ns_per_s=-100_000.0)
    for delta in (F_NOM, 60 * F_NOM, 3600 * F_NOM):
        ours = st.utc_ns_at(1_000_000 + delta)
        theirs = st.utc_ref_ns + round(st.phase_ns + 1e9 * delta / st.f_meas)
        assert abs(ours - theirs) <= 1, f"delta={delta}"


def test_the_projection_matches_an_analytic_truth_from_the_physical_rate():
    """The expectation comes from f_true, not from what this module computes.

    Both of the other rate tests compare the module against itself, so a
    consistently wrong pair satisfies them. This one starts from a physical
    sample rate, computes the truth in exact rational arithmetic, and would
    catch a build that applied the rate twice by 36 ms over an hour
    (controller ruling R16, 2026-09-08).
    """
    from fractions import Fraction

    f_true = Fraction(2_400_024, 100)  # 24000.24 exactly, i.e. +10 ppm
    rate_ns_per_s = 10**9 * (Fraction(F_NOM, 1) / f_true - 1)

    st = fresh(rate_ns_per_s=float(rate_ns_per_s))
    delta = 3600 * F_NOM  # one hour of samples
    truth_ns = round(Fraction(10**9) * delta / f_true)

    span = st.utc_ns_at(1_000_000 + delta) - st.utc_ns_at(1_000_000)
    assert span == truth_ns


def test_a_hundred_thousand_advances_lose_no_nanoseconds():
    """The reference plane must survive folding exactly (spec section 2)."""
    st = fresh(rate_ns_per_s=-1234.5)
    control = fresh(rate_ns_per_s=-1234.5)

    rtp = 1_000_000
    # Not a whole second of samples, so the fractional-nanosecond carry
    # bites. And small enough that 100,000 of them stay inside HALF a
    # counter wrap: the control's own single big fold must remain
    # unambiguous too. 100,000 x 24,007 = 2.4007e9 samples would exceed
    # 2**31 and alias by exactly one wrap period (ruling R11, 2026-09-08).
    step = 12_007
    for _ in range(100_000):
        rtp += step
        st.advance_to(rtp, QUIET)
    control.advance_to(rtp, QUIET)

    # One nanosecond, not zero: floats at ~1e14 ns resolve near 0.015 ns,
    # so 100,000 small folds need not round identically to one big fold.
    # A biased half-nanosecond error per fold would reach 50 microseconds
    # here, so 1 ns still proves no accumulation (ruling R4, 2026-09-08).
    assert abs(st.utc_ns_at(rtp) - control.utc_ns_at(rtp)) <= 1


def test_a_zero_interval_advance_changes_no_belief():
    """Replaces test_a_rebase_changes_no_belief: tau=0 gives F=I, Q=0."""
    st = fresh(p=np.array([[100.0, 5.0], [5.0, 2.0]]))
    before = st.p.copy()
    st.advance_to(st.rtp_ref, QUIET)
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


def test_reseed_phase_accepts_now_and_refuses_backwards():
    """reseed_phase inherits advance_to's refusal to run backwards.

    At or after the current reference works: a step proposal's median
    innovation already lives at the current reference, so there is never a
    reason to reseed earlier than it. Reaching backwards raises, naming
    the direction.
    """
    st = fresh(rate_ns_per_s=-750.0, p=np.array([[10.0, 3.0], [3.0, 9.0]]))
    st.reseed_phase(
        utc_ns=st.utc_ns_at(1_000_000) + 1_000_000,
        rtp=1_000_000,
        sigma_ns=1.0e6,
    )
    assert st.rate_ns_per_s == pytest.approx(-750.0)

    earlier = fresh(
        rate_ns_per_s=-750.0,
        p=np.array([[10.0, 3.0], [3.0, 9.0]]),
    )
    earlier.advance_to(1_000_000 + F_NOM, QUIET)
    with pytest.raises(ValueError, match="backwards"):
        earlier.reseed_phase(utc_ns=0, rtp=1_000_000, sigma_ns=1.0e6)


def test_f_meas_refuses_a_stopped_or_reversed_clock():
    """A rate at or past -1e9 ns/s stops or reverses the clock; only a
    diverged filter reaches it, so f_meas names the rate and raises rather
    than dividing by zero or returning a negative rate.
    """
    st = fresh(rate_ns_per_s=-1_000_000_000.0)
    with pytest.raises(ValueError, match="-1000000000"):
        st.f_meas
