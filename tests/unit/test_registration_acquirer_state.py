import numpy as np
import pytest

from hf_timestd.core.registration_acquirer import (
    ORIGIN_SIGMA_FLOOR_MS,
    Registration,
    RegistrationAcquirer,
)
from synth_ticks import make_tick_audio, label_timing

SR = 24000
MIN = 1_800_000_000
T0 = MIN - 1.0  # buffer 0 starts 1 s before minute 0 (truth)
D = {"WWV": 0.0125}


def _minute(k, walk_s, snr_db=15.0, stations=D):
    """Minute k: 62 s buffer starting at T0 + 60k (truth)."""
    t0 = T0 + 60 * k
    audio = make_tick_audio(62, SR, t0, stations, snr_db=snr_db, seed=7 + k)
    label = label_timing(t0, walk_s, SR)
    start_rtp = 1_000_000 + k * 60 * SR
    return audio, label, start_rtp, MIN + 60 * k


def test_bootstrap_then_acquires_within_one_minute_at_good_snr():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    assert acq.state == acq.STATE_BOOTSTRAP
    audio, label, rtp, m = _minute(0, walk_s=0.250, snr_db=20.0)
    reg = acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert reg is not None and acq.state == acq.STATE_ACQUIRED
    assert reg.sample0_utc_for(rtp) == pytest.approx(T0, abs=0.002)
    assert reg.counter_epoch_id == "ep-1" and reg.sigma_ms >= 1.0


def test_weak_signal_extends_the_fold_to_three_minutes():
    # snr_db is against the full 12 kHz band.  Measured directly against this
    # implementation's fold_tick_train (bandpass -> envelope -> 400 Hz LPF,
    # not a raw-tone SNR budget): at snr_db=-25 the fold never crosses the
    # ~13 dB noise-extreme threshold even at 162 rows (measured 8.9 / 8.8 /
    # 9.4 dB at 54/108/162 rows) -- the brief's -7 dB-per-tick / 10*log10(N)
    # estimate does not hold once the tone passes through the envelope
    # detector at this depth.  Stepping snr_db up in 2 dB increments (the
    # opposite direction from the brief's fallback, which anticipated the
    # first minute acquiring too early rather than never crossing the sill):
    # -25/-23/-21/-19 all still fail to acquire by 180 s.
    #
    # task-11b's peak-persistence gate (spec §10) additionally folds the
    # FIRST and SECOND HALF of the acquiring buffer independently and
    # requires the winning peak to cross the same ACQ_MIN_FOLD_SNR_DB floor
    # in BOTH (effective floor 20*log10(max(10^(10/20), sqrt(2*ln(800))+1))
    # = 13.36 dB) -- so at -17 dB the full 162-row fold clears the floor
    # (15.00 dB), but each ~81-row HALF (80/82 rows exactly) only reaches
    # 11.71 / 12.38 dB, under the 13.36 dB floor, and the gate correctly
    # refuses to acquire on a signal this weak.  -16 dB (measured 17.02 dB
    # full, 13.93 / 13.89 dB per half -- a bare ~0.5 dB margin over the
    # floor, review fix round 1 M7) clears both halves while still failing
    # at one minute (54 rows, no peak at all) -- keeping the "one minute
    # must NOT suffice" half of this test meaningful.  Cost: gate (a) moves
    # the acquisition floor from -17 to about -16.5 dB here (~1 dB of input
    # SNR, from halving the fold's row count) -- recorded in
    # docs/METROLOGY.md's self-registration paragraph (review fix round 1,
    # M6); this deterministic (seed=7+k) control is sensitive to any future
    # change to ENVELOPE_LPF_HZ, the MAD estimator, or the noise-extreme
    # n_eff term.
    acq = RegistrationAcquirer("SHARED_10000", SR)
    outcomes = []
    for k in range(3):
        audio, label, rtp, m = _minute(k, walk_s=-0.300, snr_db=-16.0)
        outcomes.append(acq.offer_minute(audio, label, rtp, m, D, "ep-1"))
    assert (
        outcomes[0] is None
    ), "one minute must NOT suffice at this SNR (else the test is toothless)"
    assert outcomes[-1] is not None, "180 s fold must lift the tick over the threshold"
    assert outcomes[-1].sample0_utc_for(rtp) == pytest.approx(T0 + 120, abs=0.003)


def test_held_registration_ignores_a_new_label_plane():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.1, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    # next minute the ring anchor refreshes to a different pair (label jumps 0.4 s)
    audio, label, rtp, m = _minute(1, walk_s=0.5, snr_db=20.0)
    reg = acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert reg.sample0_utc_for(rtp) == pytest.approx(T0 + 60, abs=0.002)


def test_counter_epoch_change_resets_to_bootstrap():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.1, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    audio, label, rtp, m = _minute(1, walk_s=0.1, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-2")
    # a fresh acquisition from this one minute is allowed; the OLD one is gone
    assert acq.registration is None or acq.registration.counter_epoch_id == "ep-2"


def test_corroborate_tightens_and_flags_sustained_residual():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    # task-11b: corroborate only tightens a VERIFIED plane (unverified ->
    # routes to verify instead); this test is about corroborate's own
    # tightening/reacquire logic, so mark verified directly rather than
    # spending a call on verify().
    acq.registration.verified = True
    s0 = acq.registration.sigma_ms
    assert acq.corroborate({"WWV": (0.4, 0.5)}) == "tightened"
    assert acq.registration.sigma_ms <= s0
    # a plane that moved 30 ms: two consecutive minutes on two stations -> reacquire
    assert acq.corroborate({"WWV": (30.0, 0.5), "WWVH": (30.5, 0.6)}) == "held"
    assert acq.corroborate({"WWV": (30.2, 0.5), "WWVH": (30.1, 0.6)}) == "reacquire"
    assert acq.state == acq.STATE_BOOTSTRAP


def test_resolve_ambiguity_prefers_same_site_tolerance():
    # shared 10 MHz channel hears ONE 1000 Hz tick: WWV (d=0.010) or BPM (d=0.044)?
    acq = RegistrationAcquirer("SHARED_10000", SR)
    t0 = T0
    audio = make_tick_audio(62, SR, t0, {"WWV": 0.010}, snr_db=20.0)
    label = label_timing(t0, 0.100, SR)  # label 100 ms late
    d = {"WWV": 0.010, "BPM": 0.044}
    assert acq.offer_minute(audio, label, 1_000_000, MIN, d, "ep-1") is None
    assert acq.state == acq.STATE_BOOTSTRAP and len(acq._open) == 2
    # a WWV-only sibling (20 MHz) places the plane 0.8 ms from truth: same site -> 1.5 ms tolerance
    sib = Registration(
        "ep-1",
        rtp_ref=1_000_000,
        utc_ref=t0 + 0.0008,
        sample_rate=SR,
        sigma_ms=1.0,
        channel="WWV_20000",
        stations=("WWV",),
    )
    reg = acq.resolve_ambiguity(sib, 1_000_000, label.sample0_utc)
    assert reg is not None and acq.state == acq.STATE_ACQUIRED
    assert reg.stations == ("WWV",)
    assert reg.sample0_utc_for(1_000_000) == pytest.approx(t0, abs=0.002)


def test_resolve_ambiguity_cross_site_is_looser_but_bounded():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.010}, snr_db=20.0)
    label = label_timing(T0, 0.100, SR)
    d = {"WWV": 0.010, "BPM": 0.044}
    acq.offer_minute(audio, label, 1_000_000, MIN, d, "ep-1")
    # a WWVH-derived sibling 3 ms off truth: cross-site -> 4 ms tolerance still picks WWV
    sib = Registration(
        "ep-1", 1_000_000, T0 + 0.003, SR, 1.0, channel="WWVH_5000", stations=("WWVH",)
    )
    assert acq.resolve_ambiguity(sib, 1_000_000, label.sample0_utc) is not None
    # 20 ms off: nothing agrees -> None, still BOOTSTRAP
    acq2 = RegistrationAcquirer("SHARED_10000", SR)
    acq2.offer_minute(audio, label, 1_000_000, MIN, d, "ep-1")
    sib2 = Registration(
        "ep-1", 1_000_000, T0 + 0.020, SR, 1.0, channel="WWVH_5000", stations=("WWVH",)
    )
    assert acq2.resolve_ambiguity(sib2, 1_000_000, label.sample0_utc) is None
    assert acq2.state == acq2.STATE_BOOTSTRAP


def test_adopt_sibling_registration():
    acq = RegistrationAcquirer("WWV_20000", SR)
    reg = Registration(
        counter_epoch_id="ep-1",
        rtp_ref=5_000,
        utc_ref=T0,
        sample_rate=SR,
        sigma_ms=1.2,
        channel="SHARED_10000",
    )
    acq.adopt(reg)
    assert acq.state == acq.STATE_ACQUIRED
    assert acq.registration.sample0_utc_for(5_000 + 60 * SR) == pytest.approx(T0 + 60)
    # C1: adopt must stamp THIS channel's own name and mark the plane
    # derived, never the donor's channel (RegistrationStore would file it
    # under the donor's name -- e.g. "fused.json" -- losing this channel's
    # own provenance) and never indistinguishable from fresh evidence.
    assert acq.registration.channel == "WWV_20000"
    assert acq.registration.method == "adopted"


def test_corroborate_moves_the_plane_toward_truth_not_away():
    """C2: timing_error_ms = front_edge - expected (tick_edge_detector.py):
    a POSITIVE residual means the plane's labels ran LATE, so corroborate
    must move the plane EARLIER, not later.  Inject a known 1.5 ms late
    error onto a freshly-acquired (n_minutes=0) plane and feed back exactly
    that residual; the plane must land close to truth, not twice as far."""
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    acq.registration.verified = True  # task-11b: corroborate needs a verified plane
    truth_s0 = acq.registration.sample0_utc_for(rtp)
    acq.registration.utc_ref += 0.0015  # inject 1.5 ms late
    before_ms = abs(acq.registration.sample0_utc_for(rtp) - truth_s0) * 1000.0
    acq.corroborate({"WWV": (1.5, 0.3)})
    after_ms = abs(acq.registration.sample0_utc_for(rtp) - truth_s0) * 1000.0
    assert after_ms < before_ms  # moved TOWARD truth, not away
    assert after_ms < 0.2


# ── Task 11b: peak persistence (spec §10) + verification gate ─────────


def test_lone_transient_peak_does_not_acquire():
    """A single one-off burst (RFI, not a recurring tick) folds to a lone
    peak that a single-station channel would otherwise promote straight to
    "unambiguous" -- exactly the ND WWV_25000 phantom mechanism (task-11b
    brief).  62 s of quiet noise (no ticks at all) plus ONE 40 ms burst of
    1000 Hz at an arbitrary position in second 12, amplitude 5x a normal
    tick's (a plausible transient, not an exotic one): with the current
    ~13.36 dB effective detection floor and 54-row averaging, this single
    occurrence is strong enough to cross the floor at the one fold length
    the acquirer uses -- confirmed directly against the unpatched acquirer
    to acquire before this fix (task-11b, gate a).  The peak-persistence
    gate must refuse it: the burst is absent from whichever half of the
    buffer it did not land in."""
    sr = SR
    n = 62 * sr
    rng = np.random.default_rng(11)
    audio = 0.05 * rng.standard_normal(n)
    burst_start_s = 12.37  # arbitrary offset within second 12, well clear
    # of either half's boundary (half = 31 s)
    i0 = int(burst_start_s * sr)
    i1 = i0 + int(0.040 * sr)  # 40 ms burst
    t = np.arange(i1 - i0) / sr
    audio[i0:i1] += 5.0 * np.cos(2 * np.pi * 1000.0 * t)
    label = label_timing(T0, 0.0, sr)
    acq = RegistrationAcquirer("SHARED_10000", sr)
    result = acq.offer_minute(audio, label, 1_000_000, MIN, {"WWV": 0.010}, "ep-1")
    assert result is None
    assert acq.state == acq.STATE_BOOTSTRAP


def test_verify_confirms_a_tick_like_ensemble():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert acq.registration.verified is False
    assert acq.verify({"WWV": (0.5, 0.4)}) == "verified"
    assert acq.state == acq.STATE_ACQUIRED
    assert acq.registration.verified is True


def test_verify_rejects_a_non_tick_like_ensemble():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert acq.verify({"WWV": (2.0, 14.6)}) == "rejected"
    assert acq.state == acq.STATE_BOOTSTRAP


def test_verify_rejects_a_tick_like_ensemble_with_a_large_residual():
    """task-11b fix round 2 (N1): a marker-anchored search sits on the
    signal's OWN grid, so sigma_single_ms stays tick-like (~0.01 ms)
    however wrong our plane is -- only ensemble_timing_error_ms carries
    the plane error for that anchor.  A tick-like ensemble whose residual
    exceeds VERIFY_MAX_RESIDUAL_MS (= TickEdgeDetector.SEARCH_WINDOW_MS,
    20 ms) is itself a rejection, not "pending"."""
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert acq.verify({"WWV": (30.0, 0.01)}) == "rejected"
    assert acq.state == acq.STATE_BOOTSTRAP


def test_verify_confirms_a_tick_like_ensemble_with_a_small_residual():
    """task-11b fix round 2 (N1): the companion case -- tick-like sigma AND
    a residual well inside VERIFY_MAX_RESIDUAL_MS still verifies."""
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert acq.verify({"WWV": (4.0, 0.3)}) == "verified"
    assert acq.registration.verified is True


def test_verify_pending_then_rejects_after_max_minutes():
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert acq.verify({}) == "pending"
    assert acq.verify({}) == "pending"
    assert acq.verify({}) == "rejected"
    assert acq.state == acq.STATE_BOOTSTRAP


def test_corroborate_on_unverified_registration_routes_to_verify():
    """(b): corroborate must not tighten an unverified (CANDIDATE) plane --
    it routes to verify instead, whichever outcome that produces."""
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert acq.registration.verified is False
    assert acq.corroborate({"WWV": (0.4, 0.5)}) == "verified"
    assert acq.registration.verified is True


def test_acquire_then_verify_then_corroborate_runs():
    """task-11b fix round 1 (I3/I4): the real seam, walked end to end --
    acquire (CANDIDATE) -> verify (confirms, does not tighten) ->
    corroborate (now runs, and accumulates evidence).

    final review C2: corroborate no longer tightens sigma BELOW
    ORIGIN_SIGMA_FLOOR_MS, and at 20 dB the acquisition sigma already sits
    on that floor -- so what this walk pins now is that corroborate RUNS
    (n_minutes accumulates) and that the floor holds, not that the number
    shrinks.  The floor is the delay-model accuracy bound; shrinking past
    it published repeatability as accuracy."""
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    assert acq.registration.verified is False
    sigma_after_acquire = acq.registration.sigma_ms
    assert acq.verify({"WWV": (0.5, 0.4)}) == "verified"
    assert acq.registration.verified is True
    assert (
        acq.registration.sigma_ms == sigma_after_acquire
    )  # verify confirms, doesn't tighten
    assert acq.registration.n_minutes == 0
    assert acq.corroborate({"WWV": (0.4, 0.4)}) == "tightened"
    assert acq.registration.n_minutes == 1
    assert acq.registration.sigma_ms <= sigma_after_acquire
    assert acq.registration.sigma_ms >= ORIGIN_SIGMA_FLOOR_MS


def test_offer_minute_resets_when_the_epoch_offset_steps(caplog):
    """C1's id string is ``ep-<int(epoch_offset_s)>``, so a re-anchor that
    moves the mapping DOWN by 0.5-1.0 s opens a new epoch in
    CounterEpochTracker while spelling it exactly the same way.  The offset
    itself always sees the step (within one epoch the tracker reports a
    running MINIMUM, which moves at most COUNTER_EPOCH_STEP_S per
    observation), so spec §5's "step on counter-epoch change" must key on
    it too -- otherwise a registration held in the OLD RTP frame survives
    the change."""
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-958", epoch_offset_s=958.9)
    assert acq.state == acq.STATE_ACQUIRED
    rng = np.random.default_rng(4)
    noise = 0.05 * rng.standard_normal(62 * SR)
    with caplog.at_level("INFO"):
        acq.offer_minute(
            noise,
            label_timing(T0 + 60, 0.0, SR),
            rtp + 60 * SR,
            m + 60,
            D,
            "ep-958",  # SAME id string
            epoch_offset_s=958.3,  # 0.6 s down: a different counter space
        )
    assert acq.state == acq.STATE_BOOTSTRAP
    assert "counter epoch offset" in caplog.text


def test_offer_minute_keeps_the_plane_across_ordinary_pair_skew():
    """The companion case: an offset that moved less than
    COUNTER_EPOCH_STEP_S is the pair's own skew, not a new counter space --
    the registration must survive it (I3)."""
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    reg0 = acq.offer_minute(audio, label, rtp, m, D, "ep-958", epoch_offset_s=958.9)
    reg1 = acq.offer_minute(
        audio,
        label_timing(T0 + 60, 0.0, SR),
        rtp + 60 * SR,
        m + 60,
        D,
        "ep-958",
        epoch_offset_s=958.5,
    )
    assert reg1 is reg0 and acq.state == acq.STATE_ACQUIRED


# ── C2 + I5 (final review): one sigma floor, long filter memory ───────


def test_corroborate_sigma_never_falls_below_the_floor():
    """C2: ``corroborate`` used to clamp at ORIGIN_SIGMA_FLOOR_MS * 0.1 and
    reached 0.17 ms within thirty minutes.  That sigma is a repeatability
    bound (fold SNR / rise time, divided by sqrt(n)); the acquired origin's
    ACCURACY is bounded by expected_delays_s -- propagation model plus mode
    ambiguity, milliseconds up.  Publishing the smaller number let the
    judge's same-tier sigma tie-break hand the published T3 offset to
    hf_acquired instead of FusionBench.  One floor, 1 ms."""
    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, rtp, m = _minute(0, walk_s=0.0, snr_db=20.0)
    acq.offer_minute(audio, label, rtp, m, D, "ep-1")
    acq.registration.verified = True
    for _ in range(60):
        assert acq.corroborate({"WWV": (0.0, 0.4)}) in ("tightened", "held")
    assert acq.registration.sigma_ms == pytest.approx(ORIGIN_SIGMA_FLOOR_MS)


def _corroborating_plane(n_minutes, sigma_ms=ORIGIN_SIGMA_FLOOR_MS):
    acq = RegistrationAcquirer("SHARED_10000", SR)
    acq._state = acq.STATE_ACQUIRED
    acq._reg = Registration(
        counter_epoch_id="ep-1",
        rtp_ref=1_000_000,
        utc_ref=T0,
        sample_rate=SR,
        sigma_ms=sigma_ms,
        channel="SHARED_10000",
        n_minutes=n_minutes,
        stations=("WWV",),
        verified=True,
    )
    return acq


def test_the_filter_has_a_long_memory_not_a_five_minute_one():
    """I5: spec §5 asks for "a running weighted mean with a long memory,
    not a tracker".  With w_new floored at 0.1 ms and w_old at 1.0 ms, a
    realistic 0.4 ms per-tick sigma under-weighted the history by
    (1.0/0.4)^2 = 6.25x per minute against a w_old capped at
    FILTER_MEMORY_MINUTES -- an effective memory of about five minutes,
    short enough to follow path-delay wander into the origin.  One floor on
    both weights makes a saturated filter move by 1/(1+FILTER_MEMORY_MINUTES)
    of a new residual, not by a sixth of it."""
    acq = _corroborating_plane(RegistrationAcquirer.FILTER_MEMORY_MINUTES)
    before = acq.registration.utc_ref
    assert acq.corroborate({"WWV": (2.0, 0.4)}) == "tightened"
    moved_ms = (before - acq.registration.utc_ref) * 1000.0
    expected = 2.0 / (1 + RegistrationAcquirer.FILTER_MEMORY_MINUTES)
    # utc_ref sits at ~1.8e9 s, where one float64 ulp is 2.4e-4 ms
    assert moved_ms == pytest.approx(expected, abs=1e-3)
    # the pre-fix asymmetry would have moved it 5.3x further
    assert moved_ms < 0.1


def test_a_fresh_plane_still_follows_its_first_evidence():
    """The other side of I5: long memory must not mean frozen.  With no
    accumulated history (n_minutes = 0) the first minute's residual is
    taken in full."""
    acq = _corroborating_plane(0)
    before = acq.registration.utc_ref
    assert acq.corroborate({"WWV": (2.0, 0.4)}) == "tightened"
    moved_ms = (before - acq.registration.utc_ref) * 1000.0
    assert moved_ms == pytest.approx(2.0, abs=1e-3)
