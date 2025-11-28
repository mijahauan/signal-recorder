# WWV/WWVH Discrimination Methods

## Overview
Complete discrimination strategy for separating WWV (Fort Collins, CO) and WWVH (Kauai, HI) signals on shared frequencies (2.5, 5, 10, 15 MHz).

## Active Discrimination Methods

### 1. 440 Hz Hourly Tone Analysis
**Purpose:** Clean amplitude reference without harmonic contamination

**Schedule:**
- Minute 1: WWVH transmits 440 Hz
- Minute 2: WWV transmits 440 Hz

**Method:**
- Bandpass filter around 440 Hz (430-450 Hz)
- FFT-based power measurement
- SNR calculation vs noise floor

**Advantages:**
- No harmonic interference (500/600 Hz harmonics are at 1000/1200 Hz, not 440 Hz)
- Hourly calibration reference for carrier measurements
- Unambiguous station identification

**Limitations:**
- Only 2 data points per hour
- Requires strong signal for reliable detection

**Output:** `tone_440hz_wwv_power_db`, `tone_440hz_wwvh_power_db`

---

### 2. BCD Cross-Correlation (Primary Method)
**Purpose:** Differential delay measurement + amplitude tracking with high temporal resolution

**Signal:** 100 Hz BCD time code (identical from both stations)

**Integration:** 10-second windows with 1-second sliding steps
- 10 seconds: Sweet spot for SNR (10× gain over 1-second)
- Below typical HF coherence time (Tc ~15-20 seconds)
- 1-second steps: 90% overlap for tracking rapid variations

**Method:**
1. Bandpass filter around 100 Hz (50-150 Hz) to isolate BCD subcarrier
2. AM demodulate to extract BCD envelope
3. Low-pass filter (0-5 Hz) to get BCD modulation pattern
4. Generate expected BCD template for the minute
5. Sliding cross-correlation to find two peaks (WWV + WWVH arrivals)
6. Peak separation = differential delay (5-30 ms typical)
7. Peak heights = individual station amplitudes (normalized by template energy)

**Amplitude Measurement:**
- **100 Hz BCD signal IS the carrier** - both stations modulate it
- Correlation peak heights directly represent individual station strengths
- No contamination from 500/600 Hz time marker tones (different frequencies)
- Normalized by template energy for consistent scaling

**Output:** ~50 data points per minute
- `bcd_wwv_amplitude`, `bcd_wwvh_amplitude` (from correlation peaks)
- `bcd_differential_delay_ms` (ionospheric path difference)
- `bcd_correlation_quality` (SNR metric)

**Advantages:**
- High temporal resolution (1-second updates)
- Direct measurement of both delay AND amplitude from same correlation
- Continuous throughout entire minute (no contamination issues)
- Optimal SNR/resolution trade-off
- 100 Hz isolated from time marker tones

---

### 3. 1000/1200 Hz Time Marker Tone Measurements with Schedule Filtering
**Purpose:** Per-minute identification tone analysis (secondary method)

**Signal:** 1000 Hz (WWV) and 1200 Hz (WWVH) pure time marker tones
- NOT carriers - these are unmodulated identification tones
- Primarily for station identification, not continuous amplitude tracking

**Challenge:** 500 Hz and 600 Hz tones create 2nd harmonics at 1000 Hz and 1200 Hz
- Cannot reliably measure 1000 Hz when 500 Hz active (2× harmonic)
- Cannot reliably measure 1200 Hz when 600 Hz active (2× harmonic)

**Solution:** Use official WWV/WWVH tone schedule (`tone_sched_wwv.py`) to filter measurements
- Only use 1000 Hz measurements when no 500 Hz tone present
- Only use 1200 Hz measurements when no 600 Hz tone present
- Apply to per-second tick analysis (Method 4)

**Application:**
- Used in tick detection windows (skip contaminated seconds)
- Per-minute tone detection already has built-in filtering
- BCD method (Method 2) unaffected - uses 100 Hz, not 1000/1200 Hz

**Note:** For continuous amplitude tracking, use Method 2 (BCD) instead

---

### 4. Per-Second Tick Analysis with Coherent Integration
**Purpose:** Fine-grained discrimination using 5ms tick tones

**Method:**
- 6 windows per minute (10 seconds each: 1-10, 11-20, 21-30, 31-40, 41-50, 51-59)
- Skip second 0 (contains 800ms marker tone)
- Notch filters to remove 440/500/600 Hz fundamentals (prevent harmonics)
- Coherent integration when phase stable (10 dB gain)
- Incoherent integration when phase unstable (5 dB gain)
- Automatic selection based on phase stability metric

**Output:** `tick_windows_10sec` with 6 data points per minute
- `wwv_snr_db`, `wwvh_snr_db`
- `ratio_db` (WWV - WWVH)
- `coherence_quality` (0-1 phase stability)
- `integration_method` ('coherent' or 'incoherent')

**Advantages:**
- 6× better resolution than per-minute tones
- Adaptive to channel conditions
- Harmonic contamination removed

**Limitations:**
- Requires clean notch filtering
- Phase instability reduces gain

---

### 5. Per-Minute Tone Detection (Baseline)
**Purpose:** Basic discrimination from standard tone detection

**Signal:** 1000 Hz (WWV) and 1200 Hz (WWVH) identification tones

**Method:**
- Phase-invariant quadrature matched filtering
- Correlation = √(sin² + cos²)
- Noise-adaptive threshold
- Differential delay from cross-correlation peaks

**Output:** One measurement per minute
- `wwv_power_db`, `wwvh_power_db`
- `power_ratio_db`
- `differential_delay_ms`

**Advantages:**
- Robust, well-tested
- Works even with weak signals
- Baseline for comparison

**Limitations:**
- Only 1 data point per minute
- Subject to harmonic contamination
- No sub-minute dynamics

---

## Discrimination Confidence Hierarchy

**High Confidence (preferred):**
1. 440 Hz tone detection (minutes 1 & 2)
2. BCD correlation with clean carrier measurements (no interference)
3. Coherent tick integration (phase stable)

**Medium Confidence:**
1. BCD correlation with partial contamination (one station clean)
2. Incoherent tick integration
3. Per-minute tone detection with good SNR

**Low Confidence:**
1. BCD correlation with both stations contaminated
2. Per-minute tone detection with weak signals
3. Noise floor measurements (no detection)

---

## Data Integration Strategy

**Temporal Resolution:**
- BCD: ~50 windows/minute (1-second resolution)
- Ticks: 6 windows/minute (10-second resolution)
- Per-minute: 1 measurement/minute
- 440 Hz: 2 measurements/hour

**Cross-Validation:**
- Use 440 Hz as hourly calibration anchor
- Compare BCD amplitudes with tick SNR measurements
- Validate per-minute detection against sub-minute data
- Filter contaminated periods using tone schedule

**Quality Metrics:**
- BCD correlation quality (peak SNR)
- Tick coherence quality (phase stability)
- Contamination flags (tone schedule)
- 440 Hz detection confidence

---

## Adaptive Optimization (Future)

**SNR-Based Window Adjustment:**
- Strong signals: Reduce to 5-second windows for finer detail
- Weak signals: Increase to 15-20 seconds for better SNR
- Monitor coherence time to stay below Tc limit

**Machine Learning Potential:**
- Train on 440 Hz clean references
- Correct for systematic biases in contaminated periods
- Predict optimal integration time from channel state

---

## Implementation Files

- `src/signal_recorder/wwvh_discrimination.py`: Main discrimination module
- `src/signal_recorder/wwv_tone_schedule.py`: Official tone schedule
- `src/signal_recorder/wwv_bcd_encoder.py`: BCD template generation
- `web-ui/discrimination.js`: Visualization and plotting

## References

- NIST Special Publication 432: *NIST Time and Frequency Radio Stations: WWV, WWVH, and WWVB*
- WWV/WWVH Broadcast Format Documentation
- HF Propagation and Ionospheric Coherence Time Analysis
