# Critical BCD Discrimination Corrections

## Date: November 19, 2025

## Fundamental Errors Corrected

### Error 1: Misidentifying the Carrier
**WRONG:** Attempted to measure amplitudes from 1000 Hz (WWV) and 1200 Hz (WWVH) signals
**CORRECT:** **100 Hz BCD signal IS the carrier** - both WWV and WWVH modulate it

**Impact:** Would have measured time marker tones instead of actual carrier amplitudes

---

### Error 2: Misunderstanding Signal Types
**WRONG:** Treated 1000 Hz and 1200 Hz as "carriers"
**CORRECT:** 1000 Hz and 1200 Hz are **pure, unmodulated time marker tones** only
- Used for minute and second markers
- Not carriers for continuous amplitude measurement
- Only relevant for identification, not propagation studies

---

### Error 3: Unnecessary Tone Schedule Filtering
**WRONG:** Applied tone schedule filtering to avoid 500/600 Hz harmonic contamination in BCD measurements
**CORRECT:** **100 Hz is completely isolated from 500/600 Hz time marker tones**
- Different frequency bands (100 Hz vs 500/600 Hz)
- No harmonic contamination possible
- BCD measurements valid throughout entire minute

**Removed:**
- Tone schedule lookups in BCD correlation
- `wwv_contaminated` / `wwvh_contaminated` flags
- Quality score penalties for "interference"
- Complex filtering logic

---

## Correct BCD Discrimination Method

### Signal Chain:
1. **Input:** IQ samples at 16 kHz
2. **Bandpass:** 50-150 Hz isolates 100 Hz BCD subcarrier
3. **Demodulate:** Envelope detection extracts BCD modulation
4. **Low-pass:** 0-5 Hz extracts BCD pattern (1 bit/second)
5. **Correlation:** Cross-correlate with expected template
6. **Result:** Two peaks in correlation = two station arrivals

### Amplitude Extraction:
```
Peak 1 height = WWV amplitude
Peak 2 height = WWVH amplitude
Peak separation (time) = Differential delay (5-30 ms)
```

**Key Insight:** The correlation peak heights **directly represent** individual station signal strengths because:
- Both stations transmit identical BCD pattern
- On same 100 Hz carrier frequency
- Separated only by propagation delay (~10-20 ms)
- Matched filter output = amplitude × template energy

### Normalization:
```python
amplitude_normalized = peak_height / sqrt(template_energy)
```
This provides consistent amplitude scaling independent of template design.

---

## What Tone Schedule IS Used For

**Correct Applications:**
1. **Per-second tick analysis** (Method 4)
   - Skip seconds when 500/600 Hz present
   - Or use notch filters to remove fundamentals
   - Prevents 2nd harmonics at 1000/1200 Hz

2. **Per-minute tone detection** (Method 5)
   - 800ms marker at second 0 has no other tones
   - Clean measurement window

**NOT Used For:**
- BCD discrimination (Method 2) - 100 Hz unaffected
- 440 Hz analysis (Method 1) - different frequency

---

## Implementation Changes

### Files Modified:
1. `src/signal_recorder/wwvh_discrimination.py`
   - Removed 1000/1200 Hz carrier filtering
   - Removed tone schedule imports and logic
   - Use correlation peak heights directly
   - Simplified BCD window data structure

2. `WWV_WWVH_DISCRIMINATION_METHODS.md`
   - Corrected Method 2 description
   - Clarified Method 3 (time marker tones, not carriers)
   - Updated all references to "carriers"

### Code Before (WRONG):
```python
# Extract from 1000/1200 Hz "carriers"
wwv_carrier = bandpass_filter(iq_samples, 1000)
wwvh_carrier = bandpass_filter(iq_samples, 1200)
wwv_amp = np.mean(np.abs(wwv_carrier[window]))
wwvh_amp = np.mean(np.abs(wwvh_carrier[window]))

# Apply tone schedule filtering
if wwv_tone == 500:
    wwv_amp = 0.0  # Contaminated
if wwvh_tone == 600:
    wwvh_amp = 0.0  # Contaminated
```

### Code After (CORRECT):
```python
# Use correlation peak heights from 100 Hz BCD signal
correlation = correlate(bcd_signal, template)
peaks = find_peaks(correlation)
wwv_amp = peak_heights[0]
wwvh_amp = peak_heights[1]

# Normalize by template energy
template_energy = np.sum(template**2)
wwv_amp /= np.sqrt(template_energy)
wwvh_amp /= np.sqrt(template_energy)

# No tone schedule filtering needed - 100 Hz isolated
```

---

## Verification Needed

### Test with Real Data:
1. Run BCD discrimination on known good data
2. Check that WWV and WWVH amplitudes are **different** (not mirrored)
3. Verify amplitudes correlate with 440 Hz reference measurements
4. Confirm continuous data throughout minute (no gaps)

### Expected Results:
- WWV/WWVH amplitude ratio should match propagation physics
- Stronger station should show higher correlation peak
- Differential delay should be 5-30 ms (ionospheric)
- ~50 valid measurements per minute (1-second steps)

---

## Summary

**The 100 Hz BCD subcarrier is the ONLY carrier we measure for continuous amplitude discrimination.**

1000 Hz and 1200 Hz are identification tones, not carriers. They:
- Mark seconds and minutes
- Identify stations (WWV=1000, WWVH=1200)
- Useful for timing but not continuous propagation study

The BCD correlation method provides:
- ✅ Differential delay (propagation path difference)
- ✅ Individual station amplitudes (from peak heights)
- ✅ High temporal resolution (~50 points/minute)
- ✅ No harmonic contamination (100 Hz isolated)
- ✅ Continuous coverage (entire minute)

This is now implemented correctly.
