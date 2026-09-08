"""What a witness may say to the estimator.

Two statements, and no others. A phase observation names a sample and gives
its UTC. A rate observation gives parts per million. Each declares the plane
it was measured on, because a host-plane observation may reach the refusal
gates and must never reach the filter (spec section 3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

PLANE_LABEL = "label"
PLANE_HOST = "host"
_PLANES = (PLANE_LABEL, PLANE_HOST)

# 1 ppm of frequency error walks the phase correction by 1000 ns every second.
# Mirrors PPM_PER_NS_PER_S = 1.0/1000.0 in core/offset_judge.py, redefined here
# because this package may not import the core (spec section 7).
NS_PER_S_PER_PPM = 1000.0


def _check_plane(plane: str) -> None:
    if plane not in _PLANES:
        raise ValueError(f"plane {plane!r} names neither {_PLANES}")


def _check_sigma(sigma: float, what: str) -> None:
    if not math.isfinite(sigma) or sigma <= 0.0:
        raise ValueError(f"{what} sigma {sigma!r} carries no information")


@dataclass(frozen=True)
class PhaseObservation:
    """The sample at ``rtp`` carried UTC ``utc_ns``, to within ``sigma_ns``."""

    tier: str
    rtp: int
    utc_ns: int
    sigma_ns: float
    plane: str
    source: str

    def __post_init__(self) -> None:
        _check_plane(self.plane)
        _check_sigma(self.sigma_ns, "phase")

    @property
    def is_label_plane(self) -> bool:
        return self.plane == PLANE_LABEL


@dataclass(frozen=True)
class RateObservation:
    """The ruler runs ``ppm`` parts per million fast.

    To within ``sigma_ppm``.
    """

    tier: str
    ppm: float
    sigma_ppm: float
    span_s: float
    n: int
    plane: str
    source: str

    def __post_init__(self) -> None:
        _check_plane(self.plane)
        _check_sigma(self.sigma_ppm, "rate")

    @property
    def ns_per_s(self) -> float:
        """The state's rate. A fast converter needs a shrinking correction."""
        return -self.ppm * NS_PER_S_PER_PPM

    @property
    def sigma_ns_per_s(self) -> float:
        return self.sigma_ppm * NS_PER_S_PER_PPM

    @property
    def is_label_plane(self) -> bool:
        return self.plane == PLANE_LABEL
