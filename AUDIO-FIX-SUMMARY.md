# Audio Streaming Fix - Complete Summary
**Date:** October 31, 2025  
**Status:** ✅ FIXED - Ready for testing

---

## The Root Cause

**Original assumption:** ka9q `sample_rate=16000` with `preset='iq'` means "16k real = 8k complex IQ"  
**Reality:** It means **16k complex IQ samples/sec**

This 2x rate error broke everything.

---

## The Fix - Two Parts

### Part 1: Correct IQ Processing (16 kHz)
**Files changed:**
- `audio_streamer.py` - Now correctly processes 16 kHz IQ
- `grape_rtp_recorder.py` - WWV tone detector resamples 16k → 3k

### Part 2: Browser Compatibility (Decimate to 8 kHz)
**Why?** Browsers handle standard sample rates (8k, 44.1k, 48k) better for real-time streaming.

**How?** 
- Demodulate at 16 kHz
- Decimate to 8 kHz (take every 2nd sample)
- Stream 8 kHz to browser

**Result:**
- 50% less bandwidth
- Smoother browser playback
- Standard 8 kHz WAV format

---

## Technical Details

### Audio Pipeline
```
RTP (16 kHz complex IQ)
  ↓
Demodulate to 16 kHz real audio
  ↓
Decimate to 8 kHz (::2)
  ↓
Stream to browser as 8 kHz PCM
```

### Chunk Sizes
- **IQ input**: 800 samples @ 16 kHz = 50ms
- **Audio output**: 400 samples @ 8 kHz = 50ms
- **Queue**: 100 chunks = 5 seconds buffer

---

## Files Modified

| File | Change |
|------|--------|
| `audio_streamer.py` | 16k IQ processing + 8k decimation |
| `grape_rtp_recorder.py` | Tone detector: 16k → 3k resampling |
| `simple-server.js` | WAV header: 8 kHz sample rate |

---

## Testing

### ✅ Test 1: Direct 8 kHz Audio
```bash
cd /home/mjh/git/signal-recorder
python3 test-8khz-audio.py
aplay /tmp/wwv-8khz-decimated.wav
```

**Expected:** Clear WWV audio (this is exactly what the browser receives)

**Result:** ✓ Working - 5 seconds of clean 8 kHz audio captured

### 🔄 Test 2: Web Streaming
1. Refresh browser: http://localhost:3000/monitoring
2. Click 🔈 button on any WWV channel
3. **Expected:** Smooth, intelligible audio

**Instructions:**
- If still choppy, try different browser (Chrome/Firefox handle audio differently)
- Check browser console (F12) for errors
- Check Network tab to verify audio is streaming

---

## Why This Should Fix Choppiness

| Issue | Before | After |
|-------|--------|-------|
| **Sample rate** | 16 kHz (non-standard) | 8 kHz (standard) |
| **Bandwidth** | 32 kB/s | 16 kB/s (50% less) |
| **Browser buffering** | Difficult | Easy (standard rate) |
| **Chunk timing** | 50ms @ 16k (800 samples) | 50ms @ 8k (400 samples) |

---

## WWV Tone Detection Status

**Still being tuned** - The 16 kHz fix enables proper detection, but we're seeing rejections:
- Envelope levels low (0.01-0.04)
- Detected durations too short (0.004-0.041s vs needed 0.5-1.2s)

**Possible causes:**
1. Signal weak at this time
2. Tone not present or intermittent
3. Threshold needs adjustment

**Next steps for tone detection:**
- Capture audio during minute boundary with `python3 capture-minute-tone.py`
- Listen for actual tone presence
- Adjust detector threshold if tone is present but weak

---

## Key Insight

**Your observation:** "Sounds normal at 2x speed"

This was THE critical clue that revealed the 2x sample rate error!

---

*Last updated: 2025-10-31 09:25*  
*Web UI restarted with 8 kHz fix - ready to test*
