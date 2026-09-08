"""One estimator per station, on the ruler.

Three verbs. ``observe`` takes a witness statement, ``advance`` moves the
state to a sample index, ``solve`` returns a solution and rebases. No thread
owns this object; the caller holds whatever lock it already holds.

Every notion of time here arrives as a sample index inside an observation.
The estimator accumulates its own ``_ruler_s`` from those indices and runs
every age, dwell and span on it, so no host clock reaches any decision.

**The independence obligation.** ``Admitter`` counts distinct tier strings,
and one tier string must mean one independent witness. Neither it nor this
class can check that: only whoever wires the adapters knows whether two tier
strings name two antennas or one. Two adapters reading a single source would
agree perfectly, pass concordance, and let a lone witness move the plane.
This class therefore does not deduplicate either, because an enforcement
that cannot enforce invites reliance on it. The obligation belongs to
integration (controller ruling R20, 2026-09-08).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import numpy as np
from hamsci_dsp.stability import (  # type: ignore[import-untyped]
    compute_phase_adev,
)

from .admission import AdmissionPolicy, Admitter, Verdict
from .clock_state import PHASE, RATE, ClockState
from .gates import GateConfig, GateInputs, refusal
from .observations import PhaseObservation, RateObservation
from .process_noise import (
    RulerNoise,
    noise_from_adev,
    noise_from_standin,
    standin_sigma_ppm,
)
from .solution import VERDICT_PUBLISH, VERDICT_WITHHOLD, TimingSolution

_NS_PER_S = 1_000_000_000
_NS_PER_S_PER_PPM = 1000.0

# The rate uncertainty a cold estimator seeds with.
#
# NOT the stand-in sigma of ``process_noise``. That number says how far a
# rate WANDERS in an hour; this one says how far the seed's assumed zero may
# sit from the truth, and the two differ by orders of magnitude. An
# uncompensated crystal in a software radio is specified in tens of parts
# per million absolute while holding a couple of parts per million of
# short-term stability, so seeding the rate variance at the wander sigma
# tells the filter it already knows the frequency to two parts per million.
# A sixty-parts-per-million ruler then arrives as a thirty-sigma event and
# every phase witness reporting it is rejected as an outlier.
#
# Measured on the synthetic station of ``tests/estimator/test_estimator.py``:
# seeded at 2 ppm the filter recovers 0.43 of a 60 ppm error and rejects 9
# of 10 witnesses; seeded at 50, 100 or 500 ppm it recovers 60 ppm to better
# than 0.06 ppm and rejects none. The answer is insensitive across that
# range, so the constant buys diffuseness rather than tuning.
SEED_RATE_SIGMA_PPM = 100.0

A_LEVEL_GOVERNED = "A1"
A_LEVEL_FREE = "A0"

REASON_SEEDED = "seeded"
REASON_NO_PLANE = "no_plane"
REASON_HOST_PLANE = "host_plane"
REASON_ACCEPTED = "accepted"


def _fractional_ppm(rate_ns_per_s: float) -> float:
    """The ruler's fractional frequency offset, in parts per million.

    Exactly the offset the published ``rate_samples_per_utc_sec`` implies:
    the measured rate over the nominal one, less one, times a million --
    written here in a form that never divides by the nominal rate, so the
    package keeps its single sanctioned nominal division.
    ``ClockState.rate_ppm`` is the phase-slope convention,
    ``-rate_ns_per_s / 1000``, which equals this only to first order and
    lands 0.0036 ppm away at 60 ppm. Publishing both would put two
    arithmetics on the one quantity this library exists to have one of, so
    the solution publishes this one and the two published rate fields stay
    two spellings of a single number.
    """
    denom = _NS_PER_S + float(rate_ns_per_s)
    if denom == 0.0:
        return math.nan
    return -float(rate_ns_per_s) * 1.0e6 / denom


@dataclass(frozen=True)
class EstimatorConfig:
    gates: GateConfig = field(default_factory=GateConfig)
    admission: AdmissionPolicy = field(default_factory=AdmissionPolicy)
    adev_refit_every: int = 60
    adev_min_points: int = 20
    standin_horizon_s: float = 3600.0
    a1_max_ppm: float = 0.05
    seed_rate_sigma_ppm: float = SEED_RATE_SIGMA_PPM


class StationTimingEstimator:
    """Phase and rate against a sample counter, and every tier a witness."""

    def __init__(
        self,
        f_nom: int,
        ruler_provenance: str = "assumed",
        config: EstimatorConfig | None = None,
    ) -> None:
        self.f_nom = int(f_nom)
        self.ruler_provenance = str(ruler_provenance)
        self.config = config or EstimatorConfig()
        self._admitter = Admitter(self.config.admission)
        self._standin = noise_from_standin(
            standin_sigma_ppm(self.ruler_provenance),
            horizon_s=self.config.standin_horizon_s,
        )
        self._noise: RulerNoise = self._standin
        self._state: ClockState | None = None
        self._generation = 0
        self._ruler_s = 0.0
        self._last_phase_at_s: float | None = None
        self._n_updates = 0
        self._seed_s = 0.0
        self._residuals: list[tuple[float, float]] = []
        self._since_refit = 0
        self._coarse: tuple[float, float] | None = None
        self._rates: dict[str, float] = {}
        self._sigma_by_tier: dict[str, float] = {}
        self._surviving_rate: tuple[float, float] | None = None

    @property
    def generation(self) -> int:
        return self._generation

    # ---- the three verbs ------------------------------------------------

    def observe(self, obs: PhaseObservation | RateObservation) -> Verdict:
        """Take one witness statement and say what became of it."""
        if isinstance(obs, PhaseObservation):
            return self._observe_phase(obs)
        if isinstance(obs, RateObservation):
            return self._observe_rate(obs)
        raise TypeError(f"{type(obs).__name__} is not an observation")

    def advance(self, rtp: int) -> None:
        """Move the state and its plane to ``rtp``, and the ruler clock too.

        One call does both the prediction and the rebase, because two
        extrapolation mechanisms counted the ruler's rate twice (ruling
        R13). A request to run backwards changes nothing rather than
        raising: an out-of-order arrival is a caller's ordering problem, not
        a timing fault, and the state it would corrupt is the thing worth
        protecting.
        """
        state = self._state
        if state is None:
            return
        if state.elapsed_s(state.rtp_ref, rtp) < 0.0:
            return
        self._ruler_s += state.advance_to(rtp, self._noise)

    def solve(self, rtp: int) -> TimingSolution:
        """The solution at ``rtp``, published or withheld, always reasoned."""
        self.advance(rtp)
        state = self._state
        if state is None:
            return self._empty_solution(rtp)

        step_pending = self._settle_step(state, rtp)
        return self._build_solution(state, step_pending)

    def note_counter_epoch_change(self, why: str) -> None:
        """The counter's origin moved. Drop phase, keep the ruler's rate.

        A counter epoch change moves the origin and leaves the oscillator
        alone, so the rate and its variance survive to seed the next plane
        while everything stamped against the old origin goes.

        ``_ruler_s`` restarts at zero, so the admitter must be reset in the
        same breath: dissents stamped on the old timeline would make
        ``judge`` see ruler time run backwards, which it now refuses
        outright (controller ruling R19, 2026-09-08).
        """
        state = self._state
        if state is not None:
            self._surviving_rate = (
                state.rate_ns_per_s,
                float(state.p[RATE, RATE]),
            )
        self._state = None
        self._generation += 1
        self._ruler_s = 0.0
        self._seed_s = 0.0
        self._last_phase_at_s = None
        self._n_updates = 0
        self._coarse = None
        self._residuals.clear()
        self._since_refit = 0
        self._sigma_by_tier.clear()
        # Rate observations describe the oscillator, which the epoch change
        # did not touch, so the rate-spread gate keeps its witnesses.
        self._admitter.reset(why)

    # ---- observations ---------------------------------------------------

    def _observe_phase(self, obs: PhaseObservation) -> Verdict:
        r = float(obs.sigma_ns) ** 2
        state = self._state
        if state is None:
            if not obs.is_label_plane:
                # No plane exists, so a host-plane reading has nothing to
                # disagree with and may not seed one either.
                return Verdict(False, REASON_NO_PLANE, 0.0, r)
            self._seed(obs)
            return Verdict(True, REASON_SEEDED, 0.0, r)

        self.advance(obs.rtp)
        residual_ns = float(obs.utc_ns - state.utc_ns_at(obs.rtp))
        z = residual_ns + state.phase_ns
        nu, s = state.innovation(z, PHASE, r)
        verdict = self._admitter.judge(nu, s, obs, self._ruler_s)

        if not obs.is_label_plane:
            # Wide-angle network time feeds the coarse gate and nothing
            # else. Newest reading only (spec section 5).
            self._coarse = (residual_ns, float(obs.sigma_ns))
            return verdict

        self._sigma_by_tier[obs.tier] = float(obs.sigma_ns)
        if verdict.accepted:
            state.update(z, PHASE, r)
            self._last_phase_at_s = self._ruler_s
            self._n_updates += 1
            self._note_residual(nu)
        return verdict

    def _observe_rate(self, obs: RateObservation) -> Verdict:
        r = float(obs.sigma_ns_per_s) ** 2
        if not obs.is_label_plane:
            # A host-plane rate witness imports host error as ruler rate.
            # That path helped walk ND on 2026-09-07.
            return Verdict(False, REASON_HOST_PLANE, 0.0, r)

        self._rates[obs.source] = float(obs.ppm)
        state = self._state
        if state is None:
            return Verdict(False, REASON_NO_PLANE, 0.0, r)

        nu, s = state.innovation(obs.ns_per_s, RATE, r)
        state.update(obs.ns_per_s, RATE, r)
        return Verdict(True, REASON_ACCEPTED, nu, s)

    def _seed(self, obs: PhaseObservation) -> None:
        """Set the plane exactly where the first witness put it."""
        if self._surviving_rate is None:
            rate = 0.0
            rate_var = (
                float(self.config.seed_rate_sigma_ppm) * _NS_PER_S_PER_PPM
            ) ** 2
        else:
            rate, rate_var = self._surviving_rate
            self._surviving_rate = None
        p = np.array(
            [[float(obs.sigma_ns) ** 2, 0.0], [0.0, rate_var]], dtype=float
        )
        self._state = ClockState(
            f_nom=self.f_nom,
            rtp_ref=int(obs.rtp),
            utc_ref_ns=int(obs.utc_ns),
            phase_ns=0.0,
            rate_ns_per_s=rate,
            p=p,
        )
        self._seed_s = self._ruler_s
        self._last_phase_at_s = self._ruler_s
        self._n_updates = 1
        self._sigma_by_tier[obs.tier] = float(obs.sigma_ns)

    # ---- process noise from the ruler's own residuals -------------------

    def _note_residual(self, nu_ns: float) -> None:
        self._residuals.append((self._ruler_s, float(nu_ns) / _NS_PER_S))
        self._since_refit += 1
        if self._since_refit < self.config.adev_refit_every:
            return
        if len(self._residuals) < self.config.adev_min_points:
            return
        self._refit_noise()

    def _refit_noise(self) -> None:
        """Read q1 and q2 off the accepted residuals' Allan deviation.

        Two honesty points. ``compute_phase_adev`` assumes a uniformly
        sampled series and these observations are only roughly periodic, so
        the median spacing stands in for a sample interval the series does
        not really have. And every coefficient is floored at the stand-in
        for the declared ruler, so the filter can widen its memory but never
        narrow it below what the declared hardware supports (spec section
        10).
        """
        times = [t for t, _ in self._residuals]
        gaps = [b - a for a, b in zip(times, times[1:]) if b > a]
        if not gaps:
            return
        tau0 = statistics.median(gaps)
        phase = np.array([v for _, v in self._residuals], dtype=float)
        taus, adev = compute_phase_adev(phase, tau0)
        self._noise = noise_from_adev(taus, adev, floor=self._standin)
        self._since_refit = 0

    # ---- the step, and the gates ---------------------------------------

    def _settle_step(self, state: ClockState, rtp: int) -> bool:
        """Apply a ripe step proposal; report whether one still dwells."""
        proposal = self._admitter.step(self._ruler_s)
        sigmas = [
            self._sigma_by_tier[t]
            for t in (() if proposal is None else proposal.tiers)
            if t in self._sigma_by_tier
        ]
        # Every dissenting tier reached ``judge`` through ``_observe_phase``,
        # which records its sigma, so an empty list contradicts the
        # admitter's own bookkeeping. Refuse the step rather than reseed on
        # a zero variance, which would claim perfect phase knowledge; the
        # candidate stays dwelling and the solution keeps saying so.
        if proposal is not None and sigmas:
            sigma_ns = max(proposal.spread_ns, min(sigmas))
            state.reseed_phase(
                utc_ns=state.utc_ns_at(rtp) + round(proposal.implied_error_ns),
                rtp=rtp,
                sigma_ns=sigma_ns,
            )
            self._admitter.clear_step()
            # A reseed places phase from witnesses, so it is as fresh as an
            # accepted observation and the staleness gate must see it that
            # way -- otherwise a quorum that spent its dwell rejecting
            # ripens into a step and is refused for the rejecting.
            self._last_phase_at_s = self._ruler_s
            self._n_updates += 1
        return self._admitter.dwelling

    def _rate_spread_ppm(self) -> float | None:
        if len(self._rates) < 2:
            return None
        values = list(self._rates.values())
        return max(values) - min(values)

    def _a_level(self, rate_ppm: float, sigma_rate_ppm: float) -> str:
        """Diagnosis only. Nothing in this class branches on it."""
        limit = float(self.config.a1_max_ppm)
        if abs(rate_ppm) <= limit and sigma_rate_ppm <= limit:
            return A_LEVEL_GOVERNED
        return A_LEVEL_FREE

    def _build_solution(
        self, state: ClockState, step_pending: bool
    ) -> TimingSolution:
        try:
            f_meas = state.f_meas
        except ValueError:
            # A rate at or past -1e9 ns/s stops the clock. Only a diverged
            # filter reaches it, and the honest report of a diverged filter
            # is a refusal that names the divergence, not an exception out
            # of the one call a consumer makes every cycle.
            f_meas = math.nan
        rate_ppm = _fractional_ppm(state.rate_ns_per_s)
        sigma_rate_ppm = state.sigma_rate_ppm
        covariance = (
            float(state.p[PHASE, PHASE]),
            float(state.p[PHASE, RATE]),
            float(state.p[RATE, RATE]),
        )
        span_s = self._ruler_s - self._seed_s
        age_s = (
            0.0
            if self._last_phase_at_s is None
            else self._ruler_s - self._last_phase_at_s
        )
        coarse = self._coarse
        inputs = GateInputs(
            has_phase=self._last_phase_at_s is not None,
            phase_age_s=age_s,
            step_pending=step_pending,
            sigma_phase_ns=state.sigma_phase_ns,
            coarse_delta_ns=None if coarse is None else coarse[0],
            coarse_sigma_ns=None if coarse is None else coarse[1],
            rate_spread_ppm=self._rate_spread_ppm(),
        )
        # The gates read what the caller supplied; these are what this class
        # derived, and a NaN in any of them is the same fault under the same
        # name. Naming it here is what lets the record carry the NaN at all
        # (controller ruling R28).
        derived = (
            state.phase_ns,
            f_meas,
            rate_ppm,
            sigma_rate_ppm,
            span_s,
        ) + covariance
        if any(not math.isfinite(v) for v in derived) or f_meas <= 0.0:
            reason: str | None = "not_finite"
        else:
            reason = refusal(inputs, self.config.gates)
        return TimingSolution(
            rtp_ref=state.rtp_ref,
            utc_ref_ns=state.utc_ref_ns,
            phase_ns=state.phase_ns,
            sigma_phase_ns=state.sigma_phase_ns,
            rate_ppm=rate_ppm,
            sigma_rate_ppm=sigma_rate_ppm,
            rate_samples_per_utc_sec=f_meas,
            covariance=covariance,
            verdict=VERDICT_WITHHOLD if reason else VERDICT_PUBLISH,
            refusal=reason,
            witnesses=self._admitter.counts(),
            a_level=self._a_level(rate_ppm, sigma_rate_ppm),
            ruler_provenance=self.ruler_provenance,
            q_source=self._noise.source,
            span_s=span_s,
            n_updates=self._n_updates,
            generation=self._generation,
        )

    def _empty_solution(self, rtp: int) -> TimingSolution:
        """No witness has ever placed a plane, and the refusal says so.

        The numbers are zeros because ``TimingSolution`` permits a
        non-finite float only under ``not_finite``, deliberately narrowly.
        ``no_phase_witness`` disowns every one of them; the nominal rate
        appears because it is the only rate anybody has claimed yet.
        """
        return TimingSolution(
            rtp_ref=int(rtp),
            utc_ref_ns=0,
            phase_ns=0.0,
            sigma_phase_ns=0.0,
            rate_ppm=0.0,
            sigma_rate_ppm=0.0,
            rate_samples_per_utc_sec=float(self.f_nom),
            covariance=(0.0, 0.0, 0.0),
            verdict=VERDICT_WITHHOLD,
            refusal="no_phase_witness",
            witnesses=self._admitter.counts(),
            a_level=A_LEVEL_FREE,
            ruler_provenance=self.ruler_provenance,
            q_source=self._noise.source,
            span_s=0.0,
            n_updates=0,
            generation=self._generation,
        )
