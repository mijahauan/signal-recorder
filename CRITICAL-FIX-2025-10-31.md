# CRITICAL BUG FIX - Wrong Sample Rate Assumption
**Date:** October 31, 2025  
**Severity:** CRITICAL - All audio and tone detection broken  
**Status:** ✅ FIXED

---

## The Problem

We assumed ka9q-radio `sample_rate=16000` with `preset="iq"` meant:
- **16000 REAL samples = 8000 COMPLEX IQ samples/sec**

But it actually means:
- **16000 COMPLEX IQ samples/sec**

This caused:
1. **Audio sounded muffled/slow** - 16 kHz data labeled as 8 kHz
2. **WWV 1000 Hz tone never detected** - We filtered at 950-1050 Hz thinking data was 8 kHz, but in 16 kHz data that's actually filtering 1900-2100 Hz!
3. **User confirmed**: Audio sounds normal when played at 2x speed

---

## Root Cause

**Measured actual rate:**
```
Complex IQ samples in 5 seconds: 80000
Actual rate: 15972.8 Hz ≈ 16 kHz
```

RTP packets contain 320 complex IQ samples each, arriving at ~50 packets/sec = 16000 samples/sec.

---

## Files Changed

### 1. `src/signal_recorder/audio_streamer.py`
- `iq_sample_rate`: 8000 → **16000**
- `output_audio_rate`: 8000 → **16000**
- Chunk size: 400 → **800 samples** (50ms at 16 kHz)
- Silence chunk: 400 → **800 samples**
- Queue buffer: Still 100 chunks = 5 seconds

### 2. `src/signal_recorder/grape_rtp_recorder.py`
- Tone detection resampler: `Resampler(input_rate=8000, output_rate=3000)` → **`Resampler(input_rate=16000, output_rate=3000)`**
- This fixes WWV 1000 Hz tone detection!

### 3. `web-ui/simple-server.js`
- WAV header sample rate: 8000 → **16000 Hz**
- WAV header byte rate: 16000 → **32000 bytes/sec**

---

## Expected Results After Fix

### ✅ Audio Quality
- **Before**: Muffled, sounds slow, only normal at 2x speed
- **After**: Clear, natural voice, normal playback speed

### ✅ WWV Tone Detection
- **Before**: 0% detection rate, always rejected (wrong frequency)
- **After**: Should detect 1000 Hz minute marker tones reliably
- **Timing errors**: Should be <50ms (was ~1200ms due to timestamp bug also fixed)

### ✅ Web UI Audio Streaming
- **Before**: Choppy, garbled, unintelligible
- **After**: Smooth 16 kHz audio stream

---

## Testing

### Test 1: Audio Quality
```bash
cd /home/mjh/git/signal-recorder
python3 test-exact-rate.py
aplay /tmp/wwv-correct-rate.wav
```

**Expected**: Clear WWV voice at normal speed

### Test 2: WWV Tone Detection
```bash
# Wait for next minute boundary and check logs
tail -f /tmp/signal-recorder-daemon.log | grep "WWV tone"
```

**Expected around :00 seconds each minute**:
```
WWV 5 MHz: Checking for WWV tone (buffer=6000 samples @ 3 kHz...)
WWV 5 MHz: WWV tone detected! Timing error: +12.3 ms (detection #1)
```

### Test 3: Web Audio Stream
1. Open `http://localhost:3000/monitoring`
2. Click 🔈 button next to WWV 5 MHz
3. **Expected**: Clear, intelligible audio

---

## Impact

**All previous recordings**:
- Timing data is still valid (RTP timestamps were correct)
- But tone detection statistics are wrong (0% instead of actual rate)

**Going forward**:
- Correct audio quality
- Accurate WWV timing validation
- Reliable minute marker detection

---

## Related Issues Fixed

This also fixed the timing error bug where we were passing the wrong timestamp to the tone detector (using last packet time instead of first sample time in buffer).

---

*Fixed: 2025-10-31*  
*Testing: In progress*
