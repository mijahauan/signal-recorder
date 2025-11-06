# Phase 2: WWV-based time_snap - COMPLETE

## Implementation Summary

**Date**: 2024-11-03
**Prerequisite**: Phase 1 (Resequencing Queue)
**Based on**: KA9Q-radio pcmrecord.c time_snap mechanism

## Changes Made

### 1. Added time_snap State Variables
**File**: `src/signal_recorder/grape_channel_recorder_v2.py`

```python
# Time snap reference (Phase 2: WWV-based timing)
self.time_snap_rtp = None       # RTP timestamp at snap point
self.time_snap_utc = None       # UTC time (seconds) at snap point
self.time_snap_established = False
self.time_snap_source = None    # "wwv_first", "wwv_verified", or "wwv_corrected"
```

### 2. Enhanced WWV Detection to Capture RTP Timestamps

**Added to tone buffer tracking**:
```python
self.tone_buffer_start_rtp = None  # RTP timestamp at buffer start
```

**Modified `_process_wwv_tone()` signature**:
```python
def _process_wwv_tone(self, unix_time: float, iq_samples: np.ndarray, rtp_timestamp: int)
```

**Detection result now includes**:
```python
{
    'detected': True,
    'timing_error_ms': -2.5,
    'onset_rtp_timestamp': 12345678,    # NEW: RTP ts of tone onset
    'onset_utc_time': 1762222800.0,      # NEW: UTC time of tone onset
    'snr_db': 20.0,
    'duration_ms': 800.0
}
```

### 3. Implemented time_snap Calculation

**Method**: `_calculate_sample_time(rtp_timestamp)`
- If `time_snap_established`: Uses KA9Q formula
  ```python
  utc_time = time_snap_utc + (rtp_ts - time_snap_rtp) / sample_rate
  ```
- Else: Falls back to `time.time()`

**Handles RTP wraparound**:
```python
delta_samples = (rtp_timestamp - time_snap_rtp) & 0xFFFFFFFF
if delta_samples > 0x7FFFFFFF:
    delta_samples = delta_samples - 0x100000000
```

### 4. WWV-based time_snap Establishment

**Method**: `_process_wwv_time_snap(wwv_result)`

**Algorithm**:
1. Get WWV tone onset (RTP timestamp + UTC time)
2. Round UTC time to nearest minute boundary (:00.000)
3. Account for timing error from detector
4. Calculate RTP timestamp that corresponds to minute boundary
5. Establish time_snap reference

**First Detection**:
```python
self.time_snap_rtp = onset_rtp - offset_samples
self.time_snap_utc = minute_boundary
self.time_snap_established = True
logger.info("⏱️  TIME_SNAP ESTABLISHED from WWV")
```

**Subsequent Detections**:
```python
predicted_utc = self._calculate_sample_time(onset_rtp)
drift_ms = (predicted_utc - actual_utc) * 1000

if abs(drift_ms) > 50.0:  # Re-establish if >50ms drift
    logger.warning("Large timing drift, re-establishing")
    # Update time_snap
else:
    logger.info(f"Timing verified: drift = {drift_ms:+.1f} ms")
```

## Benefits Achieved

✅ **Precise timing**: WWV rising edge provides sub-millisecond reference  
✅ **RTP ↔ UTC mapping**: Any RTP timestamp can be converted to UTC  
✅ **Drift detection**: Monitors clock drift via repeated WWV detections  
✅ **Self-correcting**: Re-establishes time_snap if drift exceeds threshold  
✅ **Dual purpose**: WWV serves both timing and propagation science

## How It Works

### Initial State (no time_snap)
```
RTP packets arrive → time = time.time() (approximate)
```

### After First WWV Detection
```
WWV detected at :00.000
  ├─ onset_rtp_timestamp = 12345678
  ├─ onset_utc_time = 1762222800.123
  └─ minute_boundary = 1762222800.000

time_snap established:
  ├─ time_snap_rtp = 12345678 - 1968  (offset correction)
  └─ time_snap_utc = 1762222800.000

Now all RTP timestamps → UTC:
  RTP 12347646 → UTC 1762222801.0  (:00.1 + 1 second)
  RTP 12349614 → UTC 1762222802.0  (:00.2 + 2 seconds)
```

### Ongoing Operation
```
Every WWV detection:
  1. Calculate what UTC time RTP predicts
  2. Compare with actual WWV onset time
  3. Log drift
  4. Re-establish if drift > 50ms
```

## Time Reconstruction Accuracy

**Sources of error**:
1. WWV detector timing resolution: ~1 ms
2. RTP timestamp quantization: 1/16000 s = 0.0625 ms
3. Resampling artifacts: < 0.1 ms

**Expected accuracy**: < 2 ms (excellent for HF propagation studies)

## Integration with Resequencing Queue

**Critical synergy**:
- Resequencing ensures correct RTP timestamp for each sample
- time_snap maps RTP timestamp to UTC
- Together: **every sample has precise UTC time**

**Example**: WWV tone detection
```
1. Reseq queue processes packets in order
2. WWV tone detected in sample buffer
3. onset_idx in 3 kHz buffer → converted to 16 kHz sample offset
4. RTP timestamp = buffer_start_rtp + offset
5. time_snap establishes RTP ↔ UTC mapping
6. All future samples have precise UTC time
```

## Testing Verification

1. **Initial establishment**: Watch for "⏱️  TIME_SNAP ESTABLISHED" log
2. **Drift monitoring**: Check "WWV timing verification: drift = X ms"
3. **Time accuracy**: Compare predicted vs actual WWV detections
4. **Multi-channel**: Each WWV channel establishes independent time_snap

## Expected Log Output

```
WWV_5_MHz: WWV tone detected! Timing error: -2.3 ms, RTP ts: 12345678
WWV_5_MHz: ⏱️  TIME_SNAP ESTABLISHED from WWV
  RTP timestamp 12343710 = UTC 00:00:00
  Timing error: -2.3 ms

[1 minute later]
WWV_5_MHz: WWV tone detected! Timing error: +1.8 ms, RTP ts: 13305678
WWV_5_MHz: WWV timing verification: drift = +0.5 ms
```

## Next Steps

1. **Test with live data**: Monitor overnight for timing stability
2. **Cross-validate**: Compare time_snap across multiple WWV channels
3. **Long-term stability**: Track drift over 24+ hours
4. **Documentation**: Update user guide with timing accuracy specs

## Files Modified

- `src/signal_recorder/grape_channel_recorder_v2.py`
  - Added time_snap state variables
  - Enhanced `_process_wwv_tone()` to capture RTP timestamps
  - Implemented `_calculate_sample_time()` with time_snap
  - Added `_process_wwv_time_snap()` for establishment/verification
  - Updated buffer trimming to track RTP timestamps

## References

- KA9Q-radio `/home/mjh/git/ka9q-radio/src/pcmrecord.c` line 607
- `docs/TIMING_ARCHITECTURE_V2.md` (design document)
- `docs/PHASE1_RESEQUENCING_COMPLETE.md` (prerequisite)

## Success Criteria

✅ Phase 1 (Resequencing) implemented  
✅ Phase 2 (time_snap) implemented  
🔄 Awaiting live testing with WWV detections  

**Status**: Implementation complete, ready for testing
