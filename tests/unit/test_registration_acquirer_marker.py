import pytest

from hf_timestd.core.registration_acquirer import (
    integer_second_correction,
    locate_minute_marker,
)
from synth_ticks import make_tick_audio

SR = 24000
MIN = 1_800_000_000
T0 = MIN - 4.0  # 10 s buffer: the ±1.5 s marker search must fit for walks up to ±1.2 s


@pytest.mark.parametrize("walk_s", [0.0, 0.4, -0.7, 1.2])
def test_marker_found_where_truth_put_it(walk_s):
    audio = make_tick_audio(10, SR, T0, {"WWV": 0.012}, snr_db=15.0)
    res = locate_minute_marker(audio, SR, T0 + walk_s, "1000", MIN)
    assert res is not None
    offset_s, snr = res
    # in the label frame the marker onset sits at d + walk after the minute
    assert offset_s == pytest.approx(0.012 + walk_s, abs=0.005)
    assert snr > 6.0


def test_no_marker_returns_none():
    audio = make_tick_audio(10, SR, T0, {"WWV": 0.012}, snr_db=15.0, marker=False)
    assert locate_minute_marker(audio, SR, T0, "1000", MIN) is None


@pytest.mark.parametrize("snr_db", [30.0, 40.0])
def test_no_marker_at_high_tick_snr(snr_db):
    # strong ticks must not leak past the gate as the tick SNR rises --
    # a windowed-MEAN score's own MAD shrinks as fast as the leak it is
    # trying to detect above, which is why the score statistic is a
    # bin-median, not a mean-over-MAD ratio.
    audio = make_tick_audio(10, SR, T0, {"WWV": 0.012}, snr_db=snr_db, marker=False)
    assert locate_minute_marker(audio, SR, T0, "1000", MIN) is None


def test_window_does_not_fit_returns_none():
    audio = make_tick_audio(10, SR, T0, {"WWV": 0.012}, snr_db=15.0)
    # the minute sits only 0.5 s after the label's sample0 -- the
    # ±1.5 s search cannot fit before it
    label = MIN - 0.5
    assert locate_minute_marker(audio, SR, label, "1000", MIN) is None


@pytest.mark.parametrize(
    "walk_s,frac,expected",
    [
        (
            0.4,
            -0.4,
            0,
        ),  # label 0.4 s late: total correction -0.4, fold says -0.4, no whole second
        (
            1.2,
            -0.2,
            -1,
        ),  # label 1.2 s late: total -1.2, fold wraps to -0.2, marker adds -1
        (
            -0.7,
            -0.3,
            1,
        ),  # label 0.7 s early: total +0.7, fold wraps to -0.3, marker adds +1
    ],
)
def test_integer_second_from_marker(walk_s, frac, expected):
    # the fold only ever reports (-0.5, 0.5]; the marker supplies the rest
    # marker_offset = d + walk ; total correction = -walk ; integer = round(-walk - frac)
    d = 0.012
    assert integer_second_correction(d + walk_s, d, frac) == expected


# ── Task 15: the 800 ms marker excludes BPM ───────────────────────────
#
# A shared channel that folds ONE 1000 Hz peak carries two hypotheses --
# WWV or BPM, 34 ms apart on ND -- and no sibling channel can choose
# between them when the dedicated channels hear no tick (AC0G-ND
# 2026-09-07 20:34Z: BOOTSTRAP indefinitely, so the anchor closure had
# nothing to anchor to).  WWV and WWVH transmit an 800 ms tone at second
# 0; BPM transmits no minute marker at all.  An 800 ms tone standing on
# the same fold position as the ticks therefore names their source.

D_SHARED = {"WWV": 0.010, "BPM": 0.044}
RUN_UP_S = 3.0  # the +-1.5 s marker search needs run-up before the minute


def _shared_channel_minute(walk_s, marker, station="WWV", snr_db=20.0, seed=7):
    """One 62 s buffer starting RUN_UP_S before the minute, so the marker
    search fits inside this single buffer."""
    from synth_ticks import label_timing

    t0 = MIN - RUN_UP_S
    audio = make_tick_audio(
        62,
        SR,
        t0,
        {station: D_SHARED[station]},
        snr_db=snr_db,
        seed=seed,
        marker=marker,
    )
    return audio, label_timing(t0, walk_s, SR), t0


def test_marker_names_wwv_on_a_shared_channel():
    """The acceptance case: one WWV tick train on a shared channel, both
    WWV and BPM eligible, no sibling.  The marker names WWV."""
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer

    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, t0 = _shared_channel_minute(walk_s=0.100, marker=True)
    reg = acq.offer_minute(audio, label, 1_000_000, MIN, D_SHARED, "ep-1")
    assert reg is not None, "the 800 ms marker should have named WWV"
    assert acq.state == acq.STATE_ACQUIRED
    assert reg.stations == ("WWV",)
    assert reg.hypotheses_open == 0
    assert acq._open == []
    assert reg.verified is False  # still a CANDIDATE: gate (b) has not run
    assert "marker" in reg.method
    # correction == -walk: the plane lands on truth
    assert reg.sample0_utc_for(1_000_000) == pytest.approx(t0, abs=0.003)


def test_no_marker_leaves_both_hypotheses_open():
    """Same audio without the marker: today's behaviour, unchanged."""
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer

    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, _t0 = _shared_channel_minute(walk_s=0.100, marker=False)
    assert acq.offer_minute(audio, label, 1_000_000, MIN, D_SHARED, "ep-1") is None
    assert acq.state == acq.STATE_BOOTSTRAP
    # task 16a: the BPM reading of the same peak no longer survives as a
    # hypothesis; one open WWV reading remains, ambiguous because band
    # 1000 admits BPM as a READING of that peak
    assert len(acq._open) == 1


def test_bpm_like_train_stays_bootstrap():
    """A train at BPM's delay with no 800 ms marker (BPM's own minute
    structure) must NOT be promoted -- nothing names it, and the marker
    rule may not invent a station."""
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer

    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, _t0 = _shared_channel_minute(
        walk_s=0.100, marker=False, station="BPM"
    )
    assert acq.offer_minute(audio, label, 1_000_000, MIN, D_SHARED, "ep-1") is None
    assert acq.state == acq.STATE_BOOTSTRAP
    # task 16a: the BPM reading of the same peak no longer survives as a
    # hypothesis; one open WWV reading remains, ambiguous because band
    # 1000 admits BPM as a READING of that peak
    assert len(acq._open) == 1


def test_live_minute_geometry_needs_a_second_minute():
    """The live ring hands the acquirer [minute, minute + 60 s), so the
    FIRST minute's own marker has no 1.5 s of run-up ahead of it and the
    search cannot fit.  The marker becomes searchable once a second
    minute is buffered, because ``_try_acquire`` folds and searches the
    CONCATENATED buffer in the frame of the oldest label -- where the
    second minute's marker sits 60 s in, with run-up on both sides."""
    from synth_ticks import label_timing
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer

    acq = RegistrationAcquirer("SHARED_10000", SR)
    got = None
    for k in range(2):
        t0 = MIN + 60 * k  # buffer starts exactly at the minute, as the ring does
        audio = make_tick_audio(
            62, SR, t0, {"WWV": D_SHARED["WWV"]}, snr_db=20.0, seed=7 + k
        )
        got = acq.offer_minute(
            audio,
            label_timing(t0, 0.100, SR),
            1_000_000 + k * 60 * SR,
            MIN + 60 * k,
            D_SHARED,
            "ep-1",
        )
        if k == 0:
            assert got is None, "one live-geometry minute cannot reach its own marker"
            assert len(acq._open) == 1
    assert got is not None, "the second minute puts a marker inside the search window"
    assert got.stations == ("WWV",)
    assert got.sample0_utc_for(1_000_000) == pytest.approx(MIN, abs=0.003)


# ── the naming rule itself, on hand-built hypotheses ──────────────────


def _hyp(station, band, correction_s, position_s, snr_db=30.0):
    from hf_timestd.core.registration_acquirer import Hypothesis

    return Hypothesis(
        correction_s=correction_s,
        sigma_ms=1.0,
        assignments=((station, band, position_s, snr_db),),
        support=1,
        unambiguous=False,
    )


def test_marker_names_wwvh_in_the_1200_band():
    """Symmetric rule: a marker in the 1200 band names WWVH."""
    from hf_timestd.core.registration_acquirer import marker_names_one_hypothesis

    d = {"WWVH": 0.023, "BPM": 0.041}
    # one 1200-band peak at 0.123 s: WWVH's correction is 0.023 - 0.123
    h_wwvh = _hyp("WWVH", "1200", correction_s=0.023 - 0.123, position_s=0.123)
    named = marker_names_one_hypothesis(
        [h_wwvh], d, lambda band: (0.1235, 22.0) if band == "1200" else None
    )
    assert named is not None
    assert named[0] is h_wwvh and named[1] == "1200"


def test_marker_off_every_hypothesis_names_nothing():
    """A marker that stands nowhere near the folded ticks belongs to
    something else (a carrier, a neighbouring station) -- hypotheses stay
    open."""
    from hf_timestd.core.registration_acquirer import marker_names_one_hypothesis

    h_wwv = _hyp("WWV", "1000", correction_s=0.010 - 0.080, position_s=0.080)
    h_bpm = _hyp("BPM", "1000", correction_s=0.044 - 0.080, position_s=0.080)
    assert (
        marker_names_one_hypothesis(
            [h_wwv, h_bpm], D_SHARED, lambda band: (0.140, 20.0)
        )
        is None
    )


def test_marker_on_the_ticks_excludes_bpm():
    """Both hypotheses come from ONE peak, so both predict the SAME
    marker position -- the position check confirms the marker belongs to
    this tick train, and BPM falls because BPM transmits no marker."""
    from hf_timestd.core.registration_acquirer import marker_names_one_hypothesis

    h_wwv = _hyp("WWV", "1000", correction_s=0.010 - 0.080, position_s=0.080)
    h_bpm = _hyp("BPM", "1000", correction_s=0.044 - 0.080, position_s=0.080)
    named = marker_names_one_hypothesis(
        [h_wwv, h_bpm], D_SHARED, lambda band: (0.0805, 31.0)
    )
    assert named is not None
    h, band, offset_s, snr_db, excluded = named
    assert h is h_wwv and band == "1000"
    assert offset_s == pytest.approx(0.0805) and snr_db == 31.0
    assert excluded == ("BPM",)


def test_absent_marker_names_nothing():
    from hf_timestd.core.registration_acquirer import marker_names_one_hypothesis

    h_wwv = _hyp("WWV", "1000", correction_s=0.010 - 0.080, position_s=0.080)
    h_bpm = _hyp("BPM", "1000", correction_s=0.044 - 0.080, position_s=0.080)
    assert (
        marker_names_one_hypothesis([h_wwv, h_bpm], D_SHARED, lambda band: None) is None
    )


# ── Task 16a at the acquirer: two 1000 Hz peaks, one marker ───────────


def _two_train_minute(marker, walk_s=0.100):
    """One WWV train (marker optional) plus a second 1000 Hz train 34 ms
    later carrying none -- the ND 20:36Z geometry.  The second train's
    own call runs at 60 dB so it adds ticks without adding noise."""
    from synth_ticks import label_timing

    t0 = MIN - RUN_UP_S
    wwv = make_tick_audio(
        62, SR, t0, {"WWV": 0.010}, snr_db=20.0, seed=7, marker=marker
    )
    artefact = make_tick_audio(
        62, SR, t0, {"BPM": 0.044}, snr_db=60.0, seed=99, marker=False
    )
    return wwv + artefact, label_timing(t0, walk_s, SR), t0


def test_a_second_1000_hz_peak_never_registers_as_bpm():
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer

    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, t0 = _two_train_minute(marker=True)
    reg = acq.offer_minute(audio, label, 1_000_000, MIN, D_SHARED, "ep-1")
    assert reg is not None, "the marker should have named WWV"
    assert reg.stations == ("WWV",)
    assert "BPM" not in reg.stations
    # the correction comes from the WWV peak alone: -walk, not a mean
    # pulled toward the artefact 34 ms away
    assert reg.sample0_utc_for(1_000_000) == pytest.approx(t0, abs=0.003)


def test_the_two_peak_pair_without_a_marker_stays_bootstrap():
    """Before task 16a this pair called itself unambiguous with support 2
    and anchored the station on it."""
    from hf_timestd.core.registration_acquirer import RegistrationAcquirer

    acq = RegistrationAcquirer("SHARED_10000", SR)
    audio, label, _t0 = _two_train_minute(marker=False)
    assert acq.offer_minute(audio, label, 1_000_000, MIN, D_SHARED, "ep-1") is None
    assert acq.state == acq.STATE_BOOTSTRAP
    assert acq._open, "the WWV readings stay open"
    assert all(
        "BPM" not in {a[0] for a in h.assignments} for h in acq._open
    ), "no open hypothesis may name BPM"
