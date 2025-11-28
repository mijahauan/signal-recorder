# Tone Detection: Startup vs Analytics

## Summary of Implementation

### Startup Tone Detector (NEW - Fixed!)
**Purpose**: Establish time_snap and capture initial tone measurements  
**Timing**: Runs once at core recorder startup (120-second buffer)  
**Method**: Matched filtering (same as analytics)

**What it provides:**
1. ✅ **time_snap** - Precise timing reference from WWV/CHU tone
2. ✅ **tone_power_1000_hz_db** - WWV/CHU 1000 Hz power  
3. ✅ **tone_power_1200_hz_db** - WWVH 1200 Hz power
4. ⚠️ **wwvh_differential_delay_ms** - Usually 0.0 at startup

**Why differential delay is 0.0 at startup:**
- 120-second buffer contains ~120 different second marks
- WWV and WWVH alternate seconds on shared frequencies
- Strongest peaks often from DIFFERENT seconds → 5+ second difference!
- Example: 1000 Hz at 51.9s, 1200 Hz at 57.4s → 5.4s apart → different seconds
- **Solution**: Only calculate if peaks within 1.5 seconds (same second mark)
- **Result**: Usually 0.0 at startup (no simultaneous detections in random buffer)

### Analytics Tone Detector (Existing - Working!)
**Purpose**: Per-minute discrimination and propagation analysis  
**Timing**: Runs every minute on 60-second NPZ files  
**Method**: Same matched filtering

**What it provides:**
1. ✅ **Differential delay** - Accurate measurement from simultaneous tones
2. ✅ **Per-minute trends** - Track propagation changes over time
3. ✅ **Discrimination** - WWV vs WWVH using multiple signals

**Why analytics gets good differential delay:**
- Processes ONE minute at a time
- Looks for tones at THE SAME second boundary (minute :00)
- When both WWV and WWVH transmit together → true differential delay
- Typical values: ±1-20 ms (physically reasonable)

---

## Data Flow

```
┌─────────────────────────────┐
│  Core Recorder Startup      │
│  (120-second buffer)         │
└─────────────┬───────────────┘
              │
              ├──> time_snap (WWV/CHU)
              ├──> tone_power_1000_hz_db (WWV strength)
              ├──> tone_power_1200_hz_db (WWVH strength)
              └──> wwvh_differential_delay_ms (usually 0.0)
              │
              ▼
┌─────────────────────────────┐
│  NPZ File Metadata          │
│  (embedded in every file)   │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Analytics Service          │
│  (per-minute processing)    │
└─────────────┬───────────────┘
              │
              ├──> Reads tone_power_* from NPZ (no re-detection!)
              ├──> Detects tones at minute boundary
              ├──> Calculates TRUE differential delay (simultaneous)
              └──> Discrimination analysis (WWV vs WWVH)
```

---

## Key Insight

**Startup detector**: Provides tone POWERS for analytics efficiency  
**Analytics detector**: Provides TIMING (differential delay) for science

Both use the same matched filtering, but:
- Startup: Strongest peak across 120 seconds → great for time_snap
- Analytics: Expected peak at :00.0 boundary → great for differential delay

**Result**: No wasted computation, complementary measurements! 🎉

---

## Example Data

### Startup (120-second buffer):
```
tone_power_1000_hz_db = 35.4 dB  ← Strong WWV
tone_power_1200_hz_db = 20.9 dB  ← Moderate WWVH  
wwvh_differential_delay_ms = 0.0 ← Tones 5.4s apart (different seconds)
```

### Analytics (per minute at :00 boundary):
```
Minute 12:00:
  WWV detected: 35.2 dB, time = :00.003
  WWVH detected: 21.1 dB, time = :00.008
  Differential delay = +5.0 ms  ← WWVH 5ms after WWV (valid!)

Minute 12:01:
  WWVH only (WWV not transmitting this second)
  No differential delay

Minute 12:02:
  Both detected again
  Differential delay = +4.8 ms  ← Consistent with previous
```

---

## Conclusion

The 5-second "differential delay" at startup was correct behavior - it was detecting tones from different second marks! The fix now:
1. Only reports differential delay if tones within 1.5 seconds (same second)
2. Otherwise sets to 0.0 (no valid simultaneous measurement)
3. Analytics will calculate accurate differential delay from per-minute data

**No code change needed in analytics** - it already does this correctly! ✅
