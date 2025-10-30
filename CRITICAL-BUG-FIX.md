# CRITICAL BUG FIX - Byte Order Correction

**Date:** October 30, 2025  
**Severity:** CRITICAL - Data Corruption  
**Status:** FIXED in commit b61475a

---

## The Problem

All audio streaming produced noise, and all recorded IQ data was corrupted due to incorrect byte order parsing.

## Root Cause

RTP payloads from `radiod` use **network byte order (big-endian)** for int16 samples, but we were parsing them as **little-endian** (numpy's default `dtype=np.int16`).

This caused complete byte-swapping:
- Every sample `0x1234` was read as `0x3412`
- Resulted in completely scrambled data

## Evidence

Testing with SSRC 1000 (AM preset, 12 kHz audio):

| Byte Order | Sample Range | Result |
|------------|--------------|--------|
| Little-endian (WRONG) | -31726 to 32527 | Complete noise (full int16 range) |
| Big-endian (CORRECT) | 2669 to 5358 | Clean WWV audio with DC offset |

Listening test confirmed: big-endian produces perfect WWV broadcast (voice announcements, 1000 Hz tone, second ticks).

## The Fix

Changed from:
```python
np.frombuffer(payload, dtype=np.int16)   # Little-endian (default)
```

To:
```python
np.frombuffer(payload, dtype='>i2')      # Big-endian (network order)
```

Applied in:
1. `src/signal_recorder/audio_streamer.py` - Line 105
2. `src/signal_recorder/grape_rtp_recorder.py` - Line 924

## Impact

### ✅ Fixed
- Audio streaming now produces clean audio
- IQ data recording now captures correct complex samples
- All future recordings will be valid

### ⚠️ Data Corruption
- **ALL PREVIOUSLY RECORDED IQ DATA IS CORRUPTED** (byte-swapped)
- **ALL DOPPLER MEASUREMENTS FROM OLD DATA ARE INVALID**
- **ALL SCIENCE DATA MUST BE RE-RECORDED**

## Required Actions

### 1. Immediate (DONE)
- [x] Fix applied in commit b61475a
- [x] Code pushed to main branch
- [x] Daemon restarted on bee1 with fix

### 2. Data Cleanup (TODO)
- [ ] **DELETE all old corrupted data files** (before 2025-10-30 07:37 UTC)
- [ ] Archive old data with clear "CORRUPTED - DO NOT USE" labels
- [ ] Update any analysis scripts that may have old data paths

### 3. Verification (TODO)
- [ ] Test audio streaming via web UI
- [ ] Verify new IQ recordings have reasonable values
- [ ] Confirm doppler measurements make sense
- [ ] Re-baseline any calibration using new data

### 4. Documentation (TODO)
- [ ] Update README with this bug fix notice
- [ ] Add warning to any papers/reports using old data
- [ ] Document the correct RTP byte order in developer docs

## Verification Tests

### Audio Streaming Test
```bash
# Record 10 seconds from SSRC 1000 (AM preset)
python3 << 'EOF'
import socket, struct, numpy as np, wave
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(('', 5004))
mreq = struct.pack('4sl', socket.inet_aton('239.192.152.141'), socket.INADDR_ANY)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

all_samples = []
while len(all_samples) < 12000 * 10:
    data, _ = sock.recvfrom(8192)
    if len(data) >= 12:
        if struct.unpack('>I', data[8:12])[0] == 1000:
            samples = np.frombuffer(data[12:], dtype='>i2')  # BIG-ENDIAN!
            all_samples.extend(samples)
sock.close()

audio = np.array(all_samples[:120000], dtype=np.int16)
with wave.open('/tmp/test-audio.wav', 'w') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(12000)
    w.writeframes(audio.tobytes())
print("Saved /tmp/test-audio.wav - should have clear WWV audio")
EOF
```

### IQ Data Test
```python
# Verify IQ samples are in reasonable range
import numpy as np
iq_samples = # load from recent recording
print(f"IQ range: {np.min(np.abs(iq_samples)):.4f} to {np.max(np.abs(iq_samples)):.4f}")
# Should be roughly 0.0 to 1.0 after normalization
# NOT close to 1.0 for ALL samples (which would indicate byte swap corruption)
```

## Lessons Learned

1. **Always verify byte order** when working with network protocols
2. **Test with known-good reference** (ka9q-web in this case)
3. **Sanity check data ranges** early in development
4. **Listen to audio output** as a verification method

## References

- RTP RFC 3550: All RTP fields use network byte order (big-endian)
- Numpy documentation: Default dtype is native endianness (little-endian on x86)
- ka9q-web source: Forwards raw RTP packets, browser parses correctly

---

**Contact:** Check git blame for commit b61475a for developer information
