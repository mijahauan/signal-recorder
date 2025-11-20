# Optimal SNR Implementation for 5ms Tick Detection

## Mathematical Foundation

### SNR Relationship
$$\text{SNR} = \frac{S}{N_0 \times B_{\text{signal}}}$$

Where:
- $S$ = Signal power (W)
- $N_0$ = Noise power density (W/Hz)
- $B_{\text{signal}}$ = Effective signal filter bandwidth (Hz)

**Key insight**: To maximize SNR, minimize $B_{\text{signal}}$ while capturing the signal energy.

## Implementation Changes (Nov 19, 2025)

### 1. Zero-Padding for Fine Frequency Resolution

**Previous**: 10 Hz resolution
```python
# 100ms window × 16 kHz = 1600 samples
fft_result = rfft(windowed_tick)  # 10 Hz bins
```

**New**: 1 Hz resolution
```python
# Zero-pad to 1 second worth of samples
padded_length = sample_rate  # 16000 samples
padded_tick = np.pad(windowed_tick, (0, padded_length - len(windowed_tick)))
fft_result = rfft(padded_tick)  # 1 Hz bins
freqs = rfftfreq(padded_length, 1/sample_rate)
```

**Result**: Signal energy more concentrated, better frequency selectivity

### 2. Noise Power Density (N₀) Calculation

**Previous**: Average noise power (no bandwidth normalization)
```python
# Wrong: Compares signal in 10 Hz to raw noise average
noise_energy = np.mean(np.abs(noise_bins)**2)
snr = 10 * np.log10(signal_power / (noise_energy * N_ticks))
```

**New**: Properly normalized noise power density
```python
# Measure noise in 50 Hz clean band (825-875 Hz)
noise_low_idx = np.argmin(np.abs(freqs - 825.0))
noise_high_idx = np.argmin(np.abs(freqs - 875.0))
noise_bins = fft_result[noise_low_idx:noise_high_idx]

# Calculate power spectral density
total_noise_power = np.mean(np.abs(noise_bins)**2)
noise_bandwidth_hz = 50.0
N0 = total_noise_power / noise_bandwidth_hz  # W/Hz

# Accumulate over ticks
noise_estimate_sum += N0
```

**Why 825-875 Hz?**
- Below both signals (WWV 1000 Hz, WWVH 1200 Hz)
- Avoids 100 Hz modulation sidebands:
  - WWV: 1000 ± 100 Hz = 900-1100 Hz
  - WWVH: 1200 ± 100 Hz = 1100-1300 Hz
- Clean measurement region

### 3. Proper SNR Calculation with Bandwidth

**Signal filter bandwidth**: 5 Hz (conservative estimate)
- 1 Hz FFT bins
- Hann window → 1.5 Hz effective noise bandwidth
- Allow margin for signal spreading → 5 Hz

**Coherent integration**:
```python
N0_avg = noise_estimate_sum / valid_ticks
B_signal = 5.0  # Hz

# Coherent power from phase-aligned amplitude sum
wwv_coherent_power = np.abs(wwv_complex_sum)**2

# Noise power in signal bandwidth
noise_power = N0_avg * B_signal * valid_ticks

# SNR with proper normalization
coherent_wwv_snr = 10 * np.log10(wwv_coherent_power / noise_power)
```

**Incoherent integration**:
```python
# Power sum (not phase-aligned)
wwv_energy_sum = sum of |complex_i|^2

# Same noise calculation
noise_power = N0_avg * B_signal * valid_ticks

# SNR
incoherent_wwv_snr = 10 * np.log10(wwv_energy_sum / noise_power)
```

## Comparison: Old vs New

### Old Method Issues
1. **10 Hz bins** → Signal energy spread across multiple bins
2. **No bandwidth normalization** → Comparing apples to oranges
3. **Wrong noise band** (1350-1450 Hz) → Far from signals, higher uncertainty
4. **Inflated SNR** → Not accounting for effective noise bandwidth

### New Method Benefits
1. **1 Hz resolution** → Signal energy concentrated in single bin
2. **N₀ normalization** → Proper units (dBW/Hz)
3. **Clean noise band** (825-875 Hz) → Below signals and sidebands
4. **Accurate SNR** → Accounts for filter bandwidth

### Expected Changes

**SNR will change** (not necessarily higher or lower, but more accurate):
- Narrower filter → Less noise captured
- Proper normalization → Correct comparison
- Better frequency selectivity → Improved discrimination

## CSV Field Changes

### New Fields
- `noise_power_density_db`: N₀ in dBW/Hz (was `noise_power_db`)
- `signal_bandwidth_hz`: Effective filter bandwidth (5.0 Hz)

### Backward Compatibility
Old CSV files with `noise_power_db` will not work with new web UI.
**Must reprocess** to get corrected SNR values.

## Scientific Validation

### Check 1: Noise Consistency
N₀ should be relatively constant over time (receiver + atmospheric noise).
Large variations suggest interference or equipment issues.

### Check 2: SNR Improvement
Coherent integration should show ~10 dB gain over incoherent (~5 dB gain).
If not, phase coherence is poor (multipath, fading).

### Check 3: Discrimination
WWV vs WWVH difference should be stable with narrow filter.
Even low absolute SNR can give good discrimination if difference is large.

## Filter Bandwidth Discussion

**Why 5 Hz and not 1 Hz?**

1. **Hann window** effective noise bandwidth: 1.5 × bin width = 1.5 Hz
2. **Signal spreading**: Even pure tone has finite bandwidth after windowing
3. **Conservative estimate**: Better to slightly overestimate noise than underestimate
4. **Doppler**: Ionospheric motion can shift frequency ±1 Hz

**Could optimize further**:
- Measure actual -3dB bandwidth from signal peak
- Adaptive bandwidth based on SNR
- Use Kaiser window for better sidelobe rejection

## Reprocessing Required

**All data must be reprocessed** with new algorithm to get:
- Corrected SNR values
- N₀ measurements
- 1 Hz frequency resolution benefits

Run:
```bash
./REPROCESS-DISCRIMINATION.sh
# Option 4: Reprocess all available data
```

## References

- Matched filter theory: Signal energy must match filter bandwidth
- Noise power density: Standard in communications theory
- Zero-padding: Does not add information but improves frequency resolution
- Coherent integration: Phase-aligned amplitude sum → N gain vs √N for incoherent

## Files Modified

- `src/signal_recorder/wwvh_discrimination.py`:
  - Zero-padding for 1 Hz bins
  - N₀ calculation (825-875 Hz)
  - Bandwidth-normalized SNR
  - New diagnostic fields

- `web-ui/discrimination.js`:
  - Updated field names
  - N₀ overlay trace
  - Better hover info

- `web-ui/discrimination.html`:
  - Updated legend with filter specs
  - N₀ description

## Summary

This implementation follows proper signal processing theory to maximize SNR through:
1. **Narrow filtering** (5 Hz vs 10 Hz)
2. **Fine frequency resolution** (1 Hz bins)
3. **Proper noise normalization** (N₀ in W/Hz)
4. **Clean noise measurement** (825-875 Hz guard band)

The result is scientifically rigorous SNR measurements that accurately reflect signal quality and enable better discrimination between WWV and WWVH.
