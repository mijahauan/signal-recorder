"""Ring content written under a previous RTP numbering is unreadable.

AC0G-ND, 2026-09-10 23:18-23:20Z.  radiod restarted and re-based its RTP
counter (+27,963 s).  The core recorder restarted 50 s later and ADOPTED
the six SysV rings, which still held ~180 s of samples written under the
old numbering.  The fresh metrology processes bootstrapped two minutes
back from the ring head, into that content.  ``RingBufferReader`` maps a
sample index to RTP from the newest batch, ``(batch_rtp + (index -
batch_pos)) & 0xFFFFFFFF``; for content older than the new numbering the
bracket goes negative and the mask turns -2,051,110 into 4,292,916,186.
``RegistrationAcquirer`` registered SHARED_5000 on that minute
(``rtp_ref=4292916186``, verified), five siblings adopted it, and every raw
RTP subtraction downstream read 2**32/24000 = 178,956.97 s.

The ring knows when its numbering changes (it already warns on the RTP
discontinuity).  From now on it publishes the write-cursor position where
the current numbering began, and the reader refuses to serve anything
before it, exactly as it refuses an overwritten window.
"""
from __future__ import annotations

import uuid

import numpy as np
import pytest

pytest.importorskip("sysv_ipc")

from hf_timestd.core.ring_buffer import RingBuffer, HOT_RTP_BASE_CURSOR  # noqa: E402
from hf_timestd.core.ring_buffer_reader import (  # noqa: E402
    RingBufferBeforeBaseError,
    RingBufferOverrunError,
    RingBufferReader,
)

G0 = 1_400_000_000_000_000_000  # some GPS ns; only differences matter here


def _name() -> str:
    return f"TESTRB_{uuid.uuid4().hex[:12]}"


def _samples(n: int) -> np.ndarray:
    return np.zeros(n, dtype=np.complex64)


@pytest.fixture
def ring():
    buf = RingBuffer.create(_name(), sample_rate=1000, ring_seconds=2)
    yield buf
    try:
        buf.destroy()
    except Exception:
        pass


# ── the producer marks where the current numbering began ──────────────────

def test_continuous_writes_keep_the_base_at_zero(ring):
    ring.update_anchor(G0, 1_000_000)
    ring.write_samples(_samples(400), 1_000_000)
    ring.write_samples(_samples(400), 1_000_400)
    assert ring.rtp_base_cursor == 0


def test_a_small_forward_gap_is_not_a_rebase(ring):
    """Lost packets move RTP forward by the loss; under one second the
    ring keeps its history (the per-batch anchor already covers it)."""
    ring.update_anchor(G0, 1_000_000)
    ring.write_samples(_samples(400), 1_000_000)
    ring.write_samples(_samples(400), 1_000_500)   # 100 samples = 0.1 s lost
    assert ring.rtp_base_cursor == 0


def test_a_counter_rebase_moves_the_base_to_that_batch(ring):
    ring.update_anchor(G0, 1_000_000)
    ring.write_samples(_samples(1000), 1_000_000)
    # radiod restarted: new numbering starts near zero.
    ring.update_anchor(G0 + 1_000_000_000, 100)
    ring.write_samples(_samples(500), 100)
    assert ring.rtp_base_cursor == 1000
    assert int(ring._hot[HOT_RTP_BASE_CURSOR]) == 1000


def test_a_backward_step_of_one_second_is_a_rebase(ring):
    ring.update_anchor(G0, 1_000_000)
    ring.write_samples(_samples(500), 1_000_000)
    ring.write_samples(_samples(500), 1_000_500 - 1000)   # numbering moved back 1 s
    assert ring.rtp_base_cursor == 500


def test_adopting_producer_that_does_not_continue_the_numbering_sets_the_base(ring):
    ring.update_anchor(G0, 1_000_000)
    ring.write_samples(_samples(1000), 1_000_000)
    adopted = RingBuffer.create(ring.channel_name, sample_rate=1000, ring_seconds=2)
    adopted.update_anchor(G0 + 1_000_000_000, 100)
    adopted.write_samples(_samples(200), 100)
    assert adopted.rtp_base_cursor == 1000


def test_adopting_producer_that_continues_the_numbering_keeps_the_history(ring):
    ring.update_anchor(G0, 1_000_000)
    ring.write_samples(_samples(1000), 1_000_000)
    adopted = RingBuffer.create(ring.channel_name, sample_rate=1000, ring_seconds=2)
    adopted.update_anchor(G0, 1_000_000)
    adopted.write_samples(_samples(200), 1_001_000)      # exactly the next RTP
    assert adopted.rtp_base_cursor == 0


# ── the reader refuses content before the base ────────────────────────────

def test_reader_refuses_a_window_before_the_base_and_names_the_first_valid_utc(ring):
    ring.update_anchor(G0, 1_000_000)
    ring.write_samples(_samples(1000), 1_000_000)
    ring.update_anchor(G0 + 1_000_000_000, 100)
    ring.write_samples(_samples(500), 100)
    reader = RingBufferReader.attach(ring.channel_name)
    try:
        head = reader.head_utc()
        # 1.2 s before the head lies 0.7 s into the OLD numbering.
        with pytest.raises(RingBufferBeforeBaseError) as ei:
            reader.extract_interval(head - 1.2, 0.5)
        assert isinstance(ei.value, RingBufferOverrunError)   # the service's resync path
        first_valid = ei.value.first_valid_utc
        # The base sample (index 1000) is 0.5 s before the head.
        assert abs(first_valid - (head - 0.5)) < 1e-6
    finally:
        reader.close()


def test_reader_still_serves_a_window_inside_the_new_numbering(ring):
    ring.update_anchor(G0, 1_000_000)
    ring.write_samples(_samples(1000), 1_000_000)
    ring.update_anchor(G0 + 1_000_000_000, 100)
    ring.write_samples(_samples(500), 100)
    reader = RingBufferReader.attach(ring.channel_name)
    try:
        head = reader.head_utc()
        samples, meta = reader.extract_interval(head - 0.4, 0.3)
        assert samples.shape[0] == 300
        assert meta["start_rtp_timestamp"] == 200          # 100 + (1100 - 1000)
        assert meta["start_rtp_timestamp"] < 2**31         # never a masked negative
    finally:
        reader.close()


def test_the_field_reproduction_never_reaches_the_reader_metadata(ring):
    """The minute that poisoned ND: the new numbering had run 85 s; the
    reader was asked for a window 100 s further back.  At 1 kHz here the
    same shape in miniature.  Before the fix the metadata carried
    ``start_rtp_timestamp = 2**32 - 600``."""
    ring.update_anchor(G0, 4_000_000)
    ring.write_samples(_samples(1500), 4_000_000)
    ring.update_anchor(G0 + 1_500_000_000, 0)
    ring.write_samples(_samples(400), 0)
    reader = RingBufferReader.attach(ring.channel_name)
    try:
        head = reader.head_utc()
        with pytest.raises(RingBufferBeforeBaseError):
            reader.extract_interval(head - 1.0, 0.5)   # s_start=900 < base=1500
    finally:
        reader.close()


# ── the metrology service resyncs to the first valid minute ───────────────

def test_metrology_resync_jumps_to_the_first_valid_minute():
    from hf_timestd.core.metrology_service import resync_minute_after
    # Base at 23:18:43.5; head five minutes later.  The plain overrun rule
    # (head - 2 min = 23:21:00) and the base rule (23:19:00) must differ
    # here, or this test proves nothing.
    base = 1_789_082_323.5          # 2026-09-10T23:18:43.5Z
    head = 1_789_082_640.0          # 23:24:00
    exc = RingBufferBeforeBaseError("x", first_valid_utc=base)
    assert resync_minute_after(exc, head_utc=head, jump_min=2) == 1_789_082_340   # 23:19:00
    plain = RingBufferOverrunError("overwritten")
    assert resync_minute_after(plain, head_utc=head, jump_min=2) == 1_789_082_520  # 23:22:00
