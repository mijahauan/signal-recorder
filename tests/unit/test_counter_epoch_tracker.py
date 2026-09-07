"""CounterEpochTracker — the live-ring twin of the recorder's
``binary_archive_writer._note_counter_epoch`` (T3 self-registration,
spec §5: step on counter-epoch change).

The recorder holds one epoch tracker per channel across the process
lifetime; the live ring needs the same rule so an ``acquired`` origin
registered in one RTP counter space is voided the instant radiod (or
the recorder) re-adopts a pair from a different one.  These tests pin
the shared constant and the open/keep decision against the same pair
arithmetic the recorder already uses.
"""

from __future__ import annotations

from hf_timestd.core import binary_archive_writer
from hf_timestd.core.counter_epoch_tracker import (
    COUNTER_EPOCH_STEP_S,
    CounterEpochTracker,
)


def test_step_constant_matches_the_recorder():
    assert COUNTER_EPOCH_STEP_S == binary_archive_writer.COUNTER_EPOCH_STEP_S


def test_same_mapping_keeps_the_epoch():
    t = CounterEpochTracker()
    assert t.epoch_id == "unregistered"
    e1 = t.observe(1_000_000_000_000, 0, 24000)
    # 10 s later in RTP, GPS advanced 10 s + 40 ms skew: same epoch
    e2 = t.observe(1_000_000_000_000 + 10_040_000_000, 240_000, 24000)
    assert e1 == e2 == t.epoch_id


def test_pair_off_by_more_than_step_opens_a_new_epoch():
    t = CounterEpochTracker()
    e1 = t.observe(1_000_000_000_000, 0, 24000)
    e2 = t.observe(1_000_000_000_000 + 10_000_000_000 + 700_000_000, 240_000, 24000)
    assert e2 != e1
