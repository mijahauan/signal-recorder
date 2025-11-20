# WWV/WWVH Discrimination Refactoring Plan
**Date:** 2025-11-20  
**Status:** APPROVED - Ready for Implementation

## Objective
Refactor discrimination analysis from a monolithic system into independent, testable, reprocessable methods with clear data storage paths.

## Current Problems
1. **Monolithic coupling** - All methods bundled in `analyze_minute_with_440hz()`
2. **External dependencies** - Tone detections passed in, not reproducible
3. **Single output file** - Cannot reprocess individual methods
4. **No provenance** - Can't track which method version produced results
5. **Missing tone data in reprocessing** - Archives don't preserve detections

## Design Principles

### Foundation Layer (Unchanged)
- **Input:** RTP stream from ka9q-radio
- **Process:** Time_snap/gap analysis + 16 kHz IQ storage
- **Output:** `archives/{channel}/YYYYMMDDTHHMMSSZ_{freq}_iq.npz`

### Independent Analysis Methods (NEW)
Each method:
- Reads ONLY from foundation archives (16 kHz NPZ)
- Writes to its own analytics directory
- Has stable input/output API
- Is independently reprocessable
- Stores results in both NPZ (provenance) and CSV (analysis)

---

## New Directory Structure

```
/tmp/grape-test/
├── archives/                       # ARCHIVE: 16 kHz IQ foundation
│   └── {channel}/
│       └── YYYYMMDDTHHMMSSZ_{freq}_iq.npz
│           Fields:
│             - iq: complex64 array (16 kHz, 60 seconds = ~960k samples)
│             - sample_rate: 16000
│             - unix_timestamp: float
│             - timing_metadata: {quality, time_snap_age_ms, source_station}
│             - quality_metadata: {completeness_pct, gaps_count, gaps_filled}
│             - tone_metadata: {detections: [station, freq, snr, power, ...]}
│
├── upload/                         # UPLOAD: 10 Hz decimated products
│   └── {channel}/
│       ├── decimated/
│       │   └── YYYYMMDDTHHMMSSZ_{freq}_iq_10hz.npz
│       │       Fields:
│       │         - iq: complex64 array (10 Hz decimated)
│       │         - sample_rate: 10
│       │         - decimation_factor: 1600
│       │         - timing_metadata: (inherited from 16 kHz)
│       │         - quality_metadata: (inherited from 16 kHz)
│       │
│       └── digital_rf/             # DRF format for GRAPE upload
│
└── analytics/                      # ANALYSES: Method-specific outputs
    └── {channel}/
        ├── tone_detections/        # Method 1: 800ms timing tones
        │   └── {channel}_tones_YYYYMMDD.csv
        │       Columns:
        │         - timestamp_utc: ISO format
        │         - station: WWV/WWVH/CHU
        │         - frequency_hz: 1000.0/1200.0
        │         - duration_sec: measured duration
        │         - timing_error_ms: offset from expected :00.000
        │         - snr_db: signal-to-noise ratio
        │         - tone_power_db: absolute power (for discrimination)
        │         - confidence: 0.0-1.0
        │         - use_for_time_snap: boolean
        │
        ├── tick_windows/           # Method 2: 5ms tick marks (10-sec windows)
        │   └── {channel}_ticks_YYYYMMDD.csv
        │       Columns:
        │         - timestamp_utc: minute timestamp
        │         - window_second: 1, 11, 21, 31, 41, 51
        │         - coherent_wwv_snr_db: coherent integration SNR
        │         - coherent_wwvh_snr_db: coherent integration SNR
        │         - incoherent_wwv_snr_db: incoherent integration SNR
        │         - incoherent_wwvh_snr_db: incoherent integration SNR
        │         - coherence_quality_wwv: phase stability 0-1
        │         - coherence_quality_wwvh: phase stability 0-1
        │         - integration_method: 'coherent'/'incoherent'
        │         - wwv_snr_db: best SNR (from chosen method)
        │         - wwvh_snr_db: best SNR (from chosen method)
        │         - ratio_db: wwv_snr - wwvh_snr
        │         - tick_count: 10 for windows 0-4, 9 for window 5
        │
        ├── station_id_440hz/       # Method 3: 440 Hz station ID (hourly)
        │   └── {channel}_440hz_YYYYMMDD.csv
        │       Columns:
        │         - timestamp_utc: minute timestamp
        │         - minute_number: 0-59 (1=WWVH, 2=WWV)
        │         - wwv_detected: boolean
        │         - wwvh_detected: boolean
        │         - wwv_power_db: power at 440 Hz
        │         - wwvh_power_db: power at 440 Hz
        │
        ├── bcd_discrimination/     # Method 4: 100 Hz BCD windows
        │   └── {channel}_bcd_YYYYMMDD.csv
        │       Columns:
        │         - timestamp_utc: minute timestamp
        │         - window_start_sec: 0.0-59.0 (in 10-sec steps)
        │         - wwv_amplitude: joint LS estimate
        │         - wwvh_amplitude: joint LS estimate
        │         - differential_delay_ms: time offset
        │         - correlation_quality: 0-1
        │         - amplitude_ratio_db: 20*log10(wwv/wwvh)
        │
        ├── discrimination/         # Method 5: Weighted voting combiner
        │   └── {channel}_discrimination_YYYYMMDD.csv
        │       Columns:
        │         - timestamp_utc: minute timestamp
        │         - dominant_station: WWV/WWVH/BALANCED/NONE
        │         - confidence: low/medium/high
        │         - method_weights: JSON showing contribution of each method
        │         - minute_type: normal/bcd_rich/station_id/etc
        │
        ├── quality/                # Existing quality analysis
        └── logs/                   # Existing logs
```

---

## Method API Specifications

### Method 1: Tone Detection (800ms timing tones)

**Function:** `ToneDetector.detect_tones()`

**Input:**
- 16 kHz NPZ from `archives/{channel}/`

**Output:**
- Embedded in NPZ: `tone_metadata['detections']`
- CSV: `analytics/{channel}/tone_detections/{channel}_tones_YYYYMMDD.csv`

**Purpose:**
- Provides time_snap updates for real-time timing
- Provides tone power for discrimination weighted voting

**Code Location:** `src/signal_recorder/tone_detector.py`

---

### Method 2: Tick Window Analysis (5ms ticks)

**Function:** `WWVHDiscriminator.detect_tick_windows()`

**Input:**
- 16 kHz NPZ from `archives/{channel}/`

**Output:**
- CSV: `analytics/{channel}/tick_windows/{channel}_ticks_YYYYMMDD.csv`

**Purpose:**
- Coherent vs. incoherent integration SNR comparison
- Per-second discrimination data (6 windows × 10 seconds)

**Code Location:** `src/signal_recorder/wwvh_discrimination.py:532`

---

### Method 3: 440 Hz Station ID

**Function:** `WWVHDiscriminator.detect_440hz_tone()`

**Input:**
- 16 kHz NPZ from `archives/{channel}/`
- Minute number (0-59)

**Output:**
- CSV: `analytics/{channel}/station_id_440hz/{channel}_440hz_YYYYMMDD.csv`

**Purpose:**
- Highest-weight discrimination in minutes 1 (WWVH) and 2 (WWV)

**Code Location:** `src/signal_recorder/wwvh_discrimination.py:482`

---

### Method 4: BCD Discrimination (100 Hz subcarrier)

**Function:** `WWVHDiscriminator.detect_bcd_discrimination()`

**Input:**
- 16 kHz NPZ from `archives/{channel}/`
- Minute timestamp (for BCD template generation)

**Output:**
- CSV: `analytics/{channel}/bcd_discrimination/{channel}_bcd_YYYYMMDD.csv`

**Purpose:**
- Joint least squares amplitude separation
- Highest-weight discrimination in BCD-rich minutes (0, 8-10, 29-30)

**Code Location:** `src/signal_recorder/wwvh_discrimination.py:858`

---

### Method 5: Weighted Voting Combiner

**Function:** `WWVHDiscriminator.finalize_discrimination()`

**Input:**
- Results from Methods 1-4 (CSV files)
- Minute number (for weighting logic)

**Output:**
- CSV: `analytics/{channel}/discrimination/{channel}_discrimination_YYYYMMDD.csv`

**Purpose:**
- Combines all discrimination signals with minute-specific weights
- Final determination of dominant station and confidence

**Code Location:** `src/signal_recorder/wwvh_discrimination.py:284`

---

## Implementation Plan

### Phase 1: Create Directory Structure
- Create new analytics subdirectories
- Update path configuration

### Phase 2: Refactor Code - Method Writers
- Extract each method to write its own CSV
- Add tone_metadata to NPZ archives
- Maintain backward compatibility during transition

### Phase 3: Update Reprocessing Scripts
- Modify to run tone detection from archives
- Write to all new CSV locations
- Remove dependency on external detections

### Phase 4: Update Web UI
- Point to new CSV paths
- Handle both old and new formats during migration

### Phase 5: Migration Utilities
- Script to split existing monolithic CSVs
- Verify data integrity after migration

### Phase 6: Testing & Validation
- Verify each method independently
- Confirm weighted voting matches previous results
- Validate reprocessing produces identical output

---

## Migration Strategy

### Backward Compatibility
During transition, support BOTH:
- Old: Single `discrimination/` CSV with all data
- New: Separate CSVs per method

### Migration Script
```bash
scripts/migrate_discrimination_data.py --date YYYYMMDD --channel "WWV 10 MHz"
```

Reads existing monolithic CSV and splits into:
- tone_detections/
- tick_windows/
- station_id_440hz/
- bcd_discrimination/
- discrimination/ (final results only)

---

## Benefits Summary

✅ **Independent reprocessing** - Improve one method without rerunning all  
✅ **Clear APIs** - Each method has defined inputs/outputs  
✅ **Testable units** - Easy to validate each method independently  
✅ **Data provenance** - Track which version produced which results  
✅ **Reproducibility** - Archives contain complete detection metadata  
✅ **Storage efficiency** - No duplication of intermediate results  
✅ **Easier debugging** - Isolate problems to specific methods  
✅ **Future-proof** - Add new methods without changing existing ones  

---

## Next Steps

1. **Review and approve** this plan
2. **Create directory structure** in `/tmp/grape-test`
3. **Implement Method 1** (tone detection CSV writer)
4. **Implement Method 2** (tick windows CSV writer)
5. **Implement Method 3** (440 Hz CSV writer)
6. **Implement Method 4** (BCD CSV writer)
7. **Implement Method 5** (weighted voting reader/combiner)
8. **Update reprocessing scripts** to use new structure
9. **Create migration utilities**
10. **Update web UI** to read from new paths
