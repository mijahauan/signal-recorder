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
