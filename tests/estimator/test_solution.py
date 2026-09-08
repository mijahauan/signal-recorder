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
