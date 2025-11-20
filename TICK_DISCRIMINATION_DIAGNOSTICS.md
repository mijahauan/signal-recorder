# Tick Discrimination Diagnostic Features

## Panel 5 Improvements

### 1. Toggleable Overlays
**Problem**: Purple difference line was obscuring individual WWV/WWVH measurements.

**Solution**: Both overlay traces are now **hidden by default**. Click legend to toggle:
- **"Difference (toggle)"** - Purple line showing WWV - WWVH
- **"Noise Floor (toggle)"** - Yellow dotted line showing 1350-1450 Hz noise power

### 2. Noise Floor Monitoring
**Purpose**: Diagnose whether low SNR is due to:
- Signal dropping (constant noise, weak signal)
- Noise rising (interference in measurement band)

**Implementation**:
- Noise measured in **1350-1450 Hz guard band**
- Avoids 100 Hz modulation sidebands:
  - WWV: 1000 ± 100 Hz = 900-1100 Hz
  - WWVH: 1200 ± 100 Hz = 1100-1300 Hz
- Per-tick noise averaged over 10-second windows

**Added to tick window results**:
- `noise_power_db`: Noise floor in dB (relative to 1.0 = 0 dB)
- Stored in JSON, plotted as yellow dotted line

## Diagnostic Workflow

### Investigating Low SNR Clusters

**Step 1**: View base data
- Open Panel 5, see WWV (green above) and WWVH (red below)
- Identify periods of low/high SNR

**Step 2**: Check noise floor
- Click "Noise Floor (toggle)" in legend
- Yellow line appears showing noise power

**Step 3**: Diagnose cause
- **Flat noise, weak signal**: Propagation fade (normal ionospheric behavior)
- **Rising noise**: Possible interference at 1350-1450 Hz
  - Check for nearby transmitters
  - Look for periodic patterns (suggests man-made interference)
  - Cross-reference with other frequencies

**Step 4**: Check discrimination
- Click "Difference (toggle)" to see WWV - WWVH
- Even with low absolute SNR, if difference is stable → discrimination still valid

## Expected Patterns

### Normal Ionospheric Behavior
- **Slowly varying SNR** (minutes to hours): Diurnal propagation changes
- **Flat noise floor**: Receiver noise + atmospheric noise (~constant)
- **Both stations fade together**: Path through same ionospheric region

### Interference Indicators
- **Sudden noise spikes**: Lightning, power line noise
- **Periodic noise patterns**: Man-made transmitters
- **Noise rises while signals drop**: Suggests in-band interference

### Phase Coherence Loss
- **Low coherence quality** → Falls back to incoherent integration
- Causes: Multipath, Doppler spread, fading
- Results in ~5 dB lower SNR (incoherent vs coherent)

## Technical Details

### Noise Measurement
```python
# Measure noise (1350-1450 Hz guard band)
noise_low_idx = np.argmin(np.abs(freqs - 1350.0))
noise_high_idx = np.argmin(np.abs(freqs - 1450.0))
noise_bins = fft_result[noise_low_idx:noise_high_idx]
noise_energy = np.mean(np.abs(noise_bins)**2)
noise_estimate_sum += noise_energy
```

### SNR Calculation
```python
# Coherent integration
wwv_coherent_power = np.abs(wwv_complex_sum)**2
coherent_wwv_snr = 10 * np.log10(wwv_coherent_power / (noise_avg * valid_ticks))

# Incoherent integration  
incoherent_wwv_snr = 10 * np.log10(wwv_energy_sum / (noise_avg * valid_ticks))
```

## Reprocessing Required

**Important**: These diagnostic features require **reprocessing** existing data.

Old CSV files (before Nov 19, 2025) do **not** have `noise_power_db` field.

Run:
```bash
./REPROCESS-DISCRIMINATION.sh
# Option 4: Reprocess all available data
```

This will add `noise_power_db` to all tick window records.

## Scientific Interpretation

### Discrimination vs SNR
- **Discrimination** = Can we tell WWV from WWVH?
  - Depends on **difference** in SNR, not absolute values
  - 5 dB WWV + 0 dB WWVH → 5 dB discrimination ✓
  - 20 dB WWV + 15 dB WWVH → 5 dB discrimination ✓

- **Absolute SNR** = How strong is each signal?
  - Matters for timing accuracy
  - Matters for phase coherence
  - Low SNR → noisy discrimination, but still valid if difference is large

### Example: Low SNR with Good Discrimination
```
Time 03:00 - 06:00 UTC (poor propagation)
WWV SNR:   2 dB  (barely above noise)
WWVH SNR: -3 dB  (below noise floor)
Difference: 5 dB → WWVH definitely weaker
Discrimination: Valid! ✓

Noise floor: -40 dB (flat, normal receiver noise)
→ Conclusion: Signals are weak (propagation fade), not interference
```

## Files Modified
- `src/signal_recorder/wwvh_discrimination.py`: Added `noise_power_db` to tick window results
- `web-ui/discrimination.js`: Parse and plot noise floor, make overlays toggleable
- `web-ui/discrimination.html`: Update legend with diagnostic instructions
