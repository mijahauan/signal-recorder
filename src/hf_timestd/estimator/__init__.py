"""One estimator on the ruler: phase, rate, and every tier as a witness.

A library. Nothing here reads a host clock, and nothing here imports the
timing core. The design spec:
docs/superpowers/specs/2026-09-08-station-timing-estimator-design.md
"""

from .estimator import EstimatorConfig, StationTimingEstimator
from .observations import (
    PLANE_HOST,
    PLANE_LABEL,
    PhaseObservation,
    RateObservation,
)
from .solution import VERDICT_PUBLISH, VERDICT_WITHHOLD, TimingSolution

__all__ = [
    "EstimatorConfig",
    "PLANE_HOST",
    "PLANE_LABEL",
    "PhaseObservation",
    "RateObservation",
    "StationTimingEstimator",
    "TimingSolution",
    "VERDICT_PUBLISH",
    "VERDICT_WITHHOLD",
]
