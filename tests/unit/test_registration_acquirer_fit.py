import pytest

from hf_timestd.core.registration_acquirer import (
    FoldPeak,
    fit_template,
    wrap_half_second,
)


def _pk(band, pos, snr=20.0):
    return FoldPeak(band=band, position_s=pos % 1.0, snr_db=snr, width_ms=10.0)


def test_wrap():
    assert wrap_half_second(0.7) == pytest.approx(-0.3)
    assert wrap_half_second(-0.6) == pytest.approx(0.4)
    assert wrap_half_second(0.5) == pytest.approx(0.5)


def test_single_station_channel_is_unambiguous():
    # WWV 20 MHz: only WWV is eligible; label late by 0.250 -> peak at d + 0.250
    hyps = fit_template([_pk("1000", 0.0125 + 0.250)], {"WWV": 0.0125})
    assert len(hyps) == 1
    h = hyps[0]
    assert h.unambiguous and h.support == 1
    assert h.correction_s == pytest.approx(-0.250, abs=1e-6)
    assert h.assignments[0][0] == "WWV"


def test_two_peaks_resolve_shared_channel():
    d = {"WWV": 0.010, "WWVH": 0.028, "BPM": 0.044}
    walk = -0.300  # label EARLY: ticks appear at d + walk (wraps to 0.71x)
    peaks = [_pk("1000", 0.010 + walk), _pk("1200", 0.028 + walk, snr=14.0)]
    hyps = fit_template(peaks, d)
    assert hyps[0].unambiguous and hyps[0].support == 2
    assert hyps[0].correction_s == pytest.approx(0.300, abs=1e-6)
    stations = {a[0] for a in hyps[0].assignments}
    assert stations == {"WWV", "WWVH"}


def test_one_peak_on_shared_channel_carries_both_hypotheses():
    d = {"WWV": 0.010, "WWVH": 0.028}
    hyps = fit_template([_pk("1000", 0.010 + 0.1)], d)
    # band 1000 excludes WWVH; only WWV compatible -> unambiguous after all
    assert len(hyps) == 1 and hyps[0].unambiguous
    # band-ambiguous case: WWV and BPM share 1000 Hz
    d2 = {"WWV": 0.010, "BPM": 0.044}
    hyps2 = fit_template([_pk("1000", 0.010 + 0.1)], d2)
    assert len(hyps2) == 2 and not any(h.unambiguous for h in hyps2)
    corr = sorted(h.correction_s for h in hyps2)
    assert corr[0] == pytest.approx(-0.100, abs=1e-6)  # if it were WWV  (0.010 - 0.110)
    assert corr[1] == pytest.approx(-0.066, abs=1e-6)  # if it were BPM  (0.044 - 0.110)


def test_bpm_wwv_collision_resolved_by_34ms_separation():
    d = {"WWV": 0.010, "BPM": 0.044}
    peaks = [_pk("1000", 0.010 + 0.05), _pk("1000", 0.044 + 0.05, snr=12.0)]
    hyps = fit_template(peaks, d)
    assert hyps[0].unambiguous and hyps[0].support == 2
    assert hyps[0].correction_s == pytest.approx(-0.050, abs=1e-6)


def test_peak_in_wrong_band_matches_nothing():
    assert fit_template([_pk("1200", 0.1)], {"WWV": 0.010}) == []


def test_sigma_from_snr_and_floor():
    h = fit_template([_pk("1000", 0.2, snr=40.0)], {"WWV": 0.010})[0]
    assert h.sigma_ms >= 1.0
    h2 = fit_template([_pk("1000", 0.2, snr=10.0)], {"WWV": 0.010})[0]
    assert h2.sigma_ms > h.sigma_ms
