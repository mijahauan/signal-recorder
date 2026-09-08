# One estimator on the ruler: phase, rate, and every tier as a witness

Status: design, approved in brainstorm 2026-09-08.
Scope: a library inside hf-timestd. No station integration in this cycle.
Supersedes nothing. Derives from `docs/design/MEASUREMENT_MODEL.md` and answers its §6.3.

---

## 0 · Why this exists

On 2026-09-07 the AC0G-ND station acquired a tick registration, verified it, held it to a
millisecond, and then walked the host clock 150 ms away from four network witnesses. Two
separate failures combined. The registration named a second the ticks could not distinguish
from three neighbours on a discrete lattice, and every projection from the sample counter to
UTC divided by a nominal sample rate while the actual converter ran tens of parts per million
away from it. The station published a confident wrong answer twice in one evening, and each
time the loop certified itself.

Seventeen sites in this repository carry that nominal integer into a plane, either by projecting
a sample index to UTC or by testing a plane built that way. The judge measures the rate error
and records it beside the label, under an explicit doctrine that forbids applying it. That
doctrine held while a governed ruler made the error negligible. On an ungoverned ruler it turns
a measurement we already hold into a measurement we deliberately discard.

Michael stated the requirement plainly. Imagine no host clock at all, only fusion. The sample
counter serves as the ruler, the received ticks register it against UTC, and every tier of
evidence appears as a witness rather than as a competing authority. This document specifies the
one estimator that reading demands, as a library with no consumers, so that the mathematics and
the refusals can be proven against recorded failure before anything reaches a live plane.

---

## 1 · The measurand, and the two numbers that carry it

A station needs one map from a sample index to UTC. The converter samples at some true rate
which the nominal rate approximates. Write `f_nom` for the configured integer and `f_true` for
what the hardware does. The fractional frequency error follows:

    y = (f_true - f_nom) / f_nom

A converter running fast gives `y > 0`. The Offset Judge already works that way, reasoning in
`offset_judge.py` about what follows "if the ADC clock runs fast by r ppm". The library inherits
that convention rather than inventing a second one.

An earlier draft of this paragraph attributed a literal `"+ = ADC runs fast"` to
`RateEstimate.ppm`'s docstring. No such line exists there. I took a paraphrase from a survey for a
quotation, and a review caught it. The convention holds; the quotation never did.

The estimator holds two numbers and no others:

| state | symbol | units | meaning |
|---|---|---|---|
| phase | `phase_ns` | nanoseconds | additive correction to UTC at the reference sample |
| rate | `rate_ns_per_s` | nanoseconds per second | the phase correction's rate of change |

The rate state relates to the fractional error by `rate_ns_per_s = -y * 1e9`. The minus sign
earns its place. A converter that samples fast accumulates sample indices faster than real time,
so a projection that divides by the nominal rate over-reads elapsed time, so the correction
that repairs it grows more negative. One thousand nanoseconds per second equals one part per
million, which matches the judge's `PPM_PER_NS_PER_S = 1.0/1000.0`.

**One convention for elapsed time, everywhere in this package.** Elapsed time means sample
count divided by the *nominal* rate, on exactly one line, and the ruler's actual rate enters
through the phase state:

    tau(delta_n) = delta_n / f_nom          # the one nominal division

That choice is not free. The two-state clock model and the Allan-variance process noise of §6
belong together, and they assume phase integrates the rate. A projection that ALSO divided by a
rate-derived sample rate would apply the rate twice. §1.1 records how nearly that shipped.

**The published projection.** The estimator carries a reference plane as two integers, and
projects with a single extrapolation:

    utc_ns(n) = utc_ref_ns + round(phase_ns + (1e9 + rate_ns_per_s) * tau(n - rtp_ref))

The host clock appears nowhere in that expression, nor in the filter's time base. The filter
advances on sample count. A station whose host clock stopped entirely would keep producing
correct UTC from this estimator until its witnesses went stale.

**What a consumer divides by.** A consumer holds no phase state and cannot integrate anything, so
the solution publishes a sample rate for it to divide by, and that rate resolves exactly to the
projection above:

    rate_samples_per_utc_sec = f_nom * 1e9 / (1e9 + rate_ns_per_s)

Not `f_nom * (1 + y)`. That linearisation disagrees with the projection at second order, and
second order is where one arithmetic quietly becomes two: measured, the gap reaches 36 microseconds
over an hour on a ruler running 100 parts per million, while the exact form agrees to the
nanosecond. `rate_ppm` publishes `y` itself, the fractional frequency offset §1 defines, in parts per
million, so the two published fields cannot disagree:

    rate_ppm = (rate_samples_per_utc_sec / f_nom - 1) * 1e6

§1.2 records why that reverses an earlier decision. A rate OBSERVATION still converts its
parts-per-million figure linearly on the way in, `-ppm * 1000` nanoseconds per second, because at
60 parts per million the difference reaches 0.0036 ppm against an observation sigma no better than
0.15 ppm. A conversion buried inside its own uncertainty is not a second arithmetic.

## 1.1 · Amendment 2026-09-08 — the rate was very nearly applied twice

The first draft of §1 declared the opposite: that elapsed time always meant sample count over the
MEASURED rate, and that nothing in the package divided by the nominal rate. The implementation
followed it faithfully, and a task review then measured the result. On a ruler running ten parts
per million, advancing the filter and then folding the plane overshot by ten microseconds every
second, the whole rate error, compounding on every solve.

The cause was mixing two self-consistent designs. Projecting with the measured rate and holding
phase constant works. Projecting with the nominal rate and letting phase carry the rate works.
Doing both counts the rate twice. The process noise settled which one survives, because the Q of
§6 is the Q of the standard clock model.

The episode belongs in the spec rather than in a commit message, because the instrument's whole
history is variations on this one fault: two quantities that each looked right, describing the
same thing twice.

---

## 1.2 · Amendment 2026-09-08 — one meaning for parts per million

§1 first published `rate_ppm` as `-rate_ns_per_s / 1000`, the linear convention the rest of the
instrument uses, so that an observed figure would round-trip through the state unchanged. A task
review then found the consequence: the two published fields disagreed, by 0.0036 parts per million
at 60, and a test demanding they agree could not pass.

The definition settles it. §1 defines `y` as `(f_true - f_nom) / f_nom`, so `y` in parts per
million IS what a reader of `rate_ppm` expects, and the linear form only ever approximated it. The
exact round-trip of an input was a convenience; one meaning for one name is the whole lesson of
§1.1. So `rate_ppm` means `y`, everywhere the instrument publishes or reads it as a diagnostic.

---

## 2 · The reference plane, and why it rebases

Absolute UTC in nanoseconds since 1970 exceeds 1.7e18. A double carries about sixteen
significant digits, so a phase held as absolute seconds in floating point resolves no better
than a few hundred nanoseconds. T6 measures edges far finer than that. So the estimator keeps
the coarse part of the answer in integers and lets the filter work on a small residual.

The reference plane holds `rtp_ref: int` and `utc_ref_ns: int`. The state's `phase_ns` measures
a residual against that plane, and stays near zero because the estimator rebases whenever it
emits a solution:

    whole = floor(phase_ns)
    utc_ref_ns += whole
    phase_ns   -= whole
    rtp_ref     = n_now      # with utc_ref_ns advanced by the projection to n_now

The subtraction keeps the fractional nanosecond rather than rounding it away. Rebasing therefore
loses nothing, and a test drives a hundred thousand rebases and asserts the plane has not moved
by a single nanosecond. The covariance passes through a rebase untouched, because a rebase
shifts coordinates and changes no belief.

A counter epoch change moves the origin and leaves the ruler alone. So on an announced epoch
change the estimator discards phase, keeps rate with its variance intact, and increments a
generation counter. The caller announces the change; the recorder already detects it and
`CounterEpochTracker` already measures it.

---

## 3 · Witnesses

Every tier reduces to one of two statements. The library defines both, accepts them from
anyone, and fetches nothing itself.

**A phase observation** says that the sample at a named index carried a given UTC.

    PhaseObservation(tier, rtp, utc_ns, sigma_ns, plane, source)

The pulse-per-second edge, the LBE per-arrival pairing and the tick registration all speak this
way. Wide-angle network time speaks this way too, once a caller pairs a disciplined host reading
with an arrival index, and it declares itself host-plane, which routes it to the gate of §5 and
keeps it out of the state.

The field `seq` appeared here in the first draft and left again on 2026-09-08, during the
pre-flight scan of the implementation plan. Nothing in this document consumed it, and ordering
already comes from `rtp`, so it carried no reader.

**A rate observation** says the ruler runs fast or slow.

    RateObservation(tier, ppm, sigma_ppm, span_s, n, plane, source)

`T6ResidualRateEstimator` speaks this way today, in exactly these units, over a window of
fifteen minutes. So does the judge's offset-slope regression.

**The measurement model per observation.** A phase observation has `H = [1, 0]` and
`R = sigma_ns^2`. A rate observation has `H = [0, 1]`, and the library converts it on entry:
`z = -ppm * 1000` nanoseconds per second, `R = (sigma_ppm * 1000)^2`. Both go through one
scalar Kalman update, so there exists one update path and one place for a sign to be wrong.

**The host-plane rule.** Each observation declares its `plane`, either `label` or `host`. The
filter admits only `label`. This rule has teeth: the judge's offset-slope rate witness rides on
whichever bench the judge selected, and when that bench sits on the host plane the witness
imports host error as ruler rate. That path helped walk ND. A `host` observation may still
serve the coarse gate of §5, where a wide and honest number does real work, and it never touches
the state.

**Tier does not weigh.** T6 outranks T3, and yet the judge's native-anchor bench floors its
sigma at 25 ms, because it measures when an anchor arrived rather than where the edge sat. A
tick registration reaching 1 ms therefore outweighs it by roughly six hundred to one, and
inverse variance produces that ratio without being told. The library ranks no tiers for
weighting. Ranking survives in one place only, the quorum of §4, where the question concerns
identity rather than precision.

---

## 4 · Admission, and the rule that a step never becomes a rate

A wrong lock announces itself as a step. A drifting ruler announces itself as a slope. A
two-state filter fed a step with no defence will absorb part of it into rate, and then project
that fabricated rate forward forever. That failure mode deserves the sharpest rule in this
document.

**Innovation test.** For each observation compute `nu = z - H x` and `S = H P H' + R`. Accept
when `|nu| <= 3 * sqrt(S)`. Otherwise reject, record the rejection against the tier, and leave
both `x` and `P` untouched. A rejected observation changes nothing at all.

**A single tier may never move the plane.** No matter how confident, how many times it repeats,
or how small its sigma, one tier's rejected observations only accumulate a rejection count.

**A concordant quorum licenses a step.** When two or more tiers each reject in the same
direction, and their implied errors agree with each other, the estimator declares a candidate
step. Concordance reuses the test already written in `witness_dissent.py`: the spread across
dissenting witnesses stays within three times twice the widest witness sigma. The library
imports nothing from that module, because §7 forbids it, but it implements the same test and
the spec records the shared lineage.

**Dwell before a re-seed.** A candidate step must persist for a dwell of 120 s, matching the
existing dissent watch and the acquirer's two-minute adoption hysteresis. While a candidate step
dwells, the solution keeps the old plane and carries the refusal `step_pending`. If the quorum
survives the dwell, the estimator re-seeds phase to the quorum's median implied UTC, inflates
the phase variance to the quorum spread, zeroes the phase-rate cross-covariance, and **leaves
the rate state and its variance exactly as they stood**. If the quorum dissolves, the candidate
expires and nothing moves.

That last clause carries the whole lesson of 2026-09-07. Three of the lattice confusions the ND
acquirer suffered appear below. Each one would have poisoned a rate estimate had the filter
absorbed it as evidence about frequency.

| confusion | phase error |
|---|---|
| WWV against WWVH | 18.7 ms |
| WWV against BPM | 34 to 37 ms |
| the two compounded | about 50 ms |

---

## 5 · Refusals

The estimator publishes a solution on every cycle, and that solution carries a verdict. It
never withholds silently and it never corrects anything. The caller decides what to do, alarms,
and withdraws. The library only tells the truth about its own state.

Refusals resolve in order, first match winning, following the shape `registration_refusal`
already established. Seven of them:

| order | reason | condition |
|---|---|---|
| 1 | `not_finite` | any numeric input the caller supplied is not a finite number |
| 2 | `counter_ambiguous` | the sample delta aliased, so the plane can no longer be trusted |
| 3 | `no_phase_witness` | no phase observation has ever been accepted |
| 4 | `stale_phase` | newest accepted phase observation older than 300 s |
| 5 | `step_pending` | a concordant quorum dwells, per §4 |
| 6 | `variance` | phase sigma above the publish ceiling, 5 ms by default |
| 7 | `coarse_disagreement` | a wide-angle witness disagrees beyond three combined sigmas |
| 8 | `rate_disagreement` | independent rate estimates differ by more than 1 ppm |

One more refusal stands outside this table. The estimator checks `rate_not_positive` itself,
second, before the gates run at all, because the gates never see the measured sample rate and
cannot judge it. Nine refusals therefore exist, eight ordered here and one ahead of them.

That ninth cannot fire today. A non-positive measured rate needs a rate state at or beyond a
stopped clock, and `ClockState.f_meas` raises on that denominator first, which the estimator
reports as `not_finite`. The refusal stays as defence in depth against a future change to that
guard, and a caller will not meet it. A document that told an operator how to respond to it would
be describing something that never happens.

`not_finite` and `rate_not_positive` share a privilege the other seven lack: a solution carrying
either may hold non-finite numbers, so the record can report the unusable number that caused it
rather than substituting a plausible one.

### 5.2 · Amendment 2026-09-08 — magnitude decides what a negative delta means

`counter_ambiguous` first latched on ANY negative sample delta. The final whole-branch review
found the consequence: one witness reporting an index behind the last withheld every later
solution until an announced epoch change, permanently, and two tiers on different cadences make
that the ordinary case rather than an exotic one.

Two of this document's own rulings had interacted. One argued a backward observation was already
refused, which held while refusing meant a silent return. A later one turned that return into a
permanent latch and never revisited the argument. No task-scoped review could see both halves.

Magnitude separates the two cases, and the separation needs no new constant. A genuinely
out-of-order arrival lies at most one staleness window behind, 300 s or 7,200,000 samples at
24 kHz. An aliased gap lands near half a wrap, about 70,000 s. A factor of three hundred divides
them. So a negative delta inside `max_phase_age_s` names an out-of-order arrival, which the
estimator refuses and counts without latching and without touching the state, and anything beyond
it latches as before. A review confirmed the boundary tracks the configured value rather than a
hard-coded one.

A host-plane observation now advances nothing at all. The estimator reads the plane before it
moves the clock, because letting a network witness advance this estimator's own time base is the
coupling §3 exists to forbid.

---

### 5.1 · Amendment 2026-09-08 — this table fell two refusals behind its own code

`counter_ambiguous` arrived with ruling R33 and `rate_not_positive` with R37, and I amended the
code both times without amending this table. Task 11's writer caught it while trying to document
the refusals and found the spec saying seven where the code said eight, and §7 saying six over a
tuple of eight.

Worth recording rather than quietly fixing, because the whole purpose of a spec that names its own
amendments is to stay ahead of the code, and twice in one day it did not. A ruling that changes
behaviour has to change this document in the same breath.

`not_finite` arrived on 2026-09-08, from a task review that probed the gates with NaN. Every
comparison against NaN evaluates false, so a NaN cleared all six original refusals and published a
clean verdict. The path was real rather than hypothetical: a rate observation validates its sigma
and never validated its parts-per-million value, so one NaN at the boundary reached the decision
point and passed. A module whose whole job is deciding whether to publish must fail closed, and it
must name the actual fault rather than dress a NaN up as staleness.

Reasons 6 and 7 deserve their mandatory character. Wide-angle network time and the WWV ticks
both trace to GPS. When they disagree by more than the network's own budget, the fault lies with
this instrument, and the honest act consists of refusing to publish and saying so loudly. The
1 ppm threshold matches the judge's existing `rate_alarm_ppm` default, so a station does not
carry two different opinions about what a rate disagreement means.

**An unstated ruler does not refuse.** The measurement model §2 rules that a ruler whose
discipline nobody observed or attested counts as undisciplined. That widens the sigma through
§6 and appears in the published diagnosis. It does not block a solution, because a wide honest
answer serves a consumer and a missing answer does not.

---

## 6 · Process noise from the measured Allan deviation

Michael's constraint: the graceful path from a governed ruler to a free-running one must fall
out of the mathematics rather than out of a constant somebody chose.

The two-state clock model takes process noise in the standard form, over an interval `tau`:

    Q(tau) = [[ q1*tau + q2*tau^3/3 ,  q2*tau^2/2 ],
              [ q2*tau^2/2          ,  q2*tau     ]]

`q1` carries white frequency noise and `q2` carries random-walk frequency noise. Both read
straight off an Allan deviation. In the white-frequency region the Allan variance falls as
`q1/tau`, and in the random-walk region it rises as `q2*tau/3`, so:

    q1 = sigma_y(tau_a)^2 * tau_a  * 1e18        # fitted at a mid tau
    q2 = 3 * sigma_y(tau_b)^2 / tau_b * 1e18     # fitted at a long tau

The factor of 1e18 converts a dimensionless frequency to nanoseconds per second, squared.
`hamsci_dsp.stability` supplies the deviation: `compute_phase_adev` takes a phase series in
seconds and a sample interval, and `identify_noise_type` names the slope, which the library uses
to choose which region each fit belongs to.

**The series must be the fixed-plane witness residual, never the filter's innovations.** §6.2
records why, and it is the subtlest mistake in this document's history.

A governed ruler measures a small deviation and the filter grows a long memory, so a
sub-millisecond witness barely nudges a rate the hardware holds to four parts in ten million.
A free-running converter measures a large deviation and the filter's memory shortens to
minutes, so the same witnesses track a rate that actually moves. One mechanism, two regimes, no
branch.

**Bootstrapping honestly.** A cold estimator has measured nothing. It therefore takes its
coefficients from the ruler's declared discipline state, using the stand-in sigmas the
measurement model already tabulates, and replaces them with measured values once the span
supports a fit. The solution publishes which of the two it used.

**Wander and seed accuracy name different quantities.** The stand-in table below says how much a
ruler's rate MOVES. It says nothing about how far from nominal that rate might already sit when
the estimator first opens its eyes, and the two differ by orders of magnitude. A free-running
oscillator wanders by a part per million or two; an RX888 whose GPSDO never reaches it can sit
hundreds of parts per million away, and the measurement model records AC0G-ND at roughly 350 ppm
on an LBE-Mini at its 8 mA drive floor.

So the initial rate variance is its own number, and a generous one. Seeded from the 2 ppm wander
stand-in, the filter puts that documented 350 ppm fault 175 sigma outside its belief, rejects
almost every witness that would correct it, and converges on nothing: measured, it recovered
-0.43 ppm against a true -60 and threw away nine witnesses in ten. Seeded at 100 ppm it recovers
-59.985 and rejects none, flat from 50 ppm to 500. §6.1 amends this into the design.

| ruler state | fractional sigma | provenance |
|---|---|---|
| disciplined, measured | 0.0004 ppm | measured on AC0G-B4, 2026-08-16 |
| disciplined, stand-in | 0.01 ppm | `t6_holdover.UNMEASURED_RATE_SIGMA_PPM` |
| undisciplined, stand-in | 2.0 ppm | `UNMEASURED_RATE_SIGMA_PPM_A0` |

### 6.2 · Amendment 2026-09-08 — a filter cannot measure what it has already removed

The first draft fed the Allan deviation from the estimator's own innovations. A task review
implemented that faithfully, measured it, and proved it degenerate: the fitted deviation tracked
`sqrt(3) * sigma_x / tau` across eight taus from 60 s to 7680 s, flat to three per cent, which is
the signature of pure white phase noise and nothing else.

The reason is structural rather than numerical. An innovation is what the filter could NOT
predict. The filter has already absorbed the ruler's wander into its rate state, so the residue
carries the witnesses' noise and none of the ruler's. Asking a filter to measure the very quantity
it exists to remove cannot work, however the fit is arranged.

The series that does carry it is the classical clock difference: each witness's UTC minus the
nominal ruler reading, both referenced to a plane FIXED at the seed and never rebased. Allan's
second differences remove any constant offset and any constant frequency error, so no correction
for the estimated rate is needed. Simulated against half-millisecond witnesses over ten hours, the
ratio of that series' deviation to the witness floor at the longest tau runs:

| ruler wander | ratio at the longest tau |
|---|---|
| 0.0035 ppm/hr | 1.03 |
| 0.035 ppm/hr | 1.09 |
| 0.35 ppm/hr | 6.5 |
| 3.5 ppm/hr | 30 |

Which is the honest division of labour. A governed ruler stays invisible and keeps its stand-in,
whose 0.01 ppm is already tight. An undisciplined one, the case where adaptive process noise earns
its place at all, announces itself loudly.

---

### 6.1 · Amendment 2026-09-08 — the seed is not the wander

`EstimatorConfig.seed_rate_sigma_ppm` defaults to 100 parts per million and seeds `P[1,1]`. It
exists because the first draft seeded the rate variance from the wander stand-in, which cannot
represent a hardware fault this instrument has actually suffered. A filter whose prior excludes
the failure it was built to survive is not conservative; it is blind.

**The A-level describes, it does not switch.** The solution publishes an A-level and the
ruler's provenance as diagnosis. Nothing in the code branches on either. That inverts today's
arrangement, where the A-level selects behaviour, and it follows from the process noise carrying
the information instead.

---

## 7 · What the library looks like

A new package, importing nothing from `hf_timestd.core`, and importing `hamsci_dsp` only for
the Allan deviation. A test walks the package's imports and fails on any reference to `core`.
That test defends the deferral of integration, which otherwise erodes one convenience at a time.

    src/hf_timestd/estimator/
      __init__.py         public surface: the estimator, the observations, the solution
      observations.py     PhaseObservation, RateObservation, plane and tier validation
      clock_state.py      the two-state predict and scalar update, and the rebase
      process_noise.py    Allan deviation to q1 and q2, with the stand-in fallback
      admission.py        innovation test, rejection counts, quorum and dwell
      gates.py            the eight ordered refusals
      solution.py         TimingSolution, frozen, with utc_ns_at
      estimator.py        StationTimingEstimator: observe, advance, solve

The repository asks for one class per file. Three of these modules group small frozen
dataclasses under a domain name instead, following the precedent of `native_anchor.py`, which
holds both `NativeAnchor` and `LabelAnchor`, and of `offset_judge.py`, which holds `RateEstimate`
beside `BenchReading`. A reviewer should read that as deliberate rather than as drift.

The repository also forbids any new use of `time.time()`, `datetime.now()` or `chronyc tracking`
in the timing path. This package contains none of the three, and the import test of §8 keeps it
that way. Every clock the estimator reads arrives as a sample index inside an observation.

**The one object.** `StationTimingEstimator` takes a nominal rate, a ruler provenance, and a
configuration. It exposes three verbs. `observe()` takes either observation type. `advance(n)`
predicts to a sample index. `solve(n)` returns a `TimingSolution` for that index and rebases.
No thread owns it; the caller holds whatever lock it already holds.

**The published solution**, frozen, carrying its own provenance:

    TimingSolution
      rtp_ref, utc_ref_ns              the reference plane, integers
      phase_ns, sigma_phase_ns
      rate_ppm, sigma_rate_ppm
      rate_samples_per_utc_sec         f_meas, a float, the thing §6.3 asked for
      covariance                       three floats
      verdict, refusal                 publish or withhold, and why
      witnesses                        per tier: accepted, rejected, last residual, last sigma
      a_level, ruler_provenance, q_source
      span_s, n_updates, generation
      utc_ns_at(rtp) -> int            the §1 projection, integer arithmetic

`rate_samples_per_utc_sec` appears as a float. The §18 field of the same name exists today as an
integer holding the nominal rate. Reconciling those two belongs to integration, and §9 records
it.

**One ruler, one counter space, one instance.** A station running several radiod counter spaces
runs one instance per space. Each independently estimates the same physical converter's rate,
which turns the multiplicity into a free cross-check rather than a problem: their rates must
agree inside the §5 threshold, and `cross_channel_rtp` already measures the constant phase
offset between spaces, 1.937 ms on ND. Composing several spaces into one station answer belongs
to integration.

---

## 8 · Testing and acceptance

**Property and unit tests, against closed forms.**

- Prediction and update reproduce a hand-computed two-state Kalman step.
- A converter running fast by a known amount yields a negative phase slope and a positive
  published parts-per-million figure. This test exists to catch the sign that broke ND.
- One hundred thousand rebases move the reference plane by zero nanoseconds.
- Each Allan-deviation shape recovers its own coefficient, and a short span falls back to the
  stand-in and says so.
- A single tier repeating a 50 ms error a thousand times moves neither phase nor rate.
- A concordant quorum moves phase after the dwell, and the rate state changes by less than
  0.1 ppm across the step.
- Each refusal fires on its own condition, and no other refusal fires with it.
- The package imports nothing from `hf_timestd.core`.

**Replay against recorded failure.** A support script under `scripts/` drives the existing
acquisition code over the four saved fixtures and writes witness traces as small line-delimited
JSON under `tests/data/estimator/`. The traces, not the fixtures, enter the test suite, so the
library's tests stay fast and depend on nothing outside the repository. The script's output gets
committed; the script itself carries no production role.

**What the corpus can and cannot establish.** The generator measures the fold peak's position
in each block, which gives phase against the ruler up to one unknown constant: the propagation
delay plus the station's identity offset. That constant cancels in a slope, so the corpus
measures rate honestly and measures absolute phase not at all. Absolute phase needs the
propagation model, which §9 leaves in the acquirer's hands. The acceptance rows below therefore
test rate, self-consistency and refusal behaviour, and never absolute UTC.

**Amendment 2026-09-08: no saved fixture carries the ND rate fault.** Before writing the plan I
measured the tick-fold drift in the fixtures directly, using the acquirer's own band envelopes
over twenty-second blocks. The strong band in each fixture gives:

| fixture | strong band | measured ruler | fit residual |
|---|---|---|---|
| `nd-20260906` | 1000 Hz | -0.03 ppm | 0.15 ms over 600 s |
| `nd-20260906-bad` | 1200 Hz | -0.12 ppm | 0.07 ms over 600 s |
| `b4-20260906-day` | 1000 Hz | +0.16 ppm | 0.05 ms over 300 s |

The method's own slope uncertainty sits near 0.15 ppm at these spans, so all three readings mean
one thing: a governed ruler. The `nd-20260906` figure also corroborates that fixture's sidecar,
which recorded -0.043 ppm, and agrees with it in sign as well as magnitude.

**Sign correction, 2026-09-08.** The three rows above first carried the opposite signs. My
measuring script mapped the fold-peak slope to parts per million as `-slope`, and the correct
mapping is `+slope`: a fast converter accumulates sample indices faster than real time, so a fixed
real tick lands on a larger index and therefore LATER within a nominal second, and the peak moves
forward. Task 9's generator recovered -60.13 ppm from a fixture resampled by an exact -60, which
closes the loop end to end, and a synthetic tick train reproduces `+slope` exactly in both
directions. Only the signs were wrong; every magnitude and every conclusion drawn from them stands,
because the finding was that all three rulers sit within a few tenths of a part per million of
nominal. A ruler fifty parts per million off would have dragged the fold peak
30 ms across the window, against a residual of 0.15 ms, so the fixtures exclude that decisively.

The 2026-09-07 figures of -51 ppm from the judge and -84 ppm from the anchor-term series
therefore describe either a fault that arrived after the sixth, or a quantity other than the
ruler. §10 records that as an open question. The acceptance table cannot ask for the recovery of
a rate no fixture contains, so a controlled resampling supplies the known truth instead.

Acceptance, stated as numbers the run must produce:

| corpus | requirement |
|---|---|
| `nd-20260906` | rate within 0.2 ppm of -0.03; phase self-consistent within 2 ms |
| `nd-20260906-bad` | rate within 0.2 ppm of -0.12, and the band disagreement raises no rate alarm |
| `b4-20260906-day` | rate within 0.2 ppm of +0.16, the governed ruler |
| `nd-20260906` resampled by -60 ppm | recovers -60 ppm within 1 ppm from ten minutes of signal |
| every corpus | lattice steps of 18.7, 34 and 50 ms injected on one tier never move the plane |

The resampled row carries the weight the ND night was meant to carry. Resampling a real fixture
by an exact factor keeps the real signal, the real noise and the real fading, and adds a truth
the recorded night never held.

---

## 9 · Out of scope, recorded

Naming these keeps them from arriving as surprises, and each one names its own successor.

1. **Every station integration.** No service constructs this estimator, no unit file changes,
   and neither ND nor B4 receives anything from this cycle.
2. **The seventeen nominal-rate projection sites.** The anchor arithmetic in `native_anchor.py`
   funnels the whole label plane through one of them. Repairing them needs the rate to reach an
   anchor first.
3. **A measured rate on the anchor.** `NativeAnchor` carries an integer `sample_rate_hz` and
   nothing else. `LabelAnchor` adds no rate. The §18 `rate_samples_per_utc_sec` publishes the
   nominal integer under an explicit contract comment. All three need a float and a sigma.
4. **The judge's doctrine.** Audit item G7 forbids folding a measured frequency into the label
   arithmetic. This library does exactly that, deliberately, and the doctrine needs an amendment
   written against this design before any consumer reads a rate-corrected plane.
5. **The hypothesis bank.** Approach B from the brainstorm. Station identity stays in the
   acquirer, which already holds open hypotheses and a resolver. The witness interface admits a
   bank later without changing anything published.
6. **The replica correlator.** Michael raised Phil Karn's `wwvsim` on 2026-09-08. Correlating the
   received signal against a locally generated broadcast would supply two things this station
   lacks: a rate observation from the signal itself, since a ruler error stretches the received
   program against the replica, and a station discriminant, since WWV and WWVH differ in
   structure rather than only in a tick's arrival. Both arrive through the witness interface this
   document already defines, so the correlator needs its own spec and changes nothing here.
7. **ND's converter lock.** The GPSDO needs to drive the RX888 at 27 MHz and 32 mA. No software
   substitutes for that, and this estimator only stops the station lying about it.
8. **Whether T6 should feed chrony at all.** The measurement model §11.7 leaves it open and this
   document does not close it.

---

## 10 · Risks

**The Allan deviation feeds on the estimator's own output.** Adaptive process noise from a
series the filter helped produce can converge on a comfortable lie. Mitigation: fit from
accepted phase residuals against the predicted plane, never from the rate state, and floor every
coefficient at the stand-in for the declared ruler state so the filter can widen its memory but
never narrow it below what the hardware supports.

**Ten minutes of fixture bounds the long fit, and now there are numbers.** A random-walk
coefficient wants hours, and a task review measured just how many. Fitting the coefficient from
70 minute-marks of a governed ruler with 0.5 ms witnesses produced an Allan deviation at the
longest available tau of 8.88e-07, against 9.02e-07 for pure witness white-phase noise alone. The
ratio, 0.984, says the entire fitted coefficient was witness noise wearing the ruler's name, and
it attributed roughly 3 parts per million per hour of wander to hardware specified at 0.01.

The separation needs a day, not an hour. Witness white-phase noise falls as `sqrt(3)*sigma_x/tau`,
so millisecond witnesses sit at 2.4e-07 at one hour and reach 1.0e-08, a governed ruler's own
level, only near 86,400 s.

So the estimator refuses a measured coefficient it cannot distinguish from its own witnesses: it
compares the fitted deviation at the longest tau against that witness floor and keeps the stand-in
unless the measurement clearly beats it. The rule needs no chosen time constant, only the sigma
the witnesses already declare. The measured path stays unproven until a shadow run supplies real
span, which §9 defers, and until then a station honestly reports `standin`.

**And for a governed ruler the ceiling is structural, not merely current.** The fixed plane of
§6.2 cannot outlive half a counter wrap, 24.86 hours at 24 kHz, so it re-anchors and the series
starts again. A review measured the reachable longest tau at 0.29 of the span, putting the ceiling
near seven hours. The 86,400 s tau that would separate a 0.01 ppm ruler from millisecond witnesses
therefore lies beyond what this architecture can reach at all, on any station, however long it
runs. A governed ruler will report `standin` permanently, and that is the correct label rather
than a temporary one. Only a station with far finer witnesses, which means a pulse-per-second
input, could ever measure its own ruler here.

**A concordant quorum can still lie.** Two tiers reading the same misidentified station agree
perfectly. The 800 ms marker addresses identity and lives in the acquirer, so this library's
quorum defends against a lone confident witness and not against a shared delusion. Approach B
answers it; §9 defers it; the coarse network gate of §5 catches the gross case, which covers the
50 ms lattice but not a 1 ms one.

**The ND rate fault has no fixture and now no confirmed cause.** The fixtures of 2026-09-06
show a governed ruler, and the incident of the following night measured tens of parts per
million twice, by two paths. Three readings fit: the converter lost lock between the sixth and
the seventh, which a marginal drive level would explain, since ND once ran 350 ppm at the
LBE-Mini's 8 mA floor and locked at 32 mA; or the judge's offset-slope rode a host-plane bench
and measured the host walking rather than the ruler drifting; or the anchor-term series projected
a stale reference forward and measured its own staleness. This library cannot settle it, and the
resampled corpus row means it does not have to. Settling it needs a fresh capture from ND while
the fault stands, which belongs to integration.

**One convention, stated once, still has to hold.** Two conventions in one file caused the
unreadable contradiction of 2026-09-07 evening, where the ticks called the plane 37 ms early
while the network called the host 30 ms fast. The §1 rule and the grep test guard against a
recurrence, and reviewers should treat any second division by `f_nom` as a defect regardless of
how local it looks.
