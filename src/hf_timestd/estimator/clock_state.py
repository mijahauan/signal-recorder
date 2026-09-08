"""Two numbers, a reference plane, and the arithmetic that keeps them exact.

Phase in nanoseconds against an integer plane, and its rate of change in
nanoseconds per second. This is the standard two-state clock model: the
elapsed time between two sample indices is always NOMINAL seconds (sample
count over the nominal rate), and the ruler's actual rate enters only
through the phase state -- which is what the Allan-variance process noise
from ``process_noise`` already assumes. Nothing extrapolates twice: the
reference plane moves WITH the state, in the same method. The host clock
appears nowhere (spec sections 1 and 2).
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

# Used only inside reseed_phase, so a reseed folds the plane without also
# growing the covariance -- the rate and its variance survive untouched.
_ZERO_NOISE = RulerNoise(q1=0.0, q2=0.0, source="reseed")


def signed_rtp_delta(rtp_from: int, rtp_to: int) -> int:
    """The shortest signed distance across a 32-bit counter wrap.

    This only resolves the true distance while ``rtp_from`` and ``rtp_to``
    sit within HALF a wrap period of one another: 2**31 samples, roughly
    24.9 hours at a 24 kHz sample rate. Past that horizon the two readings
    are indistinguishable, mod 2**32, from a pair half a wrap closer
    together, and the result silently aliases by a full wrap period rather
    than raising. A caller must therefore re-reference (``rtp_from``) more
    often than that horizon; this estimator does, by folding its plane
    forward on every solve.
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

    def _utc_ns_per_ruler_s(self) -> float:
        """How many nanoseconds of UTC one nominal second of ruler spans.

        The denominator both ``f_meas`` and ``rate_ppm`` are built on, so the
        two carry one guard and one arithmetic between them.

        Refuses a rate at or past -1e9 ns/s: that stops or reverses the
        clock, which only a diverged filter reaches, and dividing by the
        resulting zero or negative denominator would otherwise raise an
        incidental ``ZeroDivisionError`` or return a negative rate.
        """
        denom = _NS_PER_S + self.rate_ns_per_s
        if denom <= 0.0:
            raise ValueError(
                f"rate {self.rate_ns_per_s!r} ns/s stops or reverses the clock"
            )
        return denom

    @property
    def rate_ppm(self) -> float:
        """The ruler's fractional frequency offset, in parts per million.

        This is ``y``, which spec section 1 defines as the measured rate's
        excess over the nominal rate taken as a fraction of it. So a reader
        of this name cannot find two answers to one question. The linear
        ``-rate_ns_per_s / 1000`` only ever approximated it and disagreed by
        0.0036 ppm at 60 (controller ruling R29, 2026-09-08). Positive when
        the converter samples fast.

        Written as ``-rate_ns_per_s * 1e6 / (1e9 + rate_ns_per_s)``, which
        is that ratio rearranged, for two reasons. The nominal rate cancels
        out of the identity exactly, so naming it would spend the package's
        one sanctioned nominal division on a division that need not happen.
        And subtracting one from a ratio sitting within a hundred parts per
        million of unity throws away five significant digits to
        cancellation, where this form keeps them all.

        ``sigma_rate_ppm`` stays linear beside it: a sigma's second-order
        correction carries no meaning.
        """
        return -self.rate_ns_per_s * 1.0e6 / self._utc_ns_per_ruler_s()

    @property
    def f_meas(self) -> float:
        """The measured sample rate, exactly.

        NOT ``f_nom * (1 + rate_ppm / 1e6)``. That linearisation and the
        projection in ``_offset_ns_at`` disagree at second order, which is
        how one arithmetic quietly becomes two: over an hour at 100 ppm the
        gap reaches 36 microseconds. A consumer dividing by this value
        reproduces ``utc_ns_at`` to the nanosecond.
        """
        return self.f_nom * _NS_PER_S / self._utc_ns_per_ruler_s()

    @property
    def sigma_phase_ns(self) -> float:
        return math.sqrt(max(float(self.p[PHASE, PHASE]), 0.0))

    @property
    def sigma_rate_ppm(self) -> float:
        sigma_ns_per_s = math.sqrt(max(float(self.p[RATE, RATE]), 0.0))
        return sigma_ns_per_s / _NS_PER_S_PER_PPM

    def _nominal_seconds(self, delta_samples: int) -> float:
        """Nominal elapsed time over a sample count.

        The one line in this package that divides by the nominal rate. The
        ruler's actual rate enters through the phase state instead, which is
        what the two-state clock model and its Allan-variance Q assume.
        """
        return delta_samples / self.f_nom  # THE ONE NOMINAL DIVISION

    def elapsed_s(self, rtp_from: int, rtp_to: int) -> float:
        """Nominal seconds between two samples."""
        return self._nominal_seconds(signed_rtp_delta(rtp_from, rtp_to))

    # ---- projection -----------------------------------------------------

    def _offset_ns_at(self, rtp: int) -> float:
        """Nanoseconds from the plane's integer reference to UTC at ``rtp``."""
        tau = self._nominal_seconds(signed_rtp_delta(self.rtp_ref, rtp))
        return self.phase_ns + (_NS_PER_S + self.rate_ns_per_s) * tau

    def utc_ns_at(self, rtp: int) -> int:
        """UTC of the sample at ``rtp``, through the current plane and rate."""
        return self.utc_ref_ns + round(self._offset_ns_at(rtp))

    # ---- the filter -----------------------------------------------------

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
        if self.p[index, index] < 0.0 or s <= 0.0:
            raise ValueError(
                f"covariance diag {float(self.p[index, index])!r} or "
                f"innovation variance {s!r} is not usable"
            )
        k = self.p[:, index] / s
        self.x = self.x + k * nu
        self.p = self.p - np.outer(k, self.p[index, :])
        self._symmetrise()
        return nu

    def _symmetrise(self) -> None:
        self.p = 0.5 * (self.p + self.p.T)

    # ---- plane maintenance ---------------------------------------------

    def advance_to(self, rtp_now: int, noise: RulerNoise) -> float:
        """Move the state and its plane to ``rtp_now``; return the interval.

        Folds the whole nanoseconds into the integer reference and keeps the
        fraction, so the plane loses nothing. Grows the covariance over the
        same interval. Refuses to run backwards.
        """
        delta = signed_rtp_delta(self.rtp_ref, rtp_now)
        tau = self._nominal_seconds(delta)
        if tau < 0.0:
            raise ValueError(f"advance_to went backwards by {-tau} s")
        total = self._offset_ns_at(rtp_now)
        whole = math.floor(total)
        self.utc_ref_ns += int(whole)
        self.rtp_ref = int(rtp_now)
        f = np.array([[1.0, tau], [0.0, 1.0]], dtype=float)
        self.p = f @ self.p @ f.T + noise.q_matrix(tau)
        self.x[PHASE] = total - whole
        self._symmetrise()
        return tau

    def reseed_phase(self, utc_ns: int, rtp: int, sigma_ns: float) -> None:
        """Place phase from an observation, and leave the rate exactly alone.

        A wrong lock arrives as a step. Absorbing a step into rate fabricates
        a frequency error and projects it forward forever, so the rate state
        and its variance survive a reseed untouched (spec section 4). The
        internal fold uses zero process noise so the interval crossed to
        reach ``rtp`` cannot grow the rate's variance either.

        Inherits ``advance_to``'s refusal to run backwards: ``rtp`` must sit
        at or after the current reference. A step proposal's median
        innovation already lives at the current reference, so there is no
        reason to reseed earlier than it; a caller that tries raises
        ``ValueError`` naming the direction.
        """
        self.advance_to(rtp, _ZERO_NOISE)
        self.x[PHASE] = float(int(utc_ns) - self.utc_ref_ns)
        self.p[PHASE, PHASE] = float(sigma_ns) ** 2
        self.p[PHASE, RATE] = 0.0
        self.p[RATE, PHASE] = 0.0
