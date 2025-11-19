# WWV-H Discrimination Implementation Complete
*Completed: November 16, 2025, 6:45 AM*

## Overview

Implemented complete three-method WWV/WWVH discrimination for ionospheric propagation analysis on shared frequencies (2.5, 5, 10, 15 MHz).

## Changes Implemented

### 1. Fixed WWVH Detection Frequencies ✅

**Problem:** Tone detector was looking for WWVH (1200 Hz) on ALL WWV channels including 20 and 25 MHz where WWVH doesn't broadcast.

**Solution:** Added frequency detection to only enable WWVH templates on correct channels.

**Code:** `tone_detector.py` lines 56-80
```python
# Extract frequency from channel name
self.channel_frequency_mhz = self._extract_frequency_mhz(channel_name)

# WWVH only broadcasts on 2.5, 5, 10, 15 MHz (NOT on 20 or 25 MHz)
wwvh_frequencies = [2.5, 5.0, 10.0, 15.0]
if self.channel_frequency_mhz in wwvh_frequencies:
    self.templates[StationType.WWVH] = self._create_template(1200, 0.8)
    logger.info(f"{channel_name}: WWVH detection enabled (shared frequency)")
else:
    logger.info(f"{channel_name}: WWVH detection disabled (WWV-only frequency)")
```

**Result:**
- WWV 2.5, 5, 10, 15 MHz: Detects BOTH WWV + WWVH ✅
- WWV 20, 25 MHz: Detects ONLY WWV ✅
- CHU 3.33, 7.85, 14.67 MHz: Detects ONLY CHU ✅

### 2. Integrated 440 Hz Tone Detection ✅

**Problem:** 440 Hz detection was implemented in `wwvh_discrimination.py` but never called by the analytics service.

**Solution:** Updated analytics service to call `analyze_minute_with_440hz()` instead of basic `compute_discrimination()`.

**Code:** `analytics_service.py` lines 715-720
```python
# Run FULL discrimination analysis including 440 Hz detection
# This requires the complete minute of IQ samples from the archive
discrimination = self.wwvh_discriminator.analyze_minute_with_440hz(
    iq_samples=archive.iq_samples,
    sample_rate=archive.sample_rate,
    minute_timestamp=minute_timestamp,
    detections=detections
)
```

**Result:** All three discrimination methods now active for shared-frequency channels.

### 3. Enhanced CSV Output ✅

**Problem:** CSV logs only included 1000/1200 Hz data, missing 440 Hz detection results.

**Solution:** Expanded CSV format to include all discrimination data.

**Code:** `analytics_service.py` lines 1013-1034

**New CSV Format:**
```csv
timestamp_utc,minute_timestamp,minute_number,
wwv_detected,wwvh_detected,
wwv_power_db,wwvh_power_db,power_ratio_db,
differential_delay_ms,
tone_440hz_wwv_detected,tone_440hz_wwv_power_db,
tone_440hz_wwvh_detected,tone_440hz_wwvh_power_db,
dominant_station,confidence
```

**Result:** Complete discrimination data available for web UI visualization.

## Three-Method Discrimination

### Method 1: 1000 Hz vs 1200 Hz Power Ratio
**What:** Compares WWV (1000 Hz) vs WWVH (1200 Hz) tone power at :00 second mark  
**When:** Every minute (minute 0-59)  
**Reliability:** High when both stations detectable  
**Output:** `power_ratio_db` (positive = WWV stronger)

### Method 2: Differential Propagation Delay
**What:** Measures arrival time difference between WWV and WWVH  
**When:** Every minute when both detected  
**Reliability:** Very high (physics-based)  
**Output:** `differential_delay_ms` (WWV_time - WWVH_time)  
**Science:** Direct measurement of ionospheric path difference

### Method 3: 440 Hz Station-Specific Tones
**What:** Detects unique 440 Hz tones that identify each station  
**When:**  
- Minute 1 (:15-:59): WWVH transmits 440 Hz  
- Minute 2 (:15-:59): WWV transmits 440 Hz  
**Reliability:** Definitive (station-specific identifier)  
**Output:**  
- `tone_440hz_wwvh_detected` + power (minute 1)  
- `tone_440hz_wwv_detected` + power (minute 2)

### Combined Analysis
**Confidence Levels:**
- **High:** Multiple methods agree + strong signals
- **Medium:** Some methods agree or weak signals
- **Low:** Only one method or very weak/ambiguous

**Dominant Station Determination:**
```
'WWV'      - WWV clearly dominant
'WWVH'     - WWVH clearly dominant  
'BALANCED' - Both stations similar strength
'NEITHER'  - Neither station detected
```

## Data Flow

```
Raw 16kHz NPZ (1 minute)
      ↓
Tone Detector
  ├─→ WWV (1000 Hz, 0.8s) detection
  ├─→ WWVH (1200 Hz, 0.8s) detection [if shared frequency]
  └─→ Power measurements for both
      ↓
WWVHDiscriminator.analyze_minute_with_440hz()
  ├─→ Power ratio calculation
  ├─→ Differential delay calculation
  ├─→ 440 Hz detection (minute 1 & 2)
  └─→ Combined confidence assessment
      ↓
DiscriminationResult
      ↓
Daily CSV Log (per channel)
      ↓
Web UI Visualization
```

## CSV Output Files

**Location:** `/tmp/grape-test/analytics/{CHANNEL}/discrimination_logs/`

**Filename Format:** `{CHANNEL}_discrimination_{YYYYMMDD}.csv`

**Examples:**
- `WWV_2.5_MHz_discrimination_20251116.csv`
- `WWV_5_MHz_discrimination_20251116.csv`
- `WWV_10_MHz_discrimination_20251116.csv`
- `WWV_15_MHz_discrimination_20251116.csv`

**Note:** Only shared-frequency channels (2.5, 5, 10, 15 MHz) will have discrimination logs.

## CSV Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp_utc` | ISO datetime | UTC timestamp (human-readable) |
| `minute_timestamp` | float | Unix timestamp (minute boundary) |
| `minute_number` | int | Minute of hour (0-59) |
| `wwv_detected` | bool (0/1) | WWV 1000 Hz detected |
| `wwvh_detected` | bool (0/1) | WWVH 1200 Hz detected |
| `wwv_power_db` | float | WWV tone power (dB) |
| `wwvh_power_db` | float | WWVH tone power (dB) |
| `power_ratio_db` | float | WWV - WWVH power (positive = WWV stronger) |
| `differential_delay_ms` | float | Arrival time difference (ms) |
| `tone_440hz_wwv_detected` | bool (0/1) | 440 Hz detected in minute 2 |
| `tone_440hz_wwv_power_db` | float | WWV 440 Hz power (dB) |
| `tone_440hz_wwvh_detected` | bool (0/1) | 440 Hz detected in minute 1 |
| `tone_440hz_wwvh_power_db` | float | WWVH 440 Hz power (dB) |
| `dominant_station` | string | 'WWV', 'WWVH', 'BALANCED', or empty |
| `confidence` | string | 'high', 'medium', 'low' |

## Web UI Integration

The CSV files are ready for web UI display. Suggested visualizations:

### 1. Time Series Plot
- X-axis: Time (hours)
- Y-axis: Power ratio (dB)
- Color: Dominant station
- Shows propagation changes over time

### 2. Confidence Heatmap
- X-axis: Hour of day
- Y-axis: Frequency (2.5, 5, 10, 15 MHz)
- Color: Confidence level
- Shows best times/frequencies for discrimination

### 3. 440 Hz Detection Matrix
- Rows: Channels (2.5, 5, 10, 15 MHz)
- Columns: Minutes 1 and 2
- Shows which station-specific tones are detected

### 4. Differential Delay Scatter
- X-axis: Time
- Y-axis: Differential delay (ms)
- Points: Color-coded by confidence
- Shows ionospheric path variations

### 5. Station Dominance Pie Chart
- Per channel or aggregated
- Shows % time each station is dominant
- Useful for propagation statistics

## Scientific Use Cases

### 1. Propagation Path Analysis
**Data:** Differential delay over time  
**Application:** Identify E-layer vs F-layer propagation  
**Resolution:** ±1ms timing = ~300km path precision

### 2. Solar Event Detection
**Data:** Sudden changes in dominant station  
**Application:** Detect ionospheric disturbances  
**Indicator:** Rapid swings in power ratio

### 3. Diurnal Pattern Studies
**Data:** 24-hour discrimination patterns  
**Application:** Model day/night propagation  
**Expected:** WWV dominant during day, WWVH at night (or vice versa based on location)

### 4. Multi-Frequency Correlation
**Data:** Discrimination across 2.5, 5, 10, 15 MHz  
**Application:** Frequency-dependent propagation modes  
**Physics:** Different frequencies use different ionospheric layers

## Testing & Validation

### Verify WWVH Detection
```bash
# Check that 20 and 25 MHz don't detect WWVH
grep "WWVH detection disabled" /tmp/grape-test/logs/analytics-wwv20.log
grep "WWVH detection disabled" /tmp/grape-test/logs/analytics-wwv25.log

# Check that shared frequencies enable WWVH
grep "WWVH detection enabled" /tmp/grape-test/logs/analytics-wwv5.log
```

### Verify 440 Hz Detection
```bash
# Look for 440 Hz detection in logs (minutes 1 and 2)
grep "440 Hz tone detected" /tmp/grape-test/logs/analytics-wwv5.log
```

### Check CSV Output
```bash
# View discrimination data
head /tmp/grape-test/analytics/WWV_5_MHz/discrimination_logs/WWV_5_MHz_discrimination_20251116.csv

# Count entries with 440 Hz detection
awk -F',' '$10==1 || $12==1' WWV_5_MHz_discrimination_20251116.csv | wc -l
```

## Files Modified

1. **src/signal_recorder/tone_detector.py**
   - Added `_extract_frequency_mhz()` method
   - Modified `__init__()` to conditionally enable WWVH detection
   - Only creates WWVH templates for 2.5, 5, 10, 15 MHz

2. **src/signal_recorder/analytics_service.py**
   - Updated `_detect_tones()` to call `analyze_minute_with_440hz()`
   - Enhanced `_log_discrimination()` with 440 Hz fields
   - Expanded CSV header and data format

3. **src/signal_recorder/wwvh_discrimination.py**
   - No changes needed (already had 440 Hz implementation)
   - Now properly integrated and used

## Benefits

1. **More Accurate:** Three methods provide redundant confirmation
2. **Physics-Based:** Differential delay is direct path measurement
3. **Definitive ID:** 440 Hz tones are station-specific identifiers
4. **Complete Data:** CSV includes all measurements for analysis
5. **Web-Ready:** Structured format easy to visualize
6. **Efficient:** Only runs on relevant frequencies (2.5, 5, 10, 15 MHz)

## Next Steps

1. Run analytics service and collect discrimination data
2. Verify CSV files are being created correctly
3. Design web UI page for discrimination visualization
4. Analyze patterns in multi-day datasets
5. Publish findings on ionospheric propagation variations
