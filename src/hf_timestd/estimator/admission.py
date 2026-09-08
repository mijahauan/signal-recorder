"""Who gets to move the plane, and who only gets counted.

A lone witness never moves it, however confident. A quorum that agrees with
itself may, and only after a dwell. And a step, once accepted, changes phase
and never rate (spec section 4).

Tier independence: The quorum counts distinct tier strings. Each tier string
must correspond to one independent witness (e.g., one antenna and its
measurement chain). If the same physical antenna drives two tier strings, or
if two adapters feed the same source, that defeats the quorum guarantee. This
module cannot verify independence—only the caller knows the physical topology.
A violated contract hands the system a fabricated consensus from a single
source, which violates the spec that a single witness may never move the plane.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from .observations import PhaseObservation


@dataclass(frozen=True)
class AdmissionPolicy:
    k_accept: float = 3.0
    quorum: int = 2
    concord_k: float = 3.0
    dwell_s: float = 120.0
    freshness_s: float = 180.0


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reason: str
    innovation_ns: float
    s_ns2: float


@dataclass(frozen=True)
class StepProposal:
    implied_error_ns: float
    spread_ns: float
    tiers: tuple[str, ...]


@dataclass
class _Dissent:
    residual_ns: float
    sigma_ns: float
    at_s: float


@dataclass
class Admitter:
    policy: AdmissionPolicy
    last_residual_ns: dict[str, float] = field(default_factory=dict)
    _counts: dict[str, dict[str, int]] = field(default_factory=dict)
    _dissent: dict[str, _Dissent] = field(default_factory=dict)
    _candidate_since: float | None = None
    _last_now_s: float | None = None

    def judge(
        self, nu: float, s: float, obs: PhaseObservation, now_s: float
    ) -> Verdict:
        """Judge an observation for admission.

        Each tier string must correspond to one independent witness.
        See module docstring for the tier independence contract.
        """
        now = float(now_s)
        if self._last_now_s is not None and now < self._last_now_s:
            raise ValueError(
                f"judge went backwards in ruler time, {now} after"
                f" {self._last_now_s}"
            )
        self._last_now_s = now

        if not obs.is_label_plane:
            return Verdict(False, "host_plane", float(nu), float(s))

        tally = self._counts.setdefault(
            obs.tier, {"accepted": 0, "rejected": 0}
        )

        self.last_residual_ns[obs.tier] = float(nu)
        if s <= 0.0 or not math.isfinite(s):
            tally["rejected"] += 1
            return Verdict(False, "outlier", float(nu), float(s))

        if abs(nu) <= self.policy.k_accept * math.sqrt(s):
            tally["accepted"] += 1
            self._dissent.pop(obs.tier, None)
            self._reconsider_candidate(now)
            return Verdict(True, "accepted", float(nu), float(s))

        tally["rejected"] += 1
        self._dissent[obs.tier] = _Dissent(float(nu), float(obs.sigma_ns), now)
        self._reconsider_candidate(now)
        return Verdict(False, "outlier", float(nu), float(s))

    def counts(self) -> dict[str, dict[str, int]]:
        return {tier: dict(v) for tier, v in self._counts.items()}

    def step(self, now_s: float) -> StepProposal | None:
        """A concordant quorum that has dwelled long enough, or nothing."""
        agreed = self._concordant(now_s)
        if agreed is None:
            return None
        if self._candidate_since is None:
            return None
        if (float(now_s) - self._candidate_since) < self.policy.dwell_s:
            return None
        return agreed

    def clear_step(self) -> None:
        self._dissent.clear()
        self._candidate_since = None

    def reset(self, why: str) -> None:
        """Forget every count and dissent. A caller whose ruler time restarts
        must call this: stale dissents carry stamps from a timeline that no
        longer exists.
        """
        self.last_residual_ns.clear()
        self._counts.clear()
        self._dissent.clear()
        self._candidate_since = None
        self._last_now_s = None

    # ---- internals ------------------------------------------------------

    def _fresh(self, now_s: float) -> dict[str, _Dissent]:
        cutoff = float(now_s) - self.policy.freshness_s
        return {t: d for t, d in self._dissent.items() if d.at_s >= cutoff}

    def _concordant(self, now_s: float) -> StepProposal | None:
        fresh = self._fresh(now_s)
        if len(fresh) < self.policy.quorum:
            return None

        residuals = [d.residual_ns for d in fresh.values()]
        signs_match = all(r > 0 for r in residuals) or all(
            r < 0 for r in residuals
        )
        if not signs_match:
            return None

        spread = max(residuals) - min(residuals)
        combined = max(d.sigma_ns for d in fresh.values()) * 2.0
        if spread > self.policy.concord_k * max(combined, 1.0):
            return None

        return StepProposal(
            implied_error_ns=float(statistics.median(residuals)),
            spread_ns=float(spread),
            tiers=tuple(sorted(fresh)),
        )

    def _reconsider_candidate(self, now_s: float) -> None:
        if self._concordant(now_s) is None:
            self._candidate_since = None
        elif self._candidate_since is None:
            self._candidate_since = float(now_s)
