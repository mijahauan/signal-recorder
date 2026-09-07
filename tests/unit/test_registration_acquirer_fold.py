import numpy as np
import pytest

from hf_timestd.core.registration_acquirer import (
    ACQ_MIN_FOLD_SNR_DB,
    _band_envelope,
    arbitrate_bands,
    find_fold_peaks,
    fold_envelope,
    fold_tick_train,
)
from synth_ticks import make_tick_audio

SR = 24000
MIN = 1_800_000_000  # a minute boundary
T0 = MIN - 1.0  # truth: buffer starts 1 s before the minute


def _peaks(walk_s, snr_db, stations, n_seconds=60, band="1000"):
    audio = make_tick_audio(n_seconds + 2, SR, T0, stations, snr_db=snr_db)
    profile, n_rows = fold_tick_train(audio, SR, T0 + walk_s, band, n_seconds)
    assert len(profile) == SR
    assert n_rows >= n_seconds - 8  # skip set removes ≤ 6 of 60, edges ≤ 2
    return find_fold_peaks(profile, SR, band)


@pytest.mark.parametrize("snr_db", [30.0, 15.0, 5.0])
def test_wwv_tick_appears_at_delay_plus_walk(snr_db):
    peaks = _peaks(walk_s=0.250, snr_db=snr_db, stations={"WWV": 0.0125})
    assert (
        peaks
    ), "the fold must show the tick at 5 dB per tick (60 s fold gains ~17 dB)"
    best = max(peaks, key=lambda p: p.snr_db)
    assert best.band == "1000"
    assert abs(best.position_s - (0.0125 + 0.250)) < 0.002
    assert best.snr_db >= ACQ_MIN_FOLD_SNR_DB


def test_position_wraps_inside_the_second():
    peaks = _peaks(walk_s=-0.300, snr_db=20.0, stations={"WWV": 0.010})
    best = max(peaks, key=lambda p: p.snr_db)
    assert abs(best.position_s - ((0.010 - 0.300) % 1.0)) < 0.002


def test_wwvh_lands_in_the_1200_band_after_arbitration():
    # A 5 ms tick has a ~200 Hz sinc main lobe, so a 1200 Hz tick LEAKS into
    # the 900-1100 band; no filter separates them.  The tone identity comes
    # from comparing the two bands at the same fold position: the band that
    # matches the tone responds more strongly.
    audio = make_tick_audio(62, SR, T0, {"WWVH": 0.018}, snr_db=20.0)
    p1000, _ = fold_tick_train(audio, SR, T0, "1000", 60)
    p1200, _ = fold_tick_train(audio, SR, T0, "1200", 60)
    peaks = arbitrate_bands(
        {
            "1000": find_fold_peaks(p1000, SR, "1000"),
            "1200": find_fold_peaks(p1200, SR, "1200"),
        }
    )
    assert len(peaks) == 1 and peaks[0].band == "1200"
    assert abs(peaks[0].position_s - 0.018) < 0.002


def test_arbitration_keeps_distinct_positions_in_both_bands():
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.010, "WWVH": 0.028}, snr_db=20.0)
    p1000, _ = fold_tick_train(audio, SR, T0, "1000", 60)
    p1200, _ = fold_tick_train(audio, SR, T0, "1200", 60)
    peaks = arbitrate_bands(
        {
            "1000": find_fold_peaks(p1000, SR, "1000"),
            "1200": find_fold_peaks(p1200, SR, "1200"),
        }
    )
    by_band = {p.band: p.position_s for p in peaks}
    assert abs(by_band["1000"] - 0.010) < 0.002 and abs(by_band["1200"] - 0.028) < 0.002


def test_noise_alone_yields_no_peak():
    rng = np.random.default_rng(1)
    audio = 0.1 * rng.standard_normal(62 * SR)
    profile, _ = fold_tick_train(audio, SR, T0, "1000", 60)
    assert find_fold_peaks(profile, SR, "1000") == []


def test_two_stations_two_peaks():
    peaks = _peaks(walk_s=0.0, snr_db=20.0, stations={"WWV": 0.010, "BPM": 0.044})
    pos = sorted(p.position_s for p in peaks)
    assert len(pos) == 2
    assert abs(pos[0] - 0.010) < 0.002 and abs(pos[1] - 0.044) < 0.002


def test_two_same_band_ticks_20ms_apart_resolve():
    # PEAK_MIN_SEPARATION_MS=8 is a guard band on each side of a peak's
    # measured half-max width, not the resolving floor itself; two ~5 ms
    # ticks 20 ms apart (WWV @ 10 ms, BPM @ 30 ms, same "1000" band) must
    # still resolve as two distinct peaks.
    peaks = _peaks(walk_s=0.0, snr_db=20.0, stations={"WWV": 0.010, "BPM": 0.030})
    pos = sorted(p.position_s for p in peaks)
    assert len(pos) == 2
    assert abs(pos[0] - 0.010) < 0.002 and abs(pos[1] - 0.030) < 0.002


# ── I2 (final review): one envelope per band per attempt ──────────────


def test_band_envelope_is_float32():
    """I2: a 180 s envelope at 24 kHz is 34.6 MB in float64 and half that
    in float32, and the acquirer holds one per tone band across the full
    fold and both half folds.  The FILTERING stays float64 (a float32 SOS
    is where biquad cascades go unstable); only the live array narrows."""
    audio = make_tick_audio(4, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    env = _band_envelope(audio, SR, "1000")
    assert env.dtype == np.float32


def test_fold_envelope_start_offset_matches_folding_the_slice():
    """I2: the half-fold persistence gate used to re-filter a slice of the
    raw audio for its second half.  ``start_offset_s`` folds the SAME
    envelope from that point instead, which must line up sample for sample
    with the row selection the slice produced -- otherwise the gate
    compares peaks on a shifted grid."""
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    env = _band_envelope(audio, SR, "1000")
    half = 30
    off, rows_off = fold_envelope(env, SR, T0, 30, start_offset_s=float(half))
    sliced, rows_sliced = fold_envelope(env[half * SR :], SR, T0 + half, 30)
    assert rows_off == rows_sliced
    assert np.allclose(off, sliced, rtol=0, atol=0)


def test_fold_envelope_agrees_with_the_raw_audio_wrapper():
    """``fold_tick_train`` is now a wrapper over ``_band_envelope`` +
    ``fold_envelope``; the two paths must give the same profile."""
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.0125}, snr_db=20.0)
    direct, n1 = fold_tick_train(audio, SR, T0, "1000", 60)
    env = _band_envelope(audio, SR, "1000")
    viaenv, n2 = fold_envelope(env, SR, T0, 60)
    assert n1 == n2
    assert np.allclose(direct, viaenv, rtol=0, atol=0)
