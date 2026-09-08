# The station timing estimator

`src/hf_timestd/estimator/` holds one estimator that maps a sample index to Coordinated
Universal Time (UTC). It runs on the sample counter alone. No host clock reaches it, no service
constructs it, and neither AC0G-ND nor AC0G-B4 receives anything from it. It ships as a library
with 199 tests and no consumers, deliberately, so that its arithmetic and its refusals could be
proven against recorded failure before any of it touched a live plane.

Its companion, the design spec at
[`docs/superpowers/specs/2026-09-08-station-timing-estimator-design.md`](../superpowers/specs/2026-09-08-station-timing-estimator-design.md),
carries the derivations, the acceptance table, and four amendments written while the code took
shape. This document says what the library does, what it refuses to do, and what a reader of
the code alone would not find out.

One night explains why it exists. On 2026-09-07 the AC0G-ND station acquired a tick
registration, verified it, held it to a millisecond, and then walked the host clock 150 ms away
from four network witnesses. Two faults combined. The registration named a second that the
ticks could not distinguish from three neighbours on a discrete lattice, and every projection
from the sample counter to UTC divided by a nominal sample rate while the converter ran tens of
parts per million away from it. Both faults appear below as rules this library now enforces.

---

## 1 · Two numbers, and the sign they carry

The converter samples at some true rate which the nominal rate approximates. Write `f_nom` for
the configured integer and `f_true` for what the hardware does. The fractional frequency error
follows:

    y = (f_true - f_nom) / f_nom

A converter running fast gives `y > 0`. The Offset Judge already works that way, reasoning in
`offset_judge.py` about what follows if the ADC clock runs fast by r ppm. The library inherits
that convention rather than inventing a second one.

The estimator holds two numbers and no others:

| state | symbol | units | meaning |
|---|---|---|---|
| phase | `phase_ns` | nanoseconds | additive correction to UTC at the reference sample |
| rate | `rate_ns_per_s` | nanoseconds per second | the phase correction's rate of change |

The rate state relates to the fractional error by `rate_ns_per_s = -y * 1e9`. The minus sign
earns its place. A converter that samples fast accumulates sample indices faster than real
time, so a projection that divides by the nominal rate over-reads elapsed time, so the
correction that repairs it grows more negative. One thousand nanoseconds per second equals one
part per million, which matches the judge's `PPM_PER_NS_PER_S = 1.0/1000.0`.

The equation, the table and the paragraphs around them come from the spec verbatim. They stay
verbatim so the two documents cannot drift apart, and a reader who finds them differing should
trust the spec and fix this file.

Absolute UTC in nanoseconds since 1970 exceeds 1.7e18, and a double resolves no better than a
few hundred nanoseconds there. So the estimator keeps the coarse part of the answer as two
integers, `rtp_ref` and `utc_ref_ns`, and lets `phase_ns` carry only a small residual against
that plane. Every `solve` folds the whole nanoseconds of the residual into the integer
reference and keeps the fraction, so the plane moves without losing anything. A test drives one
hundred thousand folds and measures the drift at under a nanosecond.

---

## 2 · One convention for elapsed time

Elapsed time means sample count divided by the *nominal* rate, on exactly one line in the whole
package, and the ruler's actual rate enters through the phase state:

    tau(delta_n) = delta_n / f_nom          # the one nominal division

That line lives in `ClockState.nominal_seconds` and carries the marker comment `# THE ONE
NOMINAL DIVISION`. A test in `tests/estimator/test_boundaries.py` walks every source line in
the package, matches any division by a bare or dotted `f_nom`, and asserts that exactly one
such line exists and that it carries the marker. Eight further cases test the matching pattern
itself. The guard counts as the deliverable here, and a guard that quietly stops matching does
more harm than no guard at all.

The same file holds two sibling guards. One parses each module with the abstract syntax tree
and rejects any import of `hf_timestd` outside the estimator package, which catches `from
hf_timestd import core` as well as the dotted form. The other rejects `time.time()`,
`datetime.now()` and `chronyc` anywhere in the package. None of the three can see through a
local alias: assign `fs = self.f_nom` and divide by `fs`, and the text guard reports green.
They serve as smoke alarms. The real protection lives in the behavioural tests, where a state
carrying a non-zero rate whose projection still matches the nominal rate fails outright.

### The rate was very nearly applied twice

The first draft of the spec declared the opposite of the rule above: that elapsed time always
meant sample count over the *measured* rate, and that nothing in the package divided by the
nominal rate. The implementation followed it faithfully. A review then measured the result. On
a ruler running ten parts per million, advancing the filter and then folding the plane overshot
by ten microseconds every second, the whole rate error, compounding on every solve.

Mixing two self-consistent designs caused it. Projecting with the measured rate and holding
phase constant works. Projecting with the nominal rate and letting phase carry the rate works.
Doing both counts the rate twice. The process noise settled which one survives, because the
two-state clock model's Q assumes phase integrates the rate.

The correction collapsed prediction and rebase into one method, `advance_to`, so the reference
plane moves with the prediction and nothing extrapolates twice. Spec §1 now states the rule
above, and its §1.1 records the episode. The instrument's whole history is variations on this
one fault: two quantities that each looked right, describing the same thing twice.

The regression tests written to guard it lacked the power to catch it, and a reviewer showed
this by subclassing `ClockState` to reinstate the defect and running every test body against
the mutant. Sixteen of seventeen passed. The double count is exactly `rate * tau` per fold, so
it is perfectly linear, and a test that compares many small folds against one big fold cannot
see it. The replacement asserts against an analytic value derived from the physical sample rate
with exact rational arithmetic: over an hour at 24000.24 samples per second the truth reads
3,599,964,000,360 ns, the shipped code matches it exactly, and a double-counting build lands
35,999,640 ns away.

---

## 3 · What a witness must supply

Every tier reduces to one of two statements. The library defines both, accepts them from
anyone, and fetches nothing itself.

A phase observation says that the sample at a named index carried a given UTC:
`PhaseObservation(tier, rtp, utc_ns, sigma_ns, plane, source)`. The pulse-per-second edge, the
LBE per-arrival pairing and the tick registration all speak this way. So does wide-angle
network time, once a caller pairs a disciplined host reading with an arrival index. The sigma
must be finite and strictly positive; a witness that claims no uncertainty carries no
information and the constructor refuses it.

A rate observation says the ruler runs fast or slow: `RateObservation(tier, ppm, sigma_ppm,
span_s, n, plane, source)`. `T6ResidualRateEstimator` speaks this way today, in exactly these
units, over a window of fifteen minutes. So does the judge's offset-slope regression. Both
`ppm` and `sigma_ppm` must be finite, and the sigma strictly positive.

Each observation declares its `plane`, either `label` or `host`, and the filter admits only
`label`. A host-plane phase observation reaches the coarse gate of §4 and nothing else; it
cannot even seed a plane when none exists. A host-plane rate observation reaches nothing at
all. The rule has teeth. The judge's offset-slope rate witness rides on whichever bench the
judge selected, and when that bench sits on the host plane the witness imports host error as
ruler rate. That path helped walk ND. A wide and honest host-plane number still does real work
at the coarse gate, where the question concerns whether this instrument disagrees with the
network, and it never touches the state.

Tier rank does not weigh. T6 outranks T3, and yet the judge's native-anchor bench floors its
sigma at 25 ms, because it measures when an anchor arrived rather than where the edge sat. A
tick registration reaching 1 ms therefore outweighs it by roughly six hundred to one, and
inverse-variance weighting produces that ratio without being told. The library ranks no tiers
for weighting. Rank survives in one place only, the quorum of §5, where the question concerns
identity rather than precision.

### The independence obligation, which nobody in this library can discharge

The admission logic counts distinct tier strings, and one tier string must mean one independent
witness: one antenna and one measurement chain. Neither the admitter nor the estimator can
verify that. Only whoever wires the adapters knows whether two tier strings name two antennas
or one.

Two adapters reading a single source would agree perfectly. They would satisfy the quorum of
two, sail through the concordance test, and let a lone witness move the plane, the one thing §5
exists to forbid. The library therefore states the obligation in three docstrings and enforces
nothing, on purpose: an enforcement that cannot enforce invites reliance on it. The design
considered validating tier strings against the canonical T6-to-T0 vocabulary and rejected it
for the same reason: that check would look like an independence test while still passing two
adapters both labelled T3.

Whoever wires the adapters carries this. It belongs in the integration spec, where the caller
is known, and it ranks first among the things to get right when a consumer finally arrives.

---

## 4 · The refusals

The estimator publishes a solution on every cycle, and that solution carries a verdict. It
never withholds silently. It never corrects anything, never steers a clock, never restarts a
service and never raises an alarm. The caller decides what to do, alarms, and withdraws. The
library only tells the truth about its own state, and a withheld solution still carries every
number it has, because a consumer that can see why an answer was withheld can act while one
handed silence cannot.

The solution's `witnesses` mapping carries four numbers per tier, not two: the accepted and
rejected counts, and — for any tier that has supplied at least one phase observation — the last
residual the admitter judged for it and the sigma it last declared. Counts alone do not diagnose
a station. Two tiers rejecting in the same direction by the same amount name a plane step; one
tier rejecting alone at nineteen sigma names a lattice confusion. The residual is what tells
those apart, so a consumer diagnosing a station reads it there. A tier that has only ever spoken
about rate carries neither of the last two, because its innovation lives in nanoseconds per
second and its sigma in parts per million, and filing those under names that mean nanoseconds
would put two units under one word.

Refusals resolve in order, first match winning, following the shape `registration_refusal`
already established. Eight of them sit in `gates.REFUSAL_ORDER`:

1. `not_finite` — some number the caller supplied, or some number the estimator derived from
   it, is not a finite value. The record carries the actual NaN rather than a zero dressed up
   as real. A caller should read this as a defect in its own wiring and alarm, not retry.
2. `counter_ambiguous` — the sample counter delta could not be resolved, and the latch holds
   until an announced counter-epoch change clears it. See below; this one deserves its own
   discussion.
3. `no_phase_witness` — no phase observation has ever been accepted. Expected at start-up.
   A caller should alarm only when it persists past the time its witnesses take to arrive.
4. `stale_phase` — the newest accepted phase observation is older than 300 s. The witness
   supply has stopped, so the caller should look at the acquirer rather than at the filter.
5. `step_pending` — a concordant quorum dwells, per §5. The old plane still stands and is
   withheld on purpose. It clears within the 120 s dwell, one way or the other, so a caller
   should wait rather than act.
6. `variance` — the phase sigma sits above the publish ceiling, 5 ms by default. The answer
   is honest but too wide to use. A consumer should hold its last good plane.
7. `coarse_disagreement` — a wide-angle witness disagrees with the state beyond three
   combined sigmas. Alarm loudly. Wide-angle network time and the WWV ticks both trace to
   GPS, so when they disagree by more than the network's own budget the fault lies with this
   instrument.
8. `rate_disagreement` — two fresh rate witnesses differ by more than 1 ppm. Alarm. The
   threshold matches the judge's existing `rate_alarm_ppm` default, so a station does not
   carry two different opinions about what a rate disagreement means.
A ninth refusal stands outside that order. The estimator checks `rate_not_positive` itself,
second, before the gates run at all, because the gates never see the measured sample rate and
cannot judge it.

That ninth cannot fire today. A non-positive measured rate needs a rate state at or beyond a
stopped clock, and `ClockState.f_meas` raises on that denominator first, which the estimator
reports as `not_finite`. It stays as defence in depth against a future change to that guard. So
the honest caller guidance runs the other way: nobody will meet it, and whoever does should
suspect the estimator's own invariants before anything else, because the guard upstream has
changed.

`not_finite` and `rate_not_positive` share a privilege the other seven lack. A solution carrying
either may hold non-finite numbers, so the record reports the unusable number that caused the
refusal rather than substituting a plausible one.

An unstated ruler does not refuse. A ruler whose discipline nobody observed or attested counts
as undisciplined, which widens the sigma and shows in the published diagnosis. It does not
block a solution, because a wide honest answer serves a consumer and a missing answer does not.

Two refusals now expire. Neither the coarse reading nor the rate readings originally carried a
timestamp, so one transient disagreement voted forever: two rate witnesses 5 ppm apart at
minute six still forced `rate_disagreement` 194 good minutes later, survived an epoch change
and a reseed, and would have ended the station's timing product for as long as the process ran.
Both records now carry a ruler timestamp and expire at the admission policy's freshness window,
180 s. Silence from a witness is not agreement, so the gate must not treat it as disagreement
either; noticing that a witness died belongs to whoever wired it.

`not_finite` arrived last among the original seven, from a review that probed the gates with
NaN. Every comparison against NaN evaluates false, so a NaN cleared all six earlier refusals
and published a clean verdict. The path was real rather than hypothetical: the rate observation
validated its sigma and never validated its parts-per-million value, so one NaN at the boundary
reached the decision point and passed. A module whose whole job is deciding whether to publish
must fail closed, and it must name the actual fault rather than dress a NaN up as staleness.

### The counter-wrap horizon

A signed 32-bit sample delta resolves a true interval only while the two readings sit within
half a wrap of each other: 2^31 samples, about 24.9 hours at 24 kHz. Past that horizon the pair
is indistinguishable, modulo 2^32, from a pair half a wrap closer together, and a projection
aliases by a full wrap period without raising anything.

The estimator folds its plane forward on every solve, so no working station approaches the
horizon. A station that stops does. A paused daemon or a recorder outage resumes with a forward
gap that aliases to a negative delta, carrying the same sign as a backward step. The first design
said `advance` should refuse a negative delta by returning without change, and silently. A
review measured what that produced: a thirty-hour gap published with no refusal at all and a
UTC wrong by one whole wrap period, 178,956.97 s, with ruler time frozen so `stale_phase` never
fired either. Gaps at 24 hours resolve; 25 hours and beyond alias.

So the estimator latches instead of failing quietly. An unresolvable delta sets a sticky flag
and every later solution withholds under `counter_ambiguous`, until the caller announces a
counter-epoch change through `note_counter_epoch_change`, because only a fresh seed
re-establishes the plane. A station that legitimately idles more than a day must therefore
re-seed rather than resume, which is the correct behaviour for an instrument that cannot prove
how long it slept.

### What a negative delta means, and why magnitude decides

Latching on every negative delta was itself a fault, and a worse one. Two tiers on different
cadences report out of order as a matter of course, so one witness naming a sample index one
second behind the last one is ordinary integration. Latching on that withheld every later
solution, permanently, on an announced-epoch-change-only reprieve. Measured: a healthy plane,
then one witness a second behind, and every later solve returned `withhold /
counter_ambiguous` forever.

The two cases differ by magnitude, by roughly three hundred to one, and the bound needs no
constant anybody chose. A genuinely late arrival can only be so late and still matter: a phase
observation older than `gates.max_phase_age_s` is what `stale_phase` already refuses, 300 s,
which is 7,200,000 samples at 24 kHz. An aliased gap comes back near minus half a wrap, about
-70,000 s. So:

| magnitude of a negative delta | reading | what happens |
|---|---|---|
| within `max_phase_age_s` | an out-of-order arrival | that one observation is refused as `out_of_order` and counted against its tier; the state, the plane and the latch are untouched, and later solutions publish |
| beyond it | an aliased gap | `counter_ambiguous` latches, exactly as above |

An out-of-order refusal is counted through `Admitter.note_rejection`, which bumps the tally and
files no dissent. A late arrival says nothing about where the plane sits, so it must never help
a quorum license a step.

The plane is also read before the clock moves. A host-plane phase observation reaches the
coarse gate and nothing else — the ruler clock included — because letting the network advance
this estimator's own time base is the coupling §3 forbids.

One case still survives, and the library documents it rather than papering over it. A gap of
almost exactly a whole number of wrap periods aliases to a small delta of either sign. A small
positive one reads as an ordinary short interval; a small negative one reads as an out-of-order
arrival and gets refused. Neither reading detects the gap, and no arithmetic on a 32-bit counter
could. Witness innovations do, because the implied error then runs to tens of hours and every
witness rejects, loudly.


### 4.1 · Four things a consumer must know before wiring this up

A final review probed the assembled estimator and surfaced these. None of them is a defect, and
each would surprise someone reading the code alone.

A tier known only from out-of-order refusals publishes its counts with neither a last residual
nor a last sigma. Treat both keys as optional for any reason, not only for a rate-only tier.

The rejected count merges outliers with out-of-order arrivals, and the last residual comes from
the last judged observation of that tier. Only the verdict's reason separates the two, so a
consumer diagnosing a station should read the reason rather than infer from the count.

The out-of-order reason string does not appear in the package's public surface. Matching on it
means importing the estimator module's own constant.

And an unannounced backward counter step smaller than the staleness window no longer latches.
Every later witness refuses, the plane freezes, and the station surfaces as a stale phase once
solving continues at forward indices. A caller that keeps solving at ONE index never advances
ruler time, so a frozen plane would publish indefinitely with no refusal at all. Drive the solve
forward.

---

## 5 · The step rule

A wrong lock announces itself as a step. A drifting ruler announces itself as a slope. A
two-state filter fed a step with no defence absorbs part of it into rate and then projects that
fabricated rate forward forever. That failure mode earns the sharpest rule in the library.

For each observation the estimator computes the innovation and its variance and accepts when
the innovation stays within three sigma. Otherwise it rejects, records the rejection against
the tier, and leaves both the state and the covariance untouched. A rejected observation
changes nothing at all. Rate observations pass the same test, inline rather than through the
admitter, because a rejected rate witness must never reach the machinery that licenses a plane
step.

A single tier may never move the plane. No matter how confident, how small its sigma, or how
many times it repeats, one tier's rejected observations only accumulate a rejection count. A
test repeats a 50 ms error a thousand times from one tier and measures no movement in either
state.

Two or more tiers rejecting in the same direction, whose implied errors agree with each other
within three times twice the widest witness sigma, declare a candidate step. That concordance
test matches the one already written in `witness_dissent.py`; the library imports nothing from
it, because the package may not reach into the core, so it reimplements the same test and the
shared lineage lives in the spec.

A candidate must then dwell for 120 s, matching the existing dissent watch and the acquirer's
two-minute adoption hysteresis. While it dwells the solution keeps the old plane and carries
`step_pending`. If the quorum survives the dwell, the estimator reseeds phase to the quorum's
implied UTC, inflates the phase variance to the quorum spread, zeroes the phase-rate
cross-covariance, and leaves the rate state and its variance exactly as they stood. If the
quorum dissolves, the candidate expires and nothing moves.

### The 2026-09-07 lattice, worked

The ND acquirer's confusions that night sat on a discrete lattice, and each one would have
poisoned a rate estimate had the filter absorbed it as evidence about frequency:

| confusion | phase error |
|---|---|
| WWV against WWVH | 18.7 ms |
| WWV against BPM | 34 to 37 ms |
| the two compounded | about 50 ms |

Take the 18.7 ms case. One tier reports a plane 18.7 ms from where the filter believes it sits.
Against a phase sigma of a millisecond that innovation runs nearly nineteen sigma, so the gate
rejects it and the state does not move. Repeat it every minute for an hour and the state still
does not move; the rejection tally climbs and the published witness record shows one tier
dissenting hard, which hands an operator exactly the diagnosis it needs. Now suppose a second,
genuinely independent tier reports the same 18.7 ms in the same direction and the two agree
within their combined sigmas. The estimator declares a candidate, waits two minutes, and if
both hold, reseeds phase by 18.7 ms and leaves rate untouched. The plane moves; the frequency
estimate does not learn a thing from the lattice.

The acceptance suite injects all three errors on one tier across every corpus and asserts that
the plane does not move. Getting that test to fail for the right reason took work. The first
version passed because the injected step froze the filter, not because the estimator refused
it: rerunning the same body with a zero-millisecond injection also failed. The replacement runs
a clean control beside the injected subject and asserts three things together — the control
accepts most of its witnesses, the subject rejects the injected ones, and the two runs' rates
and planes agree closely. Widening the gate makes it fail on absorption, at 46.6 ppm of rate
difference; narrowing the gate makes it fail because the control stops accepting. The test now
fails in both directions, which the version first written did in neither.

### An acceptance corpus is one witness, by construction

Each corpus row comes from one subcarrier band of one radio-frequency channel of one fixture,
so every row in a series carries the same tier string. A quorum needs two distinct tiers. No
step can ever ripen from an acceptance corpus, and none of the acceptance tests may depend on
one ripening.

That is the design working, not a limitation to route around. One witness may never move the
plane, and a corpus drawn from one witness is one witness. A future test that wanted to
exercise the quorum would have to supply two genuinely distinct series, and if it faked the
distinction by relabelling the same series under two tiers it would be committing exactly the
independence violation of §3.

A related trap cost two fix rounds. Three radio-frequency channels each independently tag the
same subcarrier band string, so selecting a corpus by fixture and band alone merged three
propagation paths into one series and recovered +209.30 ppm against +0.048 for a single
channel. Every row now carries its channel and the acceptance rows select on fixture, channel
and band together.

---

## 6 · The rate, and what a consumer does with it

A consumer holds no phase state and cannot integrate anything, so the solution publishes a
sample rate for it to divide by, and that rate resolves exactly to the estimator's own
projection:

    rate_samples_per_utc_sec = f_nom * 1e9 / (1e9 + rate_ns_per_s)

Not `f_nom * (1 + y)`. That linearisation disagrees with the projection at second order, and
second order is where one arithmetic quietly becomes two: measured, the gap reaches 36
microseconds over an hour on a ruler running 100 parts per million, while the exact form agrees
to the nanosecond. A consumer that divides by the published figure reproduces
`TimingSolution.utc_ns_at` to zero nanoseconds, and the shipped code builds both the published
rate and the published parts-per-million figure from one shared denominator, so the two cannot
disagree bit-for-bit.

`rate_ppm` publishes `y` itself, the fractional frequency offset of §1, in parts per million.
That reverses an earlier decision, and the reversal is worth knowing. The first design
published `rate_ppm` as the linear phase-slope figure, `-rate_ns_per_s / 1000`, the convention
the rest of the instrument uses, so that an observed figure would round-trip through the state
unchanged. A review then found the consequence: the two published fields disagreed, by 0.0036
parts per million at 60, and the test demanding they agree could not pass. The definition
settles it. §1 defines `y` as `(f_true - f_nom) / f_nom`, so `y` in parts per million is what a
reader of `rate_ppm` expects, and the linear form only ever approximated it. One meaning for
one name is the whole lesson of the double-count episode.

A rate observation still converts its parts-per-million figure linearly on the way in, at 1000
nanoseconds per second per part per million, because at 60 parts per million the difference
reaches 0.0036 ppm against an observation sigma no better than 0.15 ppm. A conversion buried
forty times inside its own uncertainty is not a second arithmetic. The cost of that choice: a
rate observation of exactly -60.000 ppm reads back as -59.996. Nothing depends on that
round-trip.

The solution also publishes an A-level and the ruler's provenance. Both describe; nothing in
the code branches on either. That inverts today's arrangement, where the A-level selects
behaviour, and it follows from the process noise carrying the information instead.

**No consumer reads any of this yet.** The §18 authority snapshot carries a field of the same
name, `rate_samples_per_utc_sec`, and it holds the nominal integer under an explicit contract
comment. `NativeAnchor` carries an integer `sample_rate_hz` and no sigma; `LabelAnchor` adds no
rate at all. All three need a float and an uncertainty before a rate-corrected plane can reach
anybody. Audit item G7 also forbids folding a measured frequency into the label arithmetic, and
this library does exactly that, deliberately, so the judge's doctrine needs an amendment
written against this design before any consumer reads such a plane. Reconciling the integer
field with the float belongs to integration, and integration has not happened.

---

## 7 · How much the estimator trusts its own memory

Michael's constraint on the design: the graceful path from a governed ruler to a free-running
one must fall out of the mathematics rather than out of a constant somebody chose. The
two-state clock model takes process noise from two coefficients, one for white frequency noise
and one for random-walk frequency noise, and both read straight off an Allan deviation. A
governed ruler measures a small deviation, the filter grows a long memory, and a
sub-millisecond witness barely nudges a rate the hardware holds to four parts in ten million. A
free-running converter measures a large deviation, the filter's memory shortens to minutes, and
the same witnesses track a rate that actually moves. One mechanism, two regimes, no branch.

Getting the input series right took three rulings, and the first two got it wrong. The first
design fed the Allan deviation from the estimator's own innovations. Implemented faithfully and
then measured, it proved degenerate: the fitted deviation tracked the white-phase-noise
signature of the witnesses across eight taus from 60 s to 7680 s, flat to three per cent.
Structure explains that, not arithmetic. An innovation names what the filter could not predict,
and the filter has already absorbed the ruler's wander into its rate state, so the residue
carries the witnesses' noise and none of the ruler's. Asking a filter to measure the very
quantity it exists to remove cannot work, however the fit is arranged.

The series that does carry it is the classical clock difference: each witness's UTC minus the
nominal ruler reading, both referenced to a plane fixed at the seed and never rebased. Allan's
second differences remove any constant offset and any constant frequency error, so no
correction for the estimated rate is needed. Simulated against half-millisecond witnesses over
ten hours, that series' deviation at the longest tau sits at 1.03 times the witness floor for a
ruler wandering 0.0035 ppm per hour, 1.09 at 0.035, 6.5 at 0.35, and 30 at 3.5. Which is the
honest division of labour: a governed ruler stays invisible, and an undisciplined one — the
only case where adaptive process noise earns its place — announces itself loudly.

The estimator therefore refuses a coefficient it cannot distinguish from its own witnesses. It
compares the fitted deviation at the longest tau against the white-phase floor those witnesses
imply, keeps the stand-in unless the measurement clearly beats it, and refuses to fit at all
when the series carries a hole, since the Allan routine assumes uniform spacing and a median
gap is hole-blind.

### A governed ruler reports `standin` permanently, and that is correct

Separating a 0.01 parts-per-million ruler from millisecond witnesses needs a tau near a day.
Witness white-phase noise falls as the inverse of tau, so millisecond witnesses sit at 2.4e-07
at one hour and reach a governed ruler's own 1.0e-08 only near 86,400 s. Waiting does not close
that gap. The fixed measuring plane cannot outlive half a counter wrap, 24.86 hours at 24 kHz,
so it re-anchors and the series starts again, and the reachable longest tau measures 0.29 of
the span, putting the ceiling near seven hours.

The 86,400 s tau lies beyond what this architecture can reach at all, on any station, however
long it runs. A governed ruler will report `standin` for its process-noise source forever, and
that is the correct label rather than a temporary one. Only witnesses of pulse-per-second class
could ever measure such a ruler here.

The measured path still does real work, though. On a ruler wandering 3.5 ppm per hour the
fitted deviation runs 19 to 163 times the witness floor and `q_source` reads `measured` on
every seed, and it reads `standin` again the moment a three-hour hole enters the same ruler's
series.

`q_source` describes the coefficient the filter is currently running on, and it is derived from
that coefficient rather than carried beside it. A `RulerNoise`'s own `source` string travels
with the number and outlives the fit that set it, so reading the stored string published a label
about a past measurement instead of about the value in use. Whenever the random-walk coefficient
sits at the declared floor the answer is `standin`, whatever an earlier fit called itself. A
published provenance field that can disagree with the value it describes undoes the honesty the
rest of this design rests on, and one derived from the value cannot.

### A high rejection rate against a declared-disciplined ruler means the declaration is false

Remember this signature. It looks like a filter defect and it is not one.

Measured during execution: a ruler declared `observed` while genuinely wandering at 3.5 ppm per
hour rejected 522 of 599 witnesses. The 0.01 ppm stand-in lets its rate variance regrow at
0.0013 ppm per minute against a 0.45 ppm per minute walk, so every step presents a
fifteen-sigma rate error and the gate discards exactly the evidence a fit would need. Declared
`assumed`, the same ruler and the same witnesses gave 597 acceptances out of 600 and the fit
read `measured`.

The station then withholds and alarms rather than quietly adapting, and that is intended. Quiet
adaptation would mask a hardware fault. A station that declares a disciplined ruler it does not
have should stop publishing and say so, which is this instrument's standing rule: expose a
timing fault, never correct it. The rejections show in the published witness tally and the
refusal path fires, so the station withholds rather than lying.

The fix belongs at the hardware, or in the provenance if the hardware is honest and the
declaration is stale. It never belongs in the filter.

One more number, from the same family of mistakes. The seed's rate variance is not the wander
stand-in. The stand-in table says how much a ruler's rate *moves*; it says nothing about how
far from nominal that rate already sits when the estimator first opens its eyes, and the two
differ by orders of magnitude. Seeded from the 2 ppm wander figure, the filter put ND's
documented 350 ppm fault 175 sigma outside its belief, recovered -0.43 ppm against a true -60,
and threw away nine witnesses in ten. Seeded at 100 ppm it recovers -59.985 and rejects none,
flat from 50 ppm to 500. A prior that excludes the failure the library was built to survive is
blind, not conservative.

---

## 8 · What this does not provide

**Absolute accuracy.** The corpus that proves this library works measures the fold peak's
position in each block, which gives phase against the ruler up to one unknown constant: the
propagation delay plus the station's identity offset. That constant cancels in a slope, so the
corpus measures rate honestly and measures absolute phase not at all. Absolute phase needs the
propagation model, which stays in the acquirer's hands. The estimator's phase reaches as far as
its witnesses reach and no further.

**Station identity.** Two tiers reading the same misidentified station agree perfectly. The
quorum of §5 defends against a lone confident witness; it offers nothing against a shared
delusion. The 800 ms marker that names WWV against WWVH addresses identity, and it lives in the
acquirer. The coarse network gate catches the gross case, which covers the 50 ms lattice but
not a 1 ms one. A replica correlator against a locally generated broadcast would supply a real
discriminant, and it would arrive through the witness interface this library already defines,
but nobody has written it.

**Any station integration.** No service constructs the estimator, no unit file changes, no
consumer reads its rate, and neither ND nor B4 received anything from this work. The seventeen
sites in this repository that carry the nominal integer into a plane still carry it. The
judge's doctrine still forbids what this library does. Composing several radiod counter spaces
into one station answer belongs to integration too, though the multiplicity buys a free
cross-check rather than causing a problem: one instance per counter space, each estimating the
same physical converter's rate, and their rates must agree inside the 1 ppm threshold.

**A settled account of the ND rate fault.** The three fixtures of 2026-09-06 show a governed
ruler on both stations, within a few tenths of a part per million of nominal. The following
night measured tens of parts per million twice, by two paths. Three readings still fit: the
converter lost lock between the sixth and the seventh, which a marginal drive level would
explain, since ND once ran 350 ppm at the LBE-Mini's 8 mA floor and locks at 32 mA; or the
judge's offset-slope rode a host-plane bench and measured the host walking rather than the
ruler drifting; or the anchor-term series projected a stale reference forward and measured its
own staleness. This library cannot settle it. A resampled corpus, real signal and real fading
with an exact -60 ppm imposed on it, supplies the known truth the recorded night never held,
and the estimator recovers -60.14 from it.

**A fix for the hardware.** The GPSDO needs to drive the RX888 at 27 MHz and 32 mA. No software
substitutes for that. This estimator only stops the station lying about it.
