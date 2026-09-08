import math

import pytest

from hf_timestd.estimator.solution import (
    VERDICT_PUBLISH,
    VERDICT_WITHHOLD,
    TimingSolution,
)

F_NOM = 24000


def f_meas_for(ppm: float) -> float:
    """The published rate, exactly, as the estimator derives it.

    NOT F_NOM * (1 + ppm/1e6). At 60 ppm that linearisation lands 3.6 ns off
    the projection it is supposed to reproduce, which fails the tolerance
    below and, worse, would put two arithmetics in the one place this library
    exists to have one (controller ruling R13, 2026-09-08).
    """
    return F_NOM * 1e9 / (1e9 + (-ppm * 1000.0))


def make(**kw: object) -> TimingSolution:
    args: dict[str, object] = dict(
        rtp_ref=1_000_000,
        utc_ref_ns=1_788_729_000_000_000_000,
        phase_ns=0.25,
        sigma_phase_ns=1.0e6,
        rate_ppm=+0.03,
        sigma_rate_ppm=0.05,
        rate_samples_per_utc_sec=f_meas_for(+0.03),
        covariance=(1.0e12, 0.0, 2.5e-3),
        verdict=VERDICT_PUBLISH,
        refusal=None,
        witnesses={"T3": {"accepted": 12, "rejected": 0}},
        a_level="A1",
        ruler_provenance="observed",
        q_source="measured",
        span_s=600.0,
        n_updates=12,
        generation=1,
    )
    args.update(kw)
    return TimingSolution(**args)  # type: ignore[arg-type]


def test_a_solution_projects_through_its_own_measured_rate():
    sol = make(rate_ppm=+60.0, rate_samples_per_utc_sec=f_meas_for(+60.0))
    span = sol.utc_ns_at(1_000_000 + F_NOM) - sol.utc_ns_at(1_000_000)
    assert span == pytest.approx(1_000_000_000 * (1 - 60e-6), rel=1e-9)


def test_the_reference_sample_reads_back_the_plane():
    sol = make(phase_ns=0.0)
    assert sol.utc_ns_at(1_000_000) == 1_788_729_000_000_000_000


def test_the_published_projection_carries_the_phase_residual():
    """Every other test here uses a phase of 0.25 ns or of nothing.

    Drop ``phase_ns`` from ``utc_ns_at`` entirely and they all still pass,
    because a quarter of a nanosecond rounds to zero. The residual is the
    correction the whole plane exists to carry, so one test asserts it at a
    size a reader can see.
    """
    sol = make(phase_ns=5.0e6)
    assert sol.utc_ns_at(1_000_000) == 1_788_729_000_000_000_000 + 5_000_000


def test_the_projection_rounds_once_on_the_sum():
    """Spec section 1 rounds once. Two roundings cost up to a nanosecond.

    Two samples at exactly 24 kHz span 83,333.333 ns. Add 0.3 ns of phase
    and the sum rounds to 83,334; round the two parts separately and the
    phase vanishes first, leaving 83,333.
    """
    sol = make(
        phase_ns=0.3, rate_ppm=0.0, rate_samples_per_utc_sec=float(F_NOM)
    )
    assert sol.utc_ns_at(1_000_002) - sol.utc_ref_ns == 83_334


def test_a_withheld_solution_still_carries_its_numbers_and_its_reason():
    sol = make(verdict=VERDICT_WITHHOLD, refusal="rate_disagreement")
    assert sol.refusal == "rate_disagreement"
    assert sol.rate_ppm == pytest.approx(+0.03)
    assert sol.utc_ns_at(1_000_000 + F_NOM) > sol.utc_ref_ns


def test_a_solution_is_frozen():
    sol = make()
    with pytest.raises(Exception):
        sol.rate_ppm = 9.0  # type: ignore[misc]


def test_a_publishing_solution_carries_no_refusal():
    with pytest.raises(ValueError, match="refusal"):
        make(verdict=VERDICT_PUBLISH, refusal="variance")


def test_a_withholding_solution_must_name_a_reason():
    with pytest.raises(ValueError, match="refusal"):
        make(verdict=VERDICT_WITHHOLD, refusal=None)


def test_the_public_surface_exports_the_solution():
    import hf_timestd.estimator as pkg

    assert "TimingSolution" in pkg.__all__


def test_witnesses_are_deep_frozen_against_mutation():
    original_witnesses: dict[str, dict[str, int]] = {
        "T3": {"accepted": 12, "rejected": 0}
    }
    sol = make(witnesses=original_witnesses)

    # Attempt to mutate the nested dict should fail
    with pytest.raises(TypeError):
        sol.witnesses["T3"]["accepted"] = 999999  # type: ignore[index]

    # Mutating the original dict passed in should not affect the solution
    original_witnesses["T3"]["accepted"] = 999999
    assert sol.witnesses["T3"]["accepted"] == 12  # type: ignore[index]


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("phase_ns", float("nan")),
        ("phase_ns", float("inf")),
        ("phase_ns", float("-inf")),
        ("sigma_phase_ns", float("nan")),
        ("sigma_phase_ns", float("inf")),
        ("rate_ppm", float("nan")),
        ("rate_ppm", float("inf")),
        ("sigma_rate_ppm", float("nan")),
        ("sigma_rate_ppm", float("inf")),
        ("rate_samples_per_utc_sec", float("nan")),
        ("rate_samples_per_utc_sec", float("inf")),
        ("covariance", (float("nan"), 0.0, 2.5e-3)),
        ("covariance", (float("inf"), 0.0, 2.5e-3)),
        ("covariance", (1.0e12, float("nan"), 2.5e-3)),
        ("covariance", (1.0e12, float("inf"), 2.5e-3)),
        ("covariance", (1.0e12, 0.0, float("nan"))),
        ("covariance", (1.0e12, 0.0, float("inf"))),
        ("span_s", float("nan")),
        ("span_s", float("inf")),
    ],
)
def test_non_finite_floats_are_refused(field_name: str, value: object) -> None:
    with pytest.raises(ValueError, match="not finite"):
        make(**{field_name: value})


def test_zero_rate_is_refused():
    with pytest.raises(ValueError, match="strictly positive"):
        make(rate_samples_per_utc_sec=0.0)


def test_negative_rate_is_refused():
    with pytest.raises(ValueError, match="strictly positive"):
        make(rate_samples_per_utc_sec=-24000.0)


def test_a_not_finite_withholding_solution_may_carry_a_nan():
    """The one place a non-finite float is the honest answer.

    The gates' first refusal names a state that carries a NaN. If the record
    that reports that refusal cannot itself hold the NaN, the only way to
    publish the refusal is to zero the numbers and call them real, which is
    the one thing this instrument must never do (controller ruling R28).
    """
    sol = make(
        verdict=VERDICT_WITHHOLD,
        refusal="not_finite",
        phase_ns=float("nan"),
    )
    assert sol.refusal == "not_finite"
    assert math.isnan(sol.phase_ns)


@pytest.mark.parametrize(
    "refusal",
    ["no_phase_witness", "stale_phase", "step_pending", "variance"],
)
def test_a_nan_still_fails_under_every_other_refusal(refusal: str) -> None:
    with pytest.raises(ValueError, match="not finite"):
        make(
            verdict=VERDICT_WITHHOLD,
            refusal=refusal,
            phase_ns=float("nan"),
        )


def test_a_rate_not_positive_solution_may_carry_the_rate_that_refused_it():
    """The estimator publishes every cycle, so this record must construct.

    Refusing to build it made ``solve`` raise, which crashes a caller in a
    loop rather than handing it a refusal (controller ruling R37).
    """
    sol = make(
        verdict=VERDICT_WITHHOLD,
        refusal="rate_not_positive",
        rate_samples_per_utc_sec=-24000.0,
    )
    assert sol.refusal == "rate_not_positive"
    assert sol.rate_samples_per_utc_sec == -24000.0


@pytest.mark.parametrize(
    "refusal",
    ["no_phase_witness", "counter_ambiguous", "stale_phase", "variance"],
)
def test_a_bad_rate_still_fails_under_every_other_refusal(
    refusal: str,
) -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        make(
            verdict=VERDICT_WITHHOLD,
            refusal=refusal,
            rate_samples_per_utc_sec=0.0,
        )
