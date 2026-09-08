"""Six refusals, resolved in order, first match winning.

The estimator publishes a solution every cycle and that solution carries a
verdict. It never withholds silently and never corrects anything: the caller
alarms and withdraws (spec section 5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

REFUSAL_ORDER = (
    "no_phase_witness",
    "stale_phase",
    "step_pending",
    "variance",
    "coarse_disagreement",
    "rate_disagreement",
)


@dataclass(frozen=True)
class GateConfig:
    max_phase_age_s: float = 300.0
    publish_sigma_max_ns: float = 5.0e6
    coarse_k: float = 3.0
    # Matches rate_alarm_ppm in core/offset_judge.py, so one station does not
    # carry two opinions about what a rate disagreement means.
    rate_alarm_ppm: float = 1.0


@dataclass(frozen=True)
class GateInputs:
    has_phase: bool
    phase_age_s: float
    step_pending: bool
    sigma_phase_ns: float
    coarse_delta_ns: float | None
    coarse_sigma_ns: float | None
    rate_spread_ppm: float | None


def refusal(inputs: GateInputs, config: GateConfig) -> str | None:
    """The first reason this solution may not be published, or None."""
    if not inputs.has_phase:
        return "no_phase_witness"

    if inputs.phase_age_s > config.max_phase_age_s:
        return "stale_phase"

    if inputs.step_pending:
        return "step_pending"

    if inputs.sigma_phase_ns > config.publish_sigma_max_ns:
        return "variance"

    delta, sigma = inputs.coarse_delta_ns, inputs.coarse_sigma_ns
    if delta is not None and sigma is not None:
        combined = math.hypot(float(sigma), float(inputs.sigma_phase_ns))
        if abs(float(delta)) > config.coarse_k * combined:
            return "coarse_disagreement"

    spread = inputs.rate_spread_ppm
    if spread is not None and abs(float(spread)) > config.rate_alarm_ppm:
        return "rate_disagreement"

    return None
