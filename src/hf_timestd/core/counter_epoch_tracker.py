"""CounterEpochTracker — the live-ring twin of the recorder's
``binary_archive_writer._note_counter_epoch``.

radiod's (GPS_TIME, RTP_TIMESNAP) pair is re-adopted at every radiod or
recorder restart.  Within one counter space a new pair predicts the old
one to within the pair's skew (< COUNTER_EPOCH_STEP_S); a jump past that
means the RTP counter space itself changed, and every registration held
in the old RTP frame is void (T3 self-registration spec §5, "step on
counter-epoch change").

This tracker exists because the live ring (metrology_engine) needs the
same open/keep decision the recorder's archive writer already makes,
so an ``acquired`` origin (BufferTiming.origin_source) is discarded the
instant the epoch it was registered in closes.  The prediction
arithmetic — including RTP wrap handling — is copied verbatim from
``binary_archive_writer._note_counter_epoch`` so the two trackers never
disagree about where an epoch boundary falls.
"""

from __future__ import annotations

from typing import Optional, Tuple

# Same value as binary_archive_writer.COUNTER_EPOCH_STEP_S — pinned equal
# by test_counter_epoch_tracker.test_step_constant_matches_the_recorder.
COUNTER_EPOCH_STEP_S = 0.5


class CounterEpochTracker:
    """Live-ring twin of ``binary_archive_writer``'s per-channel epoch state."""

    def __init__(self) -> None:
        self._id: Optional[str] = None
        # (gps_time_ns, rtp_timesnap, sample_rate) of the pair in force.
        self._pair: Optional[Tuple[int, int, int]] = None

    @property
    def epoch_id(self) -> str:
        return self._id or "unregistered"

    def observe(self, gps_time_ns: int, rtp_timesnap: int, sample_rate: int) -> str:
        """Adopt a new (GPS_TIME, RTP_TIMESNAP) pair.

        Keeps the current epoch when the new pair's GPS time sits within
        COUNTER_EPOCH_STEP_S of the mapping already in force; otherwise
        opens a new epoch, named for the GPS time of its first pair.
        Returns the (possibly new) epoch id.
        """
        gps = int(gps_time_ns)
        rtp = int(rtp_timesnap)
        sr = int(sample_rate)
        prev = self._pair
        if prev is not None:
            p_gps, p_rtp, p_sr = prev
            delta = (rtp - p_rtp) & 0xFFFFFFFF
            if delta > 0x7FFFFFFF:
                delta -= 0x1_0000_0000
            predicted_ns = p_gps + 1_000_000_000 * delta // p_sr
            if abs(gps - predicted_ns) <= COUNTER_EPOCH_STEP_S * 1e9:
                self._pair = (gps, rtp, sr)
                return self.epoch_id
        self._pair = (gps, rtp, sr)
        self._id = f"ep-{gps}"
        return self._id
