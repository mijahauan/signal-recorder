# T3 self-registration — the received ticks place the second, not radiod's pair

**Status:** APPROVED by Michael 2026-09-06 ("Looks good. Proceed."); plan: docs/superpowers/plans/2026-09-06-t3-self-registration.md
**Date:** 2026-09-06
**Authors:** Michael (mjh) with Claude
**Governs:** `hf-timestd` metrology on stations with and without a TS-1
**Principle (mjh):** "The WWV and WWVH signals themselves provide the best evidence for
where to look for the signal. It may require a bootstrap period to lock. But we have the
GPSDO for stability and every minute, new evidence for corroboration or correction."
**Related:** `docs/design/MEASUREMENT_MODEL.md` (one measurand, one ruler, one registration),
`docs/METROLOGY.md` §4.5–4.6 (T3 recovers UTC from the HF broadcasts alone),
`core/tick_edge_detector.py`, `core/buffer_timing.py`, `core/stream_recorder_v2.py`

## 1. The defect this removes

T3 is the timing authority for stations that have no time-standard injector. It must
stand on its own. Today it does not, for one mechanical reason: the tick detector
searches a ±20 ms window around a label plane it neither verifies nor can re-find.

The label plane comes from radiod's `(GPS_TIME, RTP_TIMESNAP)` pair, which the recorder
adopts at every radiod or recorder restart and folds into the ring anchor. That pair is
not atomic: radiod samples GPS_TIME live and RTP_TIMESNAP from a cached block field, so
the pair carries the status thread's emission lateness as skew. The recorder's own
`ANCHOR PAIR AUDIT` measured it on 2026-09-06:

| Station | running max pair skew | tick search window |
|---|---|---|
| AC0G-ND | 232 ms | ±20 ms |
| AC0G-B4 | 701 ms | ±20 ms (masked: T6 folds its own correction into the anchor) |

When an adoption lands outside the window the detector finds noise on every channel at
once: SNR 9–10 dB, per-tick σ 14–19 ms, which the detector's own comment predicts for
"uniform junk over ±20 ms". The `LABEL_ANCHOR_MAX_SIGMA_MS = 6` rule then refuses to
promote that junk, correctly. Nothing re-registers. The station stays dark until the next
restart draws a better pair. ND drew badly at 21:29Z on 09-05 and at 07:16Z on 09-06 and
lost T3 both times; it drew well at 05:49Z and 21:24Z and recovered both times. Chance
decided a timing authority.

Measured proof that the signal was never the problem: replaying ND's own SHARED_10000
chunk through `tick_edge_detector.detect_edges` with the chunk sidecar's label plane finds
WWV at 33 dB, σ 0.3 ms, 57/57 ticks. Same file, same detector, correct plane. And a plain
one-second fold of the envelope, with no label at all, finds the tick at 14 dB in sixty
seconds.

## 2. Principle

The registration `utc(sample) = sample0_utc + sample / sample_rate` has two parts. The
rate is the GPSDO's and needs no help. The origin, `sample0_utc`, is a measurement, and
the received ticks are the best measurement of it this station will ever have. radiod's
pair and the host clock resolve which second; the ticks resolve where in the second.

Three rules follow:

1. **Acquire from the signal.** Before any ±20 ms search, find the second boundary in the
   sample stream from the tick train itself. A bootstrap period is acceptable.
2. **Hold on the ruler.** The acquired origin is constant in RTP as long as the counter
   epoch holds, because the sample clock is GPSDO-locked. It steps only when radiod's
   counter space changes, and the recorder already announces that.
3. **Corroborate or correct every minute.** Each minute's ensembles either confirm the
   origin, tighten it, or show it has moved. The plane never waits for a restart.

radiod's pair keeps a role: it bounds the whole-second ambiguity (its skew is under a
second) and it seeds the search. It no longer defines the plane.

## 3. Where the change lives

```
core/registration_acquirer.py   NEW  — fold, template match, origin estimate, per-radiod fusion
core/metrology_service.py       MOD  — apply the acquired origin to BufferTiming before process_minute;
                                       feed each minute's ensembles back; detect counter-epoch change
core/tick_edge_detector.py      MOD  — accept an externally supplied anchor plane; report its residual
core/buffer_timing.py           MOD  — BufferTiming gains `origin_source` ("acquired" | "radiod_pair" | ...)
                                       and `origin_sigma_ms`
core/offset_judge.py            MOD  — a new bench, "hf_acquired": the acquired origin vs the radiod pair,
                                       host-clock independent
/run/hf-timestd/registration.json NEW — the acquired registration and its history (provenance)
```

Nothing changes in: the chrony refclock gate; the arrival gate (still log-only); the
recorder's pair adoption and ring anchor (a separate item, §9); T6's anchor inversion,
which overrides the plane when authoritative.

## 4. Acquisition

Per channel, per counter epoch, on the buffer the metrology already holds:

1. **Envelope and tone bands.** `env = |iq| − mean`; bandpass 900–1100 Hz (WWV and BPM
   ticks, 1000 Hz) and 1100–1300 Hz (WWVH ticks, 1200 Hz). The tone frequency identifies
   WWV/BPM against WWVH; geometry separates WWV from BPM (§4 step 4).
2. **Fold at one second.** Reshape `N` seconds to `(N, sample_rate)` and average. Start
   with `N = 60`; if the best peak's fold SNR is under `ACQ_MIN_FOLD_SNR_DB = 10`, extend
   to 120 and 180 s. Skip seconds 0 and 29/59 of each minute where WWV/WWVH omit or alter
   the tick. This is the bootstrap period: one to three minutes.
3. **Peak set.** Take every fold peak above the threshold in each band, with its position
   in the second (ms) and SNR. On ND at 21:3xZ the 1000 Hz fold gave one peak at 14 dB.
4. **Template match.** Candidates and their geometric delays come from the same
   `expected_delays_by_station` the engine already computes (great-circle, F2 hop) and the
   same eligibility rules (`eligible_candidates`: frequency, BPM schedule, UT1 minutes).
   Fit the peak set to the delay template by a common shift `Δ`: for a set of peaks
   `p_i` and candidate delays `d_j`, the best `Δ` minimises `Σ min_j |p_i − d_j − Δ|`
   with the pairing forced to respect the tone bands. Two or more peaks make the fit
   unambiguous (WWV−WWVH 18 ms, WWV−BPM 34 ms, from either site). One peak on a
   single-station channel is unambiguous by construction. One peak on a shared channel is
   ambiguous between hypotheses `Δ_WWV` and `Δ_WWVH` (and `Δ_BPM` if 1000 Hz); carry both
   forward, and let the minute-marker station identity or a second channel decide (§5).
5. **Origin estimate.** `Δ` is the correction to the label plane: `sample0_utc_acquired =
   sample0_utc_label + Δ`, modulo one second. The whole-second part comes from the label
   plane, which radiod's pair keeps within ±1 s. Uncertainty: from fold SNR and the tick
   rise time, floored at 1 ms; the fine stage tightens it.
6. **Per-radiod fusion.** Every channel on one radiod shares one ADC and one RTP counter,
   so they share one origin. Combine the per-channel `Δ` estimates (inverse-variance,
   after rejecting outliers past 3 ms from the median) into one registration per radiod
   per counter epoch. A channel with no acquisition inherits the shared one.

Acquisition succeeds when at least one unambiguous channel estimate exists, or two
ambiguous ones agree on the same hypothesis. Until then the station is `BOOTSTRAP`: the
engine still runs, products still write, but no timing measurement is promoted and T3 is
not offered. This replaces today's silent noise with a named state.

## 5. Corroboration and correction, every minute

The fine ±20 ms search runs where it always did, but centred on the acquired plane rather
than the raw label. Each minute yields, per station, an ensemble offset and σ₁. Then:

- **Corroborate.** If the ensemble is tick-like (σ₁ ≤ `LABEL_ANCHOR_MAX_SIGMA_MS`) its
  residual against the acquired plane updates the registration through a slow filter. On
  the GPSDO the true origin is constant, so the filter is a running weighted mean with a
  long memory, not a tracker.
- **Correct.** If the residual exceeds 3 σ of the registration for two consecutive minutes
  on two or more channels, re-acquire (§4). This catches a plane that has moved without a
  counter-epoch announcement.
- **Resolve ambiguity.** A shared channel carrying two hypotheses drops the one whose fine
  search yields junk while the other yields ticks, or the one the minute-marker's tone
  (1000 vs 1200 Hz) contradicts. A sibling channel's plane also names the station, and
  the agreement it demands depends on geography (mjh, 2026-09-06): broadcasts from one
  site — WWV on 2.5 through 25 MHz, all from Fort Collins — share the great-circle path and
  agree to about a millisecond, while corrections derived from different sites (Fort
  Collins, Kauai, Lintong) carry independent path-model error. Same-site agreement is
  tested at 1.5 ms, cross-site at 4 ms; each registration records the stations that
  produced it so the right tolerance applies.
- **Step on counter-epoch change.** When `resolve_buffer_timing` reports a new counter
  epoch (radiod restart), discard the registration and re-acquire from the new epoch's
  first minute. The shared origin means the second radiod-channel to acquire gets it free.

The detector's `anchor_source` gains the value `acquired`; `timing_admissible` treats it
like `minute_marker` once the registration σ is under 2 ms, so acquired-plane ensembles
promote to timing the way marker-anchored ones do today.

## 6. Interaction with the Offset Judge and the ring

The Offset Judge gains a bench, `hf_acquired`: the acquired origin compared with the raw
radiod pair for the same RTP. It is the one bench that does not use the host clock, so it
witnesses pair skew directly, with the tick-derived σ. On ND today it would read the
+16.7 ms residual the T4 bench flags, and name its cause.

The judge continues to publish `offset_ns` into the ring anchor as it does now; the
metrology no longer depends on that path for its search, so a skewed anchor costs one
minute of bootstrap rather than an outage. §9 records the recorder-side follow-up.

When T6 is authoritative it wins, as today: the acquired registration is then a witness,
and its residual against T6 is a free measurement of the acquisition method's accuracy.

## 7. Provenance

`/run/hf-timestd/registration.json`, rewritten each minute: counter epoch id, acquired
`Δ_ms`, σ, method (`fold+template`), channels contributing, hypotheses still open, minutes
since acquisition, last correction, and the raw-pair residual. `authority.json` and
`timing_chain.json` carry `registration.source = "hf_acquired"` where the plane came from
this path. The provenance sidecar work already planned (Phase 1+2) consumes these.

## 8. Testing and acceptance

**On the devbox, never on a station.** Chunks and sidecars copy over by `scp`; the replay
sweep that killed two recorders on 2026-09-06 runs here from now on.

- Unit: fold peak detection on synthetic tick trains at 5–30 dB; template fit with one,
  two and three stations including the BPM/WWV tone collision; ambiguity carry and
  resolution; per-radiod fusion with an outlier channel; counter-epoch step handling.
- Replay: ND's SHARED_10000 chunk of 2026-09-06 21:30Z with the sidecar label deliberately
  shifted by −300, −100, +50, +250 ms. Acceptance: acquisition recovers the shift within
  ±2 ms inside 180 s, and the fine search then reports σ₁ under 1 ms. Same on B4's chunk,
  where the answer is known from T6.
- Replay: an ND chunk from a bad window (09-06 08–20Z) must go from junk to ticks with no
  restart.
- Live acceptance on ND (T6-less), by Michael's hand: after the next natural recorder
  restart, L2 timing measurements resume on every audible channel within three minutes,
  fusion reaches T3, and the chrony gate re-enables FUSE, all without a second restart.
  `registration.json` shows the acquired Δ and the raw-pair residual.
- Live non-regression on B4: T6 remains authoritative; the `hf_acquired` bench residual
  against T6 stays under 2 ms.

## 9. Out of scope, recorded

- **Recorder watchdog kills.** ND's `timestd-core-recorder` hit its 3-minute systemd
  watchdog five times in 48 hours (B4: never until an operator sweep loaded it). Each kill
  is a restart and, today, a pair lottery. This spec ends the lottery's consequence; the
  kills themselves are a recorder robustness item.
- **RX888 USB stalls on ND** (four in 48 h; "libusb timeout", sample rate 0.0) and the
  sdr-recover cycles they trigger: hardware, for Rob.
- **Recorder pair adoption.** Whether the recorder should refuse a pair that disagrees
  with the host clock by more than the pair's known skew bound is a separate, smaller
  change; with this spec in place it becomes hygiene rather than survival.
- **The arrival gate's k·σ coupling** stays log-only; when it goes live it must use the
  acquired plane's σ (millisecond) rather than the judge tier's, or the differences-only
  form recorded in memory.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Fold peaks from multipath or scatter mislead the template fit | Peaks must recur across the bootstrap window; scattered arrivals fail the tone-band and delay-window tests the engine already applies |
| Weak nights: no channel reaches fold SNR 10 dB | Extend to 180 s; hold the last registration on the GPSDO ruler (rule 2) and stay `BOOTSTRAP` honestly rather than promote junk |
| BPM shares WWV's 1000 Hz tick | Template fit uses the 34 ms separation; BPM stays excluded from timing as today |
| Whole-second ambiguity if the pair is off by more than a second | The recorder announces counter-epoch changes past 0.5 s; the minute marker's 800 ms tone resolves the second within the minute |
| The slow filter follows a drifting plane into error | It only integrates tick-like ensembles; the correction rule re-acquires on a sustained 3 σ residual |

## 11. Amendment 2026-09-07 — the registration must reach the anchor (mjh)

Live on AC0G-ND, 2026-09-07 11:32Z onward: six channels acquired and verified a registration
~20 ms from radiod's pair and held it to a millisecond, while the host clock walked 150 ms from
four NTP witnesses and psk decodes died. The ticks and the 800 ms marker corrected the metrology's
plane every minute; nothing carried that correction to the anchor the clients read. §6's "radiod's
pair keeps the whole-second role" and §9's deferral of the ring anchor left two registrations on
one station, which violates the one-registration rule (mjh, 2026-09-04).

Michael's statement of the requirement: psk, wspr, meteor-scatter — every client keys off UTC;
without TS-1, T5 or T4, T3 carries the burden and must beat WAN NTP; what must not drift is the
alignment of the RTP counter with UTC. The verified, marker-corroborated registration is therefore
the anchor on a T6-less station, and every consumer reads it:

1. **The anchor IS the registration.** Michael, the same day: "Why do we compare things to the host
   clock? It is not the ruler or the standard but a product of FUSION. Imagine there is no host clock
   at all, but ONLY FUSION." On a station with no authoritative T6, the recorder builds its native
   anchor directly from the verified registration — `NativeAnchor(anchor_rtp=rtp_ref,
   anchor_utc_ns=utc_ref, captured_via_tier="T3")` — exactly as the T6 inversion builds it from the
   PPS edge, and drives the ring anchor and the authority.json §18 fields from it. Radiod's
   host-stamped pair is no longer the base of anything; it names the whole second during bootstrap
   and nothing else. The Offset Judge's `hf_acquired` bench remains a witness (its σ floor stands).
2. **chrony is disciplined from the anchor, never consulted.** The FUSE sample is the anchor's UTC
   of the newest arrived sample, placed at that sample's arrival instant — the shape the T6 native
   bench already forms. Fusion's d_clock becomes a diagnostic in that regime. The host clock appears
   in exactly one role: the thing being disciplined.
3. **Acceptance.** On ND, the T3-anchored UTC holds within the NTP witnesses' own scatter
   indefinitely (`chronyc sources` offsets of the pool servers stay within ±10 ms of zero), the
   `hf_acquired` verdict and FUSE agree, and `raw_pair_residual_ms` in registration.json trends
   toward zero once the ring re-anchors.
