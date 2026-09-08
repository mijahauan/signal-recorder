import pytest

from hf_timestd.estimator.gates import (
    REFUSAL_ORDER,
    GateConfig,
    GateInputs,
    refusal,
)

MS = 1_000_000.0
CFG = GateConfig()


def clean(**kw) -> GateInputs:
    args = dict(
        counter_ambiguous=False,
        has_phase=True,
        phase_age_s=10.0,
        step_pending=False,
        sigma_phase_ns=1.0 * MS,
        coarse_delta_ns=None,
        coarse_sigma_ns=None,
        rate_spread_ppm=None,
        n_updates=30,
        fit_scatter_ns=0.2 * MS,
    )
    args.update(kw)
    return GateInputs(**args)


def test_a_clean_state_publishes():
    assert refusal(clean(), CFG) is None


def test_no_phase_witness():
    assert refusal(clean(has_phase=False), CFG) == "no_phase_witness"


def test_stale_phase():
    assert refusal(clean(phase_age_s=301.0), CFG) == "stale_phase"


def test_step_pending():
    assert refusal(clean(step_pending=True), CFG) == "step_pending"


def test_variance():
    assert refusal(clean(sigma_phase_ns=5.1 * MS), CFG) == "variance"


def test_coarse_disagreement_beyond_three_combined_sigmas():
    inputs = clean(coarse_delta_ns=100.0 * MS, coarse_sigma_ns=25.0 * MS)
    assert refusal(inputs, CFG) == "coarse_disagreement"


def test_coarse_agreement_inside_the_budget_publishes():
    inputs = clean(coarse_delta_ns=30.0 * MS, coarse_sigma_ns=25.0 * MS)
    assert refusal(inputs, CFG) is None


def test_rate_disagreement_beyond_one_ppm():
    assert refusal(clean(rate_spread_ppm=1.5), CFG) == "rate_disagreement"


def test_rate_agreement_inside_one_ppm_publishes():
    assert refusal(clean(rate_spread_ppm=0.4), CFG) is None


def test_an_unstated_ruler_does_not_refuse():
    """Measurement model section 2: it widens sigma, it does not withhold."""
    assert refusal(clean(), GateConfig()) is None


def test_the_order_is_fixed_and_the_earliest_reason_wins():
    both = clean(
        phase_age_s=float("nan"),
        has_phase=False,
        step_pending=True,
        sigma_phase_ns=9e9,
        coarse_delta_ns=9e9,
        coarse_sigma_ns=1.0,
        rate_spread_ppm=9e9,
    )
    assert refusal(both, CFG) == REFUSAL_ORDER[0]
    # not_finite must be first
    assert REFUSAL_ORDER[0] == "not_finite"


def test_an_ambiguous_counter_outranks_every_reason_but_a_bad_number():
    """A plane read through an aliased delta is unmoored, not merely stale."""
    inputs = clean(
        counter_ambiguous=True,
        has_phase=False,
        phase_age_s=1e9,
        step_pending=True,
        sigma_phase_ns=9e9,
    )
    assert refusal(inputs, CFG) == "counter_ambiguous"
    assert REFUSAL_ORDER.index("counter_ambiguous") == 1
    assert REFUSAL_ORDER.index("counter_ambiguous") < REFUSAL_ORDER.index(
        "no_phase_witness"
    )
    # A bad number still wins, because it may be the reason for the rest.
    worse = clean(counter_ambiguous=True, phase_age_s=float("nan"))
    assert refusal(worse, CFG) == "not_finite"


def test_step_pending_outranks_variance():
    inputs = clean(step_pending=True, sigma_phase_ns=9e9)
    assert refusal(inputs, CFG) == "step_pending"
    idx_pending = REFUSAL_ORDER.index("step_pending")
    idx_variance = REFUSAL_ORDER.index("variance")
    assert idx_pending < idx_variance


def test_every_named_refusal_can_actually_fire():
    fired = set()
    for inputs in (
        clean(phase_age_s=float("nan")),
        clean(counter_ambiguous=True),
        clean(has_phase=False),
        clean(phase_age_s=1e9),
        clean(step_pending=True),
        clean(n_updates=1),
        clean(fit_scatter_ns=1e9),
        clean(sigma_phase_ns=1e9),
        clean(coarse_delta_ns=1e9, coarse_sigma_ns=1.0),
        clean(rate_spread_ppm=1e9),
    ):
        reason = refusal(inputs, CFG)
        assert reason is not None
        fired.add(reason)
    assert fired == set(REFUSAL_ORDER)


NAN_INF_CASES = [
    ("phase_age_s", float("nan")),
    ("phase_age_s", float("inf")),
    ("sigma_phase_ns", float("nan")),
    ("sigma_phase_ns", float("inf")),
    ("coarse_delta_ns", float("nan")),
    ("coarse_delta_ns", float("inf")),
    ("coarse_sigma_ns", float("nan")),
    ("coarse_sigma_ns", float("inf")),
    ("rate_spread_ppm", float("nan")),
    ("rate_spread_ppm", float("inf")),
    ("fit_scatter_ns", float("nan")),
    ("fit_scatter_ns", float("inf")),
]


@pytest.mark.parametrize("field,value", NAN_INF_CASES)
def test_not_finite_refusal_on_nan_and_infinity(field, value):
    assert refusal(clean(**{field: value}), CFG) == "not_finite"


COARSE_PARAMS = [(None, 25.0 * MS), (100.0 * MS, None)]


@pytest.mark.parametrize("delta,sigma", COARSE_PARAMS)
def test_a_half_reported_coarse_witness_does_not_refuse(delta, sigma):
    inputs = clean(coarse_delta_ns=delta, coarse_sigma_ns=sigma)
    assert refusal(inputs, CFG) is None


def test_a_thin_fit_refuses():
    """Too few accepted witnesses to have fitted anything worth publishing."""
    assert refusal(clean(n_updates=7), CFG) == "thin_fit"


def test_the_minimum_update_count_publishes():
    assert refusal(clean(n_updates=8), CFG) is None


def test_wide_fit_scatter_refuses():
    assert refusal(clean(fit_scatter_ns=2.1 * MS), CFG) == "fit_scatter"


def test_scatter_inside_the_bound_publishes():
    assert refusal(clean(fit_scatter_ns=1.9 * MS), CFG) is None


def test_an_unmeasured_scatter_does_not_refuse():
    """Too few rows to measure belongs to thin_fit, not to this gate."""
    assert refusal(clean(fit_scatter_ns=None), CFG) is None


def test_a_thin_fit_outranks_its_own_wide_variance():
    """Two witnesses on a two-state filter explain the wide sigma.

    Naming ``variance`` here would report the symptom and hide the cause: a
    filter with two updates has fitted a two-parameter plane exactly, so its
    sigma comes from the witness floor rather than from any goodness of fit.
    """
    inputs = clean(n_updates=2, sigma_phase_ns=9e9)
    assert refusal(inputs, CFG) == "thin_fit"


def test_an_exactly_determined_fit_shows_no_scatter_and_still_refuses():
    """The measured ND failure: 2 of 25 accepted, 0.019 ms scatter, -46.8 ppm.

    A two-state filter fed exactly two witnesses passes through both of them,
    so the scatter gate sees a perfect fit. Only the update count catches it.
    """
    inputs = clean(n_updates=2, fit_scatter_ns=0.019 * MS)
    assert refusal(inputs, CFG) == "thin_fit"


def test_both_new_reasons_appear_in_the_refusal_order():
    assert "thin_fit" in REFUSAL_ORDER
    assert "fit_scatter" in REFUSAL_ORDER


def test_a_thin_fit_is_named_before_the_variance_it_explains():
    assert REFUSAL_ORDER.index("thin_fit") < REFUSAL_ORDER.index("variance")
