import pytest

from hf_timestd.estimator.observations import (
    NS_PER_S_PER_PPM,
    PLANE_HOST,
    PLANE_LABEL,
    PhaseObservation,
    RateObservation,
)


def test_a_phase_observation_names_a_sample_and_its_utc():
    obs = PhaseObservation(
        tier="T3",
        rtp=1_000_000,
        utc_ns=1_788_729_000_000_000_000,
        sigma_ns=1.0e6,
        plane=PLANE_LABEL,
        source="registration",
    )
    assert obs.rtp == 1_000_000
    assert obs.is_label_plane is True


def test_a_host_plane_observation_says_so():
    obs = PhaseObservation(
        tier="T2",
        rtp=5,
        utc_ns=7,
        sigma_ns=25.0e6,
        plane=PLANE_HOST,
        source="ntp-pool",
    )
    assert obs.is_label_plane is False


def test_a_rate_observation_converts_ppm_to_nanoseconds_per_second():
    """A converter running FAST gives positive ppm and a NEGATIVE state rate.

    Spec section 1: rate_ns_per_s = -y * 1e9, and 1 ppm = 1000 ns/s.
    """
    obs = RateObservation(
        tier="T6",
        ppm=+2.0,
        sigma_ppm=0.5,
        span_s=900.0,
        n=900,
        plane=PLANE_LABEL,
        source="t6-residual",
    )
    assert obs.ns_per_s == pytest.approx(-2000.0)
    assert obs.sigma_ns_per_s == pytest.approx(500.0)
    assert NS_PER_S_PER_PPM == 1000.0


def test_a_slow_converter_gives_a_positive_state_rate():
    obs = RateObservation(
        tier="T6",
        ppm=-60.0,
        sigma_ppm=1.0,
        span_s=600.0,
        n=30,
        plane=PLANE_LABEL,
        source="fold-drift",
    )
    assert obs.ns_per_s == pytest.approx(+60_000.0)


@pytest.mark.parametrize("plane", ["", "Label", "host ", "anchor"])
def test_an_unknown_plane_is_refused(plane):
    with pytest.raises(ValueError, match="plane"):
        PhaseObservation(
            tier="T3",
            rtp=1,
            utc_ns=2,
            sigma_ns=1.0,
            plane=plane,
            source="x",
        )


@pytest.mark.parametrize("sigma", [0.0, -1.0, float("nan"), float("inf")])
def test_a_useless_sigma_is_refused(sigma):
    with pytest.raises(ValueError, match="sigma"):
        PhaseObservation(
            tier="T3",
            rtp=1,
            utc_ns=2,
            sigma_ns=sigma,
            plane=PLANE_LABEL,
            source="x",
        )


def test_observations_are_frozen():
    obs = PhaseObservation(
        tier="T3",
        rtp=1,
        utc_ns=2,
        sigma_ns=1.0,
        plane=PLANE_LABEL,
        source="x",
    )
    with pytest.raises(Exception):
        obs.rtp = 9  # type: ignore[misc]
