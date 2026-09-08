"""Process noise, read off the ruler's own Allan deviation.

A governed ruler measures a small deviation, so the filter grows a long
memory and a witness barely nudges the rate. A free-running one measures a
large deviation, so the memory shortens to minutes and the same witnesses
track a rate that actually moves. One mechanism, two regimes, no branch
(spec section 6).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

# Copied from core/t6_holdover.py, which this package may not import.
# A synthesised GPSDO holding an RX888 measures 0.0004 ppm; the stand-in
# below sits 25x above that, and a free-running TCXO runs 0.5 to 2 ppm.
SIGMA_PPM_DISCIPLINED_STANDIN = 0.01
SIGMA_PPM_UNDISCIPLINED_STANDIN = 2.0

_DISCIPLINED_PROVENANCE = ("observed", "attested")
_NS_PER_S_PER_PPM = 1000.0
_MIN_ADEV_POINTS = 2
_DIMENSIONLESS_TO_NS = 1e18  # (ns/s)^2 per (s/s)^2


@dataclass(frozen=True)
class RulerNoise:
    """``q1`` in ns^2/s, ``q2`` in ns^2/s^3, and where they came from."""

    q1: float
    q2: float
    source: str

    def q_matrix(self, tau_s: float) -> np.ndarray:
        """The standard two-state process covariance over ``tau_s``."""
        tau = float(tau_s)
        q1_elem = self.q1 * tau + self.q2 * tau**3 / 3.0
        q2_elem = self.q2 * tau**2 / 2.0
        return np.array(
            [[q1_elem, q2_elem], [q2_elem, self.q2 * tau]], dtype=float
        )


def standin_sigma_ppm(provenance: str) -> float:
    """Undisciplined unless provenance is observed or attested."""
    if provenance in _DISCIPLINED_PROVENANCE:
        return SIGMA_PPM_DISCIPLINED_STANDIN
    return SIGMA_PPM_UNDISCIPLINED_STANDIN


def noise_from_standin(
    sigma_ppm: float, horizon_s: float = 3600.0
) -> RulerNoise:
    """Floor noise so rate uncertainty regrows to stand-in over horizon.

    ``q1`` stays zero deliberately. Phase white-frequency noise on any ruler
    we own sits below every witness sigma we have, and the innovation gate and
    the staleness refusal handle over-confidence in phase.
    """
    sigma_ns_per_s = float(sigma_ppm) * _NS_PER_S_PER_PPM
    q2 = sigma_ns_per_s**2 / float(horizon_s)
    return RulerNoise(q1=0.0, q2=q2, source="standin")


def noise_from_adev(
    taus: Sequence[float], adev: Sequence[float], floor: RulerNoise
) -> RulerNoise:
    """Fit ``q1`` at shortest tau and ``q2`` at longest, then floor both.

    Both fits err toward a wider, more agile filter when the noise type does
    not match the region, which keeps the error on the safe side.
    """
    tau_arr = np.asarray(taus, dtype=float)
    adev_arr = np.asarray(adev, dtype=float)
    good = (
        np.isfinite(tau_arr)
        & np.isfinite(adev_arr)
        & (tau_arr > 0)
        & (adev_arr > 0)
    )
    if int(good.sum()) < _MIN_ADEV_POINTS:
        return floor

    tau_arr, adev_arr = tau_arr[good], adev_arr[good]
    order = np.argsort(tau_arr)
    tau_arr, adev_arr = tau_arr[order], adev_arr[order]

    tau_short, adev_short = float(tau_arr[0]), float(adev_arr[0])
    tau_long, adev_long = float(tau_arr[-1]), float(adev_arr[-1])

    # This q1 reaches no assembled system, and that is deliberate rather
    # than an oversight. ``noise_from_standin`` floors q1 at zero, and
    # ``StationTimingEstimator._refit_noise`` keeps that floor and takes
    # only q2 from the fit -- so the value computed here is discarded on
    # every path the estimator uses. The short tau is exactly where witness
    # white phase noise dominates and the ruler's own contribution is
    # smallest, so a q1 read there measures the witnesses. Measured on a
    # governed ruler with 0.5 ms witnesses: q1 = 1.49e10 ns^2/s, crediting
    # the hardware with 866 microseconds of phase wander a minute where its
    # true wander is nanoseconds, and phase sigma then parked at 451
    # microseconds instead of averaging down (controller ruling R34,
    # 2026-09-08). The fit stays here, honest about what it found, for a
    # caller that wants the whole curve.
    q1 = adev_short**2 * tau_short * _DIMENSIONLESS_TO_NS
    q2 = 3.0 * adev_long**2 / tau_long * _DIMENSIONLESS_TO_NS
    if not (math.isfinite(q1) and math.isfinite(q2)):
        return floor
    return RulerNoise(
        q1=max(q1, floor.q1), q2=max(q2, floor.q2), source="measured"
    )
