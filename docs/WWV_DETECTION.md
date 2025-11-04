# WWV/CHU Tone Detection System

## Overview

The GRAPE V2 recorder includes live detection of 1000 Hz time signal tones broadcast by WWV (NIST) and CHU (NRC Canada) to measure timing accuracy and propagation conditions.

## Time Signal Characteristics

### WWV (NIST - USA)
- **Frequencies**: 2.5, 5, 10, 15, 20, 25 MHz
- **Tone**: 1000 Hz for 0.8 seconds
- **Timing**: Starts precisely at :00.0 of each minute
- **Location**: Fort Collins, Colorado (40.68°N, 105.04°W)

### CHU (NRC - Canada)  
- **Frequencies**: 3.33, 7.85, 14.67 MHz
- **Tone**: 1000 Hz for 0.5 seconds
- **Timing**: Starts precisely at :00.0 of each minute
- **Location**: Ottawa, Ontario (45.30°N, 75.75°W)

## Detection Algorithm

### Signal Processing Pipeline

1. **Input**: 16 kHz complex IQ samples
2. **Resampling**: Decimate to 3 kHz (reduces CPU load)
3. **AM Demodulation**: `magnitude = abs(IQ)`
4. **DC Removal**: Remove mean to isolate signal
5. **Bandpass Filter**: 950-1050 Hz Butterworth (order 5)
6. **Envelope Detection**: Hilbert transform → `abs(analytic_signal)`
7. **Normalization**: Scale envelope to [0, 1]
8. **Thresholding**: Detect samples > 0.5 threshold
9. **Edge Detection**: Find rising/falling edges
10. **Duration Validation**: Accept 0.5-1.2 second pulses
11. **Timing Calculation**: Measure error from expected :00.0

### Detection Window

- **Buffer Accumulation**: Starts ~:58 seconds, accumulates continuously
- **Check Window**: :01.0 to :02.5 (after tone completes)
- **Why Delayed**: Ensures full 0.8s tone is in buffer before checking
- **Buffer Size**: Typically 2-3 seconds (6000-9000 samples @ 3 kHz)

### Detection Criteria

**Accept if:**
- Envelope exceeds 50% of peak for sustained period
- Rising and falling edges clearly defined
- Duration: 0.5-1.2 seconds (handles both WWV and CHU)
- Only one detection per minute (prevents duplicates)

**Reject if:**
- Signal too weak (max envelope near noise floor)
- No clear edges found
- Duration too short (<0.5s) or too long (>1.2s)
- Already detected in current minute

## Propagation Considerations

HF propagation varies significantly due to ionospheric conditions:

### Factors Affecting Detection

1. **Time of Day**: 
   - Daytime: Higher frequencies propagate better
   - Nighttime: Lower frequencies propagate better
   - Critical for D-layer absorption

2. **Season**:
   - Summer: Higher absorption, shorter skip
   - Winter: Lower absorption, longer skip

3. **Solar Activity**:
   - High activity: Better HF propagation
   - Low activity: Reduced ionization

4. **Distance/Path**:
   - Skip zone: Too close for skywave, too far for groundwave
   - Multi-hop: Signal may fade in/out

5. **Frequency**:
   - Lower bands (2.5-5 MHz): Better at night
   - Middle bands (7-15 MHz): Transition bands
   - Upper bands (20-25 MHz): Better during day

### Expected Signal Strength Variations

Based on testing, envelope strength varies dramatically:

| Condition | Max Envelope | SNR | Detection | Example Time (UTC) |
|-----------|--------------|-----|-----------|-------------------|
| Strong | 0.05-0.10 | 50-60 dB | ✅ Reliable | 00:23 (night) |
| Moderate | 0.01-0.05 | 20-40 dB | ✅ Usually | Morning/evening |
| Weak | 0.001-0.01 | 5-15 dB | ⚠️ Marginal | Wrong time of day |
| Very Weak | <0.001 | <5 dB | ❌ No detection | Skip zone |

**This is normal and expected!** The goal is to study these propagation patterns.

## Detection Threshold Tuning

Current threshold: **0.5** (50% of peak envelope)

### Threshold Trade-offs

**Higher Threshold (e.g., 0.6-0.7)**
- ✅ Fewer false positives
- ❌ Misses weaker valid signals
- Use when: High noise environment

**Lower Threshold (e.g., 0.3-0.4)**
- ✅ Detects weaker signals
- ❌ More false positives from noise
- Use when: Clean signal, want max sensitivity

**Recommended Approach**: 
- Start with 0.5 (current setting)
- Collect data for several days
- Analyze detection rate vs. false positive rate
- Adjust based on your signal environment

### Adjusting Threshold

Edit `/home/mjh/git/signal-recorder/src/signal_recorder/grape_rtp_recorder.py`:

```python
# Line ~207
self.envelope_threshold = 0.5  # Adjust this value (0.0-1.0)
```

Lower values = more sensitive, higher values = more selective.

## Monitoring Detection Performance

### Live Status

Check `/tmp/live_quality_status.json`:

```bash
cat /tmp/live_quality_status.json | jq '.channels.WWV_10_MHz.wwv'
```

Output:
```json
{
  "enabled": true,
  "last_detection": 1730678400.5,  // Unix timestamp
  "last_error_ms": -12.3,           // Timing error in ms
  "detections_today": 47            // Count of detections
}
```

### Quality CSV Files

Per-minute quality files include WWV detections:

```bash
# View WWV detections for a day
cat analytics/quality/20241104/WWV_10_MHz_minute_quality_20241104.csv | \
  awk -F, '$11=="true" {print $2, $12}'
```

Columns:
- Column 11: `wwv_detected` (true/false)
- Column 12: `wwv_error_ms` (timing error in milliseconds)

### Web UI

The **Quality** tab shows live WWV timing data:
- **WWV ERROR** column displays timing error when detected
- Updates every ~5 seconds
- Empty when no recent detection (normal during poor propagation)

## Diagnostic Tools

### Post-Analysis Detection

Verify tones in archived data:

```bash
python3 scripts/debug_wwv_signal.py /path/to/test/output
```

Generates:
- Detailed signal analysis
- Spectrograms showing tone presence
- Envelope plots
- Detection diagnostics
- PNG plots in `/tmp/wwv_diagnostic_*.png`

### Manual Signal Inspection

```python
import numpy as np

# Load minute file
data = np.load('path/to/WWV_10_MHz/file.npz')
iq = data['iq']

# Check first 2 seconds (where tone should be)
first_2s = iq[:32000]  # 16 kHz sample rate

# AM demodulate
magnitude = np.abs(first_2s)
print(f"Max signal: {np.max(magnitude):.6f}")

# Strong signal: >0.01, Weak: <0.001
```

## Troubleshooting

### No Detections at All

**Check:**
1. Is WWV/CHU channel configured with `is_wwv_channel=True`?
2. Is tone_detector initialized? (Log should show "tone detection ENABLED")
3. Are you capturing during good propagation times?
4. Check signal strength in files (see manual inspection above)

**Try:**
- Wait for different time of day
- Check multiple frequencies (some will always be better)
- Lower threshold temporarily to see if weak signals exist

### Too Many False Positives

**Symptoms:**
- Detections at wrong times (not on minute boundaries)
- Very short durations reported
- Timing errors >100ms

**Solutions:**
- Raise threshold (0.6-0.7)
- Check for local interference at 1000 Hz
- Verify system clock accuracy

### Timing Errors Large but Consistent

**Symptoms:**
- Detections work but error always +50ms or -50ms

**Possible Causes:**
- System clock drift
- RTP timestamp calibration issue
- Audio latency in processing chain

**Check:**
- System clock: `ntpq -p` (should be synchronized)
- Compare across multiple WWV frequencies

### Signal Present But Not Detected

**Diagnostic Steps:**

1. Run post-analysis tool to confirm tone exists
2. Check envelope strength in diagnostic output
3. If envelope < 0.01, signal may be too weak for live detection
4. Try lowering threshold or wait for better propagation

## Integration with Quality Monitoring

WWV detections provide three key quality metrics:

### 1. **Timing Accuracy**
- Measures RTP clock vs WWV reference
- Detects clock drift over time
- Typical: <50ms error for good system

### 2. **Propagation Health**  
- Detection rate indicates band conditions
- Compare across frequencies for propagation study
- No detections = poor propagation (not necessarily system fault)

### 3. **System Validation**
- Regular detections prove receiver chain working
- Multi-band comparison validates frequency response
- Timing consistency validates clock stability

## Future Enhancements

### Threshold Auto-Tuning
- Track detection rate and signal strengths
- Dynamically adjust threshold per channel
- Learn optimal settings for each band/time

### SNR Calculation
- Currently placeholder (20.0 dB)
- Calculate actual SNR from signal/noise ratio
- Use for detection confidence metric

### Tone Duration Measurement
- Currently placeholder (800.0 ms)
- Measure actual pulse width
- Validate WWV vs CHU (0.8s vs 0.5s)

### Multi-Tone Analysis
- WWV broadcasts multiple tones at different times
- Could detect 500 Hz and 600 Hz tones
- Provides redundant timing references

## References

- **NIST WWV**: https://www.nist.gov/pml/time-and-frequency-division/time-distribution/radio-station-wwv
- **NRC CHU**: https://nrc.canada.ca/en/certifications-evaluations-standards/canadas-official-time/chu-digital-time-signal
- **HF Propagation**: https://www.electronics-notes.com/articles/antennas-propagation/ionospheric/hf-propagation-basics.php

## Summary

The WWV/CHU detection system is **working correctly**. Detection success depends primarily on **propagation conditions**, which vary by time, frequency, and ionospheric state. This variability is **the phenomenon being studied**, not a system defect.

**Key Takeaways:**
- ✅ System detects strong signals reliably
- ✅ Threshold can be tuned for your environment
- ✅ Propagation variations are expected and normal
- ✅ Multiple frequencies provide redundancy
- ✅ Post-analysis confirms signal quality

**Expected Behavior:**
- Some frequencies/times: frequent detections
- Other frequencies/times: no detections (poor propagation)
- This is **normal** - you're measuring the ionosphere!
