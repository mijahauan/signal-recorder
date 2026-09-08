"""The WWV/WWVH minute template, against the structure wwvsim generates.

Read off Phil Karn's wwvsim (github.com/ka9q/wwvsim, `gen_ticks`): an 800 ms
marker at second 0 in the station's own tick band, a 5 ms tick on every second
from 1 to 58 except 29, and nothing at 29 or 59. WWV ticks at 1000 Hz and WWVH
at 1200 Hz, so the two stations share this TIME structure exactly and one
template serves both -- the band selects the station, not the template.
"""

import numpy as np

from hf_timestd.replica.template import (
    MARKER_MS,
    NO_TICK_SECONDS,
    TICK_MS,
    minute_template,
)

FS = 2000


def test_the_template_spans_exactly_one_minute():
    assert len(minute_template(FS)) == 60 * FS


def test_second_zero_carries_the_eight_hundred_millisecond_marker():
    t = minute_template(FS)
    edge = MARKER_MS * FS // 1000
    on = t[0:edge]
    off = t[edge:FS]
    assert np.all(on > 0)
    assert np.all(off == 0)


def test_every_ordinary_second_carries_a_five_millisecond_tick():
    t = minute_template(FS)
    width = TICK_MS * FS // 1000
    for s in range(1, 59):
        if s in NO_TICK_SECONDS:
            continue
        a, b = s * FS, (s + 1) * FS
        seg = t[a:b]
        assert np.all(seg[:width] > 0), f"second {s} carries no tick"
        assert np.all(seg[width:] == 0), f"second {s} tick runs long"


def test_the_silent_seconds_are_silent():
    t = minute_template(FS)
    for s in sorted(NO_TICK_SECONDS):
        a, b = s * FS, (s + 1) * FS
        seg = t[a:b]
        assert np.all(seg == 0), f"second {s} should carry no tick"


def test_the_silent_seconds_are_twenty_nine_and_fifty_nine():
    assert NO_TICK_SECONDS == frozenset({29, 59})


def test_the_marker_dominates_the_energy_of_any_single_tick():
    """160 ms of marker against 5 ms of tick is what makes a minute unique."""
    t = minute_template(FS)
    a, b = 5 * FS, 6 * FS
    marker = float(t[0:FS].sum())
    tick = float(t[a:b].sum())
    assert marker > 100 * tick
