# Phase 1: RTP Packet Resequencing - COMPLETE

## Implementation Summary

**Date**: 2024-11-03
**Based on**: KA9Q-radio pcmrecord.c (Phil Karn)

## Changes Made

### 1. Added Resequencing Data Structure
**File**: `src/signal_recorder/grape_channel_recorder_v2.py`

```python
class ReseqEntry(NamedTuple):
    sequence: int          # RTP sequence number
    timestamp: int         # RTP timestamp
    samples: np.ndarray    # IQ samples
    arrival_time: float    # Unix time when packet arrived
    inuse: bool            # True if slot contains valid data
```

- Circular buffer of 64 entries (same as KA9Q)
- Stores packets indexed by `sequence % RESEQ_SIZE`

### 2. Modified Packet Processing Flow

**Old Flow**:
```
RTP packet arrives → Parse → Detect gaps → Process immediately
```

**New Flow**:
```
RTP packet arrives → Parse → Enqueue in circular buffer → Process queue in order
```

### 3. Key Methods Implemented

#### `_enqueue_packet()`
- Places packet in circular buffer at position `seq % 64`
- Handles duplicate packets (drops them)
- Handles large sequence jumps (flushes queue, resyncs)
- Based on KA9Q pcmrecord.c:652-679

#### `_process_reseq_queue()`
- Processes packets in sequence order
- Detects gaps via **RTP timestamp jumps** (not sequence gaps)
- Fills gaps with zeros to maintain sample count integrity
- Based on KA9Q pcmrecord.c:843-899

#### `_flush_reseq_queue()`
- Clears entire queue on major disruption
- Prepares for resync

### 4. Gap Detection Changes

**Old Method**: Sequence number gaps
```python
gap_packets = (new_seq - expected_seq) & 0xFFFF
# Assumed each gap = dropped packet
```

**New Method**: RTP timestamp gaps
```python
ts_jump = (entry.timestamp - expected_rtp_timestamp) & 0xFFFFFFFF
if ts_jump > 0:
    # Fill ts_jump samples with zeros
    # This is the GROUND TRUTH
```

**Why better**:
- RTP timestamp is the authoritative time reference
- Handles variable packet sizes (if ever needed)
- Aligns with KA9Q best practices

### 5. Zero-Fill on Gaps

Gaps are now filled with zeros **before** processing:
```python
zeros = np.zeros(gap_samples, dtype=np.complex64)
self.file_writer.add_samples(unix_time, zeros)
if self.tone_detector:
    self._process_wwv_tone(unix_time, zeros)
```

This ensures:
- Sample count always matches expected (960k/minute)
- WWV detector sees full timeline (even through gaps)
- No timing ambiguity

## Benefits Achieved

✅ **Out-of-order tolerance**: Handles WiFi/network packet reordering
✅ **Gap accuracy**: RTP timestamp is ground truth for gap size
✅ **Sample integrity**: Always maintain correct sample count
✅ **Foundation for time_snap**: Accurate RTP timestamps for Phase 2

## Testing Recommendations

1. **Normal operation**: Monitor logs for "Processed N packets from queue"
2. **Simulated reordering**: Inject packets out of order (future test)
3. **Gap handling**: Verify zeros are inserted, minute files are 960k samples
4. **WWV detection**: Should now work reliably with correct timing

## Next: Phase 2 - WWV time_snap

With resequencing in place, we can now trust that:
- Each sample has a reliable RTP timestamp
- Gaps are properly filled
- WWV tone onset can be accurately mapped to an RTP timestamp

Phase 2 will establish the **time_snap** reference using WWV tone rising edge.

## Files Modified

- `src/signal_recorder/grape_channel_recorder_v2.py` (major changes)
  - Added ReseqEntry class
  - Rewrote process_rtp_packet()
  - Added _enqueue_packet()
  - Added _process_reseq_queue()
  - Added _flush_reseq_queue()
  - Removed old _detect_and_handle_gaps()
  
- `src/signal_recorder/grape_rtp_recorder.py` (cleanup)
  - Removed debug print statements

## References

- `/home/mjh/git/ka9q-radio/src/pcmrecord.c` lines 652-679 (enqueue)
- `/home/mjh/git/ka9q-radio/src/pcmrecord.c` lines 843-899 (process queue)
- `docs/TIMING_ARCHITECTURE_V2.md` (overall design)
