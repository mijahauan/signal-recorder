# BCD-Based WWV/WWVH Discrimination

## Overview

Implements a novel discrimination method using 100 Hz BCD time code cross-correlation, running in parallel with the existing 1000/1200 Hz tick-based method.

## Key Insight

Both WWV and WWVH transmit the **identical 100 Hz BCD time code** simultaneously. Since the signals arrive at different times due to ionospheric propagation (typically 10-20ms differential delay), cross-correlation against the expected template produces **two distinct peaks**.

## Advantages Over Tick Method

1. **No carrier separation needed** - Works on 100 Hz only (avoids 1000/1200 Hz discrimination problem)
2. **60 seconds of integration** - Massive processing gain vs 5ms ticks
3. **Known signal structure** - BCD pattern is precisely known for each minute
4. **Narrowband** - Only 0-150 Hz bandwidth needed (excellent SNR)
5. **Direct TOA measurement** - Peak separation = differential propagation delay

## Ionospheric Coherence Time Considerations

**Critical insight:** Using a full 60-second correlation window would completely mask ionospheric dynamics!

The ionosphere's coherence time (Tc) varies from:
- **Quiet conditions:** 30+ seconds
- **Disturbed/dawn/dusk:** 5-15 seconds
- **Severe scintillation:** <5 seconds

**Sliding Window Strategy:**
- **Window length:** 15 seconds (compromise between SNR and Tc)
- **Step size:** 1 second (high temporal resolution)
- **Output:** ~45 data points per minute (vs 1 with full correlation)
- **Captures:** Rapid fading, TIDs, selective fading events

This approach operates within typical coherence times, providing accurate instantaneous measurements of amplitude ratios and differential TOA as they evolve throughout the minute.

## Implementation

### BCD Encoder (`wwv_bcd_encoder.py`)

Based on Phil Karn's `wwvsim.c`, generates accurate IRIG-H time code templates:

**Encoding (Little-Endian BCD):**
- Seconds 4-7, 51-54: Year (last 2 digits)
- Seconds 10-13, 15-17: Minute
- Seconds 20-23, 25-26: Hour (24-hour)
- Seconds 30-33, 35-37, 40-41: Day of year

**Pulse Widths:**
- Position markers (0, 9, 19, 29, 39, 49, 59): 800ms HIGH, 200ms LOW
- Binary 1: 500ms HIGH, 500ms LOW
- Binary 0: 200ms HIGH, 800ms LOW

**Modulation:**
- 100 Hz sine wave carrier
- HIGH amplitude: -6 dB
- LOW amplitude: -20 dB

### Discrimination Method (`detect_bcd_discrimination()`)

**Processing Chain:**
```
IQ samples → Envelope detect → LPF (0-150 Hz) → Cross-correlate with template
   ↓
Find two peaks → Measure amplitudes and separation → WWV & WWVH parameters
```

**Peak Detection:**
- Minimum separation: 5ms (eliminates self-correlation artifacts)
- Maximum separation: 30ms (reasonable ionospheric delay range)
- Uses two strongest peaks above threshold (mean + 2σ)

**Outputs:**
- `bcd_wwv_amplitude`: WWV correlation peak height
- `bcd_wwvh_amplitude`: WWVH correlation peak height
- `bcd_differential_delay_ms`: Time separation between peaks (ionospheric delay)
- `bcd_correlation_quality`: Peak-to-noise ratio

## CSV Output

Five new columns added to discrimination CSV:
- `bcd_wwv_amplitude` - Mean WWV correlation peak amplitude across all windows
- `bcd_wwvh_amplitude` - Mean WWVH correlation peak amplitude across all windows
- `bcd_differential_delay_ms` - Mean differential TOA delay across all windows
- `bcd_correlation_quality` - Mean peak-to-noise ratio across all windows
- `bcd_windows` - JSON array of per-window measurements (~45 data points/minute):
  - `window_start_sec`: Window start time (seconds into minute)
  - `wwv_amplitude`: WWV peak amplitude for this window
  - `wwvh_amplitude`: WWVH peak amplitude for this window
  - `differential_delay_ms`: Differential TOA for this window
  - `correlation_quality`: Peak-to-noise ratio for this window

## Comparison with Tick Method

**Tick-Based (existing):**
- ✓ 10-second time resolution (6 measurements/minute)
- ✓ Proven to work
- ✗ Requires 1000/1200 Hz separation
- ✗ Contaminated by 500/600 Hz harmonics
- ✗ Only 5ms integration per tick

**BCD-Based (new):**
- ✓ No carrier separation needed
- ✓ 15 seconds integration per window (excellent SNR)
- ✓ Immune to 500/600 Hz contamination (filtered out)
- ✓ ~45 measurements per minute (captures ionospheric Tc)
- ✓ Tracks rapid fading, TIDs, selective fading
- ⚠️ Untested - needs validation

## Tunable Parameters

The sliding window correlation can be adjusted for different ionospheric conditions:

```python
# In detect_bcd_discrimination() call:
window_seconds = 15   # Window length (5-30 sec recommended)
step_seconds = 1      # Sliding step (1-5 sec recommended)
```

**Trade-offs:**
- Longer windows → Better SNR, but may exceed coherence time
- Shorter windows → Faster response, but lower SNR
- Smaller steps → More data points, higher CPU load
- Larger steps → Fewer data points, lower CPU load

## Known Limitations

1. **Template accuracy critical** - Encoder must exactly match transmitted BCD
2. **Assumes two stations** - Won't detect if only one station present
3. **Peak assignment ambiguous** - Currently assumes first peak = WWV (may not always be true)
4. **Multipath effects** - Could smear or split peaks
5. **Window length fixed** - Currently 15s default; may need adaptive adjustment based on observed coherence

## Next Steps

1. **Reprocess data** - Run on existing NPZ files to populate BCD fields
2. **Compare methods** - Validate BCD results against tick-based measurements
3. **Tune parameters** - Adjust threshold, peak detection if needed
4. **Add visualization** - Plot BCD correlation peaks and amplitudes in web UI

## Files Modified

- `src/signal_recorder/wwv_bcd_encoder.py` - New BCD template generator
- `src/signal_recorder/wwvh_discrimination.py` - Added `detect_bcd_discrimination()` method
- `scripts/reprocess_discrimination.py` - Added BCD columns to CSV output

## Reference

Based on Phil Karn KA9Q's `wwvsim.c` implementation of WWV/WWVH IRIG-H time code.
