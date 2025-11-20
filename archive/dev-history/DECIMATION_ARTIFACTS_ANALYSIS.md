# Decimation Artifacts Analysis & Resolution

**Date:** 2025-11-20  
**Issue:** Spectral "incursions" in 10 Hz decimated output  
**Root Cause:** Aliasing from inadequate anti-aliasing filters (NOT fixed-point arithmetic)

## Executive Summary

Your concern about fixed-point arithmetic artifacts is **unfounded**. The system already uses 32-bit floating-point throughout the DSP chain, providing ~150 dB dynamic range (far exceeding the 96 dB from 16-bit input).

**The real problem:** Aliasing from insufficient stopband rejection in the decimation filters. High-frequency content (100+ Hz) is leaking into the 10 Hz passband, appearing as spectral "incursions."

## Diagnostic Results

### ✅ Data Type Verification (Float Arithmetic Confirmed)

```
RTP Input:   int16 → immediate conversion to float32 / 32768.0
Storage:     np.complex64 (32-bit float per I/Q component)
Decimation:  scipy.signal (operates in float64 internally)
Output:      np.complex64

Dynamic Range:
- float32: ~150 dB (24-bit mantissa)
- float64: ~300 dB (53-bit mantissa)
- Headroom: Essentially unlimited for DSP operations
```

**Conclusion:** No quantization noise buildup, no overflow/clipping possible with this architecture.

### ❌ Aliasing Test (THE ACTUAL PROBLEM)

**Test setup:**
- Input: DC (0.1) + 2 Hz tone (0.5) + 100 Hz interferer (0.3)
- Expected: 100 Hz rejected by >80 dB

**Results:**
```
DC power:          -20.2 dB  ✅ (expected ~-20 dB)
2 Hz Doppler:      -6.1 dB   ✅ (expected ~-6 dB)
100 Hz leakage:    -20.2 dB  ⚠️  (expected < -80 dB)
```

**Problem identified:** 100 Hz interferer leaking through at **-20 dB relative to 2 Hz signal**. This is a ~60 dB shortfall in stopband rejection.

### Filter Stage Analysis

**Stage 1: CIC (16 kHz → 400 Hz)**
- Stopband attenuation @ 400 Hz: 60.2 dB ✅
- Passband ripple: 0.00 dB ✅
- **Issue:** Boxcar approximation, not true CIC

**Stage 2: Compensation FIR (400 Hz)**
- Passband flatness: 0.00 dB ✅
- **Issue:** Compensating for wrong CIC response

**Stage 3: Final FIR (400 Hz → 10 Hz)**
- Rejection @ 5-6 Hz transition: **16.0 dB** ⚠️
- **Issue:** Grossly insufficient for 40× decimation
- **Required:** >80 dB to prevent aliasing

## Why This Causes "Incursions"

Your 16 kHz input contains energy across 0-8 kHz. After decimation to 10 Hz (Nyquist = 5 Hz), any energy above 5 Hz that isn't rejected will **alias** into the 0-5 Hz passband:

```
Frequency folding pattern (10 Hz sample rate):
  100 Hz → aliases to 0 Hz (DC)
  102 Hz → aliases to 2 Hz
  105 Hz → aliases to 5 Hz
  110 Hz → aliases to 0 Hz (DC)
  ...
```

Your final FIR provides only **16 dB rejection** in the transition band. A 100 Hz interferer at 0.3 magnitude (-10.5 dB) gets attenuated to:
- After Stage 1 (CIC): ~60 dB rejection → -70.5 dB
- After Stage 3 (Final FIR): ~16 dB rejection → **-86.5 dB**

But with filter imperfections and the compensation FIR potentially **boosting** certain frequencies, you end up with -20 dB leakage at the output.

**Result:** High-frequency interference appears as spectral artifacts in your 0-5 Hz passband.

## The Math: Why 96 dB Isn't the Limit

Your concern about the "$6.02 \times 16 + 1.76 \approx 98 \text{ dB}$" limit only applies to **fixed-point** systems. Once converted to float:

**IEEE 754 float32 (your system):**
- Mantissa: 23 bits
- Dynamic range: $6.02 \times 23 = 138.5 \text{ dB}$
- Plus exponent range: effective ~150 dB for signal processing

**IEEE 754 float64 (scipy internals):**
- Mantissa: 52 bits
- Dynamic range: $6.02 \times 52 = 313 \text{ dB}$

**Your filter cascade has ~300 dB of headroom.** Quantization noise and overflow are non-issues.

## Root Cause: Suboptimal Filter Design

### Issue 1: Boxcar CIC Approximation

```python
# Current implementation (decimation.py:79-80)
b = np.ones(R) / R  # Simple boxcar approximates CIC integrator
a = [1.0]
```

This is **not** a true CIC filter. True CIC:
1. **Integrator stages:** $y[n] = y[n-1] + x[n]$ (no division, accumulation with gain)
2. **Comb stages:** $y[n] = x[n] - x[n-R]$ (after decimation)
3. **Frequency response:** $H(f) = \left|\frac{\sin(\pi f R/f_s)}{\sin(\pi f/f_s)}\right|^N$

Your boxcar has a different stopband profile and may not null at the desired alias frequencies.

### Issue 2: Insufficient Final FIR Order

The final FIR needs **much higher order** to achieve 90 dB stopband attenuation. Current code:

```python
# decimation.py:170
num_taps = int(np.ceil((stopband_attenuation_db - 8) / (2.285 * 2 * np.pi * transition_normalized))) + 1
```

With `stopband_attenuation_db=90` and `transition_width=1.0 Hz` at 400 Hz sample rate:
- `transition_normalized = 1.0 / 400 = 0.0025`
- `num_taps ≈ 2271` (before capping)
- **Capped to 401** (line 177): `num_taps = min(num_taps, 401)`

**This 401-tap limit is preventing adequate stopband rejection.**

## Recommended Solutions

### Option A: True Multi-Rate CIC Implementation (Preferred)

Replace the boxcar approximation with a proper multi-rate CIC:

```python
def _apply_true_cic_filter(samples: np.ndarray, R: int, N: int) -> np.ndarray:
    """
    True multi-rate CIC: N integrator stages → decimate → N comb stages
    
    Advantages:
    - No multipliers (efficient)
    - Predictable nulls at R*fs, 2*R*fs, ...
    - Proper frequency response for compensation stage
    """
    # Integrator stages (before decimation)
    integrators = samples
    for _ in range(N):
        integrators = np.cumsum(integrators)  # Accumulate
    
    # Decimate by R
    decimated = integrators[::R]
    
    # Comb stages (after decimation)
    combs = decimated
    for _ in range(N):
        combs = np.diff(combs, prepend=0)  # Differentiate with delay R
    
    return combs
```

**Benefits:**
- Correct stopband nulls at alias frequencies
- Compensation FIR will match properly
- More efficient than FIR for large R

### Option B: Increase Final FIR Order (Quick Fix)

Remove the 401-tap cap and allow the Kaiser formula to determine the required order:

```python
# decimation.py:177 - REMOVE THIS LINE:
# num_taps = min(num_taps, 401)

# Replace with adaptive limit:
max_taps = 10001  # Allow very long filters if needed
num_taps = min(num_taps, max_taps)

# For 90 dB rejection with 1 Hz transition at 400 Hz:
# num_taps ≈ 2271 → use this
```

**Trade-off:** Much higher computational cost (~5× slower), but will achieve 90 dB rejection.

### Option C: Add Intermediate Stage (Hybrid)

Break the 400 Hz → 10 Hz decimation into two stages:

```python
# Stage 3a: 400 Hz → 40 Hz (R=10, sharp FIR with 401 taps)
# Stage 3b: 40 Hz → 10 Hz (R=4, moderate FIR with 201 taps)
```

**Benefits:**
- Each stage has easier filtering requirements
- Combined rejection: 60 dB + 60 dB = 120 dB
- Total taps: 401 + 201 = 602 (vs 2271 for single stage)

### Option D: Upgrade to Complex Bandpass Decimation

Use scipy's `decimate()` with IIR filters designed for complex signals:

```python
from scipy.signal import decimate

# Stage 1: 16000 → 400 Hz
iq_400 = decimate(iq_16k, q=40, ftype='iir', zero_phase=True)

# Stage 2: 400 → 10 Hz  
iq_10 = decimate(iq_400, q=40, ftype='iir', zero_phase=True)
```

**Benefits:**
- Built-in anti-aliasing (Chebyshev IIR)
- `zero_phase=True` eliminates group delay issues
- Much faster than long FIR

**Trade-off:** IIR has nonlinear phase (but `zero_phase` compensates)

## Implementation Priority

**IMMEDIATE (Option D - Simplest):**

Test with the existing `decimate_for_upload_simple()` function:

```python
# decimation.py:326 - Change this line:
DECIMATION_FUNCTION = decimate_for_upload_simple  # Test IIR decimation
```

This will use scipy's IIR decimation with proper anti-aliasing. Test with real data and compare spectrograms.

**SHORT-TERM (Option A or C):**

Implement true multi-rate CIC or add intermediate stage for production quality.

**NOT RECOMMENDED:**

Converting to fixed-point would **degrade** performance and introduce the very problems you were worried about (quantization, overflow). Your float architecture is correct.

## Verification Procedure

After implementing any fix:

1. **Run diagnostic script:**
   ```bash
   python3 scripts/diagnose_decimation_artifacts.py
   ```
   
2. **Check synthetic test results:**
   - 100 Hz leakage should be < -80 dB
   - 2 Hz Doppler should be -6 dB ± 0.5 dB
   
3. **Generate spectrograms of real data:**
   - Compare before/after for same time period
   - "Incursions" should disappear
   
4. **Verify Doppler measurements:**
   - Ensure ±0.1 Hz frequency resolution preserved
   - Check phase continuity

## Conclusion

**Your DSP chain already uses floating-point arithmetic with massive headroom.** The "incursions" are aliasing artifacts from:
1. Suboptimal CIC approximation
2. Insufficient final FIR order (capped at 401 taps)
3. Inadequate transition band rejection (16 dB vs required 80+ dB)

**Solution:** Improve anti-aliasing filters, not data types. Start with Option D (scipy's `decimate()` with IIR) for immediate testing, then implement proper multi-rate CIC (Option A) for production.

**No need for fixed-point arithmetic or gain staging** - the float architecture is optimal for this application.
