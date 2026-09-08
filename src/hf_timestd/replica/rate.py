"""A rate from a lag series, with an uncertainty admitting what it cannot see.

The residuals are not independent. Fading and ionospheric path drift move a
correlation lag SMOOTHLY, and a smooth drift IS a slope as far as any fit can
tell, so least squares assuming independence is confident about precisely the
thing it cannot distinguish.

⚠ On what this is NOT calibrated against. An injection ladder -- resample a
recording by a known ppm and re-measure it -- looked like it exposed a 15
sigma error, and it does not: re-measuring the SAME recording re-uses the same
fading, which couples to the injection and produced scale errors from -6.3 %
to +4.1 % across four fixtures, sign included. Repeatability across
INDEPENDENT recordings is the measure that means something, and on 2026-09-08
it came to 0.05 ppm at B4 and 0.15 ppm at ND over spans hours apart. The
inflation below brackets those; the naive sigma sits just under them.

The correction is the standard effective-sample-size one: with lag-1
autocorrelation ``rho`` in the residuals, n independent points are worth
n(1-rho)/(1+rho), so the slope's sigma widens by sqrt((1+rho)/(1-rho)).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Two points determine a line exactly and leave no residual to read an
# autocorrelation from, so the honest floor sits above a line's own freedom.
MIN_POINTS = 4
# rho at 1 makes the inflation infinite, which is true in the limit and
# useless in practice: a pure ramp cannot be told from a rate at all. Cap it,
# and let the resulting sigma be large rather than unbounded.
MAX_RHO = 0.95


@dataclass(frozen=True)
class RateEstimate:
    """Parts per million, with both the honest and the naive uncertainty."""

    ppm: float
    sigma_ppm: float
    naive_sigma_ppm: float
    rho: float
    n: int


def _lag1_autocorrelation(resid: np.ndarray) -> float:
    var = float(np.dot(resid, resid))
    if var <= 0.0:
        return 0.0
    return float(np.dot(resid[:-1], resid[1:]) / var)


def fit_rate(times_s: np.ndarray, lags_s: np.ndarray) -> RateEstimate | None:
    """Fit ppm to a lag series, or ``None`` with too few points to speak."""
    t = np.asarray(times_s, dtype=float)
    y = np.asarray(lags_s, dtype=float)
    if len(t) != len(y):
        raise ValueError(f"{len(t)} times against {len(y)} lags")
    if len(t) < MIN_POINTS:
        return None
    design = np.vstack([t, np.ones_like(t)]).T
    (slope, intercept), *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ np.array([slope, intercept])
    dof = len(t) - 2
    s_err_sq = float(np.dot(resid, resid)) / dof
    naive_var = s_err_sq * float(np.linalg.inv(design.T @ design)[0, 0])
    naive_sigma = float(np.sqrt(max(naive_var, 0.0)))
    rho = min(max(_lag1_autocorrelation(resid), 0.0), MAX_RHO)
    # Only ever widen. A negative autocorrelation says the residuals
    # alternate, which does not license MORE confidence in the slope than
    # independence would -- it just means the noise is not drift.
    inflation = float(np.sqrt((1.0 + rho) / (1.0 - rho)))
    return RateEstimate(
        ppm=slope * 1e6,
        sigma_ppm=naive_sigma * inflation * 1e6,
        naive_sigma_ppm=naive_sigma * 1e6,
        rho=rho,
        n=len(t),
    )
