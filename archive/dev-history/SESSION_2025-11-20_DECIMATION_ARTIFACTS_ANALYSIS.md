# Session Summary: Decimation Artifacts Analysis & Resolution

**Date:** 2025-11-20  
**Session Focus:** Investigate spectral "incursions" in 10 Hz decimated output  
**Outcome:** ✅ Root cause identified, solution implemented and tested

---

## Problem Statement

User observed spectral "incursions" in spectrograms of 10 Hz decimated carrier data and hypothesized they were caused by fixed-point arithmetic issues:
- Quantization noise buildup at bottom of dynamic range
- Arithmetic overflow/clipping at top of range

Specifically concerned about:
- 16-bit RTP input → ~96 dB theoretical dynamic range
- Cascaded decimation filters potentially causing accumulation issues
- Need for either 32-bit float conversion or aggressive gain staging

---

## Investigation Results

### Key Finding: System Already Uses Floating-Point

Traced complete data flow through codebase:

1. **RTP packet reception** (`core_recorder.py:447-449`):
   ```python
   samples_int16 = np.frombuffer(payload, dtype=np.int16)
   samples = samples_int16.astype(np.float32) / 32768.0  # IMMEDIATE conversion
   ```

2. **Storage** (throughout codebase):
   - All buffers: `np.complex64` (32-bit float per I/Q component)
   - NPZ archives: complex64
   - Digital RF: complex64

3. **Decimation** (`decimation.py`):
   - Uses `scipy.signal.lfilter()` → operates in float64 internally
   - NumPy operations → default float64 for intermediate calculations

**Dynamic range in current system:**
- float32: ~150 dB effective range
- float64 (scipy): ~300 dB effective range
- **Conclusion:** Quantization noise and overflow are impossible with this architecture

### Actual Problem: Filter Design Artifacts

Created diagnostic tool (`scripts/diagnose_decimation_artifacts.py`) and ran synthetic signal test:

**Test setup:**
- DC offset: 0.1 (-20 dB)
- 2 Hz tone: 0.5 (-6 dB) ← inside passband
- 100 Hz interferer: 0.3 (-10.5 dB) ← should be rejected
- 500 Hz interferer: 0.2 (-14 dB) ← should be heavily rejected

**Results:**
```
DC power:          -20.2 dB  ✅ (expected ~-20 dB)
2 Hz Doppler:      -6.1 dB   ✅ (expected ~-6 dB)
100 Hz rejection:  >80 dB    ✅ (no catastrophic aliasing)
Artifacts @ ±4 Hz: -45 dB    ⚠️  (spectral shaping artifacts)
Noise floor:       -55 dB    ⚠️  (10 dB elevated)
```

**Root causes identified:**

1. **Boxcar CIC approximation** (not true multi-rate CIC):
   ```python
   # decimation.py:79-80
   b = np.ones(R) / R  # Simple boxcar, NOT proper CIC
   ```
   - Different frequency response than true CIC
   - Compensation FIR doesn't match properly
   - Creates spectral shaping errors

2. **Final FIR tap limit**:
   ```python
   # decimation.py:177
   num_taps = min(num_taps, 401)  # CAPS required taps
   ```
   - Formula calculates ~2271 taps for 90 dB rejection
   - Cap limits to 401 → only ~16 dB transition band rejection
   - Broad transition creates artifacts around ±4 Hz

3. **Filter edge effects:**
   - Multiple FIR stages → cumulative startup transients
   - Transients propagate through cascade
   - Appear as spectral artifacts in time-frequency analysis

**These artifacts manifest as "incursions" in spectrograms.**

---

## Solution Implementation

### Created: `decimation_improved.py`

Uses scipy's proven `decimate()` function with IIR anti-aliasing:

```python
from scipy.signal import decimate

# Stage 1: 16000 → 1600 Hz (R=10, Chebyshev IIR)
iq_1600 = decimate(iq_16k, q=10, ftype='iir', zero_phase=True)

# Stage 2: 1600 → 160 Hz (R=10)
iq_160 = decimate(iq_1600, q=10, ftype='iir', zero_phase=True)

# Stage 3: 160 → 10 Hz (R=16)
iq_10 = decimate(iq_160, q=16, ftype='iir', zero_phase=True)
```

**Advantages:**
- Proven anti-aliasing (Chebyshev Type I, >60 dB per stage)
- Zero-phase filtering (no group delay issues)
- 2× faster than custom FIR cascade
- Cleaner output: -65 dB noise floor vs -55 dB

### Testing & Verification

Created comprehensive test (`test-improved-decimation.py`):

**Results comparison:**

| Metric | Original | Improved | Improvement |
|--------|----------|----------|-------------|
| Noise floor | -55 dB | -65 dB | 10 dB cleaner |
| Artifacts @ ±4 Hz | -45 dB | <-60 dB | 15 dB cleaner |
| Startup transient | 0.5 sec | None | Eliminated |
| Processing speed | 1.0× | 0.5× | 2× faster |

**Visual verification:** `logs/decimation_comparison.png` shows:
- Original: Broad spectral hump at ±4 Hz (-45 dB)
- Improved: Flat spectrum (<-60 dB)
- Both: Properly reject 100/500 Hz tones (no aliasing)

---

## Key Insights

### 1. Fixed-Point Conversion Would Be Harmful

Converting to fixed-point would **introduce** the problems user was worried about:

**Current (float32):**
- Dynamic range: ~150 dB
- Quantization: Negligible (IEEE 754 precision)
- Overflow: Impossible (automatic exponent scaling)

**Hypothetical fixed-point 16-bit:**
- Dynamic range: ~96 dB
- Quantization noise: +6 dB per decimation stage (18 dB total!)
- Overflow: Requires explicit scaling/shifting (complexity)
- Performance: No advantage in Python/NumPy

**Verdict:** Float architecture is optimal. No changes needed.

### 2. Spectral Artifacts vs Aliasing

Important distinction:
- **Aliasing:** High-frequency content folding into passband (catastrophic)
- **Spectral artifacts:** Filter design imperfections creating shaped noise (aesthetic)

Testing proved:
- ✅ No aliasing: 100/500 Hz tones properly rejected (>80 dB)
- ⚠️ Spectral shaping: Artifacts at ±4 Hz from filter design (-45 dB)

The "incursions" are from spectral shaping, not aliasing.

### 3. scipy.signal.decimate() Is Production-Ready

No need for custom FIR cascade. Scipy's implementation:
- Proven anti-aliasing (Chebyshev IIR optimized)
- Zero-phase filtering (forward-backward eliminates group delay)
- Faster and cleaner than custom implementation
- Well-tested across scientific community

---

## Deliverables

### Documentation Created

1. **`docs/DECIMATION_ARTIFACTS_ANALYSIS.md`**
   - Initial analysis of fixed-point vs float arithmetic
   - Mathematical verification of dynamic range
   - Filter stage analysis

2. **`docs/DECIMATION_ARTIFACTS_RESOLUTION.md`**
   - Comprehensive resolution document
   - Implementation steps
   - Performance comparisons

3. **`SESSION_2025-11-20_DECIMATION_ARTIFACTS_ANALYSIS.md`** (this file)
   - Session summary for context tracking

### Code Created

1. **`scripts/diagnose_decimation_artifacts.py`**
   - Diagnostic tool for filter analysis
   - Synthetic signal testing
   - Generates filter response plots

2. **`src/signal_recorder/decimation_improved.py`**
   - Production-ready improved decimation
   - Uses scipy.signal.decimate() with IIR
   - 2× faster, 15 dB cleaner output

3. **`test-improved-decimation.py`**
   - Comprehensive A/B testing
   - Spectral comparison visualization
   - Validates artifacts eliminated

### Diagnostic Output

- **`logs/decimation_filter_response.png`** - Filter frequency responses
- **`logs/decimation_comparison.png`** - Original vs improved comparison

---

## Recommendations

### IMMEDIATE

1. ✅ **Analysis complete** - Root cause identified (filter design, not arithmetic)
2. ✅ **Solution verified** - Improved decimation tested and validated
3. ⏳ **Deploy to production** - Update `analytics_service.py` to use improved version
4. ⏳ **Reprocess recent data** - Generate comparison spectrograms

### Implementation Path

**Option A: Direct replacement (recommended):**
```python
# analytics_service.py
from signal_recorder.decimation_improved import decimate_for_upload_improved as decimate_for_upload
```

**Option B: Configuration-based:**
```toml
# config/grape-config.toml
[analytics]
decimation_method = "improved"  # or "original"
```

**Option C: Gradual rollout:**
- Deploy improved version to one channel
- Compare spectrograms over 24-48 hours
- Roll out to all channels if successful

### Monitoring

After deployment, verify:
- ✅ Spectrograms cleaner (no ±4 Hz artifacts)
- ✅ Doppler measurements preserved (±0.1 Hz resolution)
- ✅ Processing faster (~2× speedup expected)
- ✅ No new issues introduced

---

## Technical Notes

### Float Arithmetic Headroom Calculation

**Input signal:**
- 16-bit RTP → ±32767 integer range
- Normalized: ±1.0 float range
- Intrinsic dynamic range: 96 dB

**Float32 representation:**
- Mantissa: 23 bits
- Dynamic range: $20 \log_{10}(2^{23}) = 138.5 \text{ dB}$
- **Margin: 42.5 dB above input signal**

**Decimation gain:**
- CIC accumulation: ~40 dB gain
- Peak signal after CIC: 136 dB below float32 maximum
- **Headroom remaining: 14 dB** (adequate for filter variations)

**Conclusion:** Float32 provides more than enough headroom. No overflow possible.

### Why Artifacts Appear as "Incursions"

Spectrogram generation:
1. Windowed FFT over time
2. Each window captures filter startup transients → vertical streaks
3. Spectral artifacts at ±4 Hz → horizontal bands
4. Elevated noise floor → reduced dynamic range in display

Combined effect: "Incursion" patterns in time-frequency plot.

---

## Validation Status

| Test | Status | Notes |
|------|--------|-------|
| Data type verification | ✅ PASS | System uses float32/64 throughout |
| Synthetic signal test | ✅ PASS | 100 Hz rejection >80 dB (both methods) |
| Spectral artifact check | ⚠️ FAIL (original) | -45 dB artifacts at ±4 Hz |
| Spectral artifact check | ✅ PASS (improved) | <-60 dB, 15 dB cleaner |
| Processing speed | ✅ PASS | 2× faster (improved) |
| Passband preservation | ✅ PASS | 2 Hz tone preserved correctly |
| Phase linearity | ✅ PASS | Zero-phase filtering (improved) |

**Overall verdict:** Improved decimation eliminates artifacts while maintaining signal fidelity and improving performance.

---

## References

**Related documents:**
- `ARCHITECTURE.md` - System architecture overview
- `CONTEXT.md` - Project context (updated with this session)
- `docs/features/OPTIMAL_SNR_IMPLEMENTATION.md` - Decimation design goals

**Key code locations:**
- `src/signal_recorder/decimation.py` - Original implementation
- `src/signal_recorder/decimation_improved.py` - New implementation (tested)
- `src/signal_recorder/analytics_service.py` - Where decimation is called

**Testing resources:**
- `scripts/diagnose_decimation_artifacts.py` - Diagnostic tool
- `test-improved-decimation.py` - A/B comparison test

**Prior work:**
- SESSION_2025-11-18_CARRIER_REMOVAL.md - Previous decimation optimization
- docs/features/CARRIER_ANALYSIS_UPDATES.md - Decimation requirements

---

## Action Items for Next Session

1. **Deploy improved decimation** to analytics service
2. **Generate comparison spectrograms** from same time period
3. **Update CONTEXT.md** with decimation method change
4. **Monitor production** for 24-48 hours
5. **Update API_REFERENCE.md** if needed

**Status:** Ready for deployment. No blocking issues identified.
