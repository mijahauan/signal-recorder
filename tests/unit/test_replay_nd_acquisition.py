"""Spec §8 replay acceptance on real station chunks copied to the devbox.

Runs ONLY on the devbox: the fixtures live outside the repo
(``/home/mjh/hamsci/fixtures/...``) and every test here skips when its
fixture is absent.  Never run this module on a station -- the ND fold
sweep that produced these numbers loaded two station recorders to their
watchdog on 2026-09-06 (see the task-11 brief).

Fixtures (devbox only):
  - ``nd-20260906/1788729000.{bin.zst,json}``      ND good window (21:20Z)
  - ``nd-20260906-bad/1788696000.{bin.zst,json}``  ND dark window (12:00Z)
  - ``b4-20260907/1788742800.{bin.zst,json}``       B4 with T6 (01:00Z)

``MetrologyEngine``'s real constructor takes ``raw_buffer_dir``,
``output_dir``, ``channel_name``, ``frequency_hz``, ``receiver_grid``,
``sample_rate``, ``precise_lat``, ``precise_lon`` (see
``metrology_engine.py`` ~L234 and how ``metrology_service.py`` ~L203-220
builds one) -- NOT the four-argument constructor the original brief
guessed.  ``raw_buffer_dir`` is a legacy no-op the engine only stores;
``output_dir`` needs to exist on disk but nothing here writes physics
products (``enable_physics_products=False``: timing-only, skip the
secondary-arrival search).  The sidecar's ``station`` block already
carries ``grid_square`` directly, so no lat/lon -> grid conversion is
needed.
"""

import dataclasses
import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

FIX = Path(
    os.environ.get("HF_TIMESTD_ND_FIXTURE", "/home/mjh/hamsci/fixtures/nd-20260906")
)
CHUNK = FIX / "1788729000.bin.zst"
SIDECAR = FIX / "1788729000.json"

pytestmark = pytest.mark.skipif(not CHUNK.exists(), reason="ND fixture not present")


def _engine(meta: dict):
    """Build the engine the way ``metrology_service.py`` does (task-11
    controller ruling): ``raw_buffer_dir`` is a legacy no-op argument,
    ``output_dir`` gets a throwaway temp directory, ``receiver_grid``
    comes straight from the sidecar's ``station.grid_square`` (present
    on all three fixtures -- no maidenhead conversion needed), and
    ``precise_lat``/``precise_lon`` drive the actual geometric-delay
    math that ``expected_delays_s`` uses."""
    from hf_timestd.core.metrology_engine import MetrologyEngine

    st = meta["station"]
    out_dir = Path(tempfile.mkdtemp(prefix="hf_timestd_replay_"))
    return MetrologyEngine(
        raw_buffer_dir=Path("/dev/null"),
        output_dir=out_dir,
        channel_name=meta["channel_name"],
        frequency_hz=float(meta["frequency_hz"]),
        receiver_grid=st.get("grid_square", ""),
        sample_rate=int(meta["sample_rate"]),
        precise_lat=float(st["latitude"]),
        precise_lon=float(st["longitude"]),
        enable_physics_products=False,
    )


@pytest.fixture(scope="module")
def chunk():
    import zstandard

    raw = zstandard.ZstdDecompressor().decompress(
        CHUNK.read_bytes(), max_output_size=1 << 31
    )
    iq = np.frombuffer(raw, dtype="<c8")
    meta = json.loads(SIDECAR.read_text())
    return iq, meta


@pytest.mark.parametrize("shift_ms", [-300.0, -100.0, 50.0, 250.0])
def test_acquisition_recovers_a_shifted_label(chunk, shift_ms):
    from hf_timestd.core.buffer_timing import resolve_buffer_timing
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer
    from hf_timestd.core.tick_edge_detector import TickEdgeDetector

    iq, meta = chunk
    sr = int(meta["sample_rate"])
    eng = _engine(meta)
    acq = RegistrationAcquirer("SHARED_10000", sr)
    bt_true = resolve_buffer_timing(meta, sample_rate=sr)
    got = None
    a = 0
    for k in range(3):  # up to 180 s of bootstrap
        a = k * 60 * sr
        seg = iq[a : a + 62 * sr]
        minute_utc = int(meta["minute_boundary"]) + 60 * k
        label = dataclasses.replace(
            bt_true, sample0_utc=bt_true.sample0_utc + a / sr + shift_ms / 1000.0
        )
        audio = eng.prepare_audio(seg)
        delays = eng.expected_delays_s(label.sample0_utc, minute_utc)
        got = acq.offer_minute(
            audio,
            label,
            int(meta["start_rtp_timestamp"]) + a,
            minute_utc,
            delays,
            "ep-nd",
        )
        if got is not None:
            break
    assert got is not None, f"no acquisition within 180 s (shift {shift_ms:+.1f} ms)"
    recovered_ms = (
        got.sample0_utc_for(int(meta["start_rtp_timestamp"]) + a)
        - (bt_true.sample0_utc + a / sr)
    ) * 1000.0
    # fine search on the acquired plane
    bt_acq = dataclasses.replace(
        bt_true,
        sample0_utc=got.sample0_utc_for(int(meta["start_rtp_timestamp"]) + a),
        origin_source="acquired",
        origin_sigma_ms=got.sigma_ms,
    )
    det = TickEdgeDetector(sample_rate=sr)
    res = det.detect_edges(
        audio_signal=audio,
        station="WWV",
        minute_number=minute_utc,
        buffer_timing=bt_acq,
        expected_delay_sec=delays["WWV"],
        is_dedicated_channel=False,
        iq_samples=None,
    )
    print(
        f"\n  shift_ms={shift_ms:+7.1f}  minutes={k + 1}  recovered_ms={recovered_ms:+8.3f}  "
        f"sigma_ms={got.sigma_ms:6.3f}  fine_sigma1={res.sigma_single_ms if res else float('nan'):7.3f}  "
        f"fine_err_ms={res.ensemble_timing_error_ms if res else float('nan'):+7.3f}  "
        f"n_detected={res.n_detected if res else -1}"
    )
    # Truth reference (task-11 controller ruling): the sidecar plane on this
    # fixture was measured 2026-09-06 to sit ~+8.8 ms from where the WWV
    # ticks actually are, so "within truth" means within ±2 ms of that WWV
    # timing error AFTER the fine search's own residual is folded in.
    assert res is not None and res.anchor_source == "acquired"
    assert abs(res.ensemble_timing_error_ms) < 2.0, (
        f"fine search on the acquired plane still shows {res.ensemble_timing_error_ms:+.2f} ms "
        f"of error -- the acquired plane is not converging to the ticks"
    )
    assert (
        res.sigma_single_ms < 1.0
    ), f"fine sigma1 {res.sigma_single_ms:.2f} ms >= 1.0 ms"
    assert (
        res.n_detected >= 40
    ), f"only {res.n_detected} ticks detected on the acquired plane"


BAD = Path(
    os.environ.get(
        "HF_TIMESTD_ND_BAD_FIXTURE", "/home/mjh/hamsci/fixtures/nd-20260906-bad"
    )
)
B4 = Path(
    os.environ.get("HF_TIMESTD_B4_FIXTURE", "/home/mjh/hamsci/fixtures/b4-20260907")
)
# Real same-site sibling: B4's WWV_20000 channel, same radiod instance and
# RTP counter as the SHARED_10000 chunk above, same 10-minute window
# (task-11 fix round 2).  Confirmed same counter space: the two sidecars'
# own (gps_time_ns, rtp_timesnap) pairs, extrapolated to a common RTP via
# resolve_buffer_timing, agree to ~1.3 ms -- well inside "a few ms".


def _load(dirpath: Path, stem: str):
    import zstandard

    raw = zstandard.ZstdDecompressor().decompress(
        (dirpath / f"{stem}.bin.zst").read_bytes(), max_output_size=1 << 31
    )
    return np.frombuffer(raw, dtype="<c8"), json.loads(
        (dirpath / f"{stem}.json").read_text()
    )


def _acquire_first_minutes(iq, meta, shift_ms=0.0):
    """Run the acquirer over the first <=3 minutes of a chunk with the
    sidecar label shifted.  Returns (registration, start_rtp_of_last_minute,
    audio, delays, minute_utc, bt_true, offset_samples)."""
    from hf_timestd.core.buffer_timing import resolve_buffer_timing
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer

    sr = int(meta["sample_rate"])
    eng = _engine(meta)
    acq = RegistrationAcquirer(meta["channel_name"], sr)
    bt_true = resolve_buffer_timing(meta, sample_rate=sr)
    got, a = None, 0
    for k in range(3):
        a = k * 60 * sr
        seg = iq[a : a + 62 * sr]
        minute_utc = int(meta["minute_boundary"]) + 60 * k
        label = dataclasses.replace(
            bt_true, sample0_utc=bt_true.sample0_utc + a / sr + shift_ms / 1000.0
        )
        audio = eng.prepare_audio(seg)
        delays = eng.expected_delays_s(label.sample0_utc, minute_utc)
        got = acq.offer_minute(
            audio,
            label,
            int(meta["start_rtp_timestamp"]) + a,
            minute_utc,
            delays,
            "ep-replay",
        )
        if got is not None:
            break
    return (
        got,
        int(meta["start_rtp_timestamp"]) + a,
        audio,
        delays,
        minute_utc,
        bt_true,
        a,
    )


@pytest.mark.skipif(
    not (BAD / "1788696000.bin.zst").exists(),
    reason="ND bad-window fixture not present",
)
def test_bad_window_chunk_goes_from_junk_to_ticks_without_restart():
    """Spec §8: an ND chunk from the dark window (09-06 12:00Z) must
    acquire.  Whatever the sidecar plane says, acquisition must land a
    plane on which the fine search sees ticks.

    Fix-round-1 finding: on this chunk the acquirer correctly locks onto
    WWVH (`stations=('WWVH',)`) -- WWV's Fort Collins path isn't open to
    ND at 12:00Z while WWVH's Kauai path is.  The 1000-band peak this
    fold sees is WWVH's own tick LEAKING into the WWV/BPM band
    (`arbitrate_bands` correctly discards it), not a real WWV tick, so a
    fine search hard-coded to `station="WWV"` reads ~the WWV-WWVH delay
    separation (18.7 ms predicted here) as spurious "error" against a
    plane that was never claiming to be WWV.  Query the station the
    acquirer actually locked (`got.stations[0]`) instead."""
    iq, meta = _load(BAD, "1788696000")
    sr = int(meta["sample_rate"])
    got, rtp, audio, delays, minute_utc, bt_true, a = _acquire_first_minutes(
        iq, meta, shift_ms=-250.0
    )
    assert got is not None, "no acquisition within 180 s on the bad-window chunk"
    from hf_timestd.core.tick_edge_detector import TickEdgeDetector

    station = got.stations[0]
    bt_acq = dataclasses.replace(
        bt_true,
        sample0_utc=got.sample0_utc_for(rtp),
        origin_source="acquired",
        origin_sigma_ms=got.sigma_ms,
    )
    det = TickEdgeDetector(sample_rate=sr)
    res = det.detect_edges(
        audio_signal=audio,
        station=station,
        minute_number=minute_utc,
        buffer_timing=bt_acq,
        expected_delay_sec=delays[station],
        is_dedicated_channel=False,
        iq_samples=None,
    )
    print(
        f"\n  bad-window: acquired stations={got.stations}  station queried={station}  "
        f"sigma1={res.sigma_single_ms if res else float('nan'):.3f} ms  "
        f"n_detected={res.n_detected if res else -1}  "
        f"fine_err_ms={res.ensemble_timing_error_ms if res else float('nan'):+.3f}"
    )
    assert res is not None
    assert res.sigma_single_ms < 1.5, f"sigma1 {res.sigma_single_ms:.2f} ms >= 1.5 ms"
    assert res.n_detected >= 30, f"only {res.n_detected} ticks detected"
    assert abs(res.ensemble_timing_error_ms) < 2.0, (
        f"fine search on the acquired plane for its own station ({station}) still "
        f"shows {res.ensemble_timing_error_ms:+.2f} ms of error"
    )


@pytest.mark.skipif(
    not (B4 / "1788742800.bin.zst").exists(), reason="B4 fixture not present"
)
def _acquire_channel(iq, meta, shift_ms, epoch_id, engine=None):
    """Run the acquirer over up to 3 minutes of one channel's chunk.
    Returns (registration_or_None, acquirer, start_rtp_of_last_minute,
    audio, delays, minute_utc, bt_true, offset_samples, k)."""
    from hf_timestd.core.buffer_timing import resolve_buffer_timing
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer

    sr = int(meta["sample_rate"])
    eng = engine or _engine(meta)
    acq = RegistrationAcquirer(meta["channel_name"], sr)
    bt_true = resolve_buffer_timing(meta, sample_rate=sr)
    got, a, k = None, 0, 0
    audio, delays, minute_utc = None, None, None
    for k in range(3):
        a = k * 60 * sr
        seg = iq[a : a + 62 * sr]
        minute_utc = int(meta["minute_boundary"]) + 60 * k
        label = dataclasses.replace(
            bt_true, sample0_utc=bt_true.sample0_utc + a / sr + shift_ms / 1000.0
        )
        audio = eng.prepare_audio(seg)
        delays = eng.expected_delays_s(label.sample0_utc, minute_utc)
        start_rtp = int(meta["start_rtp_timestamp"]) + a
        got = acq.offer_minute(audio, label, start_rtp, minute_utc, delays, epoch_id)
        if got is not None:
            break
    return (
        got,
        acq,
        int(meta["start_rtp_timestamp"]) + a,
        audio,
        delays,
        minute_utc,
        bt_true,
        a,
        k,
    )


def _max_fold_snr_by_band(iq, meta, sr):
    """Diagnostic-only: the best fold-peak SNR reachable in each tone band
    using ALL available minutes (not the acquirer's 3-minute bootstrap
    cap) -- answers "is there any usable tick signal in this chunk at
    all," independent of window-length or label-shift choices."""
    from hf_timestd.core import registration_acquirer as ra
    from hf_timestd.core.buffer_timing import resolve_buffer_timing

    bt_true = resolve_buffer_timing(meta, sample_rate=sr)
    eng = _engine(meta)
    audio_all = eng.prepare_audio(iq)
    n_sec = min(270, len(audio_all) // sr)
    out = {}
    for band in ra.TONE_BANDS_HZ:
        profile, rows = ra.fold_tick_train(
            audio_all, sr, bt_true.sample0_utc, band, n_sec
        )
        if rows == 0:
            out[band] = (0, float("nan"))
            continue
        baseline = np.median(profile)
        dev = profile - baseline
        mad = np.median(np.abs(dev)) * 1.4826
        snr_db = 20 * np.log10(dev.max() / mad) if mad > 0 else float("nan")
        out[band] = (rows, snr_db)
    return out


def test_b4_shared_channel_resolved_by_real_wwv20000_sibling():
    """Spec §4: on a shared channel (SHARED_10000, WWV and BPM both keying
    the 1000 Hz tick band), standalone single-peak acquisition is NOT
    expected -- the design carries the open hypotheses and lets a sibling
    channel decide.  On B4 the dedicated WWV_20000/25000 channels do that
    live, and a REAL WWV_20000 chunk from the same 10-minute window (same
    radiod, same RTP counter -- see the module-level comment above ``B4``)
    is now on disk, replacing fix round 1's synthetic sidecar-plane
    sibling.

    The sidecar's ``timing`` block carries ``judge_tier="T4"`` (a
    host-clock-witnessed raw pair) on this chunk, not the tick-based T6
    plane -- the T6 comparison proper belongs to Task 12's live B4
    non-regression run.

    Fix-round-2 finding: this specific WWV_20000 window (2026-09-07
    01:00-01:05Z) carries NO usable 20 MHz tick signal.  Its raw IQ
    amplitude is ~35 dB below the SHARED_10000 (10 MHz) chunk from the
    same window (RMS 2.2e-5 vs. 1.3e-3), and the fold-peak SNR in either
    tone band never crosses the ~13 dB detection floor even integrating
    every available minute (see the per-band dump this test prints) --
    consistent with 20 MHz, a daytime band, having dropped below B4's MUF
    by 01:00Z local-evening in September.  So the intended demonstration
    (WWV_20000 acquires standalone, then resolves SHARED_10000's
    ambiguity, then fuses) cannot run end-to-end on the fixture as
    provided -- this is reported plainly rather than forced, with the
    real, cross-checked numbers the controller asked for: the two
    channels' own T4-judged pairs, extrapolated to a common RTP, agree
    with each other to ~1.3 ms (same counter space, confirmed), while the
    SHARED_10000 channel's own fold shows its T4 plane sits ~77 ms from
    where the real WWV tick actually is -- a residual on the shared
    channel's OWN ticks, not something WWV_20000 could independently
    confirm or refute here since it has no detectable tick of its own in
    this window."""
    from hf_timestd.core.registration_acquirer import (
        CROSS_SITE_AGREE_MS,
        RegistrationAcquirer,
        SAME_SITE_AGREE_MS,
        wrap_half_second,
    )
    from hf_timestd.core.registration_store import fuse_registrations
    from hf_timestd.core.tick_edge_detector import TickEdgeDetector

    iq20, meta20 = _load(B4, "wwv20000-1788742800")
    sr = int(meta20["sample_rate"])

    # ── Step 1: acquire WWV_20000 standalone (single-station channel) ──
    got20, acq20, rtp20, audio20, delays20, minute_utc20, bt_true20, a20, k20 = (
        _acquire_channel(iq20, meta20, shift_ms=0.0, epoch_id="ep-b4")
    )
    snr_by_band = _max_fold_snr_by_band(iq20, meta20, sr)
    print(
        f"\n  WWV_20000 standalone: {k20 + 1} minutes offered, state={acq20.state}, "
        f"got={'ACQUIRED' if got20 is not None else None}"
    )
    print(
        "  WWV_20000 max fold SNR over all available minutes "
        f"({'/'.join(f'{b}:{s:.1f}dB(n={n})' for b, (n, s) in snr_by_band.items())})"
    )

    if got20 is None:
        pytest.xfail(
            "WWV_20000 did not acquire standalone in this fixture: no tone-band "
            "fold peak ever crosses the detection floor "
            f"({snr_by_band}), consistent with 20 MHz being below B4's MUF at "
            "2026-09-07 01:00Z (see docstring for the amplitude comparison) -- "
            "not a bug in the acquirer.  The resolve_ambiguity/fuse_registrations "
            "demonstration needs a WWV_20000/25000 window where 20 MHz is open."
        )

    # ── WWV_20000's own fine search on its own acquired plane ──
    bt_acq20 = dataclasses.replace(
        bt_true20,
        sample0_utc=got20.sample0_utc_for(rtp20),
        origin_source="acquired",
        origin_sigma_ms=got20.sigma_ms,
    )
    det = TickEdgeDetector(sample_rate=sr)
    res20 = det.detect_edges(
        audio_signal=audio20,
        station="WWV",
        minute_number=minute_utc20,
        buffer_timing=bt_acq20,
        expected_delay_sec=delays20["WWV"],
        is_dedicated_channel=True,
        iq_samples=None,
    )
    print(
        f"  WWV_20000 own-plane fine search: sigma={got20.sigma_ms:.3f} ms  "
        f"sigma1={res20.sigma_single_ms if res20 else float('nan'):.3f} ms  "
        f"n={res20.n_detected if res20 else -1}  "
        f"err={res20.ensemble_timing_error_ms if res20 else float('nan'):+.3f} ms"
    )
    assert got20.stations == ("WWV",)

    # ── Step 2: SHARED_10000 bootstraps with open {WWV, BPM} ──
    iq_shared, meta_shared = _load(B4, "1788742800")
    gotS, acqS, rtpS, audioS, delaysS, minute_utcS, bt_trueS, aS, kS = _acquire_channel(
        iq_shared, meta_shared, shift_ms=120.0, epoch_id="ep-b4"
    )
    assert (
        gotS is None
    ), "standalone acquisition should NOT complete on a shared channel"
    assert acqS.state == RegistrationAcquirer.STATE_BOOTSTRAP
    open_stations = {h.assignments[0][0] for h in acqS._open}
    print(
        f"  SHARED_10000 open hypotheses after {kS + 1} minutes: {sorted(open_stations)}"
    )
    for h in acqS._open:
        print(
            f"    corr={h.correction_s * 1000:+9.3f} ms  sigma={h.sigma_ms:6.3f}  "
            f"support={h.support}  assignments={h.assignments}"
        )
    assert open_stations == {"WWV", "BPM"}

    # measurement for Michael: how far off is the SHARED sidecar plane from
    # the real WWV tick, per the shared channel's own (ambiguous) fold?
    wwv_hyp = next(h for h in acqS._open if h.assignments[0][0] == "WWV")
    shared_gap_ms = 120.0 + wwv_hyp.correction_s * 1000.0  # vs bt_trueS, unshifted
    print(
        f"  SHARED_10000 sidecar/T4 plane vs real WWV tick (own fold): {shared_gap_ms:+.3f} ms"
    )

    # ── resolve SHARED_10000's ambiguity using the REAL WWV_20000 sibling ──
    # ``h.correction_s`` is anchored to whichever minute's label produced
    # it; every minute's label here is built from the SAME bt_trueS base
    # plus the same shift_ms, so it is linear in RTP and the last offered
    # minute's (label, start_rtp) pair is as valid an anchor as the first
    # (see fix-round-2 report for the derivation) -- use the LAST minute's
    # label together with its own start_rtp (rtpS), matching what
    # resolve_ambiguity expects: a (start_rtp, label_s0) pair from the SAME
    # minute.
    label_s0_last = bt_trueS.sample0_utc + aS / sr + 120.0 / 1000.0
    for h in acqS._open:
        st_h = h.assignments[0][0]
        tol = SAME_SITE_AGREE_MS if st_h in got20.stations else CROSS_SITE_AGREE_MS
        sib_s0 = got20.sample0_utc_for(rtpS)
        frac_ms = wrap_half_second((label_s0_last + h.correction_s) - sib_s0) * 1000.0
        print(f"    vs WWV_20000 sibling: {st_h} frac={frac_ms:+9.3f} ms  tol={tol} ms")
    result = acqS.resolve_ambiguity(got20, rtpS, label_s0_last)
    print(f"  resolve_ambiguity -> {result}")
    assert (
        result is not None
    ), "resolve_ambiguity should resolve using the real WWV_20000 sibling"
    assert result.stations == ("WWV",)

    bt_acqS = dataclasses.replace(
        bt_trueS,
        sample0_utc=result.sample0_utc_for(rtpS),
        origin_source="acquired",
        origin_sigma_ms=result.sigma_ms,
    )
    resS = det.detect_edges(
        audio_signal=audioS,
        station="WWV",
        minute_number=minute_utcS,
        buffer_timing=bt_acqS,
        expected_delay_sec=delaysS["WWV"],
        is_dedicated_channel=False,
        iq_samples=None,
    )
    print(
        f"  SHARED_10000 resolved-plane fine search WWV: "
        f"sigma1={resS.sigma_single_ms if resS else float('nan'):.3f} ms  "
        f"n={resS.n_detected if resS else -1}  "
        f"err={resS.ensemble_timing_error_ms if resS else float('nan'):+.3f} ms"
    )
    assert resS is not None
    assert resS.sigma_single_ms < 1.0
    assert resS.n_detected >= 40
    assert abs(resS.ensemble_timing_error_ms) < 2.0

    # ── per-radiod fusion on real data ──
    fused = fuse_registrations([result, got20], rtpS)
    print(f"  fuse_registrations([shared_resolved, wwv20000]) -> {fused}")
    assert fused is not None
