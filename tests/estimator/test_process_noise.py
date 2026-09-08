import numpy as np
import pytest

from hf_timestd.estimator.process_noise import (
    SIGMA_PPM_DISCIPLINED_STANDIN,
    SIGMA_PPM_UNDISCIPLINED_STANDIN,
    RulerNoise,
    noise_from_adev,
    noise_from_standin,
    standin_sigma_ppm,
)

NO_FLOOR = RulerNoise(q1=0.0, q2=0.0, source="standin")


def test_white_frequency_noise_recovers_its_own_coefficient():
    """sigma_y(tau) = A / sqrt(tau) implies q1 = A**2 * 1e18."""
    amplitude = 3.0e-9
    taus = np.array([1.0, 2.0, 4.0, 8.0, 16.0, 32.0])
    adev = amplitude / np.sqrt(taus)
    noise = noise_from_adev(taus, adev, floor=NO_FLOOR)
    assert noise.q1 == pytest.approx(amplitude**2 * 1e18, rel=0.01)
    assert noise.source == "measured"


def test_random_walk_frequency_noise_recovers_its_own_coefficient():
    """sigma_y(tau) = B * sqrt(tau) implies q2 = 3 * B**2 * 1e18."""
    amplitude = 2.0e-11
    taus = np.array([10.0, 100.0, 1000.0])
    adev = amplitude * np.sqrt(taus)
    noise = noise_from_adev(taus, adev, floor=NO_FLOOR)
    assert noise.q2 == pytest.approx(3.0 * amplitude**2 * 1e18, rel=0.01)


def test_the_floor_is_never_undercut():
    taus = np.array([1.0, 2.0, 4.0])
    adev = np.array([1e-15, 1e-15, 1e-15])
    floor = RulerNoise(q1=500.0, q2=7.0, source="standin")
    noise = noise_from_adev(taus, adev, floor=floor)
    assert noise.q1 >= floor.q1
    assert noise.q2 >= floor.q2


def test_too_few_points_falls_back_to_the_floor_and_says_so():
    taus = np.array([1.0])
    adev = np.array([1e-12])
    floor = RulerNoise(q1=500.0, q2=7.0, source="standin")
    noise = noise_from_adev(taus, adev, floor=floor)
    assert noise == floor
    assert noise.source == "standin"


def test_a_standin_forgets_back_to_its_sigma_over_the_horizon():
    """Rate variance regrows to standin when no witness over horizon."""
    horizon = 3600.0
    noise = noise_from_standin(  # noqa: E501
        SIGMA_PPM_UNDISCIPLINED_STANDIN, horizon_s=horizon
    )
    sigma_ns_per_s = SIGMA_PPM_UNDISCIPLINED_STANDIN * 1000.0
    assert noise.q2 * horizon == pytest.approx(  # noqa: E501
        sigma_ns_per_s**2, rel=1e-9
    )
    assert noise.q1 == 0.0
    assert noise.source == "standin"


@pytest.mark.parametrize(
    "provenance,expected",
    [
        ("observed", SIGMA_PPM_DISCIPLINED_STANDIN),
        ("attested", SIGMA_PPM_DISCIPLINED_STANDIN),
        ("assumed", SIGMA_PPM_UNDISCIPLINED_STANDIN),
        ("", SIGMA_PPM_UNDISCIPLINED_STANDIN),
        ("nonsense", SIGMA_PPM_UNDISCIPLINED_STANDIN),
    ],
)
def test_an_unstated_ruler_counts_as_undisciplined(provenance, expected):
    """Measurement model section 2: never silently assume discipline."""
    assert standin_sigma_ppm(provenance) == expected


def test_the_standin_numbers_have_not_drifted_from_the_core():
    """This package may not import the core, so a test compares the copies."""
    from hf_timestd.core.t6_holdover import (
        UNMEASURED_RATE_SIGMA_PPM,
        UNMEASURED_RATE_SIGMA_PPM_A0,
    )

    assert SIGMA_PPM_DISCIPLINED_STANDIN == UNMEASURED_RATE_SIGMA_PPM
    assert SIGMA_PPM_UNDISCIPLINED_STANDIN == UNMEASURED_RATE_SIGMA_PPM_A0
