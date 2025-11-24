# Core Recorder Bug - Incomplete NPZ Files

**Date**: 2025-11-23  
**Priority**: HIGH  
**Status**: IDENTIFIED, NOT FIXED

---

## Problem Summary

NPZ archive files contain only ~23 seconds of data instead of the configured 60 seconds, blocking the 60-second discrimination baseline validation.

---

## Root Cause

**File**: `src/signal_recorder/core_npz_writer.py`  
**Lines**: 98-110

The `add_samples()` method has **two conflicting completion checks**:

### Check 1: Wall Clock Minute Boundary (BUGGY)
```python
wall_clock = datetime.now(tz=timezone.utc)
minute_boundary = wall_clock.replace(second=0, microsecond=0)

if self.current_minute_timestamp is not None and minute_boundary != self.current_minute_timestamp:
    # Minute complete - write it
    if len(self.current_minute_samples) > 0:
        file_path = self._write_minute_file()
```

**Problem**: Writes file immediately when wall clock minute changes, even if insufficient samples collected.

### Check 2: Sample Count (CORRECT)
```python
if len(self.current_minute_samples) >= self.samples_per_minute:
    # Trim to exactly one minute
    self.current_minute_samples = self.current_minute_samples[:self.samples_per_minute]
    file_path = self._write_minute_file()
```

**This check is correct** but never reached because Check 1 fires first.

---

## Evidence

### File Analysis
```bash
# 00:08 UTC file (test signal minute)
File: 20251124T000800Z_10000000_iq.npz
Samples: 368,920 (expected: 960,000)
Duration: 23.1 seconds (expected: 60.0)
Created: 00:09:00.811 UTC (< 1 second after minute rollover)
Packets rx: 2925 / 3000 expected
```

### Pattern
All recent files show consistent ~23 second duration:
```
00:07:  368,680 samples, 23.0s
00:08:  368,920 samples, 23.1s
00:09:  368,320 samples, 23.0s
00:10:  368,440 samples, 23.0s
```

### Why ~23 Seconds?
Unknown, but possibilities:
1. Recorder starts ~37 seconds into each minute
2. Stream timing relative to wall clock
3. Buffer timing issue

The exact mechanism doesn't matter - the fix is the same.

---

## Impact

### Immediate
- **60-second baseline untestable**: Discrimination code implemented but can't validate
- **Test signal detection fails**: Requires full 40-second signal
- **BCD correlation incomplete**: Needs full 60-second time code
- **Tick stacking reduced**: Only 23 ticks instead of 59

### Long-term
- Analytics expecting 60 seconds will fail
- Scientific integrity compromised (incomplete data)
- Upload to PSWS may fail validation
- Time-series analysis corrupted

---

## Solution

### Required Changes

**Remove the wall clock check entirely** (lines 98-110). The recorder should:

1. ✅ **Use RTP timestamp** as primary reference (already done)
2. ✅ **Accumulate samples** until `samples_per_minute` reached (already done)
3. ✅ **Write file** when sample count complete (already done)
4. ❌ **DO NOT** check wall clock minute boundaries
5. ✅ **Name file** using RTP timestamp converted to UTC (already done)

### Proposed Code Fix

**DELETE** lines 96-110:
```python
# Determine minute boundary
# Note: We use RTP timestamp as primary reference, but wall clock for file organization
wall_clock = datetime.now(tz=timezone.utc)
minute_boundary = wall_clock.replace(second=0, microsecond=0)

# Check for minute rollover
completed_minute = None
if self.current_minute_timestamp is not None and minute_boundary != self.current_minute_timestamp:
    # Minute complete - write it
    if len(self.current_minute_samples) > 0:
        file_path = self._write_minute_file()
        completed_minute = (self.current_minute_timestamp, file_path)
    
    # Reset for new minute
    self._reset_minute_buffer(minute_boundary, rtp_timestamp)
elif self.current_minute_timestamp is None:
    # First samples
    self._reset_minute_buffer(minute_boundary, rtp_timestamp)
```

**KEEP** lines 119-137 (sample count check) - this is correct.

### Initialization

The only place wall clock should be used is for **initial minute timestamp** when first samples arrive. This can remain as-is or use RTP timestamp converted to minute boundary.

---

## Testing Plan

### After Fix

1. **Restart core recorder**
2. **Wait 2 minutes** for new files
3. **Check file sizes**:
   ```bash
   python3 -c "
   import numpy as np
   file = '/tmp/grape-test/archives/WWV_10_MHz/[LATEST].npz'
   archive = np.load(file)
   print(f'Samples: {len(archive[\"iq\"])}')
   print(f'Expected: 960000')
   print(f'Duration: {len(archive[\"iq\"]) / 16000:.1f}s')
   "
   ```

4. **Validate**: Should see 960,000 samples (60.0 seconds)

### Discrimination Validation

Once core recorder fixed:
1. Wait for minute 8 or 44 (test signal)
2. Check test signal detection in CSV
3. Validate 60-second BCD correlation scores
4. Compare confidence levels vs historical 10-second windows

---

## Why This Wasn't Caught Earlier

### Development Path
1. Original recorder development focused on packet handling
2. Tests likely used short durations or didn't validate exact file length
3. Wall clock check seemed reasonable for "minute boundaries"
4. Sample count check (correct one) was added as fallback
5. In practice, wall clock always fires first

### Why It Matters Now
- **60-second discrimination baseline** requires full minute
- Previous 10-second analytics worked fine with partial minutes
- Test signal detection exposed the issue (needs 40+ seconds)
- Geographic ToA enhancement revealed timing precision needs

---

## Related Files

### Core Recorder
- `src/signal_recorder/core_recorder.py`: Calls NPZ writer
- `src/signal_recorder/core_npz_writer.py`: BUG HERE
- `src/signal_recorder/packet_resequencer.py`: RTP handling (OK)

### Analytics (Uses NPZ Files)
- `src/signal_recorder/analytics_service.py`: Expects 60 seconds
- `src/signal_recorder/wwvh_discrimination.py`: 60-second baseline implemented

### Documentation
- `CONTEXT.md`: Bug documented (lines 50)
- `60SEC_BASELINE_IMPLEMENTATION.md`: Expected performance
- `DISCRIMINATION_PHILOSOPHY.md`: Why 60 seconds matters

---

## Timing Architecture Reminder

From `CONTEXT.md`:

> **RTP timestamp is PRIMARY reference** - Never "stretch" time to fit wall clock

The core recorder violated this principle by using wall clock for minute boundaries. The fix realigns with the architecture:

- ✅ RTP timestamp primary
- ✅ Sample count integrity
- ✅ Write when data complete
- ❌ NO wall clock minute boundaries

---

## Next Session Checklist

- [ ] Review this document
- [ ] Read `core_npz_writer.py` lines 82-157
- [ ] Remove wall clock check (lines 96-110)
- [ ] Test with 2-3 minute capture
- [ ] Validate file sizes (960,000 samples each)
- [ ] Restart analytics services
- [ ] Wait for test signal (minute 8 or 44)
- [ ] Validate discrimination confidence improvement
- [ ] Update this document with results

---

**End of Bug Report**  
**Next Action**: Fix core recorder in dedicated session
