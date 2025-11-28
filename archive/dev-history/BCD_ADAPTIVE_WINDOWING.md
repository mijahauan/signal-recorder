# BCD Adaptive Windowing Strategy

## Overview
The BCD cross-correlation uses **adaptive windowing** to optimize the trade-off between amplitude discrimination and temporal resolution based on real-time signal conditions.

## Sliding Window Mechanics

### Always Active:
- **Integration Window:** 10 seconds (default, adjustable)
- **Step Size:** 1 second
- **Overlap:** 90%
- **Result:** ~50 measurements per minute

### Example Timeline:
```
Window 1:  [0-10s]   → WWV amp, WWVH amp, delay, quality
Window 2:  [1-11s]   → WWV amp, WWVH amp, delay, quality
Window 3:  [2-12s]   → WWV amp, WWVH amp, delay, quality
...
Window 50: [49-59s]  → WWV amp, WWVH amp, delay, quality
```

Each window produces:
1. **WWV amplitude** (from correlation peak 1 height)
2. **WWVH amplitude** (from correlation peak 2 height)
3. **Differential delay** (peak separation in time)
4. **Quality** (correlation SNR)

---

## Adaptive Window Recommendations

The system analyzes the amplitude ratio and quality, then logs recommendations for optimal window sizing:

### Case 1: Similar Amplitudes (Hard to Discriminate)
**Condition:** WWV/WWVH amplitude difference < 3 dB

**Problem:** Signals are too similar to reliably separate

**Solution:** **EXPAND window to 15 seconds**
- Better SNR (15× vs 10×)
- Clearer peak separation in correlation
- More confident amplitude measurements

**Trade-off:** Fewer measurements (~40/minute instead of ~50)

**Log Message:**
```
Similar amplitudes (+1.2dB) - consider 15-second windows for better discrimination
```

---

### Case 2: One Station Dominant (Clear Winner)
**Condition:** WWV/WWVH amplitude difference > 10 dB

**Interpretation:** 
- One station much stronger (dominant path)
- OR one station disappeared (fading/dropout)

**Solution:** **TIGHTEN window to 5 seconds**
- Better temporal resolution for tracking dynamics
- Catch rapid fading events
- Higher data rate for the strong station

**Trade-off:** Lower SNR (5× vs 10×), but acceptable since signal is strong

**Log Message:**
```
One station dominant (+12.3dB) - consider 5-second windows for better resolution
```

---

### Case 3: Weak Signals (Poor SNR)
**Condition:** Quality metric < 3.0 (correlation SNR too low)

**Problem:** Both signals weak, hard to detect peaks

**Solution:** **EXPAND window to 15-20 seconds**
- Maximum SNR gain (approaching Tc limit)
- More reliable peak detection
- Trade temporal resolution for detection confidence

**Trade-off:** Slower updates (~12-40/minute)

**Log Message:**
```
Weak signals (quality=2.3) - consider 15-20 second windows for better SNR
```

---

## Window Size Guidelines

### Window Duration vs Performance:

| Window | SNR Gain | Measurements/min | Use Case |
|--------|----------|------------------|----------|
| 5s     | 5×       | ~55              | Dominant station, track fast fading |
| 10s    | 10×      | ~50              | **Default: balanced performance** |
| 15s    | 15×      | ~40              | Similar amplitudes, need discrimination |
| 20s    | 20×      | ~12              | Very weak signals, near Tc limit |

### Coherence Time Constraint (Tc):
- **HF Ionosphere:** Tc ≈ 15-20 seconds (typical)
- **Must stay below Tc** for coherent integration
- **Beyond 20s:** Correlation degrades (channel changes during integration)

---

## Implementation

### Current Behavior (Passive Recommendations):
The system **logs recommendations** but does **not automatically adjust**.

**Advantages:**
- Operator maintains control
- Clear reasoning in logs
- Can manually tune for specific conditions

**Usage:**
1. Run with default 10-second windows
2. Monitor logs for recommendations
3. Manually adjust `window_seconds` parameter if needed

### Example Log Output:
```
2025-11-19 20:00:01 INFO: WWV 10 MHz: BCD correlation (50 windows, 10s) - 
  WWV amp=8.3±1.2, WWVH amp=7.9±1.1, ratio=+0.4dB, delay=12.5±0.8ms, quality=5.2

2025-11-19 20:00:02 INFO: WWV 10 MHz: Similar amplitudes (+0.4dB) - 
  consider 15-second windows for better discrimination
```

---

## Manual Adjustment

### Reprocessing with Different Windows:

```bash
# Similar amplitudes - need discrimination
python3 scripts/reprocess_discrimination_timerange.py \
  --date 20251119 --channel "WWV 10 MHz" \
  --start-hour 12 --end-hour 16 \
  --bcd-window 15  # Expand to 15 seconds

# One station dominant - want resolution
python3 scripts/reprocess_discrimination_timerange.py \
  --date 20251119 --channel "WWV 10 MHz" \
  --start-hour 12 --end-hour 16 \
  --bcd-window 5   # Tighten to 5 seconds

# Weak signals - need SNR
python3 scripts/reprocess_discrimination_timerange.py \
  --date 20251119 --channel "WWV 10 MHz" \
  --start-hour 12 --end-hour 16 \
  --bcd-window 20  # Expand to 20 seconds (near Tc limit)
```

---

## Future Enhancement: Automatic Adaptation

**Potential Implementation:**
- Start each minute with 10s windows
- After first pass analysis, detect condition
- Reprocess minute with adjusted window
- Store both results (coarse + fine)

**Challenges:**
- 2× processing time per minute
- Real-time feasibility concerns
- Need to validate coherence time assumption

**Decision:** Keep passive recommendations for now. Automatic adaptation can be added later if needed.

---

## Signal Condition Examples

### Example A: Sunrise/Sunset (Changing Paths)
```
06:00 UTC: WWV +5 dB  → Stay at 10s (balanced)
06:15 UTC: WWV +1 dB  → Recommend 15s (similar)
06:30 UTC: WWV -2 dB  → Recommend 15s (similar)
06:45 UTC: WWVH +8 dB → Stay at 10s (moderate)
07:00 UTC: WWVH +15 dB → Recommend 5s (dominant)
```

### Example B: Station Dropout
```
14:00 UTC: WWV +3 dB  → Stay at 10s
14:15 UTC: WWV +8 dB  → Stay at 10s
14:30 UTC: WWV +12 dB → Recommend 5s (WWV dominant)
14:45 UTC: WWV only   → 5s for tracking (WWVH faded)
15:00 UTC: WWV +6 dB  → Back to 10s (WWVH returned)
```

### Example C: Weak Propagation
```
22:00 UTC: Quality 5.2 → Stay at 10s (good)
22:30 UTC: Quality 3.8 → Stay at 10s (acceptable)
23:00 UTC: Quality 2.1 → Recommend 15-20s (weak)
23:30 UTC: Quality 1.5 → Expand to 20s (very weak)
00:00 UTC: Quality 6.1 → Back to 10s (recovered)
```

---

## Summary

**Adaptive windowing provides intelligent recommendations based on:**
1. ✅ Amplitude discrimination needs (similar vs distinct)
2. ✅ Single vs dual station presence
3. ✅ Signal strength (SNR)
4. ✅ Temporal resolution requirements

**Result:** Operator can optimize for:
- **Amplitude accuracy** when discrimination is hard
- **Temporal resolution** when one station dominates
- **Detection confidence** when signals are weak

**All while staying within the HF coherence time constraint (Tc).**
