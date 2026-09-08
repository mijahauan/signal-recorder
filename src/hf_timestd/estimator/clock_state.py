"""Two numbers, a reference plane, and the arithmetic that keeps them exact.

Phase in nanoseconds against an integer plane, and its rate of change in
nanoseconds per second. Elapsed time always means sample count over the
MEASURED rate. The host clock appears nowhere (spec sections 1 and 2).
"""

from __future__ import annotations

import math

import numpy as np

from .process_noise import RulerNoise

PHASE = 0
RATE = 1

_NS_PER_S = 1_000_000_000
_NS_PER_S_PER_PPM = 1000.0
_WRAP = 2**32
_HALF_WRAP = 2**31


def signed_rtp_delta(rtp_from: int, rtp_to: int) -> int:
    """The shortest signed distance across a 32-bit counter wrap.

    This only resolves the true distance while ``rtp_from`` and ``rtp_to``
    sit within HALF a wrap period of one another: 2**31 samples, roughly
    24.9 hours at a 24 kHz sample rate. Past that horizon the two readings
    are indistinguishable, mod 2**32, from a pair half a wrap closer
    together, and the result silently aliases by a full wrap period rather
    than raising. A caller must therefore re-reference (``rtp_from``) more
    often than that horizon; this estimator does, by rebasing its plane on
    every solve.
    """
    return ((int(rtp_to) - int(rtp_from) + _HALF_WRAP) % _WRAP) - _HALF_WRAP


class ClockState:
    """The station's clock: a plane, a residual, a rate, and a covariance."""

    def __init__(
        self,
        f_nom: int,
        rtp_ref: int,
        utc_ref_ns: int,
        phase_ns: float = 0.0,
        rate_ns_per_s: float = 0.0,
        p: np.ndarray | None = None,
    ) -> None:
        if int(f_nom) <= 0:
            raise ValueError(f"nominal rate {f_nom!r} makes no ruler")
        self.f_nom = int(f_nom)
        self.rtp_ref = int(rtp_ref)
        self.utc_ref_ns = int(utc_ref_ns)
        self.x = np.array([float(phase_ns), float(rate_ns_per_s)], dtype=float)
        self.p = np.eye(2) if p is None else np.array(p, dtype=float)

    # ---- readings -------------------------------------------------------

    @property
    def phase_ns(self) -> float:
        return float(self.x[PHASE])

    @property
    def rate_ns_per_s(self) -> float:
        return float(self.x[RATE])

    @property
    def rate_ppm(self) -> float:
        """Positive when the converter samples fast (spec section 1)."""
        return -self.rate_ns_per_s / _NS_PER_S_PER_PPM

    @property
    def f_meas(self) -> float:
        """The measured sample rate. The one place the nominal rate divides."""
        y = -self.rate_ns_per_s / _NS_PER_S
        return self.f_nom * (1.0 + y)

    @property
    def sigma_phase_ns(self) -> float:
        return math.sqrt(max(float(self.p[PHASE, PHASE]), 0.0))

    @property
    def sigma_rate_ppm(self) -> float:
        sigma_ns_per_s = math.sqrt(max(float(self.p[RATE, RATE]), 0.0))
        return sigma_ns_per_s / _NS_PER_S_PER_PPM

    def elapsed_s(self, rtp_from: int, rtp_to: int) -> float:
        """Seconds between two samples, by the measured rate."""
        return signed_rtp_delta(rtp_from, rtp_to) / self.f_meas

    # ---- projection -----------------------------------------------------

    def _projection_ns(self, rtp: int) -> float:
        return _NS_PER_S * signed_rtp_delta(self.rtp_ref, rtp) / self.f_meas

    def utc_ns_at(self, rtp: int) -> int:
        """UTC of the sample at ``rtp``, through the current plane and rate."""
        projection = round(self._projection_ns(rtp))
        return self.utc_ref_ns + round(self.phase_ns) + projection

    # ---- the filter -----------------------------------------------------

    def predict(self, tau_s: float, noise: RulerNoise) -> None:
        tau = float(tau_s)
        f = np.array([[1.0, tau], [0.0, 1.0]], dtype=float)
        self.x = f @ self.x
        self.p = f @ self.p @ f.T + noise.q_matrix(tau)
        self._symmetrise()

    def innovation(
        self,
        z: float,
        index: int,
        r: float,
    ) -> tuple[float, float]:
        """``(nu, s)`` for a scalar observation, without touching the state."""
        nu = float(z) - float(self.x[index])
        s = float(self.p[index, index]) + float(r)
        return nu, s

    def update(self, z: float, index: int, r: float) -> float:
        nu, s = self.innovation(z, index, r)
        if s <= 0.0:
            raise ValueError(f"innovation variance {s!r} is not positive")
        k = self.p[:, index] / s
        self.x = self.x + k * nu
        self.p = self.p - np.outer(k, self.p[index, :])
        self._symmetrise()
        return nu

    def _symmetrise(self) -> None:
        self.p = 0.5 * (self.p + self.p.T)

    # ---- plane maintenance ---------------------------------------------

    def rebase(self, rtp_now: int) -> None:
        """Move the plane to ``rtp_now``, keeping the fractional nanosecond."""
        total = self.phase_ns + self._projection_ns(rtp_now)
        whole = math.floor(total)
        self.utc_ref_ns += int(whole)
        self.x[PHASE] = total - whole
        self.rtp_ref = int(rtp_now)

    def reseed_phase(self, utc_ns: int, rtp: int, sigma_ns: float) -> None:
        """Place phase from an observation, and leave the rate exactly alone.

        A wrong lock arrives as a step. Absorbing a step into rate fabricates
        a frequency error and projects it forward forever, so the rate state
        and its variance survive a reseed untouched (spec section 4).
        """
        self.rebase(rtp)
        self.x[PHASE] = float(int(utc_ns) - self.utc_ref_ns)
        self.p[PHASE, PHASE] = float(sigma_ns) ** 2
        self.p[PHASE, RATE] = 0.0
        self.p[RATE, PHASE] = 0.0
