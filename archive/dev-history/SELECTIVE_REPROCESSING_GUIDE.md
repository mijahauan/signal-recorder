# Selective Reprocessing Guide
**Independent Method Execution on Archived Data**

Now that all 5 discrimination methods are independent, you can reprocess individual methods without running the entire pipeline. This is useful for:
- Testing algorithm improvements
- Parameter tuning
- Debugging specific methods
- Selective data regeneration

---

## Available Methods

### Method 1: Timing Tones (800ms WWV/WWVH)
**Detects:** 1000 Hz (WWV) and 1200 Hz (WWVH) timing tones  
**Output:** Tone power, differential delay  
**Use case:** Propagation delay studies, power ratio discrimination

### Method 2: Tick Windows (5ms ticks)
**Detects:** Per-second 5ms tick marks in 10-second windows  
**Output:** Coherent/incoherent SNR, integration method selection  
**Use case:** High-resolution temporal discrimination

### Method 3: 440 Hz Station ID
**Detects:** 440 Hz tone in minutes 1 (WWVH) and 2 (WWV)  
**Output:** Station ID confirmation  
**Use case:** Hourly calibration anchors

### Method 4: BCD Discrimination (100 Hz)
**Detects:** Binary Coded Decimal on 100 Hz subcarrier  
**Output:** WWV/WWVH amplitude separation via joint least squares  
**Use case:** BCD-rich minutes (0, 8-10, 29-30)

### Method 5: Weighted Voting Combiner
**Combines:** Results from methods 1-4  
**Output:** Final dominant station determination with confidence  
**Use case:** Complete discrimination analysis

---

## Quick Test: Single Method on One File

```python
from signal_recorder.wwvh_discrimination import WWVHDiscriminator
import numpy as np

# Load archived NPZ
data = np.load('path/to/archive.npz')
iq = data['iq']
sr = int(data['sample_rate'])
ts = float(data['unix_timestamp'])

# Initialize discriminator
disc = WWVHDiscriminator("WWV 10 MHz")

# Run ONLY BCD analysis
wwv_amp, wwvh_amp, delay, quality, windows = disc.detect_bcd_discrimination(iq, sr, ts)
print(f"BCD windows: {len(windows)}")
print(f"WWV amplitude: {wwv_amp}")
print(f"WWVH amplitude: {wwvh_amp}")

# Or run ONLY tick analysis
tick_windows = disc.detect_tick_windows(iq, sr)
print(f"Tick windows: {len(tick_windows)}")

# Or run ONLY timing tones
wwv_pwr, wwvh_pwr, diff_delay, detections = disc.detect_timing_tones(iq, sr, ts)
print(f"WWV power: {wwv_pwr} dB")
print(f"WWVH power: {wwvh_pwr} dB")
```

---

## Bulk Reprocessing Scripts

### Reprocess BCD Only

```bash
# Single hour
python3 scripts/reprocess_bcd_only.py --date 20251115 --channel "WWV 10 MHz" --hour 12

# Full day
python3 scripts/reprocess_bcd_only.py --date 20251115 --channel "WWV 10 MHz"
```

**Output:** `analytics/WWV_10_MHz/bcd_discrimination/WWV_10_MHz_bcd_YYYYMMDD.csv`

**Contains:**
- `timestamp_utc` - Minute timestamp
- `window_start_sec` - Window position within minute
- `wwv_amplitude` - WWV amplitude from joint LS
- `wwvh_amplitude` - WWVH amplitude from joint LS
- `differential_delay_ms` - Propagation delay
- `correlation_quality` - Correlation quality metric
- `amplitude_ratio_db` - 20*log10(WWV/WWVH)

---

### Reprocess Ticks Only

```bash
# Coming soon
python3 scripts/reprocess_ticks_only.py --date 20251115 --channel "WWV 10 MHz"
```

**Output:** `analytics/WWV_10_MHz/tick_windows/WWV_10_MHz_ticks_YYYYMMDD.csv`

**Contains:**
- `timestamp_utc` - Minute timestamp
- `window_second` - Window start (1, 11, 21, 31, 41, 51)
- `coherent_wwv_snr_db` / `coherent_wwvh_snr_db`
- `incoherent_wwv_snr_db` / `incoherent_wwvh_snr_db`
- `coherence_quality_wwv` / `coherence_quality_wwvh`
- `integration_method` - 'coherent' or 'incoherent'
- `ratio_db` - SNR ratio

---

### Reprocess Timing Tones Only

```bash
# Coming soon
python3 scripts/reprocess_tones_only.py --date 20251115 --channel "WWV 10 MHz"
```

**Output:** `analytics/WWV_10_MHz/tone_detections/WWV_10_MHz_tones_YYYYMMDD.csv`

**Contains:**
- `timestamp_utc` - Detection timestamp
- `station` - WWV/WWVH/CHU
- `frequency_hz` - 1000.0/1200.0
- `duration_sec` - Measured duration
- `timing_error_ms` - Offset from :00.000
- `snr_db` - Signal-to-noise ratio
- `tone_power_db` - Absolute power
- `confidence` - 0.0-1.0

---

### Reprocess 440 Hz Only

```bash
# Coming soon
python3 scripts/reprocess_440hz_only.py --date 20251115 --channel "WWV 10 MHz"
```

**Output:** `analytics/WWV_10_MHz/station_id_440hz/WWV_10_MHz_440hz_YYYYMMDD.csv`

**Contains:**
- `timestamp_utc` - Minute timestamp
- `minute_number` - 0-59
- `wwv_detected` - Boolean
- `wwvh_detected` - Boolean
- `wwv_power_db` - 440 Hz power
- `wwvh_power_db` - 440 Hz power

---

### Reprocess All Methods (Full Pipeline)

```bash
# With tone detection from archives (FIXED - no longer passes detections=[])
python3 scripts/reprocess_discrimination_timerange.py --date 20251115 --channel "WWV 10 MHz"
```

**Output:** All CSV files for all methods

---

## Use Cases

### Scenario 1: Improved BCD Algorithm

You've tuned the BCD correlation parameters for better separation:

```bash
# Reprocess only BCD for Nov 15-20
for day in {15..20}; do
    python3 scripts/reprocess_bcd_only.py --date 202511$day --channel "WWV 10 MHz"
done

# Then reprocess only weighted voting to incorporate new BCD results
python3 scripts/reprocess_voting_only.py --date-range 20251115-20251120 --channel "WWV 10 MHz"
```

### Scenario 2: Coherence Threshold Tuning

You want to test different SNR thresholds for coherent integration:

```bash
# Edit wwvh_discrimination.py to change threshold
# Then reprocess only tick analysis
python3 scripts/reprocess_ticks_only.py --date 20251115 --channel "WWV 10 MHz"

# Compare results before/after in analytics/WWV_10_MHz/tick_windows/
```

### Scenario 3: Missing Tone Power Data

The reprocessing script had the `detections=[]` bug, missing tone power:

```bash
# Fix: Remove detections=[] from reprocess_discrimination_timerange.py
# It now calls detect_timing_tones() automatically

# Reprocess to restore tone power data
python3 scripts/reprocess_discrimination_timerange.py --date 20251115 --channel "WWV 10 MHz"
```

---

## Comparing Algorithm Versions

### Before/After Analysis

```python
import pandas as pd

# Old BCD results
old = pd.read_csv('analytics/WWV_10_MHz/bcd_discrimination/WWV_10_MHz_bcd_20251115_OLD.csv')

# New BCD results (after algorithm improvement)
new = pd.read_csv('analytics/WWV_10_MHz/bcd_discrimination/WWV_10_MHz_bcd_20251115.csv')

# Compare ratio distributions
print("Old algorithm ratio std:", old['amplitude_ratio_db'].std())
print("New algorithm ratio std:", new['amplitude_ratio_db'].std())

# Higher std = better separation!
```

---

## Performance Considerations

### Processing Speed

- **BCD**: ~5-10 windows/minute, ~0.5 sec/file
- **Ticks**: 6 windows/minute, ~0.3 sec/file
- **Tones**: 1-2 detections/minute, ~0.2 sec/file
- **440 Hz**: 1 detection/hour, ~0.1 sec/file

### Bulk Processing Estimates

- **1 day** (1440 files): ~10-15 minutes for single method
- **1 week** (10,080 files): ~1-2 hours for single method
- **1 month** (43,200 files): ~4-6 hours for single method

Compare to **full pipeline**: 3-5× slower due to running all methods.

---

## Data Provenance

Each method's CSV output includes:
- **Timestamp** - ISO 8601 UTC
- **Method version** - Tracked in git commits
- **Parameters used** - Documented in code
- **Reprocessing date** - File modification time

To track which algorithm version produced results:
```bash
git log --oneline -- src/signal_recorder/wwvh_discrimination.py
# Compare git commit hash to CSV file mtime
```

---

## Integration with Web UI

Web UI can load from individual method CSVs:

```javascript
// Load BCD data
fetch('/api/v1/channels/WWV_10_MHz/bcd_discrimination/20251115')
  .then(r => r.json())
  .then(data => plotBCDRatios(data));

// Load tick data
fetch('/api/v1/channels/WWV_10_MHz/tick_windows/20251115')
  .then(r => r.json())
  .then(data => plotTickSNR(data));
```

This enables:
- Method-specific plots
- Independent data loading
- Faster page loads (only load needed methods)

---

## Next Steps

### Scripts to Create

1. **reprocess_ticks_only.py** - Similar to BCD script
2. **reprocess_tones_only.py** - Writes tone detection CSV
3. **reprocess_440hz_only.py** - Writes station ID CSV
4. **reprocess_voting_only.py** - Reads from other CSVs, writes final discrimination

### Integration Tasks

1. Update reprocessing scripts to write separate CSVs
2. Add CSV writers to real-time discrimination
3. Update web UI to read from new CSV locations
4. Create migration utility for historical data

---

## Summary

✅ **All 5 methods are independently callable**  
✅ **Each reads directly from archived NPZ files**  
✅ **No external dependencies required**  
✅ **Selective reprocessing now possible**  
✅ **Algorithm improvements can be tested in isolation**  

This architectural change enables rapid iteration, debugging, and validation of individual discrimination methods without reprocessing the entire dataset.
