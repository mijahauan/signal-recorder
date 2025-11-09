# GRAPEChannelRecorder V1 - Archived Code

**Date Archived:** November 9, 2024  
**Reason:** Dead code with critical bug, replaced by V2

---

## Why This Was Archived

### The Problem

There were **two versions** of `GRAPEChannelRecorder` coexisting:

1. **V1** (this archive): Embedded in `grape_rtp_recorder.py` as `GRAPEChannelRecorder` class
2. **V2** (active): Separate file `grape_channel_recorder_v2.py` as `GRAPEChannelRecorderV2` class

### The Confusion

- **V1 was exported** in `__init__.py` but **never instantiated** - misleading API
- **V2 was used** in production but **not exported** - inconsistent
- Both existed simultaneously - maintainability nightmare

### The Critical Bug in V1

**Line 800-802 (grape_rtp_recorder.py):**
```python
# Note: Radiod reports 16 kHz sample rate, but that's for REAL samples (I+Q combined)
# For complex I/Q: 16 kHz real / 2 = 8 kHz complex samples
# Resampler: 8 kHz complex IQ → 10 Hz output (GRAPE standard)
self.resampler = Resampler(input_rate=8000, output_rate=10)
```

**This was WRONG.** The actual rate is:
- Radiod sends **16 kHz complex IQ** (not 16 kHz real)
- Each RTP packet contains 320 IQ pairs with timestamp increment of 320
- This was confirmed Nov 2024 and fixed in V2

**Impact:** WWV tone detection failed, all frequency-domain analysis was off

### What V2 Fixed

**grape_channel_recorder_v2.py (correct):**
- Uses 16 kHz complex IQ input rate
- Proper tone detection resampling (16k → 3k)
- Samples per minute: 960,000 (not 480,000)
- RTP timestamp increment: 320 per packet (not 160)

---

## Decision

**V1 was never used in production** - the `GRAPERecorderManager.start()` method (line 1770) always instantiates `GRAPEChannelRecorderV2`, not `GRAPEChannelRecorder`.

Therefore, V1 was archived to:
1. **Eliminate confusion** - single source of truth
2. **Prevent accidental use** - dead code with known bug
3. **Clean up API** - remove misleading export

---

## If You Need This Code

**Don't.** Use `GRAPEChannelRecorderV2` instead, which:
- Has the correct sample rate (16 kHz complex IQ)
- Is actively maintained and tested
- Has proper health monitoring integration
- Includes the 8 kHz bug fix from Nov 2024

If you absolutely need to reference V1 code, it's preserved here for historical purposes only.

---

## Cleanup Actions Taken

1. ✅ Removed `GRAPEChannelRecorder` class from `grape_rtp_recorder.py` (lines 768-1620)
2. ✅ Removed export from `src/signal_recorder/__init__.py`
3. ✅ Created this README to explain why
4. ✅ Verified V2 is the only implementation in use

**No code was instantiating V1** - verified by searching entire codebase for `GRAPEChannelRecorder(` calls.

---

## References

- **Bug fix commit:** Nov 3, 2024 - "8 kHz → 16 kHz complex IQ correction"
- **Memory:** CRITICAL BUG FIXED 2024-11-03 (see system memories)
- **V2 location:** `/src/signal_recorder/grape_channel_recorder_v2.py`
- **Used by:** `GRAPERecorderManager.start()` line 1770

---

**Status:** ARCHIVED - DO NOT USE
