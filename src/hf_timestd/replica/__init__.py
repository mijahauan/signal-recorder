"""Replica correlation against a locally generated WWV/WWVH broadcast.

A ruler error stretches the received program against the replica, so the drift
of the correlation lag measures the ruler without reading any host clock. The
correlation SNR is the other half of the point: it says whether the channel
carries WWV structure AT ALL, refusing at the source what the estimator can
otherwise only refuse downstream, after something has already manufactured a
number from noise.

Provenance: the template's structure is read off Phil Karn's ``wwvsim``
(github.com/ka9q/wwvsim), which this package does NOT depend on at runtime.
"""

from .correlate import MIN_CC_SNR, Correlation, correlate_minute
from .rate import MIN_POINTS, RateEstimate, fit_rate
from .second_of_minute import (
    MIN_MARGIN,
    SECONDS,
    SecondOfMinute,
    accumulate_energy,
    per_second_energy,
    resolve_from_energy,
    resolve_if_admissible,
    resolve_second_of_minute,
)
from .template import (
    MARKER_MS,
    NO_TICK_SECONDS,
    TICK_MS,
    minute_template,
)

__all__ = [
    "MARKER_MS",
    "MIN_CC_SNR",
    "MIN_MARGIN",
    "MIN_POINTS",
    "NO_TICK_SECONDS",
    "SECONDS",
    "TICK_MS",
    "Correlation",
    "RateEstimate",
    "SecondOfMinute",
    "accumulate_energy",
    "correlate_minute",
    "fit_rate",
    "minute_template",
    "per_second_energy",
    "resolve_from_energy",
    "resolve_if_admissible",
    "resolve_second_of_minute",
]
