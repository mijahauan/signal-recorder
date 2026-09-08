"""Fitting a rate to a lag series, with an HONEST uncertainty.

Fading and ionospheric path drift move a correlation lag SMOOTHLY, and a
smooth drift is degenerate with a slope: no fit can tell one from the other
over a short span. Least squares assuming independent residuals is therefore
confident about exactly the thing it cannot see. The fit widens itself by the
standard effective-sample-size factor instead.

The thresholds below are MEASURED, not chosen: at ten points the inflation
reaches 1.82 on a smooth residual and 1.09 on a rough one of the same size,
and it falls to 1.04 by forty points. Repeatability across independent
recordings on 2026-09-08 came to 0.05 ppm at B4 and 0.15 ppm at ND, which the
widened sigma brackets and the naive one sits just under.
"""

import numpy as np
import pytest

from hf_timestd.replica.rate import MIN_POINTS, fit_rate

MIN_S = 60.0


def series(ppm, n=10, resid=None):
    t = np.arange(n, dtype=float) * MIN_S
    lag = t * ppm * 1e-6
    if resid is not None:
        lag = lag + np.asarray(resid, dtype=float)
    return t, lag


def test_an_exact_line_recovers_its_rate():
    t, lag = series(-60.0)
    r = fit_rate(t, lag)
    assert r.ppm == pytest.approx(-60.0, abs=1e-6)


def test_a_clean_line_reports_a_tiny_sigma():
    t, lag = series(+0.5)
    assert fit_rate(t, lag).sigma_ppm < 1e-6


def test_three_points_refuse_to_speak():
    """A LITERAL three, not ``MIN_POINTS - 1``.

    Deriving the count from the constant under test moves the test with the
    constant: lowering MIN_POINTS to 2 then leaves this asserting about one
    point, and passes. A mutation run caught exactly that.
    """
    t, lag = series(0.0, n=3)
    assert fit_rate(t, lag) is None


def test_the_minimum_leaves_room_for_a_residual_to_exist():
    """Two points fit a line exactly, so a third leaves one degree of freedom
    and a fourth is the fewest that can show an autocorrelation at all."""
    assert MIN_POINTS == 4


def test_four_points_do_speak():
    t, lag = series(-12.0, n=4)
    r = fit_rate(t, lag)
    assert r is not None
    assert r.ppm == pytest.approx(-12.0, abs=1e-6)


def test_correlated_residuals_widen_the_sigma_far_beyond_white_ones():
    """The same residual MAGNITUDE, smooth against rough.

    A half sine is symmetric about the span's midpoint, so it is orthogonal to
    the linear term and the fit absorbs NONE of it: the scatter survives into
    the residuals intact, where its smoothness -- not its size -- is what no
    slope can be told apart from a real rate. Matching the RMS of the two
    leaves ordering as the only difference between them.
    """
    rng = np.random.default_rng(7)
    n, amp = 10, 1e-4
    white = rng.normal(0.0, amp, n)
    bow = np.sin(np.pi * np.arange(n) / (n - 1))
    bow = bow * (np.std(white) / np.std(bow))
    t, lag_w = series(0.0, n=n, resid=white)
    _, lag_c = series(0.0, n=n, resid=bow)
    sw = fit_rate(t, lag_w).sigma_ppm
    sc = fit_rate(t, lag_c).sigma_ppm
    # Measured 1.668 at ten points; without the inflation it would be 1.0.
    assert sc > 1.5 * sw, f"correlated {sc:.4f} vs white {sw:.4f}"


def test_white_residuals_stay_close_to_the_naive_sigma():
    """No inflation where none is earned, or every rate becomes unusable."""
    rng = np.random.default_rng(11)
    t, lag = series(0.0, n=40, resid=rng.normal(0.0, 1e-4, 40))
    r = fit_rate(t, lag)
    # Measured 1.037 at forty points. A guard against OVER-inflation: widen
    # every rate threefold and no rate is usable any more.
    assert r.sigma_ppm < 1.2 * r.naive_sigma_ppm


def test_the_reported_sigma_covers_a_known_hard_case():
    """A smooth half-cycle of drift, the shape fading actually produces.

    A naive fit calls this a confident rate; an honest one admits the drift
    could be the slope. 0.2 ms of sag across ten minutes is 0.33 ppm of
    apparent rate, so a sigma under that would be lying.
    """
    t = np.arange(10, dtype=float) * MIN_S
    sag = -2e-4 * np.sin(np.pi * np.arange(10) / 9.0)
    r = fit_rate(t, t * 0.0 + sag)
    assert r.sigma_ppm > 0.2, f"sigma {r.sigma_ppm:.4f} too confident"
    # Measured 1.825; the naive fit alone would report 0.147 ppm here.
    assert r.sigma_ppm > 1.5 * r.naive_sigma_ppm, "no inflation was applied"
    assert r.rho > 0.5, f"rho {r.rho:.3f} should see the smoothness"
