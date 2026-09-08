"""One minute of WWV/WWVH tick-band structure.

Read off ``gen_ticks`` in Phil Karn's ``wwvsim``: second 0 carries an 800 ms
marker at the station's tick frequency, seconds 1 through 58 carry a 5 ms tick
each except second 29, and seconds 29 and 59 carry none. (On the hour the
marker moves to 1500 Hz, which falls outside both tick bands and so leaves
this template alone.)

WWV ticks at 1000 Hz and WWVH at 1200 Hz, so the two stations share this time
structure exactly. ONE template serves both: the band picks the station, not
the template. That is also why the template carries no tone -- a band envelope
has already discarded the carrier, and what survives is duration and position.
"""

from __future__ import annotations

import numpy as np

MARKER_MS = 800
TICK_MS = 5
SECONDS_PER_MINUTE = 60
# Second 29 is deliberately silent; second 59 is silent so the minute marker
# that follows it stands alone. Their ABSENCE carries as much information as a
# tick does, which is what makes a minute distinguishable from a second.
NO_TICK_SECONDS = frozenset({29, 59})


def minute_template(sample_rate: int) -> np.ndarray:
    """Unit-amplitude tick-band structure of one minute, at ``sample_rate``.

    Rates that do not divide 1000 are refused rather than rounded: a tick is
    5 ms wide, and rounding its edges would move the very feature this
    template exists to locate.
    """
    fs = int(sample_rate)
    if fs <= 0:
        raise ValueError(f"sample_rate {sample_rate!r} is not positive")
    if fs % 1000 != 0:
        raise ValueError(
            f"sample_rate {fs} does not divide 1000, so a 5 ms tick has no"
            " exact width here"
        )
    per_ms = fs // 1000
    out = np.zeros(SECONDS_PER_MINUTE * fs, dtype=np.float64)
    marker_end = MARKER_MS * per_ms
    out[0:marker_end] = 1.0
    tick_width = TICK_MS * per_ms
    for second in range(1, SECONDS_PER_MINUTE):
        if second in NO_TICK_SECONDS:
            continue
        start = second * fs
        end = start + tick_width
        out[start:end] = 1.0
    return out
