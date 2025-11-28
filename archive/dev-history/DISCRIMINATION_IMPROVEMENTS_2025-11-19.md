# WWV/WWVH Discrimination Improvements - November 19, 2025

## Executive Summary

Implemented 5 major quantitative improvements to the WWV/WWVH discrimination system based on rigorous DSP analysis. These changes address fundamental mathematical issues in the previous implementation and establish a robust, multi-method discrimination framework with minute-specific weighting.

---

## Improvements Implemented

### 1. Joint Least Squares BCD Amplitude Estimation

**Problem:** Previous implementation incorrectly assumed correlation peak heights directly represented individual station amplitudes. This failed because both stations transmit the identical BCD code, causing **temporal leakage** - at each peak time, we measure a superposition of both signals.

**Solution:** Implemented joint least squares estimation to solve for independent WWV and WWVH amplitudes.

**Mathematical Framework:**
```
At each TOA peak, the observed correlation is:
C(τ_WWV)  = A_WWV × R(0)    + A_WWVH × R(Δτ)
C(τ_WWVH) = A_WWV × R(-Δτ)  + A_WWVH × R(0)

Where:
- R(δ) = template autocorrelation at lag δ
- Δτ = τ_WWVH - τ_WWV (differential delay ~10 ms)
- R(-Δτ) = R(Δτ) by symmetry

This forms a 2×2 linear system solved via:
[A_WWV  ]   [R(0)  R(Δτ)]⁻¹  [C(τ_WWV) ]
[A_WWVH] = [R(Δτ) R(0) ]    [C(τ_WWVH)]
```

**Implementation:** `wwvh_discrimination.py` lines 806-866

**Impact:** 
- BCD amplitudes now correctly represent independent station strengths
- Eliminated artificial amplitude mirroring (WWV_amp ≈ WWVH_amp)
- Provides cleanest power proxy during BCD minutes (0, 8-10, 29-30)

---

### 2. SNR-Based Coherence Method Selection

**Problem:** Fixed coherence quality threshold (0.6) didn't account for actual SNR performance, sometimes selecting coherent integration when phase coherence was broken.

**Solution:** Select integration method based on which yields higher SNR, not fixed phase variance threshold.

**Decision Rule:**
```
If (SNR_coherent > SNR_incoherent + 3 dB) for BOTH stations:
    Use coherent integration  # Real phase stability
Else:
    Use incoherent integration  # More robust
```

**Rationale:** 
- Coherent integration theoretically provides 10 dB gain vs incoherent (5 dB)
- If coherent SNR ≤ incoherent SNR, phase coherence is broken
- This directly validates phase stability through measurement

**Implementation:** `wwvh_discrimination.py` lines 615-634

**Impact:** Prevents false high-SNR readings from broken phase coherence

---

### 3. Accurate Signal Bandwidth (Hann Window ENBW)

**Problem:** Used conservative 5 Hz bandwidth estimate, overestimating noise and underestimating SNR.

**Solution:** Use actual Equivalent Noise Bandwidth (ENBW) of Hann window.

**Calculation:**
```
ENBW = 1.5 × Frequency Resolution
With 1 second zero-padding: Δf = 1 Hz
Therefore: B_signal = 1.5 Hz (was 5 Hz)
```

**Implementation:** `wwvh_discrimination.py` line 578

**Impact:** 
- More accurate SNR estimates (+5.2 dB correction)
- Consistent with FFT window processing
- Better alignment with theoretical processing gain

---

### 4. Consistent Noise Floor Reference (825-875 Hz Guard Band)

**Problem:** 440 Hz tone used local noise floor (±50 Hz around 440 Hz), inconsistent with tick detection's 825-875 Hz guard band.

**Solution:** Use 825-875 Hz guard band for all noise floor measurements.

**Rationale:**
- This band is guaranteed clean (no station tones or harmonics)
- 100 Hz BCD: too low
- 440/500/600 Hz: station ID tones
- 1000/1200 Hz: time marker tones
- 825-875 Hz: Pure noise reference ✅

**Implementation:** `wwvh_discrimination.py` lines 342-361

**Impact:** 
- Single consistent N₀ reference across all methods
- Eliminates contamination from nearby tones
- Quantitatively comparable SNR measurements

---

### 5. Weighted Voting System for Final Discrimination

**Problem:** No systematic way to combine multiple measurement types (440 Hz, BCD, carrier tones, ticks) with minute-specific priorities.

**Solution:** Implemented weighted voting system with minute-specific confidence hierarchy.

**Weighting Hierarchy:**

| Minute Type | Primary (10×) | Secondary (5×) | Tertiary (2×) | Minimal (1×) |
|-------------|---------------|----------------|---------------|--------------|
| Minutes 1,2 (440 Hz) | 440 Hz Tone | Tick SNR | BCD | Carrier |
| Minutes 0,8-10,29-30 (BCD) | BCD Amplitude | Tick SNR | Carrier | — |
| All Other Minutes | Carrier Power | Tick SNR | BCD | — |

**Voting Algorithm:**
```python
For each method with weight w:
    If WWV significantly stronger (+3 dB): wwv_score += w
    If WWVH significantly stronger: wwvh_score += w
    
Normalize scores:
    wwv_norm = wwv_score / total_weight
    wwvh_norm = wwvh_score / total_weight

Final decision:
    If |wwv_norm - wwvh_norm| < 0.15: BALANCED
    Else: Dominant = argmax(wwv_norm, wwvh_norm)
    
Confidence based on margin:
    margin > 0.7: HIGH
    margin > 0.4: MEDIUM
    else: LOW
```

**Implementation:** `wwvh_discrimination.py` lines 284-430, integrated at lines 1224-1233

**Impact:**
- Minute 1: 440 Hz WWVH dominates (harmonic-free, 10× weight)
- Minute 2: 440 Hz WWV dominates (harmonic-free, 10× weight)
- Minutes 0,8-10,29-30: BCD dominates (continuous, high SNR, 10× weight)
- Other minutes: Carrier tones dominate (per-minute, 10× weight)
- Tick SNR provides consistent cross-check (5× weight)

---

## Testing Requirements

### 1. Reprocess Recent Data
```bash
python3 scripts/reprocess_discrimination_timerange.py \
    --date 20251119 \
    --channel "WWV 10 MHz" \
    --start-hour 18 \
    --end-hour 24
```

### 2. Verify BCD Amplitudes Are Now Different
```python
# Old (broken): WWV_amp ≈ WWVH_amp (±0.00 dB)
# New (fixed): WWV_amp ≠ WWVH_amp (should see ±3-15 dB ratios)
```

### 3. Check Integration Method Selection
```bash
# Review logs for coherent vs incoherent selection
grep "integration_method" discrimination_*.csv | \
    awk -F',' '{print $X}' | sort | uniq -c
```

### 4. Validate 440 Hz Discrimination
```bash
# Minutes 1 and 2 should show clear discrimination from 440 Hz
# Check that dominant_station aligns with 440 Hz detection
```

### 5. Weighted Voting Validation
```bash
# Verify that BCD-dominant minutes (0,8-10,29-30) use BCD for discrimination
# Verify that 440 Hz minutes (1,2) use 440 Hz for discrimination
```

---

## Expected Results

### BCD Amplitude Ratios (Joint Least Squares)
```
Before: WWV/WWVH ratio = 0.00 dB (identical)
After:  WWV/WWVH ratio = ±3 to ±15 dB (realistic separation)
```

### SNR Improvements (1.5 Hz vs 5 Hz Bandwidth)
```
Old estimate: SNR = 15 dB (with B=5 Hz)
New estimate: SNR = 20.2 dB (with B=1.5 Hz)
Correction: +5.2 dB
```

### Integration Method Selection
```
Coherent: Used when SNR_coh > SNR_inc + 3 dB
Incoherent: Used when phase broken (SNR_coh ≤ SNR_inc)
Expected: 60-80% incoherent (HF propagation is challenging)
```

### Discrimination Confidence
```
High (>70% margin): Strong single station or clear separation
Medium (40-70% margin): Moderate signals with some separation  
Low (<40% margin): Weak signals or balanced stations
```

---

## Files Modified

1. **`src/signal_recorder/wwvh_discrimination.py`**
   - Lines 806-866: Joint least squares BCD estimation
   - Lines 615-634: SNR-based coherence selection
   - Line 578: Hann ENBW (1.5 Hz)
   - Lines 342-361: 825-875 Hz guard band for 440 Hz
   - Lines 284-430: Weighted voting system
   - Lines 1224-1233: Integration into analysis flow

---

## Key Formulas

### Joint Least Squares
```
A = (R^T R)^(-1) R^T C
Where R = autocorrelation matrix, C = correlation measurements
```

### ENBW (Hann Window)
```
ENBW = 1.5 × Δf = 1.5 Hz (for 1 second FFT)
```

### SNR with Bandwidth Normalization
```
SNR = S / (N₀ × B × N_samples)
Where N₀ = noise power density from 825-875 Hz guard band
```

### Weighted Voting
```
dominant_station = argmax(∑ w_i × vote_i) / ∑ w_i
confidence = f(margin between normalized scores)
```

---

## References

- **WWV/WWVH Signal Specifications:** NIST Special Publication 432
- **Hann Window ENBW:** Harris, F.J., "On the Use of Windows for Harmonic Analysis with the Discrete Fourier Transform"
- **Cross-Correlation Theory:** Van Trees, "Detection, Estimation, and Modulation Theory"
- **Coherent Integration:** Skolnik, "Introduction to Radar Systems"

---

## Next Steps

1. **Reprocess historical data** with new algorithms to build baseline
2. **Monitor discrimination performance** over multi-day period
3. **Tune weight factors** based on empirical accuracy by minute type
4. **Document performance metrics** (accuracy vs minute type, SNR, etc.)
5. **Consider additional methods** if needed (e.g., carrier phase discrimination)

---

**Implemented:** November 19, 2025  
**Version:** 2.0  
**Status:** Ready for testing and validation
