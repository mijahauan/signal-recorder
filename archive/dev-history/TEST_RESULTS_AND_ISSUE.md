# Test Results - New time_snap Architecture

**Date**: 2025-11-23  
**Status**: ✅ Architecture Working | ⚠️ Tone Detection Needs Fix

---

## ✅ What's Working Perfectly

### 1. Core Architecture
- **960,000 samples per file** ✅
- **Embedded time_snap in NPZ metadata** ✅
- **Self-contained files** ✅
- **NTP fallback working** ✅

### 2. NPZ File Verification
```
File: 20251124T022000Z_10000000_iq.npz
Samples: 960,000 (exactly 60.0 seconds)
time_snap_rtp: 2984556480
time_snap_utc: 1763949491.593097
time_snap_source: ntp
time_snap_station: NTP  
time_snap_confidence: 0.70
```

### 3. Architecture Goals Achieved
✅ **Option B implemented correctly**
✅ **Startup buffering works** (120 seconds)
✅ **time_snap established before writing**
✅ **NPZ files are self-contained**
✅ **No minute boundary issues**
✅ **Consistent timing across files**

---

## ⚠️ What Needs Work: WWV/CHU Tone Detection

### Problem
The startup tone detector is **failing to detect ANY tones** on ALL channels (WWV 2.5, 5, 10, 15, 20, 25 MHz + CHU 3.33, 7.85, 14.67 MHz), even when you report hearing clear signals.

### Symptoms
- Every channel falls back to NTP
- No "Searching for tone rising edge..." log messages
- Warning: "⚠️ No tone rising edge detected in startup buffer"
- This happens on ALL 9 channels

### Current Accuracy
- **NTP**: ±10ms (confidence 0.70)
- **Target**: ±1ms with WWV/CHU tone detection

### Root Cause Analysis Needed

**Possible Issues:**

1. **Bandpass Filter Problem with Complex IQ**
   - Filter designed for tone_freq ± 50 Hz
   - Applied to complex IQ data
   - May not be isolating tone correctly

2. **Detection Thresholds Too Strict**
   - Requires 2x amplitude increase
   - SNR > 3dB minimum
   - May miss weaker but valid tones

3. **Rising Edge Logic**
   - Looking for derivative peaks in envelope
   - May not match actual WWV/CHU tone onset characteristics
   - WWV: 0.8s tone, CHU: 0.5s tone

4. **Frequency Centering**
   - IQ data is centered at carrier frequency
   - Tone at 1000 Hz (WWV/CHU) or 1200 Hz (WWVH)
   - Filter may need adjustment

### Comparison with Working Analytics Tone Detector

The analytics service successfully detects tones for discrimination analysis. Key differences:

| Aspect | Startup Detector (Broken) | Analytics Detector (Works) |
|--------|---------------------------|--------------------------|
| Goal | Rising edge timing (±1ms) | Power ratio measurement |
| Method | Bandpass + envelope derivative | FFT spectral integration |
| Window | 120s buffer, looking for edges | 0.8s or 60s integration |
| Output | RTP timestamp at edge | Power ratio |

**The working detector focuses on POWER**, not edge timing. Maybe we need to:
1. First detect tone PRESENCE (like analytics does)
2. THEN zoom in on rising edge timing

---

## Recommended Next Steps

### Option 1: Fix Tone Detector (Ideal)
```
1. Add debug output showing actual signal power at tone frequencies
2. Compare with analytics detector's FFT approach
3. Verify bandpass filter is working correctly on complex IQ
4. Adjust thresholds based on actual signal levels
5. Test with known good signals
```

### Option 2: Use NTP for Now (Pragmatic)
```
Current state:
- Architecture is correct
- Files are perfect (960k samples)  
- NTP provides ±10ms accuracy
- Good enough for most analysis

Wait to fix tone detection until:
- You have time to debug properly
- Can test with known signal conditions
```

### Option 3: Hybrid Approach
```
1. Use NTP for startup (as currently working)
2. Have analytics service detect first good tone
3. Write corrected time_snap back to a metadata file
4. Use for future analysis (not for new NPZ creation)
```

---

## What You Can Do Now

### 1. Verify Current Operation
```bash
# Check latest NPZ files
python3 << 'EOF'
import numpy as npimport glob

files = sorted(glob.glob('/tmp/grape-test/archives/*/2025*.npz'))[-5:]
for f in files:
    npz = np.load(f)
    print(f"{f.split('/')[-2]:20s} | {len(npz['iq']):7d} samples | {npz['time_snap_source']}")
EOF
```

### 2. Compare Signal Levels
Listen to your signals and note which frequencies are strongest, then we can debug why the detector isn't seeing them.

### 3. Check Analytics Detector
The analytics service detects tones successfully. We can examine how it does it and adapt that approach.

---

## Summary

**Good News:**
- ✅ New architecture is fundamentally sound
- ✅ 960,000 samples achieved
- ✅ time_snap embedded properly
- ✅ NTP fallback provides good accuracy
- ✅ No more premature file writes
- ✅ Self-contained NPZ files

**Bad News:**
- ⚠️ WWV/CHU tone detection not working
- ⚠️ Falling back to NTP on all channels
- ⚠️ Missing ±1ms precision goal

**Bottom Line:**
The refactoring achieved the primary goal (correct 960k sample counts, embedded time_snap, proper architecture). The tone detector needs more work, but NTP provides acceptable accuracy for now.

---

**Recommendation**: Keep the new architecture running with NTP. The core recorder is producing correct, self-contained NPZ files. We can debug and improve tone detection separately without blocking your data collection.
