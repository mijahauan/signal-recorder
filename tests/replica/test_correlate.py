"""Replica correlation: an unambiguous lag, and a quality score that refuses.

The correlation SNR is the point of this module. On 2026-09-08 the fold-peak
method manufactured -46.8 and -216.6 ppm from two ND channels carrying no
usable WWV structure at all, and the estimator could only refuse that
downstream, after something had already made it. Correlation SNR refuses at
the source: measured 57.8 to 71.0 on channels that work against 6.2 and 7.2
on those two.
"""

import numpy as np
import pytest

from hf_timestd.replica.correlate import (
    MIN_CC_SNR,
    correlate_minute,
)
from hf_timestd.replica.template import minute_template

FS = 2000


def shifted(template, samples):
    return np.roll(template, samples)


def test_a_template_against_itself_lands_on_zero_lag():
    t = minute_template(FS)
    c = correlate_minute(t, FS)
    assert c.lag_s == pytest.approx(0.0, abs=1.0 / FS)
    assert c.admissible


def test_a_shifted_copy_reports_the_shift():
    t = minute_template(FS)
    c = correlate_minute(shifted(t, 15), FS)  # 15 samples = 7.5 ms
    assert c.lag_s == pytest.approx(0.0075, abs=1.0 / FS)


def test_a_negative_shift_reports_a_negative_lag():
    t = minute_template(FS)
    c = correlate_minute(shifted(t, -20), FS)
    assert c.lag_s == pytest.approx(-0.010, abs=1.0 / FS)


def test_noise_alone_is_refused():
    rng = np.random.default_rng(3)
    c = correlate_minute(rng.normal(0.0, 1.0, 60 * FS), FS)
    assert not c.admissible
    assert c.cc_snr < MIN_CC_SNR


def test_a_buried_but_present_signal_is_admitted_and_read():
    rng = np.random.default_rng(5)
    t = minute_template(FS)
    sig = shifted(t, 8) + rng.normal(0.0, 0.05, len(t))
    c = correlate_minute(sig, FS)
    assert c.admissible
    assert c.lag_s == pytest.approx(0.004, abs=0.002)


def test_the_threshold_sits_between_what_was_measured_and_what_failed():
    """Measured 2026-09-08: 57.8-71.0 admissible, 6.2-7.2 not."""
    assert 7.2 < MIN_CC_SNR < 57.8


def sub_sample_shift(x, samples):
    """Shift by a FRACTION of a sample, through a phase ramp."""
    n = len(x)
    spectrum = np.fft.rfft(x)
    k = np.arange(len(spectrum))
    return np.fft.irfft(spectrum * np.exp(-2j * np.pi * k * samples / n), n=n)


@pytest.mark.parametrize("shift", [7.4, -2.6, 0.25])
def test_a_sub_sample_shift_is_read_to_a_fraction_of_a_sample(shift):
    """Integer shifts cannot measure the interpolation, so use fractions.

    Measured accuracy 0.06 samples; rounding to the nearest sample instead
    would err by up to 0.5, so the bar below separates the two. A lag good
    only to one sample would cap the rate this module can measure.
    """
    t = minute_template(FS)
    c = correlate_minute(sub_sample_shift(t, shift), FS)
    err = abs(c.lag_s * FS - shift)
    assert err < 0.15, f"lag {c.lag_s * FS:+.4f} against {shift:+.2f} samples"
