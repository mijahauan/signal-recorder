"""What the estimator publishes, and the provenance it publishes with it.

Frozen, self-describing, and honest about its own refusal. A withheld
solution still carries every number it has, because a consumer that can see
why an answer was withheld can act; one handed silence cannot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .clock_state import signed_rtp_delta

VERDICT_PUBLISH = "publish"
VERDICT_WITHHOLD = "withhold"

# The refusals that mean the numbers THEMSELVES are unusable, rather than
# that usable numbers arrived too late or disagreed. Under these two, and
# only these two, this record carries whatever it was handed. Anything else
# still requires finite floats and a strictly positive rate.
UNUSABLE_NUMBER_REFUSALS = ("not_finite", "rate_not_positive")

_NS_PER_S = 1_000_000_000


def _check_float_finite(name: str, value: float) -> None:
    """Raise ValueError if a float is NaN or infinite."""
    if not math.isfinite(value):
        raise ValueError(f"{name} is not finite: {value}")


def _check_float_positive(name: str, value: float) -> None:
    """Raise ValueError if a float is not strictly greater than zero."""
    if value <= 0:
        raise ValueError(f"{name} must be strictly positive: {value}")


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
    # Per tier: ``accepted`` and ``rejected`` counts, and -- for a tier that
    # has supplied at least one phase observation -- ``last_residual_ns``
    # and ``last_sigma_ns``. Floats, because the last two are, and a mapping
    # whose value type depended on the key would be worse (spec section 7).
    witnesses: Mapping[str, Mapping[str, float]]
    a_level: str
    ruler_provenance: str
    q_source: str
    span_s: float
    n_updates: int
    generation: int

    def __post_init__(self) -> None:
        # Validate verdict/refusal consistency
        if self.verdict == VERDICT_PUBLISH and self.refusal is not None:
            msg = f"a publishing solution carries a refusal: {self.refusal}"
            raise ValueError(msg)
        if self.verdict == VERDICT_WITHHOLD and self.refusal is None:
            raise ValueError("a withholding solution names no refusal")
        if self.verdict not in (VERDICT_PUBLISH, VERDICT_WITHHOLD):
            msg = f"verdict {self.verdict!r} names neither outcome"
            raise ValueError(msg)

        # A withheld solution whose refusal names its own numbers as
        # unusable is the one record permitted to carry them. The gates
        # resolve ``not_finite`` first, so a state carrying a NaN can reach
        # no other refusal; if this record then refused the NaN, the only way
        # to report that refusal at all would be to zero the numbers and call
        # them real (controller ruling R28, 2026-09-08).
        #
        # ``rate_not_positive`` joined it on the same reasoning. Refusing to
        # construct broke the contract that the estimator publishes a
        # solution on EVERY cycle, so a caller in a loop crashed rather than
        # reading a refusal (controller ruling R37, 2026-09-08).
        if (
            self.verdict == VERDICT_WITHHOLD
            and self.refusal in UNUSABLE_NUMBER_REFUSALS
        ):
            self._freeze_witnesses()
            return

        # Validate all float fields are finite
        _check_float_finite("phase_ns", self.phase_ns)
        _check_float_finite("sigma_phase_ns", self.sigma_phase_ns)
        _check_float_finite("rate_ppm", self.rate_ppm)
        _check_float_finite("sigma_rate_ppm", self.sigma_rate_ppm)
        _check_float_finite(
            "rate_samples_per_utc_sec", self.rate_samples_per_utc_sec
        )
        _check_float_finite("covariance[0]", self.covariance[0])
        _check_float_finite("covariance[1]", self.covariance[1])
        _check_float_finite("covariance[2]", self.covariance[2])
        _check_float_finite("span_s", self.span_s)

        # Validate rate is strictly positive (consumers divide by it)
        _check_float_positive(
            "rate_samples_per_utc_sec", self.rate_samples_per_utc_sec
        )

        self._freeze_witnesses()

    def _freeze_witnesses(self) -> None:
        # Deep-freeze witnesses at both levels
        object.__setattr__(
            self,
            "witnesses",
            MappingProxyType(
                {
                    str(tier): MappingProxyType(dict(tally))
                    for tier, tally in self.witnesses.items()
                }
            ),
        )

    def utc_ns_at(self, rtp: int) -> int:
        """UTC at sample ``rtp`` through plane and measured rate.

        One rounding, on the sum, because spec section 1 writes one:
        ``utc_ref_ns + round(phase_ns + ...)``. Rounding the phase and the
        projection separately discards up to half a nanosecond from each
        and can land a whole nanosecond away from the single-rounded
        answer, which ``ClockState.utc_ns_at`` -- the same projection, on
        the estimator's side -- has always computed.
        """
        delta = signed_rtp_delta(self.rtp_ref, rtp)
        projection = _NS_PER_S * delta / self.rate_samples_per_utc_sec
        return self.utc_ref_ns + round(self.phase_ns + projection)
