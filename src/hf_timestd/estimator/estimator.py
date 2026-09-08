"""One estimator per station, on the ruler.

Three verbs. ``observe`` takes a witness statement, ``advance`` moves the
state to a sample index, ``solve`` returns a solution and rebases. No thread
owns this object; the caller holds whatever lock it already holds.

Every notion of time here arrives as a sample index inside an observation.
The estimator accumulates its own ``_ruler_s`` from those indices and runs
every age, dwell and span on it, so no host clock reaches any decision.

**The counter wrap, and what it can still hide.** A 32-bit sample counter
resolves a true interval only while two readings sit within half a wrap of
each other: 2**31 samples, about 24.9 hours at 24 kHz. Past that a forward
gap aliases to a NEGATIVE delta, indistinguishable from a backward step, and
``advance`` latches ``counter_ambiguous`` rather than guessing. One case
survives even that: a gap of almost exactly a whole number of wrap periods
aliases to a small POSITIVE delta, which no arithmetic on a 32-bit counter
can tell from a short interval. Nothing here detects it. Witness innovations
do, because the implied error is tens of hours and every witness rejects.

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
from collections import deque
from dataclasses import dataclass, field

import numpy as np
from hamsci_dsp.stability import (  # type: ignore[import-untyped]
    compute_phase_adev,
)

from .admission import AdmissionPolicy, Admitter, Verdict
from .clock_state import PHASE, RATE, ClockState, signed_rtp_delta
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

# The accepted-residual series the Allan fit reads. Bounded because this
# object is meant to run for months and an unbounded list is a leak: at one
# accepted witness a minute, 4096 entries hold about 68 hours, which is far
# more span than any Allan fit here needs and comfortably past the hours a
# random-walk coefficient wants (controller ruling R32, 2026-09-08). Once it
# is full the oldest residuals fall off the back, so the fit tracks the
# recent ruler rather than averaging in a day that has already ended.
RESIDUAL_CAP = 4096

# How far the widest gap in the residual series may stray from the median
# before an Allan fit means nothing. Three is loose enough to tolerate the
# ragged periodicity of real witnesses and tight enough to reject a hole.
_MAX_GAP_RATIO = 3.0

# How far above the witnesses' own noise the fitted deviation must sit before
# the fit gets to call itself measured. Two is a sigma multiple meaning
# "clearly above the noise", not a time constant.
_WITNESS_FLOOR_K = 2.0

# White phase noise of standard deviation sigma_x has an Allan deviation of
# sqrt(3) * sigma_x / tau. That is the whole criterion, and it needs no
# constant this project chose: the witnesses declare sigma_x themselves.
_WHITE_PHASE_ADEV = math.sqrt(3.0)

# (ns/s)^2 per (s/s)^2, mirroring the conversion process_noise applies when
# it turns a dimensionless deviation into q1 and q2.
_DIMENSIONLESS_TO_NS2 = 1e18

A_LEVEL_GOVERNED = "A1"
A_LEVEL_FREE = "A0"

REASON_SEEDED = "seeded"
REASON_NO_PLANE = "no_plane"
REASON_HOST_PLANE = "host_plane"
REASON_ACCEPTED = "accepted"
REASON_OUTLIER = "outlier"


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
        # (ruler_s, residual_s, sigma_ns). The sigma rides along so the
        # Allan fit can be measured against the noise of exactly the
        # witnesses that produced it, and falls off the back with them.
        self._residuals: deque[tuple[float, float, float]] = deque(
            maxlen=RESIDUAL_CAP
        )
        self._since_refit = 0
        # (delta_ns, sigma_ns, ruler_s) and {source: (ppm, ruler_s)}.
        # Both carry a stamp so a dead source's last claim cannot vote
        # forever; see _fresh_coarse and _rate_spread_ppm.
        self._coarse: tuple[float, float, float] | None = None
        self._rates: dict[str, tuple[float, float]] = {}
        self._rate_counts: dict[str, dict[str, int]] = {}
        self._sigma_by_tier: dict[str, float] = {}
        self._surviving_rate: tuple[float, float] | None = None
        self._counter_ambiguous = False
        # The Allan feed's plane, fixed at the seed and never rebased. The
        # state's plane cannot serve: it moves with every solve, and folding
        # it forward is what removes the very wander the fit must see.
        self._adev_seed_rtp: int | None = None
        self._adev_seed_utc_ns = 0

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
        R13).

        A negative delta leaves the state alone AND latches
        ``counter_ambiguous``, which withholds every later solution until an
        announced epoch change. It must not return silently: a forward gap
        past half a wrap period aliases to exactly the same negative delta as
        a backward step, so the silent path took a resuming daemon and
        published a plane a whole wrap period wrong -- 178,956.97 seconds at
        24 kHz -- with ruler time frozen, so ``stale_phase`` never fired
        either. Measured: a 24-hour gap resolves, 25 hours and beyond
        aliases. "Ambiguous" rather than "backward" because we genuinely
        cannot tell the two apart (controller ruling R33, 2026-09-08).
        """
        state = self._state
        if state is None:
            return
        if state.elapsed_s(state.rtp_ref, rtp) < 0.0:
            self._counter_ambiguous = True
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
        self._adev_seed_rtp = None
        self._adev_seed_utc_ns = 0
        self._since_refit = 0
        self._sigma_by_tier.clear()
        self._rate_counts.clear()
        self._rates.clear()
        # Only here. A fresh seed is the one thing that re-establishes the
        # plane, so it is the one thing entitled to forgive an ambiguous
        # counter delta: nothing else can tell whether the old plane still
        # describes this counter space.
        self._counter_ambiguous = False
        # ``q_source`` would otherwise describe a residual series this same
        # method just cleared.
        self._noise = self._standin
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
            self._coarse = (residual_ns, float(obs.sigma_ns), self._ruler_s)
            return verdict

        self._sigma_by_tier[obs.tier] = float(obs.sigma_ns)
        if verdict.accepted:
            state.update(z, PHASE, r)
            self._last_phase_at_s = self._ruler_s
            self._n_updates += 1
            self._note_residual(state, obs)
        return verdict

    def _observe_rate(self, obs: RateObservation) -> Verdict:
        # ``ns_per_s`` and ``sigma_ns_per_s`` convert a witness's parts per
        # million linearly, at 1000 ns/s per ppm. That is the first-order
        # form of the exact definition ``rate_ppm`` now publishes, and the
        # two differ by 0.0036 ppm at 60 against a rate witness whose sigma
        # is no better than 0.15 ppm. A conversion buried forty times inside
        # its own uncertainty is not a second arithmetic, so the input stays
        # linear where the output is exact (controller ruling R29).
        r = float(obs.sigma_ns_per_s) ** 2
        if not obs.is_label_plane:
            # A host-plane rate witness imports host error as ruler rate.
            # That path helped walk ND on 2026-09-07.
            return Verdict(False, REASON_HOST_PLANE, 0.0, r)

        # Recorded before the gate, deliberately. The rate-spread gate
        # alarms on what witnesses CLAIM, and a witness this filter just
        # rejected is exactly the disagreement worth publishing.
        self._rates[obs.source] = (float(obs.ppm), self._ruler_s)
        state = self._state
        if state is None:
            return Verdict(False, REASON_NO_PLANE, 0.0, r)

        nu, s = state.innovation(obs.ns_per_s, RATE, r)
        tally = self._rate_counts.setdefault(
            obs.tier, {"accepted": 0, "rejected": 0}
        )
        # Spec section 4's innovation test says "for each observation", and
        # one wild rate witness moving the rate state unchecked is the
        # rate-side twin of the failure this library exists to stop. Applied
        # inline rather than through ``Admitter.judge``, because that method
        # is shaped for phase observations and a rate dissent is NOT a phase
        # step: a rejected rate witness must never reach the dissent or
        # quorum machinery, where it would help license a plane step
        # (controller ruling R31, 2026-09-08).
        if not (s > 0.0 and math.isfinite(s)):
            tally["rejected"] += 1
            return Verdict(False, REASON_OUTLIER, nu, s)
        if abs(nu) > self.config.admission.k_accept * math.sqrt(s):
            tally["rejected"] += 1
            return Verdict(False, REASON_OUTLIER, nu, s)

        tally["accepted"] += 1
        state.update(obs.ns_per_s, RATE, r)
        self._n_updates += 1
        return Verdict(True, REASON_ACCEPTED, nu, s)

    def _seed(self, obs: PhaseObservation) -> None:
        """Set the plane exactly where the first witness put it."""
        if self._surviving_rate is None:
            rate = 0.0
            # The seed's rate variance is NOT the stand-in sigma of
            # ``process_noise``. That number says how far a rate MOVES over
            # an hour; this one says how far from nominal the ruler may
            # already sit before anybody has measured it, and the two differ
            # by orders of magnitude. The measurement model records this very
            # station near 350 ppm on an LBE-Mini held at its 8 mA drive
            # floor -- 175 sigma outside a 2 ppm seed. A prior that excludes
            # the documented failure this library was built to survive is
            # blind, not conservative, so the default is generous (spec
            # section 6.1).
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
        self._adev_seed_rtp = int(obs.rtp)
        self._adev_seed_utc_ns = int(obs.utc_ns)
        self._seed_s = self._ruler_s
        self._last_phase_at_s = self._ruler_s
        self._n_updates = 1
        self._sigma_by_tier[obs.tier] = float(obs.sigma_ns)

    # ---- process noise from the ruler's own residuals -------------------

    def _note_residual(self, state: ClockState, obs: PhaseObservation) -> None:
        """Append the classical clock difference against the fixed plane.

        NOT the innovation. An innovation is what the filter could not
        predict, and the filter has already absorbed the ruler's wander into
        its rate state, so the residue carries the witnesses' noise and none
        of the ruler's. Measured: that series' deviation sat at 1.001 to
        1.032 times the witness floor across eight taus from 60 s to 7680 s,
        flat, so no span could ever separate the two. Asking a filter to
        measure the quantity it exists to remove cannot work (controller
        ruling R38, 2026-09-08).

        What does carry the wander is each witness's UTC minus the NOMINAL
        ruler reading, both against a plane fixed at the seed. Allan's second
        differences remove any constant offset and any constant frequency
        error, so no correction for the estimated rate is needed and the
        accumulated linear trend does no harm.
        """
        anchor = self._adev_seed_rtp
        if anchor is None:
            return
        delta = signed_rtp_delta(anchor, obs.rtp)
        if delta < 0:
            # The fixed plane has outrun half a wrap period, about 24.9 hours
            # at 24 kHz, so its projection would alias by a whole wrap. Move
            # the anchor to here and start again. The fit loses its history
            # roughly daily, which caps the longest tau it can reach; that
            # beats feeding it a number that is 49.7 hours wrong.
            self._adev_seed_rtp = int(obs.rtp)
            self._adev_seed_utc_ns = int(obs.utc_ns)
            self._residuals.clear()
            return
        # Associated so the integers cancel first. Absolute UTC in
        # nanoseconds exceeds 1.7e18, where a double's granularity is 256 ns,
        # so adding the projection to the anchor BEFORE subtracting would
        # quantise a half-millisecond witness to a quarter of a microsecond.
        # Spec section 2 is the same point about the state's own plane.
        x_ns = float(int(obs.utc_ns) - self._adev_seed_utc_ns) - (
            _NS_PER_S * state.nominal_seconds(delta)
        )
        self._residuals.append(
            (self._ruler_s, x_ns / _NS_PER_S, float(obs.sigma_ns))
        )
        self._since_refit += 1
        if self._since_refit < self.config.adev_refit_every:
            return
        if len(self._residuals) < self.config.adev_min_points:
            return
        self._refit_noise()

    def _refit_noise(self) -> None:
        """Read q2 off the accepted residuals' Allan deviation.

        **q2 only.** The series is innovations, so it carries the witnesses'
        noise as well as the ruler's, and ``noise_from_adev`` fits q1 at the
        SHORTEST tau -- exactly where witness noise dominates most. Measured
        on a governed ruler with 0.5 ms witnesses, that fit returned
        q1 = 1.49e10 ns^2/s, crediting the hardware with 866 microseconds of
        phase wander a minute where its true wander is nanoseconds, and phase
        sigma then parked at 451 microseconds instead of averaging down. At
        long tau the ruler's random walk rises while witness white noise
        averages down, so the long-tau fit is the trustworthy one and the
        short-tau fit is contaminated. Take q2 from the fit, keep q1 at the
        declared floor (controller ruling R34, 2026-09-08).

        **And only when the fit beats the witnesses.** Keeping q1 at the
        floor was not enough: the surviving q2 was itself almost entirely
        witness noise. White phase noise of standard deviation ``sigma_x``
        has an Allan deviation of ``sqrt(3) * sigma_x / tau``, so the
        witnesses declare their own floor and this criterion needs no
        constant anybody chose. Compare the deviation the fitted q2 implies
        at the longest tau the fit used against that floor, and accept the
        fit only when it clears twice it. Otherwise keep the stand-in
        entirely, and keep saying ``standin``, because a coefficient that is
        98 percent witness noise wearing the ruler's name is a false label
        (controller ruling R36, 2026-09-08).

        This is why a governed ruler reads ``standin`` on every span this
        project can currently supply, and that is the honest answer rather
        than a shortcoming. Separating a hundredth of a part per million from
        half-millisecond witnesses needs a tau near 86,400 s, because that is
        where the ruler's own random walk finally rises above witness noise
        that falls as 1/tau. Our spans run to hundreds of seconds.

        **And only from a roughly uniform series.** ``compute_phase_adev``
        assumes uniform spacing, and a median gap is hole-blind: a 10,800 s
        hole among 60 s spacings still reported a measured fit, from second
        differences straddling it that mean nothing. Refuse the fit unless
        the widest gap sits within ``_MAX_GAP_RATIO`` of the median, and
        leave the stand-in in place.

        The floor is what lets the filter widen its memory and never narrow
        it below what the declared hardware supports (spec section 10).
        """
        times = [t for t, _, _ in self._residuals]
        gaps = [b - a for a, b in zip(times, times[1:]) if b > a]
        if not gaps:
            return
        tau0 = statistics.median(gaps)
        if max(gaps) > _MAX_GAP_RATIO * tau0:
            # No refit and no reset of the counter, so the fit is retried
            # once the hole has aged out of the bounded series.
            return

        phase = np.array([v for _, v, _ in self._residuals], dtype=float)
        taus, adev = compute_phase_adev(phase, tau0)
        # Filtered here rather than left to ``noise_from_adev``, which
        # applies the same mask privately, so ``tau_max`` below is exactly
        # the tau the q2 fit used and the comparison is against the right
        # point on the curve.
        taus = np.asarray(taus, dtype=float)
        adev = np.asarray(adev, dtype=float)
        good = (
            np.isfinite(taus) & np.isfinite(adev) & (taus > 0.0) & (adev > 0.0)
        )
        if not bool(good.any()):
            return
        taus, adev = taus[good], adev[good]
        longest = int(taus.argmax())
        tau_max, measured_adev = float(taus[longest]), float(adev[longest])

        self._since_refit = 0
        fitted = noise_from_adev(taus, adev, floor=self._standin)
        sigma_x_s = (
            statistics.median(sig for _, _, sig in self._residuals) / _NS_PER_S
        )
        witness_adev = _WHITE_PHASE_ADEV * sigma_x_s / tau_max
        # Against the MEASURED deviation at the longest tau, not against the
        # deviation the stored q2 implies. The two are the same number while
        # the fit stands on its own -- inverting ``noise_from_adev``'s
        # ``q2 = 3 * adev^2 / tau * 1e18`` returns exactly ``adev`` -- but
        # that function floors q2 at the stand-in and still stamps it
        # "measured". Inverting the FLOOR then answers a question about the
        # stand-in: a 300 ns witness made the "observed" floor read 5.5 times
        # its own noise and passed, with no measurement in it anywhere.
        if measured_adev <= _WITNESS_FLOOR_K * witness_adev:
            return
        # And the fit must actually have moved the coefficient. If the floor
        # won, the stored q2 IS the stand-in, and calling that "measured"
        # says the ruler was measured and returned its own declared
        # fallback.
        if fitted.q2 <= self._standin.q2:
            return
        self._noise = RulerNoise(
            q1=self._standin.q1, q2=fitted.q2, source=fitted.source
        )

    # ---- the step, and the gates ---------------------------------------

    def _settle_step(self, state: ClockState, rtp: int) -> bool:
        """Apply a ripe step proposal; report whether one still dwells."""
        proposal = self._admitter.step(self._ruler_s)
        if proposal is not None:
            # Every dissenting tier reached ``judge`` through
            # ``_observe_phase``, which records its sigma, so ``min`` cannot
            # see an empty sequence. If it ever does, raising is the honest
            # answer to an impossible state: the earlier guard here left
            # ``dwelling`` latched True and wedged the estimator on
            # ``step_pending`` forever, which is worse than no guard.
            sigma_ns = max(
                proposal.spread_ns,
                min(self._sigma_by_tier[t] for t in proposal.tiers),
            )
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

    def _witness_counts(self) -> dict[str, dict[str, int]]:
        """Every witness this estimator judged, phase and rate alike.

        The admitter tallies phase observations; the rate path tallies its
        own, because a rejected rate witness must stay out of the quorum
        machinery. A tier that speaks both ways appears once, and its tally
        counts observations rather than kinds (controller ruling R31).
        """
        counts = self._admitter.counts()
        for tier, tally in self._rate_counts.items():
            merged = counts.setdefault(tier, {"accepted": 0, "rejected": 0})
            merged["accepted"] += tally["accepted"]
            merged["rejected"] += tally["rejected"]
        return counts

    def _fresh_cutoff(self) -> float:
        """Ruler time before which a witness's last claim stops voting.

        Mirrors the admitter's dissents, which already expire. Two rate
        witnesses 5 ppm apart for one minute used to withhold the station's
        whole timing product for as long as it ran, surviving an epoch change
        and a reseed, because neither record carried a stamp. Silence from a
        witness is not agreement, so it must not count as disagreement
        either; noticing a dead witness belongs to whoever wired it
        (controller ruling R35, 2026-09-08).
        """
        return self._ruler_s - self.config.admission.freshness_s

    def _fresh_coarse(self) -> tuple[float, float] | None:
        coarse = self._coarse
        if coarse is None or coarse[2] < self._fresh_cutoff():
            return None
        return coarse[0], coarse[1]

    def _rate_spread_ppm(self) -> float | None:
        cutoff = self._fresh_cutoff()
        fresh = [ppm for ppm, at_s in self._rates.values() if at_s >= cutoff]
        if len(fresh) < 2:
            return None
        return max(fresh) - min(fresh)

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
            rate_ppm = state.rate_ppm
        except ValueError:
            # A rate at or past -1e9 ns/s stops the clock, and both of those
            # properties refuse it through the one guard they share. Only a
            # diverged filter reaches it, and the honest report of a diverged
            # filter is a refusal that names the divergence, not an exception
            # out of the one call a consumer makes every cycle.
            f_meas = math.nan
            rate_ppm = math.nan
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
        coarse = self._fresh_coarse()
        inputs = GateInputs(
            counter_ambiguous=self._counter_ambiguous,
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
        if any(not math.isfinite(v) for v in derived):
            reason: str | None = "not_finite"
        elif f_meas <= 0.0:
            # Unreachable: ``ClockState`` refuses a non-positive ``f_nom`` at
            # construction and refuses a denominator at or below zero in the
            # property itself, so both guards must already have been bypassed
            # to arrive here. Named for what actually happened anyway, rather
            # than dressed up as ``not_finite``, which would be a lie about a
            # perfectly finite number. ``TimingSolution`` will then refuse to
            # carry it -- ruling R28's exemption covers only ``not_finite``
            # -- so an impossible state raises loudly instead of publishing a
            # fabrication.
            reason = "rate_not_positive"
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
            witnesses=self._witness_counts(),
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
            # Never ``counter_ambiguous`` here: the latch is only set while a
            # state exists, and the only thing that drops the state clears
            # the latch in the same call.
            refusal="no_phase_witness",
            witnesses=self._admitter.counts(),
            a_level=A_LEVEL_FREE,
            ruler_provenance=self.ruler_provenance,
            q_source=self._noise.source,
            span_s=0.0,
            n_updates=0,
            generation=self._generation,
        )
