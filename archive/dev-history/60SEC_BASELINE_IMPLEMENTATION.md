# 60-Second Baseline Implementation

## Summary

Implemented discrimination-first architecture with 60-second integration windows for maximum sensitivity.

**Date**: 2025-11-23  
**Status**: ✅ Active on all WWV frequencies (2.5, 5, 10, 15, 20, 25 MHz)  
**Next Test**: 00:08 UTC (WWV test signal, 3 minutes from deployment)

---

## Changes Made

### 1. BCD Correlation (100 Hz Analysis)

**Before**: 10-second windows, 3-second steps (~20 measurements/minute)
```python
window_seconds=10,
step_seconds=3,
```

**After**: 60-second window, single measurement per minute
```python
window_seconds=60,  # Full minute for maximum SNR
step_seconds=60,    # Non-overlapping (1 measurement per minute)
```

**Impact**:
- SNR improvement: √36 = **+7.8 dB** (6x better than 10-second)
- Integration: Full 60-second BCD time code
- Measurements: 1 per minute (down from ~20)
- Confidence: Expected significant improvement

**File**: `src/signal_recorder/wwvh_discrimination.py`
- Lines 987-1001: Updated docstring with discrimination-first philosophy
- Lines 1313-1324: Changed function call parameters to 60/60

### 2. Tick Analysis (Second-Tick Stacking)

**Before**: Six 10-second windows per minute (10 ticks each)
```python
window_seconds = 10
num_windows = 6
```

**After**: Single 60-second window (59 ticks)
```python
window_seconds: int = 60  # Parameter added
if window_seconds >= 60:
    num_windows = 1
    actual_window_seconds = 59  # Seconds 1-59
```

**Impact**:
- SNR improvement: √59 ≈ **+8.9 dB** (7.7x better than 10-second)
- Integration: 59 ticks vs 10 ticks
- Measurements: 1 per minute (down from 6)
- Phase coherence: Much better over full minute

**File**: `src/signal_recorder/wwvh_discrimination.py`
- Lines 662-701: Updated function signature and docstring
- Lines 727-757: Added conditional logic for 60s vs 10s windows
- Line 1438: Changed function call to `window_seconds=60`

### 3. Documentation

**Created**:
- `DISCRIMINATION_PHILOSOPHY.md`: Comprehensive rationale for confidence-first approach
- `60SEC_BASELINE_IMPLEMENTATION.md`: This file

**Updated**:
- Code docstrings emphasize discrimination-first philosophy
- Comments clarify that temporal resolution is secondary to confidence

---

## Technical Rationale

### SNR Improvement Calculations

**BCD Correlation**:
- 60 sec vs 10 sec: 10*log10(60/10) = 10*log10(6) = **+7.8 dB**
- Integration gain: √6 = 2.45x voltage improvement
- Critical for weak signals (0-3 dB range)

**Tick Stacking**:
- 60 sec (59 ticks) vs 10 sec (10 ticks): 10*log10(59/10) = **+7.7 dB**
- Integration gain: √5.9 = 2.43x voltage improvement
- Phase-aligned coherent stacking benefits more from longer windows

### Why This Matters

**At threshold SNR (3 dB)**:
- 10-second windows: Signal barely detectable, high uncertainty
- 60-second windows: 3 + 7.8 = **10.8 dB SNR**, confident detection

**Real-world impact**:
- Previous 23:08 test: Detection failed (confidence 0.15, threshold 0.20)
- Expected 00:08 test: Should succeed if signal present (7.8 dB boost)

---

## Expected Performance Improvements

### 1. Higher Confidence Scores

**BCD Correlation**:
- More samples → better statistics
- Longer window → better frequency resolution
- Single measurement → no conflicting results within minute

**Tick Analysis**:
- More ticks → better coherent integration
- Longer phase tracking → better WWV/WWVH separation
- Single measurement → cleaner discrimination

### 2. Better Method Agreement

**Problem with 10-second windows**:
- Window 1: "WWV dominant"
- Window 2: "WWVH dominant"  
- Window 3: "BALANCED"
- **Result**: Conflicting, must average or choose

**Solution with 60-second windows**:
- Single authoritative measurement per minute
- All three methods operate on same data
- Agreement or disagreement is clear

### 3. More Definitive Results

**Fewer "BALANCED" results**:
- Better SNR separates similar-strength stations
- Longer integration resolves ambiguity

**Fewer "NONE" results**:
- Weak signals become detectable
- Noise floor drops relative to signal

### 4. Test Signal Detection

**Previous failure mode**:
- 40-second test signal fragmented across 4+ windows
- Each fragment individually weak
- Correlation peaks diluted

**New approach**:
- Entire test signal in single 60-second window
- Full multi-tone sequence captured
- Full chirp pattern available
- Expected: **Much higher correlation scores**

---

## Validation Plan

### Immediate (00:08 UTC - 3 Minutes)

**Check test signal detection**:
```bash
# Monitor in real-time
tail -f /tmp/grape-test/logs/analytics-wwv*.log | grep -i "test signal\|✨"

# After 00:08, check results
for freq in 2.5 5 10 15; do
  echo "=== WWV $freq MHz ==="
  python3 -c "
import csv
with open('/tmp/grape-test/analytics/WWV_${freq}_MHz/discrimination/WWV_${freq}_MHz_discrimination_20251123.csv') as f:
    for row in csv.DictReader(f):
        if row['minute_number'] == '8' and '00:08' in row['timestamp_utc']:
            print(f\"  Detected: {row['test_signal_detected']}, Confidence: {row['test_signal_confidence']}\")
            print(f\"  Multitone: {row['test_signal_multitone_score']}, Chirp: {row['test_signal_chirp_score']}\")
            break
"
done
```

**Expected outcome**:
- At least one frequency should detect (confidence > 0.20)
- Best chance: 5 MHz (previously strongest WWV signal)
- Scores should be **significantly higher** than previous 23:08 attempt

### Short-term (Next Hour)

**Compare discrimination confidence**:
1. Check CSV for confidence levels
2. Count "high" vs "medium" vs "low" confidence results
3. Compare to historical data (if available)

**Method agreement**:
1. Check how often all three methods agree
2. Reduced "BALANCED" and "NONE" results
3. More consistent station identification

### Medium-term (Next 24 Hours)

**Performance metrics**:
- % of minutes with confident discrimination (>0.7)
- Average confidence score per frequency
- Test signal detection rate (2 opportunities per hour)
- Method agreement statistics

**By frequency analysis**:
- Which frequencies benefit most?
- Time-of-day propagation patterns
- Optimal frequencies for discrimination

---

## Logging Changes

### What to Look For

**Successful 60-second baseline**:
```
INFO: BCD correlation: 1 window (60.0s), WWV=X.X, WWVH=Y.Y, delay=Z.Zms, quality=Q.Q
INFO: Tick analysis - 1/1 windows valid, 1/1 coherent, avg ratio: ±X.XdB
```

**Compare to previous 10-second**:
```
INFO: BCD correlation: ~20 windows (10.0s), varying results
INFO: Tick analysis - X/6 windows valid, varying ratios
```

### Key Indicators

**Good performance**:
- ✅ BCD quality > 3.0 (vs previous < 2.0)
- ✅ Tick coherence quality > 0.5
- ✅ Methods agree on dominant station
- ✅ Consistent results across consecutive minutes

**Needs attention**:
- ⚠️ Still seeing "NONE" or "BALANCED" frequently
- ⚠️ Low quality scores despite longer integration
- ⚠️ Methods still disagree
- → May indicate: poor propagation, interference, or hardware issues

---

## Future Work (Not Yet Implemented)

### Phase 2: Adaptive Windowing

**After validating 60-second baseline**:
1. Add confidence tracking state machine
2. Implement progressive shortening (60→30→20→15→10)
3. Automatic reversion when confidence drops
4. Per-frequency adaptive parameters

**Not needed immediately**:
- Must establish that 60-second works first
- Need baseline metrics for comparison
- Adaptive logic is complex, requires validation

### Phase 3: Dashboard Integration

**Visualization**:
- Current window size indicator
- Confidence history graph
- Method agreement timeline
- Automatic adaptation events

### Phase 4: Machine Learning

**Advanced features**:
- Predict optimal window size from conditions
- Learn propagation patterns
- Forecast discrimination difficulty
- Proactive adaptation

---

## Rollback Plan

**If 60-second baseline performs worse**:

1. **Stop services**:
   ```bash
   pkill -f "analytics_service.*WWV"
   ```

2. **Revert code changes**:
   ```bash
   cd /home/wsprdaemon/signal-recorder
   git diff src/signal_recorder/wwvh_discrimination.py
   # Restore previous values: window_seconds=10, step_seconds=3
   ```

3. **Restart with 10-second windows**:
   ```bash
   # Edit lines 1320-1321 and 1438 back to original values
   # Restart services
   ```

**Rollback criteria**:
- Confidence scores consistently worse
- More "NONE"/"BALANCED" results
- Test signal detection worse than before
- User feedback indicates degraded performance

**Likelihood**: Very low - longer integration almost always improves discrimination

---

## Success Criteria

### Minimum Viable Success

- ✅ System runs without errors
- ✅ Generates one discrimination measurement per minute
- ✅ CSV files populated correctly
- ✅ No performance degradation vs 10-second

### Expected Success

- ✅ Higher confidence scores (>0.7 more often)
- ✅ Better method agreement
- ✅ Fewer uncertain results
- ✅ Test signal detection improvement

### Ideal Success

- ✅ >90% of minutes with high confidence
- ✅ Test signal detected consistently (when present)
- ✅ Clear discrimination even in marginal conditions
- ✅ Foundation proven for future adaptive windowing

---

## Current Status

**Deployment Time**: 00:02 UTC, 2025-11-23  
**Active Frequencies**: 2.5, 5, 10, 15, 20, 25 MHz  
**Services Running**: 6/6 ✅  
**Next Validation**: 00:08 UTC (WWV test signal)

**Changes Summary**:
- BCD: 10s → 60s windows (+7.8 dB SNR)
- Ticks: 10s → 60s windows (+8.9 dB SNR)
- Measurements: ~20/min → 1/min
- Philosophy: Granularity → Confidence

**Expected Impact**: Dramatic improvement in discrimination confidence, especially for weak signals and test signal detection.

---

**End of Implementation Document**
