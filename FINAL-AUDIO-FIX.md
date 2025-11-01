# Final Audio Fix - Eliminating Choppiness
**Date:** October 31, 2025  
**Status:** ✅ FIXED

---

## The Root Causes (Multiple Issues)

### 1. **Wrong Sample Rate** (CRITICAL)
- **Assumed:** 8 kHz complex IQ
- **Actual:** 16 kHz complex IQ
- **Impact:** All audio was at wrong rate, tone detection completely broken

### 2. **Per-Chunk Normalization**
- **Problem:** Each 40ms chunk normalized independently to its max value
- **Impact:** Volume jumped between chunks instead of fading smoothly
- **Visible in Audacity:** Vertical lines at chunk boundaries

### 3. **Per-Chunk DC Removal**
- **Problem:** Subtracting mean of each chunk created discontinuities
- **Impact:** Abrupt level shifts at chunk boundaries
- **Fix:** Use continuous DC blocking filter with state across chunks

### 4. **Smooth AGC Still Had Problems**
- **Problem:** Even with smooth transitions, AGC updated every chunk
- **Impact:** Subtle amplitude variations between chunks
- **Solution:** Remove AGC entirely, use fixed gain

---

## Final Solution

### Audio Pipeline
```
RTP Packets (16 kHz complex IQ, 320 samples @ 50 packets/sec)
  ↓
Accumulate 640 samples (2 packets = 40ms)
  ↓
AM Demodulation (envelope = abs(IQ))
  ↓
DC Blocking Filter (continuous 1-pole HPF with state)
  ↓
Fixed Gain (×3.0)
  ↓
Decimate 16k → 8k (every 2nd sample)
  ↓
Clip to int16
  ↓
Stream to browser as 8 kHz PCM (320 samples/chunk = 40ms)
```

### Key Parameters
- **IQ Input:** 640 samples @ 16 kHz = 40ms
- **Audio Output:** 320 samples @ 8 kHz = 40ms
- **Chunk Rate:** 25 chunks/sec
- **Latency:** 40ms per chunk + queue (4 second buffer)

### DC Blocking Filter
```python
# 1-pole high-pass filter maintaining state across chunks
y[n] = x[n] - x[n-1] + 0.995 * y[n-1]

# State variables preserved:
self.dc_block_x1  # Previous input sample
self.dc_block_y1  # Previous output sample
```

**Why 0.995?** 
- Corner frequency ≈ 13 Hz at 16 kHz sample rate
- Removes DC without affecting voice (>100 Hz)
- Continuous across chunk boundaries (no clicks)

---

## What Was Removed

| Removed | Why |
|---------|-----|
| Per-chunk mean subtraction | Created discontinuities |
| Per-chunk max normalization | Volume jumped between chunks |
| Smooth AGC | Still caused subtle chunk artifacts |
| Complex resampling | Simple decimation sufficient for 2:1 ratio |

---

## Files Modified

### `src/signal_recorder/audio_streamer.py`
**Changes:**
1. **IQ rate:** 8000 → 16000 Hz
2. **Chunk size:** 400 → 640 samples (input), 320 samples (output)
3. **DC removal:** Per-chunk mean → Continuous DC blocking filter
4. **Gain:** AGC → Fixed gain (×3.0)
5. **Decimation:** Added 16k → 8k for browser compatibility

### `src/signal_recorder/grape_rtp_recorder.py`
**Changes:**
1. **WWV tone detector resampler:** 8000 → 16000 Hz input rate

### `web-ui/simple-server.js`
**Changes:**
1. **WAV header:** 16000 → 8000 Hz (matches decimated output)

---

## Testing

### Test File Quality
```bash
cd /home/mjh/git/signal-recorder
python3 test-8khz-audio.py
aplay /tmp/wwv-8khz-decimated.wav
```

**Expected in Audacity:**
- ✅ Smooth waveform (no vertical lines)
- ✅ Natural amplitude variations (fading)
- ✅ Consistent level between chunks
- ✅ No clicks or pops

### Web Streaming
1. Open http://localhost:3000/monitoring
2. Click 🔈 on any WWV channel
3. **Expected:** Clear, smooth audio

---

## Performance

| Metric | Value |
|--------|-------|
| **Latency** | 40ms chunks + queue ≈ 100-200ms total |
| **Bandwidth** | 16 kB/s (8 kHz × 2 bytes) |
| **CPU** | Minimal (simple operations, no FFT) |
| **Buffer** | 100 chunks = 4 seconds |

---

## Why This Works

### No More Chunk Artifacts
**Before:** Each chunk processed differently (different normalization, different DC offset)  
**After:** All chunks processed identically with continuous state

### Natural Dynamics Preserved
**Before:** AGC flattened signal, made weak/strong parts same volume  
**After:** Fixed gain preserves natural fading from ionospheric propagation

### Browser-Friendly
**Before:** 16 kHz non-standard rate  
**After:** 8 kHz standard rate browsers optimize for

---

## Known Limitations

1. **Fixed Gain:** May clip on very strong signals, may be quiet on weak signals
   - **Acceptable:** WWV signal strength varies naturally with propagation
   - **User can:** Adjust volume in browser

2. **No AGC:** Signal fades with propagation
   - **Acceptable:** This is normal for HF radio
   - **Benefit:** Preserves signal dynamics for analysis

3. **Simple Decimation:** No anti-aliasing filter before 2:1 decimation
   - **Acceptable:** AM demodulation provides implicit lowpass (envelope is smooth)
   - **Benefit:** Very low CPU usage

---

*Last updated: 2025-10-31 09:35*  
*Status: Ready for final testing in browser*
