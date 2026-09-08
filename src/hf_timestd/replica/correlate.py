"""Correlate a band envelope against the replica, and score the match.

The lag says where the minute sits; ``cc_snr`` says whether a minute is there
at all. Measured on 2026-09-08 across the ND and B4 fixtures: channels that
work score 57.8 to 71.0, and two ND channels carrying no usable structure
score 6.2 and 7.2 -- which is simply what pure noise scores, since the largest
of many Gaussian samples sits near 4.5 sigma while their median absolute value
sits near 0.674 sigma.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .template import minute_template

# Geometrically between the 7.2 that failed and the 57.8 that worked, so a
# threefold margin stands on either side of it.
MIN_CC_SNR = 20.0


@dataclass(frozen=True)
class Correlation:
    """Where the replica matched, and how well."""

    lag_s: float
    cc_snr: float

    @property
    def admissible(self) -> bool:
        """Whether this channel carries WWV structure worth a witness."""
        return self.cc_snr >= MIN_CC_SNR


def correlate_minute(
    envelope: np.ndarray,
    sample_rate: int,
    template: np.ndarray | None = None,
) -> Correlation:
    """Circular correlation of one minute of ``envelope`` against the replica.

    Both sides lose their mean first, so a channel's own DC offset cannot
    dominate the match. The peak is refined parabolically, because a lag good
    only to one sample would cap the rate this can measure.
    """
    fs = int(sample_rate)
    ref = (
        minute_template(fs)
        if template is None
        else np.asarray(template, dtype=np.float64)
    )
    n = len(ref)
    sig = np.asarray(envelope, dtype=np.float64)
    if len(sig) < n:
        sig = np.pad(sig, (0, n - len(sig)))
    else:
        sig = sig[:n]
    sig = sig - sig.mean()
    ref = ref - ref.mean()
    cc = np.fft.irfft(np.fft.rfft(sig) * np.conj(np.fft.rfft(ref)), n=n)
    k = int(np.argmax(cc))
    y0, y1, y2 = cc[(k - 1) % n], cc[k], cc[(k + 1) % n]
    curvature = y0 - 2.0 * y1 + y2
    frac = 0.0 if curvature == 0.0 else 0.5 * (y0 - y2) / curvature
    lag = k + frac
    if lag > n / 2.0:
        lag -= n
    floor = float(np.median(np.abs(cc)))
    # A perfectly noiseless match drives the median to zero. Report the score
    # as unbounded-but-finite rather than dividing by it: the alternative is a
    # NaN that clears the admission test it exists to fail.
    snr = float("inf") if floor <= 0.0 else float(y1) / floor
    return Correlation(lag_s=lag / fs, cc_snr=snr)
