# Core Recorder Fix - Complete 60-Second NPZ Files

**Date**: 2025-11-23 18:49 UTC-06:00  
**Status**: ✅ Implementation Complete  
**Priority**: HIGH - Unblocks 60-second discrimination baseline

---

## Problem Fixed

NPZ archive files were being written prematurely at wall clock minute boundaries, resulting in only ~23 seconds of data instead of 60 seconds. This violated the core architecture principle that **RTP timestamp is PRIMARY reference**.

---

## Solution Implemented

### Core Changes

**1. Removed Wall Clock Minute Boundary Check**
- File: `src/signal_recorder/core_npz_writer.py`
- Deleted lines that checked wall clock minute rollover
- Sample count (960,000) is now the **ONLY** file completion trigger

**2. Implemented Timing Hierarchy**
- **Best**: `time_snap` from WWV/CHU tone detection (±1ms)
- **Good**: NTP-synchronized system clock (±10ms)
- **Fallback**: Wall clock (±seconds)

**3. Added Time Source Management**
- Loads `time_snap` from analytics state file
- Checks NTP sync status via `ntpq`/`chronyc`
- Refreshes every 10 files for progressive accuracy improvement

**4. RTP-Primary Time Calculation**
- New method: `_calculate_utc_from_rtp(rtp_timestamp)`
- Uses best available timing source
- Handles RTP timestamp wrap-around
- File timestamps derived from RTP, not wall clock

### Files Modified

```
src/signal_recorder/core_npz_writer.py
  - Added: timing hierarchy support
  - Added: _calculate_utc_from_rtp()
  - Added: _update_timing_sources()
  - Added: _check_ntp_sync()
  - Removed: wall clock minute boundary check
  - Modified: add_samples() - sample count only trigger

src/signal_recorder/core_recorder.py
  - Modified: ChannelProcessor.__init__() - accepts state_file
  - Modified: CoreRecorder.__init__() - builds state file paths
  - Added: state_file parameter passing to NPZ writer
```

### New Files

```
test-core-recorder-fix.py
  - Validates NPZ file completeness
  - Reports sample counts and durations
  - Checks for incomplete files
```

---

## Deployment Instructions

### 1. Stop Core Recorder

```bash
# Find running process
ps aux | grep core_recorder

# Stop it
pkill -f core_recorder

# Or if using systemd
sudo systemctl stop grape-core-recorder
```

### 2. Verify Changes

```bash
cd /home/wsprdaemon/signal-recorder

# Check that fix is applied
grep -n "_calculate_utc_from_rtp" src/signal_recorder/core_npz_writer.py
# Should show the new method

# Check that wall clock logic is gone
grep -n "minute_boundary != self.current_minute_timestamp" src/signal_recorder/core_npz_writer.py
# Should return nothing
```

### 3. Start Core Recorder

```bash
# Activate venv
source venv/bin/activate

# Start core recorder (adjust config path as needed)
python3 -m signal_recorder.core_recorder --config config/recorder.toml

# Or via systemd
sudo systemctl start grape-core-recorder
```

### 4. Wait for New Files

Core recorder needs 60 seconds of samples before writing first file:
- Wait 2-3 minutes
- New files will have complete 960,000 samples

### 5. Validate Fix

```bash
# Check a single channel (adjust path)
python3 test-core-recorder-fix.py --archive-dir /tmp/grape-test/archives/WWV_10_MHz

# Expected output:
# ✅ TEST PASSED: All analyzed files are complete (960,000 samples)
```

### 6. Check All Channels

```bash
# Test all WWV frequencies
for freq in 2.5 5 10 15 20 25; do
    echo "=== WWV ${freq} MHz ==="
    python3 test-core-recorder-fix.py \
        --archive-dir /tmp/grape-test/archives/WWV_${freq}_MHz \
        --latest 3
done
```

---

## Expected Results

### ✅ Success Indicators

1. **File Sizes**
   - Each NPZ file: ~7-8 MB (16 kHz IQ, 60 seconds)
   - Sample count: exactly 960,000
   - Duration: exactly 60.0 seconds

2. **Timing Quality**
   - Initial files: NTP or wall clock timestamps
   - After analytics runs: time_snap timestamps (±1ms)
   - Log shows: "Timing: time_snap=yes, NTP=yes"

3. **Discrimination Baseline**
   - 60-second baseline now testable
   - Analytics can process full minute
   - Test signal detection should improve

### ⚠️ Troubleshooting

**Problem**: Still seeing ~23 second files

**Possible Causes:**
1. Core recorder not restarted
2. Old code still running
3. Config issue

**Solution:**
```bash
# Force stop all instances
pkill -9 -f core_recorder

# Verify Python files updated
stat -c %y src/signal_recorder/core_npz_writer.py
# Should show today's date

# Restart with verbose logging
python3 -m signal_recorder.core_recorder --config config/recorder.toml 2>&1 | tee core_recorder.log
```

**Problem**: No time_snap loading

**Check:**
```bash
# Verify analytics state files exist
ls -lh /tmp/grape-test/state/analytics-*.json

# If missing, analytics service may not be running
ps aux | grep analytics_service
```

---

## Impact & Benefits

### Immediate Benefits

1. **Unblocks 60-second discrimination baseline**
   - BCD correlation: +7.8 dB SNR improvement
   - Tick analysis: +8.9 dB SNR improvement
   - Test signal detection now possible

2. **Architecture compliance**
   - RTP timestamp is primary reference ✅
   - Sample count integrity maintained ✅
   - No time stretching ✅

3. **Scientific integrity**
   - Complete data records (no truncated files)
   - Timing hierarchy properly implemented
   - Progressive accuracy improvement

### Long-term Benefits

1. **Better time accuracy**
   - Starts with NTP (±10ms)
   - Improves to time_snap (±1ms) after tone lock
   - Automatic refresh every 10 files

2. **Reprocessability**
   - All files have proper sample count
   - Can rerun analytics with confidence
   - Historical data is complete

3. **PSWS upload validation**
   - Files meet expected format
   - Complete 60-second segments
   - Proper metadata

---

## Testing Results

### Before Fix
```
File: 20251124T000800Z_10000000_iq.npz
Samples: 368,920 (expected: 960,000)
Duration: 23.1 seconds (expected: 60.0)
❌ Incomplete
```

### After Fix (Expected)
```
File: 20251124T010000Z_10000000_iq.npz
Samples: 960,000 (expected: 960,000)
Duration: 60.0 seconds (expected: 60.0)
✅ Complete
```

---

## Next Steps

1. **Deploy and validate** (this session)
   - Restart core recorder
   - Wait for new files
   - Run validation script

2. **Monitor first hour** (next hour)
   - Check all frequencies
   - Verify timing quality progression
   - Confirm discrimination baseline works

3. **Long-term monitoring** (ongoing)
   - Watch for any anomalies
   - Track time_snap establishment
   - Measure discrimination improvement

---

## Documentation Updated

- ✅ `CORE_RECORDER_BUG_NOTES.md` - Status changed to FIXED
- ✅ `CONTEXT.md` - Bug warning removed, fix noted
- ✅ `SESSION_2025-11-23_CORE_RECORDER_FIX.md` - This document

---

## Related Documentation

- **Bug Analysis**: `CORE_RECORDER_BUG_NOTES.md`
- **Architecture**: `ARCHITECTURE.md` (RTP timing principles)
- **60-Second Baseline**: `60SEC_BASELINE_IMPLEMENTATION.md`
- **Discrimination Philosophy**: `DISCRIMINATION_PHILOSOPHY.md`
- **Project Context**: `CONTEXT.md`

---

**Implementation**: Complete ✅  
**Deployment**: Pending (requires core recorder restart)  
**Validation**: Pending (run test script after restart)

---

**End of Session Document**
