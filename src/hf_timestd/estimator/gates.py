"""Six refusals, resolved in order, first match winning.

The estimator publishes a solution every cycle and that solution carries a
verdict. It never withholds silently and never corrects anything: the caller
alarms and withdraws (spec section 5).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

REFUSAL_ORDER = (
    "not_finite",
    "counter_ambiguous",
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
    counter_ambiguous: bool
    has_phase: bool
    phase_age_s: float
    step_pending: bool
    sigma_phase_ns: float
    coarse_delta_ns: float | None
    coarse_sigma_ns: float | None
    rate_spread_ppm: float | None


def refusal(inputs: GateInputs, config: GateConfig) -> str | None:
    """The first reason this solution may not be published, or None."""
    # NaN and infinity must be caught first, before any comparison. A NaN in
    # phase_age_s, sigma_phase_ns, or any rate/coarse field makes every
    # comparison return False, silently publishing a clean verdict for the
    # worst possible failure mode. This module's job is deciding whether to
    # publish a timing answer: a silent pass on invalid data is the opposite
    # of that job. Name the actual fault (not_finite) rather than dressing it
    # up as some other refusal.
    numbers = [inputs.phase_age_s, inputs.sigma_phase_ns]
    numbers += [
        v
        for v in (
            inputs.coarse_delta_ns,
            inputs.coarse_sigma_ns,
            inputs.rate_spread_ppm,
        )
        if v is not None
    ]
    if any(not math.isfinite(float(v)) for v in numbers):
        return "not_finite"

    # Second, and above every other reason, because a plane read through an
    # ambiguous counter delta is not stale or wide -- it is unmoored. A gap
    # past half a wrap period aliases to a negative delta, indistinguishable
    # from a backward step, so the caller's clock state may sit a whole wrap
    # period away from the truth: 49.7 hours at 24 kHz. Nothing downstream of
    # here can be trusted while it stands.
    if inputs.counter_ambiguous:
        return "counter_ambiguous"

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
