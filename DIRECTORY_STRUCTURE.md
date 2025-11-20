# GRAPE Directory Structure - Canonical Reference

**Status:** CANONICAL - This is the single source of truth for all file paths  
**Last Updated:** 2025-11-20  
**Enforcement:** ALL code MUST use `src/signal_recorder/paths.py` GRAPEPaths API

---

## Critical Rules

1. **NO direct path construction** - Always use `GRAPEPaths` API
2. **NO ad-hoc naming** - Follow exact patterns below
3. **NO time-range suffixes** on daily files - One file per channel per day per method
4. **Mode-aware** - Paths differ between test and production modes

---

## Configuration

From `config/grape-config.toml`:

```toml
[recorder]
mode = "test"                              # or "production"
test_data_root = "/tmp/grape-test"
production_data_root = "/var/lib/signal-recorder"
```

Current mode determines `data_root` for all paths below.

---

## Complete Directory Tree

```
${data_root}/
│
├── archives/                              # Raw IQ archives (16 kHz NPZ)
│   └── {CHANNEL}/                         # e.g., WWV_5_MHz, CHU_3_33_MHz
│       └── YYYYMMDDTHHMMSSZ_{FREQ}_iq.npz
│           # Example: 20251119T120000Z_5000000_iq.npz
│           # Fields: iq (complex64), sample_rate, unix_timestamp,
│           #         rtp_timestamp, gaps_detected
│
├── analytics/                             # Per-channel analytics products
│   └── {CHANNEL}/                         # e.g., WWV_5_MHz
│       │
│       ├── decimated/                     # 10 Hz NPZ (pre-DRF)
│       │   └── YYYYMMDDTHHMMSSZ_{FREQ}_iq_10hz.npz
│       │       # Fields: iq (complex64), sample_rate, unix_timestamp
│       │
│       ├── digital_rf/                    # Digital RF format
│       │   └── {YYYYMMDD}/
│       │       └── {CALL}_{GRID}/
│       │           └── {RECEIVER}/
│       │               └── {OBS}/
│       │                   └── {CHANNEL}/
│       │                       └── rf@{TIMESTAMP}.h5
│       │
│       ├── tone_detections/               # Method 1: 1000/1200 Hz timing tones
│       │   └── {CHANNEL}_tones_YYYYMMDD.csv
│       │       # Columns: timestamp_utc, station, frequency_hz, 
│       │       #          duration_sec, timing_error_ms, snr_db,
│       │       #          tone_power_db, confidence
│       │       # One row per detected tone
│       │
│       ├── tick_windows/                  # Method 2: 5ms tick analysis
│       │   └── {CHANNEL}_ticks_YYYYMMDD.csv
│       │       # Columns: timestamp_utc, window_second,
│       │       #          coherent_wwv_snr_db, coherent_wwvh_snr_db,
│       │       #          incoherent_wwv_snr_db, incoherent_wwvh_snr_db,
│       │       #          coherence_quality_wwv, coherence_quality_wwvh,
│       │       #          integration_method, wwv_snr_db, wwvh_snr_db,
│       │       #          ratio_db, tick_count
│       │       # One row per 10-second window (6 per minute)
│       │
│       ├── station_id_440hz/              # Method 3: 440 Hz station ID
│       │   └── {CHANNEL}_440hz_YYYYMMDD.csv
│       │       # Columns: timestamp_utc, minute_number,
│       │       #          wwv_detected, wwvh_detected,
│       │       #          wwv_power_db, wwvh_power_db
│       │       # One row per detection (minutes 1 & 2 only)
│       │
│       ├── bcd_discrimination/            # Method 4: 100 Hz BCD subcarrier
│       │   └── {CHANNEL}_bcd_YYYYMMDD.csv
│       │       # Columns: timestamp_utc, window_start_sec,
│       │       #          wwv_amplitude, wwvh_amplitude,
│       │       #          differential_delay_ms, correlation_quality,
│       │       #          amplitude_ratio_db
│       │       # One row per BCD window (multiple per minute)
│       │
│       ├── discrimination/                # Method 5: Final weighted voting
│       │   └── {CHANNEL}_discrimination_YYYYMMDD.csv
│       │       # Columns: timestamp_utc, minute_timestamp, minute_number,
│       │       #          wwv_detected, wwvh_detected,
│       │       #          wwv_snr_db, wwvh_snr_db, power_ratio_db,
│       │       #          differential_delay_ms,
│       │       #          tone_440hz_wwv_detected, tone_440hz_wwv_power_db,
│       │       #          tone_440hz_wwvh_detected, tone_440hz_wwvh_power_db,
│       │       #          dominant_station, confidence,
│       │       #          tick_windows_10sec (JSON),
│       │       #          bcd_wwv_amplitude, bcd_wwvh_amplitude,
│       │       #          bcd_differential_delay_ms, bcd_correlation_quality,
│       │       #          bcd_windows (JSON)
│       │       # One row per minute
│       │
│       ├── quality/                       # Signal quality metrics
│       │   └── {CHANNEL}_quality_YYYYMMDD.csv
│       │       # Columns: timestamp, rms_power, peak_power, mean_power,
│       │       #          noise_floor, dynamic_range, clip_count
│       │
│       ├── logs/                          # Processing logs
│       │   └── analytics_YYYYMMDD.log
│       │
│       └── status/                        # Runtime status files
│           └── current_status.json
│
├── spectrograms/                          # Generated spectrogram images
│   └── {YYYYMMDD}/
│       └── {CHANNEL}_YYYYMMDD_{TYPE}_spectrogram.png
│           # TYPE: decimated, raw, etc.
│
├── state/                                 # Service state persistence
│   ├── analytics-{channel_key}.json       # Per-channel analytics state
│   │   # channel_key: wwv5, wwv10, chu3.33, etc.
│   └── core-recorder-status.json          # Core recorder state
│
└── status/                                # System-wide status
    └── analytics-service-status.json      # Analytics service health
```

---

## Channel Naming Conventions

### Human-Readable Format
Used in: Configuration, UI, function parameters
```
"WWV 10 MHz"
"WWV 5 MHz"
"WWV 2.5 MHz"
"CHU 3.33 MHz"
"WWVH 15 MHz"
```

### Directory Format
Used in: File paths, directory names
```
WWV_10_MHz
WWV_5_MHz
WWV_2_5_MHz
CHU_3_33_MHz
WWVH_15_MHz
```

### Key Format
Used in: State files, internal keys
```
wwv10
wwv5
wwv2.5
chu3.33
wwvh15
```

**Conversion Functions (in paths.py):**
- `channel_name_to_dir(name: str) -> str` - "WWV 10 MHz" → "WWV_10_MHz"
- `channel_name_to_key(name: str) -> str` - "WWV 10 MHz" → "wwv10"
- `channel_dir_to_name(dir: str) -> str` - "WWV_10_MHz" → "WWV 10 MHz"

---

## File Naming Patterns

### Archives
```
YYYYMMDDTHHMMSSZ_{FREQUENCY}_iq.npz
20251119T120000Z_5000000_iq.npz          # Correct
20251119T120000Z_5MHz_iq.npz             # WRONG - use Hz
```

### Analytics - Daily CSVs (NO time range suffixes!)
```
{CHANNEL}_{METHOD}_YYYYMMDD.csv

WWV_5_MHz_tones_20251119.csv             # Correct
WWV_5_MHz_ticks_20251119.csv             # Correct
WWV_5_MHz_440hz_20251119.csv             # Correct
WWV_5_MHz_bcd_20251119.csv               # Correct
WWV_5_MHz_discrimination_20251119.csv    # Correct

WWV_5_MHz_discrimination_20251119_12-15.csv   # WRONG - no time range
WWV_5_MHz_20251119_discrimination.csv         # WRONG - method comes before date
```

### Spectrograms
```
{CHANNEL}_YYYYMMDD_{TYPE}_spectrogram.png

WWV_5_MHz_20251119_decimated_spectrogram.png
```

### Logs
```
analytics_YYYYMMDD.log
```

---

## GRAPEPaths API Reference

All code MUST use this API. Located in `src/signal_recorder/paths.py`.

### Initialization

```python
from signal_recorder.paths import GRAPEPaths, load_paths_from_config

# From config file (recommended - respects test/production mode)
paths = load_paths_from_config('/path/to/grape-config.toml')

# Direct initialization (testing only)
paths = GRAPEPaths('/tmp/grape-test')
```

### Archive Methods

```python
paths.get_archive_dir(channel_name: str) -> Path
    # Returns: {data_root}/archives/{CHANNEL}/
    # Example: /tmp/grape-test/archives/WWV_5_MHz/

paths.get_archive_path(channel_name: str, timestamp: float, freq_hz: int) -> Path
    # Returns: {archive_dir}/{TIMESTAMP}_{FREQ}_iq.npz
    # Example: /tmp/grape-test/archives/WWV_5_MHz/20251119T120000Z_5000000_iq.npz
```

### Analytics Methods - Directories

```python
paths.get_analytics_dir(channel_name: str) -> Path
    # Returns: {data_root}/analytics/{CHANNEL}/

paths.get_decimated_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/decimated/

paths.get_digital_rf_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/digital_rf/

paths.get_tone_detections_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/tone_detections/

paths.get_tick_windows_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/tick_windows/

paths.get_station_id_440hz_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/station_id_440hz/

paths.get_bcd_discrimination_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/bcd_discrimination/

paths.get_discrimination_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/discrimination/

paths.get_quality_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/quality/

paths.get_analytics_logs_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/logs/

paths.get_analytics_status_dir(channel_name: str) -> Path
    # Returns: {analytics}/{CHANNEL}/status/
```

### Analytics Methods - Files

```python
paths.get_discrimination_csv(channel_name: str, date: str) -> Path
    # Returns: {discrimination_dir}/{CHANNEL}_discrimination_{date}.csv
    # date format: YYYYMMDD

paths.get_quality_csv(channel_name: str, date: str) -> Path
    # Returns: {quality_dir}/{CHANNEL}_quality_{date}.csv
```

### Other Methods

```python
paths.get_spectrograms_dir() -> Path
paths.get_spectrograms_date_dir(date: str) -> Path
paths.get_spectrogram_path(channel_name: str, date: str, spec_type: str) -> Path
paths.get_state_dir() -> Path
paths.get_state_file(channel_name: str) -> Path
paths.get_status_dir() -> Path
```

---

## Enforcement

### For Python Code

```python
# ✅ CORRECT - Using GRAPEPaths API
from signal_recorder.paths import load_paths_from_config

paths = load_paths_from_config()
csv_file = paths.get_discrimination_dir(channel_name) / f"{channel_dir}_discrimination_{date}.csv"
```

```python
# ❌ WRONG - Direct path construction
output_dir = Path(data_root) / 'analytics' / channel_dir / 'discrimination'
csv_file = output_dir / f"{channel_dir}_discrimination_{date}_{start_hour:02d}-{end_hour:02d}.csv"
```

### For JavaScript Code

Use `web-ui/grape-paths.js`:

```javascript
const paths = new GRAPEPaths(dataRoot);
const csvPath = paths.getDiscriminationCSV(channelName, date);
```

---

## Migration Checklist

- [ ] All Python producers use GRAPEPaths API
- [ ] All Python consumers use GRAPEPaths API  
- [ ] All JavaScript uses grape-paths.js
- [ ] No time-range suffixes on any files
- [ ] No ad-hoc directory creation
- [ ] Test mode produces correct paths
- [ ] Production mode produces correct paths
- [ ] All CSVs follow exact column ordering in this doc
- [ ] All NPZ files follow exact field naming in this doc

---

## See Also

- `docs/API_REFERENCE.md` - Function signatures and data models
- `src/signal_recorder/paths.py` - Implementation
- `web-ui/grape-paths.js` - JavaScript implementation
- `config/grape-config.toml` - Configuration
