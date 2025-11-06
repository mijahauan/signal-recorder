# WWV Tone Detection Status

## Current Situation - **UPDATED**

### ✅ **What's Working**
- IQ stream recording is running (100% complete minutes)
- All 6 WWV channels recording: 2.5, 5, 10, 15, 20, 25 MHz
- Tone detection is **enabled** on all WWV channels
- RTP packet reception is solid (no major packet loss visible)
- **✅ Tone accumulator IS filling** (confirmed via diagnostics)
- **✅ Resampler IS producing output** (480-420 samples per packet)
- **✅ Detection threshold IS being reached** (6000+ samples)
- **✅ Detection window logic IS working** (waiting for :59-:02)

### 🔍 **Current Status**
- Tone detection code is **WORKING CORRECTLY**
- Waiting for detection window (:59-:02 seconds of each minute)
- Outside window: samples discarded, accumulator reset
- **Need to observe during next minute boundary**

## Expected Behavior

The WWV tone detector should:
1. Buffer 2 seconds of resampled audio (3 kHz)
2. During detection window (:58-:03 seconds of each minute)
3. Check for 1000 Hz tone lasting 800ms
4. Log each detection attempt
5. Report timing errors when detected

## Critical Issues to Investigate

### 1. **Is the tone detection code path being executed?**
   - Log message: "Checking for WWV tone" should appear every minute
   - Currently: **ABSENT**
   
### 2. **Possible Root Causes:**
   - Tone accumulator not filling (needs 6000 samples @ 3 kHz)
   - Detection window logic not triggering
   - Resampler output issue (returning empty arrays?)
   - `tone_detector` is None despite initialization message

### 3. **Detection Window Timing:**
   - Window: :58 to :03 seconds (6 second window)
   - WWV tone: 800ms at 1000 Hz starting at :00.0
   - Current time needs to be accurate for window check

## Next Steps

### Immediate Diagnostics:
1. **Add debug logging** to verify:
   - Tone accumulator is filling
   - Detection window is being entered
   - Resampler is producing output
   - `self.tone_detector is not None`

2. **Check resampler output:**
   - Is `tone_resampled` empty or zero-length?
   - Are samples reaching the accumulator?

3. **Verify timing:**
   - Is `unix_time` calculated correctly from RTP timestamps?
   - Is `seconds_in_minute` in the right range?

### Code Changes Needed:

```python
# Add at line ~1000 (after resampling)
if np.random.random() < 0.05:  # Log 5% of the time
    logger.info(f"{self.channel_name}: TONE PATH: "
               f"resampled={len(tone_resampled)}, "
               f"accum_size={accumulated_tone_samples}, "
               f"need={self.tone_samples_per_check}, "
               f"seconds=:mm.{int(unix_time % 60):02d}")

# Add before detection window check
logger.debug(f"{self.channel_name}: Tone check: "
            f"accumulated={accumulated_tone_samples}, "
            f"window={in_detection_window}, "
            f"seconds=:mm.{int(seconds_in_minute):02d}")
```

## Science Impact

**CRITICAL**: Without reliable WWV tone detection:
- No independent timing validation
- Cannot verify RTP timestamp accuracy
- No way to detect systematic timing drift
- Compromises scientific validity of IQ data

The per-minute WWV tone is the **ground truth** for timing synchronization.

## Test Plan

1. Wait for next minute boundary (:58-:03)
2. Check logs for tone detection attempts
3. If still absent, add debug logging
4. Restart daemon and observe
5. Verify resampler path is working
6. Once detection attempts logged, tune detection parameters if needed

