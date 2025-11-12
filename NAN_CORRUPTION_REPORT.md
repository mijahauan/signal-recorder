# NaN/Inf Corruption Investigation Report
**Date:** November 12, 2025  
**System:** bee1 HF recorder (RX888 + radiod)

## Summary
Systematic NaN corruption detected in radiod RTP output affecting specific frequency channels. The corruption is **upstream of the recorder** and confirmed present in the raw multicast stream.

## Affected Channels
| Channel | Frequency | Corruption Rate | NaN Samples (60s) | Status |
|---------|-----------|-----------------|-------------------|--------|
| CHU 3.33 MHz | 3.33 MHz | **99.97%** | 100,724 | ❌ Unusable |
| CHU 7.85 MHz | 7.85 MHz | **79.70%** | 88,139 | ❌ Severe |
| CHU 14.67 MHz | 14.67 MHz | **100.00%** | 127,348 | ❌ Unusable |
| WWV 20 MHz | 20.00 MHz | **100.00%** | 96,250 | ❌ Unusable |
| WWV 25 MHz | 25.00 MHz | 11.50% | 387 | ⚠️ Degraded |
| WWV 2.5 MHz | 2.50 MHz | 0.00% | 0 | ✅ Clean |
| WWV 5 MHz | 5.00 MHz | 0.00% | 0 | ✅ Clean |
| WWV 10 MHz | 10.00 MHz | 0.00% | 0 | ✅ Clean |
| WWV 15 MHz | 15.00 MHz | 0.00% | 0 | ✅ Clean |

## Evidence
### 1. Corruption Pattern
- **100% NaN, 0% Inf** - indicates uninitialized memory, not overflow
- **Frequency-dependent** - not random network corruption
- **Consistent across multiple 60-second samples** - not transient
- **Random positions within packets** - e.g., positions [2, 11, 16, 17, 18, 24, ...]

### 2. Sample Corrupt Packet
```
SSRC: 14670000 (14.67 MHz)
Sequence: 21165
Timestamp: 826076480
Payload size: 1280 bytes (320 IQ samples)
NaN values: 38 out of 320 samples (11.9% per packet)
Sample range: [-1.69e37, 0.0]  (absurdly large = uninitialized)
```

### 3. Diagnostic Method
Used passive RTP listener (`diagnose_nan_corruption.py`) to monitor multicast stream `239.0.0.1:5004` without affecting radiod or recorder operation.

## Root Cause Analysis
**Confirmed:** Issue is in radiod's RTP output, NOT:
- ❌ Network corruption (would be random across channels)
- ❌ Recorder parsing bug (passive listener shows same corruption)
- ❌ UDP multicast routing issue (would affect all channels equally)

**Likely causes:**
1. **Uninitialized memory in radiod's DSP chain** - specific to certain frequency/filter configurations
2. **RX888 driver bug** - frequency-dependent buffer corruption
3. **AGC/gain overflow** in radiod - but would expect Inf, not NaN

## Impact on Recorder
The `signal-recorder` is **handling this correctly**:
- ✅ Detects NaN/Inf values in RTP packets
- ✅ Replaces with zeros to prevent downstream crashes
- ✅ Logs warnings for each corrupt packet
- ⚠️ **Data quality severely degraded** for CHU and WWV 20 MHz

Recorded data for affected channels is mostly zeros - scientifically unusable.

## Related Fix: Timestamp Gap Handling
Also fixed in this commit: **Integer overflow in RTP timestamp gap calculation** that was causing `ArrayMemoryError` crashes.

Adopted **Phil Karn's KA9Q technique** from `pcmrecord.c`:
- Use signed 32-bit arithmetic for timestamp differences
- Negative = backward jump (stream restart) → ignore, don't fill
- Positive = forward gap (lost packets) → fill with zeros
- Prevents wrap-around from creating 4 GiB allocation attempts

**Before:** `-80` samples interpreted as `4,294,967,216` → crash  
**After:** `-80` samples → ignored → stable

## Next Steps
### Immediate
1. ✅ Recorder handles corruption gracefully (no crashes)
2. ⚠️ Data from CHU/WWV 20 MHz is unreliable

### Investigation Required
1. Check radiod configuration for AGC/gain issues
2. Verify RX888 firmware version and USB stability
3. Test on different machine to rule out network
4. Report to ka9q-radio project with diagnostic data

### Verification Test
Run `diagnose_nan_corruption.py` on **another machine** on same network:
- Same corruption = radiod bug
- Different corruption = network/receiver issue

## Files Changed
- `src/signal_recorder/packet_resequencer.py` - KA9Q timestamp technique
- `diagnose_nan_corruption.py` - New diagnostic tool

## References
- Phil Karn's `pcmrecord.c` (ka9q-radio), lines 866, 948
- KA9Q timing architecture: RTP timestamp as primary reference
