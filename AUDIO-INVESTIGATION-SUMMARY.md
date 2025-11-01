# Audio Choppiness Investigation Summary
**Date:** October 31, 2025  
**Status:** ❌ ROOT CAUSE NOT YET RESOLVED

---

## What We've Proven

### ✅ Working (Smooth Audio)
1. **test-simple-am-16k.wav** - Offline, all 5 seconds processed at once
2. **test-dc-removed-16k.wav** - Offline with DC removal  
3. **test-decimated-8k.wav** - Offline with decimation
4. **test-all-at-once.wav** - Offline normalization
5. **test-chunked.wav** - Offline but chunked (640 IQ samples/chunk)

### ❌ Not Working (Choppy)
1. **wwv-8khz-decimated.wav** - From test-8khz-audio.py using AudioStreamer
2. **realtime-test.wav** - From test-realtime-diagnostics.py using AudioStreamer

---

## Critical Finding

**The exact same chunking algorithm**:
- ✅ Works when applied offline to pre-captured IQ data
- ❌ Fails when used in real-time AudioStreamer class

**Processing is identical:**
```python
# Both use exactly this:
envelope = np.abs(iq_samples)  # 640 samples
audio = envelope * 0.5
audio_8k = audio[::2]  # Decimate to 320 samples
audio_int16 = (audio_8k * 32767).astype(np.int16)
```

---

## Tests Performed

### RTP Stream Quality
- ✅ **No packet loss**: Sequence numbers continuous
- ✅ **No timestamp gaps**: All packets have 320-sample timestamps
- ✅ **Consistent packet rate**: 50 packets/sec (every 20ms)

### Chunk Consistency  
- ✅ **All chunks same size**: 320 samples
- ✅ **No timing delays**: get_audio_chunk() returns instantly
- ✅ **No silence chunks**: Queue never empty during test

### Processing Algorithm
- Tried: Per-chunk normalization → choppy
- Tried: Fixed gain → choppy
- Tried: DC removal (per-chunk) → choppy
- Tried: DC removal (stateful) → choppy  
- Tried: No DC removal → **still choppy**
- Tried: Soft limiting (tanh) → choppy
- Tried: No limiting → choppy

---

## The Mystery

**Why does the same algorithm produce different results?**

| Aspect | Offline (works) | Real-time (choppy) |
|--------|----------------|-------------------|
| **Data source** | Pre-captured array | Live RTP packets |
| **Processing** | Identical code | Identical code |
| **Chunking** | 640 samples/chunk | 640 samples/chunk |
| **Threading** | Single thread | Background thread + queue |
| **Result** | ✅ Smooth | ❌ Choppy |

---

## Hypothesis

The problem is likely in **AudioStreamer's threading model**:

1. **Sample accumulator logic** (lines 137-155 in audio_streamer.py)
   - Accumulates samples from RTP packets
   - Triggers processing when >= 640 samples
   - Keeps remainder for next chunk
   
2. **Queue mechanism** (line 170)
   - Processed chunks added to Queue
   - Retrieved by get_audio_chunk()
   
3. **Possible issues:**
   - Race condition in accumulator?
   - Irregular timing of queue.put()?
   - Thread scheduling delays?
   - GIL contention?

---

## Visible Symptom

Audacity waveform shows **vertical discontinuities at regular ~40ms intervals** (chunk boundaries). This suggests:
- Amplitude jumps between chunks
- Or phase discontinuities
- Or timing gaps

But our tests show:
- ✅ Chunks are exactly 320 samples
- ✅ No timing gaps in retrieval
- ✅ RTP stream is continuous

---

## Next Steps to Consider

### Option 1: Detailed Chunk Analysis
Save actual chunk data and compare:
- Offline chunks vs Real-time chunks
- Look for differences in sample values at boundaries

### Option 2: Bypass AudioStreamer
Write audio directly from RTP receive loop without queue/threading

### Option 3: Different Approach
- Use a different audio library (sounddevice, pyaudio)
- Pre-buffer larger chunks (1 second instead of 40ms)
- Process in callback instead of queue

---

## Files for Reference

**Working offline tests:**
- `/tmp/test-simple-am-16k.wav` 
- `/tmp/test-chunked.wav`

**Choppy real-time:**
- `/tmp/realtime-test.wav`

**Test scripts:**
- `test-raw-iq.py` - Captures and processes offline
- `test-chunked-processing.py` - Proves chunking works offline
- `test-realtime-diagnostics.py` - Uses AudioStreamer (choppy)

---

*Last updated: 2025-10-31 10:07*  
*Current status: Investigating threading/queue as root cause*
