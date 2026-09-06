import pytest

from hf_timestd.core.registration_acquirer import (
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
    # -25/-23/-21/-19 all still fail to acquire by 180 s; -19 measures 8.8 /
    # 10.5 / 11.3 dB (still under threshold at 162 rows); -17 measures 9.2 /
    # 14.3 / 15.2 dB, crossing between 54 and 108 rows and holding through
    # 162 -- the first minute misses, the fold does the work by the second.
    acq = RegistrationAcquirer("SHARED_10000", SR)
    outcomes = []
    for k in range(3):
        audio, label, rtp, m = _minute(k, walk_s=-0.300, snr_db=-17.0)
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
