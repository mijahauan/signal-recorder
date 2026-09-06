import numpy as np
import pytest

from hf_timestd.core.registration_acquirer import (
    ACQ_MIN_FOLD_SNR_DB, FoldPeak, arbitrate_bands, find_fold_peaks, fold_tick_train,
)
from synth_ticks import make_tick_audio

SR = 24000
MIN = 1_800_000_000          # a minute boundary
T0 = MIN - 1.0               # truth: buffer starts 1 s before the minute


def _peaks(walk_s, snr_db, stations, n_seconds=60, band="1000"):
    audio = make_tick_audio(n_seconds + 2, SR, T0, stations, snr_db=snr_db)
    profile, n_rows = fold_tick_train(audio, SR, T0 + walk_s, band, n_seconds)
    assert len(profile) == SR
    assert n_rows >= n_seconds - 8          # skip set removes ≤ 6 of 60, edges ≤ 2
    return find_fold_peaks(profile, SR, band)


@pytest.mark.parametrize("snr_db", [30.0, 15.0, 5.0])
def test_wwv_tick_appears_at_delay_plus_walk(snr_db):
    peaks = _peaks(walk_s=0.250, snr_db=snr_db, stations={"WWV": 0.0125})
    assert peaks, "the fold must show the tick at 5 dB per tick (60 s fold gains ~17 dB)"
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
    peaks = arbitrate_bands({"1000": find_fold_peaks(p1000, SR, "1000"),
                             "1200": find_fold_peaks(p1200, SR, "1200")})
    assert len(peaks) == 1 and peaks[0].band == "1200"
    assert abs(peaks[0].position_s - 0.018) < 0.002


def test_arbitration_keeps_distinct_positions_in_both_bands():
    audio = make_tick_audio(62, SR, T0, {"WWV": 0.010, "WWVH": 0.028}, snr_db=20.0)
    p1000, _ = fold_tick_train(audio, SR, T0, "1000", 60)
    p1200, _ = fold_tick_train(audio, SR, T0, "1200", 60)
    peaks = arbitrate_bands({"1000": find_fold_peaks(p1000, SR, "1000"),
                             "1200": find_fold_peaks(p1200, SR, "1200")})
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
