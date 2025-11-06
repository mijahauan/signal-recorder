# WWV Timing Analysis

## Purpose
Track WWV 1000 Hz tone timing variations across multiple HF frequencies to:
1. Validate that each frequency channel is receiving **independent audio**
2. Observe **ionospheric propagation delays** that vary by frequency and time
3. Detect **clock drift** and timing issues in the recording system

## Expected Behavior

### Different Frequencies = Different Delays
WWV signals at different frequencies travel different ionospheric paths:

- **2.5 MHz**: NVIS (Near Vertical Incidence Skywave) - short path
- **5 MHz**: 1-2 hop F-layer reflection
- **10 MHz**: 1-2 hop reflection, variable path
- **15 MHz**: 1-3 hop reflection, longer path
- **20 MHz**: 2-4 hop reflection, very variable
- **25 MHz**: Often 3+ hops, longest path

**Timing errors should differ by 10-100ms between frequencies** depending on:
- Time of day (ionosphere height changes)
- Solar activity
- Geomagnetic conditions
- Season

### 24-Hour Patterns
You should see variations over 24 hours due to:
- **Day/Night transitions**: Ionosphere changes dramatically
- **Sunrise/Sunset effects**: D-layer absorption varies
- **Local noon**: Maximum ionization
- **Midnight**: Minimum ionization

## Current Issue

**All frequencies showing identical +85ms timing error** suggests:
1. **Bug**: All channels receiving same audio stream (needs investigation)
2. **Radiod configuration**: All requesting same frequency
3. **Propagation anomaly**: Highly unlikely all paths identical

## Data Collection

### CSV Log
Location: `/home/mjh/git/signal-recorder/logs/wwv_timing.csv`

Format:
```csv
timestamp,channel,frequency_mhz,timing_error_ms,detection_count,snr_estimate
1730469600,WWV 10 MHz Audio,10.0,+85.7,29,N/A
```

### Visualization
```bash
# Generate timing plots
cd /home/mjh/git/signal-recorder
python plot_wwv_timing.py
```

Output: `logs/wwv_timing_plot.png`

Shows:
1. **Timing error vs time** for each frequency (should show different traces)
2. **Distribution histogram** (should show different peaks)

## Debugging Steps

### 1. Verify Independent Channels
```bash
# Check if different frequencies get different audio
# Listen to 5 MHz and 10 MHz - they should sound DIFFERENT
# Different propagation = different fading/distortion
```

### 2. Check Radiod Configuration
```bash
# Verify each channel is requesting correct frequency
grep "Requesting PCM audio stream" logs/daemon.log | grep "WWV.*Audio"
```

### 3. Analyze Timing Data
```bash
# After 1 hour of data collection
python plot_wwv_timing.py

# Look for:
# - Different traces for each frequency
# - Timing variations over time
# - If all traces overlap → BUG
```

## Expected Results (Healthy System)

```
=== WWV Timing Statistics ===
  2.5 MHz:  100 detections, error = +65.0 ± 15.0 ms
  5.0 MHz:   98 detections, error = +75.0 ± 20.0 ms
 10.0 MHz:   95 detections, error = +85.0 ± 25.0 ms
 15.0 MHz:   90 detections, error = +95.0 ± 30.0 ms
 20.0 MHz:   50 detections, error = +110.0 ± 40.0 ms  (lower count = weaker signal)
 25.0 MHz:   30 detections, error = +130.0 ± 50.0 ms  (even weaker)
```

## Current Results (Concerning)

```
  2.5 MHz:  173 detections, error = +85.7 ms
  5.0 MHz:   30 detections, error = +85.3 ms
 10.0 MHz:   30 detections, error = +85.3 ms
 15.0 MHz:   30 detections, error = +85.3 ms
 20.0 MHz:    0 detections, error = N/A
 25.0 MHz:   16 detections, error = +85.7 ms
```

**Problem**: All frequencies ~85ms, no variation → Investigate channel independence!

## Scientific Value

Once working correctly, this data shows:
- **Real-time ionospheric conditions**
- **MUF (Maximum Usable Frequency)** estimation
- **Propagation mode changes** (1-hop vs multi-hop)
- **Timing stability** for scientific IQ data validation
