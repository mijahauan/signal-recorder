"""What the estimator publishes, and the provenance it publishes with it.

Frozen, self-describing, and honest about its own refusal. A withheld
solution still carries every number it has, because a consumer that can see
why an answer was withheld can act; one handed silence cannot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .clock_state import signed_rtp_delta

VERDICT_PUBLISH = "publish"
VERDICT_WITHHOLD = "withhold"

_NS_PER_S = 1_000_000_000


@dataclass(frozen=True)
class TimingSolution:
    rtp_ref: int
    utc_ref_ns: int
    phase_ns: float
    sigma_phase_ns: float
    rate_ppm: float
    sigma_rate_ppm: float
    rate_samples_per_utc_sec: float
    covariance: tuple[float, float, float]
    verdict: str
    refusal: str | None
    witnesses: Mapping[str, Mapping[str, int]]
    a_level: str
    ruler_provenance: str
    q_source: str
    span_s: float
    n_updates: int
    generation: int

    def __post_init__(self) -> None:
        if self.verdict == VERDICT_PUBLISH and self.refusal is not None:
            msg = f"a publishing solution carries a refusal: {self.refusal}"
            raise ValueError(msg)
        if self.verdict == VERDICT_WITHHOLD and self.refusal is None:
            raise ValueError("a withholding solution names no refusal")
        if self.verdict not in (VERDICT_PUBLISH, VERDICT_WITHHOLD):
            msg = f"verdict {self.verdict!r} names neither outcome"
            raise ValueError(msg)

    def utc_ns_at(self, rtp: int) -> int:
        """UTC of the sample at ``rtp``, through this plane and measured rate.
        """
        delta = signed_rtp_delta(self.rtp_ref, rtp)
        projection = _NS_PER_S * delta / self.rate_samples_per_utc_sec
        return self.utc_ref_ns + round(self.phase_ns) + round(projection)
