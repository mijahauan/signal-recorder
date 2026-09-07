import dataclasses
import math

import numpy as np
from synth_ticks import make_tick_audio, label_timing

from hf_timestd.core.buffer_timing import BufferTiming


def _bt(**kw):
    base = dict(
        sample0_utc=1_800_000_000.0,
        sample_rate=24000,
        source="rtp_gps",
        n_snapshots_used=1,
        jitter_ms=0.0,
    )
    base.update(kw)
    return BufferTiming(**base)


def test_defaults_keep_existing_constructors_working():
    bt = _bt()
    assert bt.origin_source == "label"
    assert math.isinf(bt.origin_sigma_ms)
    assert bt.counter_epoch_id == "unregistered"


def test_replace_sets_acquired_origin():
    bt = dataclasses.replace(
        _bt(),
        sample0_utc=1_800_000_000.25,
        origin_source="acquired",
        origin_sigma_ms=0.8,
        counter_epoch_id="ep-1",
    )
    assert bt.origin_source == "acquired"
    assert bt.origin_sigma_ms == 0.8
    assert bt.sample_to_utc(24000) == 1_800_000_001.25


def test_synth_helper_places_a_tick_where_truth_says():
    sr = 24000
    t0 = 1_800_000_000.0 - 1.0
    audio = make_tick_audio(3, sr, t0, {"WWV": 0.010}, snr_db=40.0, marker=False)
    # second 1_800_000_000 is second 0 of a minute -> no tick (marker=False);
    # second 1_800_000_001 tick starts 2.010 s into the buffer.
    i0 = int(round(2.010 * sr))
    assert np.abs(audio[i0 : i0 + 120]).max() > 0.5
    assert np.abs(audio[i0 - 600 : i0 - 120]).max() < 0.2
    assert label_timing(t0, 0.3, sr).sample0_utc == t0 + 0.3
