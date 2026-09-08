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
        has_phase=True,
        phase_age_s=10.0,
        step_pending=False,
        sigma_phase_ns=1.0 * MS,
        coarse_delta_ns=None,
        coarse_sigma_ns=None,
        rate_spread_ppm=None,
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
        clean(has_phase=False),
        clean(phase_age_s=1e9),
        clean(step_pending=True),
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
]


@pytest.mark.parametrize("field,value", NAN_INF_CASES)
def test_not_finite_refusal_on_nan_and_infinity(field, value):
    assert refusal(clean(**{field: value}), CFG) == "not_finite"


COARSE_PARAMS = [(None, 25.0 * MS), (100.0 * MS, None)]


@pytest.mark.parametrize("delta,sigma", COARSE_PARAMS)
def test_a_half_reported_coarse_witness_does_not_refuse(delta, sigma):
    inputs = clean(coarse_delta_ns=delta, coarse_sigma_ns=sigma)
    assert refusal(inputs, CFG) is None
