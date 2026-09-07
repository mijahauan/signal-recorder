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

import math

import pytest

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


def test_pair_lateness_alone_keeps_the_epoch():
    """I3 (final review): 700 ms of GPS_TIME lateness is B4's measured pair
    skew, not a counter-space change.  The tracker used to open an epoch
    here -- and every spurious epoch throws the registration away.  Only a
    jump BELOW the running minimum (impossible within an epoch) or ABOVE it
    past COUNTER_EPOCH_SKEW_ALLOWANCE_S opens one now."""
    t = CounterEpochTracker()
    e1 = t.observe(1_000_000_000_000, 0, 24000)
    e2 = t.observe(1_000_000_000_000 + 10_000_000_000 + 700_000_000, 240_000, 24000)
    assert e2 == e1


def test_tracker_ignores_none_pair():
    """I1: a malformed pair (None, or anything non-int -- a
    present-but-null metadata field) must never raise; the tracker keeps
    whatever epoch it already holds."""
    t = CounterEpochTracker()
    assert t.observe(None, None, 24000) == "unregistered"
    assert t.epoch_id == "unregistered"
    eid = t.observe(1_000_000_000_000, 1_000_000, 24000)
    assert eid.startswith("ep-")
    # a later malformed observe leaves the epoch already held unchanged
    assert t.observe(None, 5, 24000) == eid
    assert t.observe(1_000_000_000_000, "not-an-int", 24000) == eid
    assert t.epoch_id == eid


# ── C1: epochs are compared by IMPLIED OFFSET, not by id string ───────


def test_two_trackers_on_one_mapping_agree_on_the_offset():
    """C1 (final review): metrology runs one process per channel, each with
    its own tracker sampling the ring's anchor at its own phase.  The id
    string is per-tracker and informational; ``epoch_offset_s`` is the
    quantity every channel in one physical epoch agrees on, and it is what
    ``fuse_registrations`` clusters by."""
    a = CounterEpochTracker()
    b = CounterEpochTracker()
    # one linear mapping, sampled 7 s apart by the two trackers
    a.observe(1_000_000_003_000_000_000, 3 * 24000, 24000)
    b.observe(1_000_000_010_000_000_000, 10 * 24000, 24000)
    assert a.epoch_offset_s == pytest.approx(b.epoch_offset_s, abs=1e-6)
    assert a.epoch_offset_s == pytest.approx(1_000_000_000.0, abs=1e-6)
    # the id is derived from the offset, so it is informational but stable
    assert a.epoch_id == f"ep-{int(a.epoch_offset_s)}"


def test_unregistered_tracker_has_nan_offset():
    t = CounterEpochTracker()
    assert math.isnan(t.epoch_offset_s)


# ── I3: B4's pair skew must not open spurious epochs ──────────────────


def _skewed(base_gps_ns, base_rtp, sr, seconds, skew_s):
    """A pair sampled ``seconds`` into the epoch, GPS_TIME late by skew_s."""
    return (
        base_gps_ns + int(seconds * 1e9) + int(skew_s * 1e9),
        base_rtp + seconds * sr,
        sr,
    )


def test_b4_scale_pair_skew_keeps_one_epoch():
    """I3: the pair is not atomic -- radiod samples GPS_TIME live and
    RTP_TIMESNAP from a cached block field, so consecutive samples are
    independent draws from a ONE-SIDED lateness distribution (232 ms on
    ND, 701-816 ms on B4).  A running minimum of the implied offset is
    the truest mapping, and lateness alone must never open an epoch: at
    B4's measured skew the old last-sample prediction opened one on the
    0 ms -> 816 ms step."""
    sr = 24000
    g0, r0 = 1_000_000_000_000, 1_000_000
    t = CounterEpochTracker()
    first = t.observe(g0, r0, sr)
    for k, skew in enumerate((0.816, 0.232, 0.05), start=1):
        assert t.observe(*_skewed(g0, r0, sr, 60 * k, skew)) == first
    # the running minimum stayed on the least-late pair
    assert t.epoch_offset_s == pytest.approx((g0 / 1e9) - r0 / sr, abs=1e-6)


def test_a_real_reanchor_still_opens_an_epoch():
    """I3: a genuine radiod re-anchor moves the mapping by hours.  Above
    the skew allowance it must still open a new epoch."""
    sr = 24000
    g0, r0 = 1_000_000_000_000, 1_000_000
    t = CounterEpochTracker()
    first = t.observe(g0, r0, sr)
    later = t.observe(*_skewed(g0, r0, sr, 60, 69732.0))
    assert later != first


def test_an_offset_below_the_running_minimum_opens_an_epoch():
    """I3: pair skew only makes GPS_TIME LATE, so an implied offset BELOW
    the running minimum by more than COUNTER_EPOCH_STEP_S cannot happen
    within one epoch -- it is a new counter space."""
    sr = 24000
    g0, r0 = 1_000_000_000_000, 1_000_000
    t = CounterEpochTracker()
    first = t.observe(g0, r0, sr)
    assert t.observe(*_skewed(g0, r0, sr, 60, -0.7)) != first


def test_rtp_wrap_does_not_open_an_epoch():
    """The recorder's wrap-safe delta arithmetic is preserved: the 32-bit
    RTP counter rolls every 2**32 samples (49.7 h at 24 kHz) without the
    counter SPACE changing."""
    sr = 24000
    r0 = 0x1_0000_0000 - 24000  # 1 s before the wrap
    g0 = 1_000_000_000_000
    t = CounterEpochTracker()
    first = t.observe(g0, r0, sr)
    after = t.observe(g0 + 2_000_000_000, (r0 + 2 * sr) & 0xFFFFFFFF, sr)
    assert after == first
