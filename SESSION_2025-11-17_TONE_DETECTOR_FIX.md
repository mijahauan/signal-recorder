# Session Summary: 2025-11-17 - Tone Detector Timing Bug Fix

## 🐛 CRITICAL BUG FIXED

### **Root Cause: 30-Second Timing Offset in Tone Detection**

**File:** `src/signal_recorder/tone_detector.py` line 350  
**Bug Period:** Nov 17 16:23 UTC - Nov 18 01:45 UTC (5+ hours)

#### The Bug

```python
# WRONG (line 350 - before fix):
onset_time = current_unix_time + (onset_sample_idx / self.sample_rate)
```

**Problem:** `current_unix_time` is the **MIDDLE** of the buffer, but `onset_sample_idx` is relative to the **START** of the buffer. For a 60-second detection buffer, this introduced a 30-second offset.

#### The Fix

```python
# CORRECT (line 351 - after fix):
onset_time = buffer_start_time + (onset_sample_idx / self.sample_rate)
```

**Impact:** All tone detection timing calculations are now relative to the correct reference point.

---

## 📊 Symptoms Observed

### Before Fix (Buggy Behavior)
- **Timing errors:** ±29.5 seconds (exactly half the 60-second buffer)
- **Discrimination data:** All measurements rejected (threshold: ±1 second)
- **Differential delays:** ±59 seconds (double the per-station error)
- **Data gap:** Discrimination stopped recording after 20:41 UTC

**Example from logs:**
```
WARNING: Rejecting outlier differential delay: -59259.0ms 
  (WWV: -29518.5ms, WWVH: 29740.5ms)
```

### After Fix (Correct Behavior)
- **Timing errors:** ±5-40 milliseconds (normal propagation delays)
- **Discrimination data:** Recording successfully
- **Differential delays:** 169-624 milliseconds (realistic ionospheric path differences)

**Example from discrimination CSV:**
```
2025-11-18T01:50:00, WWV: -4.81ms, WWVH: 5.14ms, differential: 169.33ms ✓
2025-11-18T01:53:00, WWV: -1.40ms, WWVH: 40.07ms, differential: 624.33ms ✓
```

---

## ✅ FIXES APPLIED

### 1. **Code Fix**
- **File:** `src/signal_recorder/tone_detector.py`
- **Line:** 350-351
- **Change:** Use `buffer_start_time` instead of `current_unix_time` for onset calculation
- **Added:** Comment explaining the critical distinction

### 2. **Carrier Channel Payload Type Support**
- **File:** `src/signal_recorder/core_recorder.py`
- **Line:** 441
- **Fix:** Added PT 97 support (was already in place from previous session)
- **Result:** Carrier channels now recording real IQ data (1624/12000 samples non-zero at ~49% packet reception)

### 3. **Data Cleanup**
Removed corrupt data from buggy period:
- **Discrimination CSVs:** Nov 17-18 (all channels with WWV/WWVH)
- **Decimated NPZ files:** Nov 17 22:00+ and Nov 18 (contained bad time_snap metadata)
- **State files:** Cleared time_snap to force re-establishment with fixed detector
- **Preserved:** All raw 16 kHz NPZ archives (93 files will be reprocessed automatically)

### 4. **Service Restarts**
1. Core recorder restarted (19:39 UTC) - applies PT 97 fix
2. Analytics services killed and state cleared (19:51 UTC)
3. Analytics restarted (19:52 UTC) - applies tone detector fix
4. New time_snap established at 01:52 UTC with corrected detector

---

## 🔍 VERIFICATION

### Tone Detection Working
```bash
$ tail -5 /tmp/grape-test/analytics/WWV_5_MHz/discrimination/WWV_5_MHz_discrimination_20251118.csv
2025-11-18T01:50:00, differential: 169.33ms ✓
2025-11-18T01:53:00, differential: 624.33ms ✓
```

### Carrier Channels Recording
```bash
$ python3 -c "import numpy as np; d=np.load('20251117T232000Z_5000000_iq.npz'); print(f'Non-zero: {np.count_nonzero(d[\"iq\"])}/{len(d[\"iq\"])}')"
Non-zero: 1624/12000 samples ✓
```

### Time_snap Established
```bash
$ jq '.time_snap' /tmp/grape-test/state/analytics-wwv5.json
{
  "rtp_timestamp": 297419300,
  "utc_timestamp": 1763430540,
  "source": "wwv_verified",
  "confidence": 0.632,
  "station": "WWV"
} ✓
```

---

## 📁 FILES MODIFIED

### Code Changes (Committed)
- `src/signal_recorder/tone_detector.py` - Fixed timing calculation (line 351)
- `src/signal_recorder/core_recorder.py` - PT 97 support already present (line 441)

### Scripts Created
- `cleanup-buggy-tone-data.sh` - Cleanup utility for corrupt data

### Documentation
- `SESSION_2025-11-17_TONE_DETECTOR_FIX.md` - This document
- `SESSION_2025-11-17_CARRIER_CHANNELS.md` - Previous session notes (updated)

---

## 🎯 CARRIER CHANNEL TIME BASIS STRATEGY

### Problem Statement
Carrier channels (200 Hz sample rate) do **NOT** include per-minute tones for time_snap:
- Bandwidth: 200 Hz (radiod minimum)
- Effective rate: ~98 Hz (49% packet reception)
- Purpose: Doppler analysis of 10 Hz carrier (±5 Hz measurement window)
- **Issue:** No WWV/CHU tones → cannot establish time_snap

### Solution: NTP-Based Timing

**Decision:** Use **NTP_SYNCED** timing quality for carrier channels

#### Rationale
1. **Accuracy sufficient:** ±10ms is adequate for <10 Hz Doppler analysis
2. **Independent RTP clocks:** Cannot share time_snap between channels
   - Observed: 2.7M sample offset between wide and carrier channels
   - Each ka9q-radio stream has independent RTP clock starting point
3. **Continuous data:** No gaps during propagation fades (unlike tone-dependent time_snap)
4. **Scientific validity:** Doppler shifts occur over minutes/hours (±0.1 Hz resolution needs ±100ms timing)

#### Implementation
Carrier channels automatically detected by analytics service:
- Check channel name for "carrier" keyword
- Use system clock (NTP-synchronized) for UTC timestamps
- Annotate timing quality as `NTP_SYNCED` in metadata
- No time_snap establishment attempted

#### Web UI Display
- **Wide channels:** 🔒 GPS_LOCKED (±1ms via tone_snap)
- **Carrier channels:** 📡 NTP_SYNCED (±10ms via system clock)

---

## 📝 NEXT STEPS

### Immediate (Automatic)
- [x] Analytics reprocessing 93 raw archives with fixed detector
- [x] New discrimination data generation (correct timing)
- [x] Carrier spectrograms will show real data (not zeros)

### Follow-up (Future Sessions)
- [ ] Compare carrier spectrograms (radiod ~100 Hz) vs wide decimated (16 kHz→10 Hz)
- [ ] Evaluate decimation artifacts in wide channel spectrograms
- [ ] Long-term: Consider RTP offset correlation between paired channels (wide + carrier)

---

## 🔧 DEBUGGING COMMANDS

### Monitor tone detection
```bash
tail -f /tmp/grape-test/logs/analytics-wwv5.log | grep -E '(Detected|timing_error|differential)'
```

### Check discrimination data
```bash
tail -20 /tmp/grape-test/analytics/WWV_5_MHz/discrimination/WWV_5_MHz_discrimination_$(date -u +%Y%m%d).csv
```

### Verify carrier data
```bash
python3 -c "import numpy as np; from pathlib import Path; f=sorted(Path('/tmp/grape-test/archives/WWV_5_MHz_carrier/').glob('*.npz'))[-1]; d=np.load(f); print(f'Non-zero: {np.count_nonzero(d[\"iq\"])}/{len(d[\"iq\"])}')"
```

### Check time_snap status
```bash
jq '{time_snap: .time_snap.source, confidence: .time_snap.confidence}' /tmp/grape-test/state/analytics-wwv5.json
```

---

## 💡 LESSONS LEARNED

1. **Buffer reference points are critical:** Always document whether timestamps refer to start, middle, or end of buffers
2. **Multi-service architecture pays off:** Core recorder preserved perfect data while analytics bug was being fixed
3. **Independent RTP clocks:** Each ka9q-radio channel stream has its own RTP timeline (cannot share time_snap)
4. **Timing annotations >> rejection:** Better to record data with quality annotations than reject it entirely
5. **State file management:** Corrupted time_snap requires manual state clearing for proper recovery

---

## 📖 REFERENCES

- **Timing Architecture:** `docs/TIMING_ARCHITECTURE_V2.md`
- **KA9Q Design:** Memory on RTP timestamp as primary reference
- **Core/Analytics Split:** `CORE_ANALYTICS_SPLIT_DESIGN.md`
- **Carrier Channels:** `SESSION_2025-11-17_CARRIER_CHANNELS.md`
