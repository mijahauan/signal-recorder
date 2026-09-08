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

A converter running fast gives `y > 0`. That sign matches the judge's existing `RateEstimate.ppm`,
whose docstring already reads "+ = ADC runs fast". The library inherits that convention rather
than inventing a second one.

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

**One convention for elapsed time, everywhere in this package.** Elapsed time always means
sample count divided by the *measured* rate:

    f_meas = f_nom * (1 + y)
    tau(delta_n) = delta_n / f_meas

One line in the package touches `f_nom`, the line that forms `f_meas`. A test greps the package
and fails on any other appearance of the nominal rate underneath a division. This
single rule removes the defect that walked ND, and stating it once removes the sign confusion
that made the evening's contradiction unreadable.

**The published projection.** The estimator carries a reference plane as two integers, and
projects:

    utc_ns(n) = utc_ref_ns + round(phase_ns) + round(1e9 * (n - rtp_ref) / f_meas)

The host clock appears nowhere in that expression, nor in the filter's time base. The filter
advances on sample count. A station whose host clock stopped entirely would keep producing
correct UTC from this estimator until its witnesses went stale.

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

    PhaseObservation(tier, rtp, utc_ns, sigma_ns, plane, source, seq)

The pulse-per-second edge, the LBE per-arrival pairing and the tick registration all speak this
way. Wide-angle network time speaks this way too, once a caller pairs a disciplined host reading
with an arrival index, and it declares itself host-plane, which routes it to the gate of §5 and
keeps it out of the state.

**A rate observation** says the ruler runs fast or slow.

    RateObservation(tier, ppm, sigma_ppm, span_s, n, source)

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
already established:

| order | reason | condition |
|---|---|---|
| 1 | `no_phase_witness` | no phase observation has ever been accepted |
| 2 | `stale_phase` | newest accepted phase observation older than 300 s |
| 3 | `step_pending` | a concordant quorum dwells, per §4 |
| 4 | `variance` | phase sigma above the publish ceiling, 5 ms by default |
| 5 | `coarse_disagreement` | a wide-angle witness disagrees beyond three combined sigmas |
| 6 | `rate_disagreement` | independent rate estimates differ by more than 1 ppm |

Reasons 5 and 6 deserve their mandatory character. Wide-angle network time and the WWV ticks
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

A governed ruler measures a small deviation and the filter grows a long memory, so a
sub-millisecond witness barely nudges a rate the hardware holds to four parts in ten million.
A free-running converter measures a large deviation and the filter's memory shortens to
minutes, so the same witnesses track a rate that actually moves. One mechanism, two regimes, no
branch.

**Bootstrapping honestly.** A cold estimator has measured nothing. It therefore takes its
coefficients from the ruler's declared discipline state, using the stand-in sigmas the
measurement model already tabulates, and replaces them with measured values once the span
supports a fit. The solution publishes which of the two it used.

| ruler state | fractional sigma | provenance |
|---|---|---|
| disciplined, measured | 0.0004 ppm | measured on AC0G-B4, 2026-08-16 |
| disciplined, stand-in | 0.01 ppm | `t6_holdover.UNMEASURED_RATE_SIGMA_PPM` |
| undisciplined, stand-in | 2.0 ppm | `UNMEASURED_RATE_SIGMA_PPM_A0` |

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
      gates.py            the six refusals, in order
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
| `nd-20260906` | 1000 Hz | +0.03 ppm | 0.15 ms over 600 s |
| `nd-20260906-bad` | 1200 Hz | +0.12 ppm | 0.07 ms over 600 s |
| `b4-20260906-day` | 1000 Hz | -0.16 ppm | 0.05 ms over 300 s |

The method's own slope uncertainty sits near 0.15 ppm at these spans, so all three readings mean
one thing: a governed ruler. The `nd-20260906` figure also corroborates that fixture's sidecar,
which recorded -0.043 ppm. A ruler fifty parts per million off would have dragged the fold peak
30 ms across the window, against a residual of 0.15 ms, so the fixtures exclude that decisively.

The 2026-09-07 figures of -51 ppm from the judge and -84 ppm from the anchor-term series
therefore describe either a fault that arrived after the sixth, or a quantity other than the
ruler. §10 records that as an open question. The acceptance table cannot ask for the recovery of
a rate no fixture contains, so a controlled resampling supplies the known truth instead.

Acceptance, stated as numbers the run must produce:

| corpus | requirement |
|---|---|
| `nd-20260906` | rate within 0.2 ppm of +0.03; phase self-consistent within 2 ms |
| `nd-20260906-bad` | rate within 0.2 ppm of +0.12, and the band disagreement raises no rate alarm |
| `b4-20260906-day` | rate within 0.2 ppm of -0.16, the governed ruler |
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

**Ten minutes of fixture bounds the long fit.** A random-walk coefficient wants hours. The
replay tests will exercise the stand-in fallback more than the measured path, and the measured
path stays partly unproven until a shadow run on a station provides span. §9 already defers
that run, and this risk stays open until it happens.

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
