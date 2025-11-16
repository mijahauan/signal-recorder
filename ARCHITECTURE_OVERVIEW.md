# GRAPE Signal Recorder - Architecture Overview

**Last Updated:** November 16, 2025  
**Status:** Production Architecture (V2)

## Executive Summary

The GRAPE Signal Recorder uses a **three-service architecture** where data flows through specialized processing stages, with **10 Hz decimated NPZ files** serving as the central pivot point for multiple downstream consumers.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CORE RECORDER SERVICE                        │
│                   (Rock-Solid Archiving)                        │
│                                                                 │
│  Input:  ka9q-radio RTP multicast (16 kHz IQ)                 │
│  Process: Resequencing + Gap Detection + Gap Fill              │
│  Output:  {timestamp}_iq.npz (16 kHz, complete scientific      │
│           record with RTP timestamps)                           │
│  Location: archives/{channel}/                                  │
│                                                                 │
│  Responsibilities:                                              │
│  - Complete data capture (no analytics)                         │
│  - Sample count integrity                                       │
│  - RTP timestamp preservation                                   │
│  - Gap filling with zeros (maintains timing)                    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   ANALYTICS SERVICE (Per Channel)               │
│              (Tone Detection + Quality + Decimation)            │
│                                                                 │
│  Input:  16 kHz NPZ files from Core Recorder                   │
│  Process:                                                       │
│    1. Tone Detection (WWV/WWVH/CHU @ 1000/1200 Hz)            │
│    2. Time_snap Management (GPS-quality timestamp anchors)     │
│    3. Quality Metrics (completeness, packet loss, gaps)        │
│    4. WWV-H Discrimination (power ratio, differential delay,   │
│       440 Hz station ID tones)                                  │
│    5. Decimation (16 kHz → 10 Hz with embedded metadata)      │
│  Output:  {timestamp}_iq_10hz.npz (10 Hz + metadata)          │
│  Location: analytics/{channel}/decimated/                       │
│                                                                 │
│  Metadata Embedded in 10Hz NPZ:                                │
│  - Timing Quality (tone_locked / ntp_synced / wall_clock)     │
│  - Quality Metrics (completeness, packet loss, gaps)           │
│  - Tone Detections (station, SNR, timing error, confidence)    │
│                                                                 │
│  Additional Outputs:                                            │
│  - Quality CSV: analytics/{channel}/quality/*.csv              │
│  - Discrimination CSV: analytics/{channel}/discrimination/*.csv│
│  - State file: state/analytics-{channel}.json (time_snap)     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
              ┌───────────────┴──────────────┐
              ↓                              ↓
┌──────────────────────────┐  ┌────────────────────────────────┐
│   DRF WRITER SERVICE     │  │   SPECTROGRAM GENERATOR        │
│   (Format Conversion)    │  │   (Carrier Visualization)      │
│                          │  │                                │
│ Input:  10Hz NPZ files   │  │ Input:  10Hz NPZ files         │
│ Process: Format          │  │ Process: FFT spectrogram       │
│          conversion only │  │          (Doppler analysis)    │
│ Output:  Digital RF HDF5 │  │ Output:  PNG files             │
│ Location: analytics/     │  │ Location: spectrograms/        │
│           {channel}/     │  │           {YYYYMMDD}/          │
│           digital_rf/    │  │                                │
│                          │  │ Shows: ±5 Hz carrier variation │
│ Next: rsync to PSWS      │  │        (ionospheric Doppler)   │
└──────────────────────────┘  └────────────────────────────────┘
```

## Key Design Decisions

### 1. **10 Hz Decimated NPZ as Pivot Point**

**Why 10 Hz?**
- **Scientific Goal:** Detect ionospheric Doppler shifts (±5 Hz window)
- **Optimal Resolution:** 0.1 Hz frequency resolution
- **Efficient Size:** 1600x smaller than 16 kHz (60 samples/minute vs 960,000)
- **HamSCI Requirement:** PSWS repository uses 10 Hz Digital RF

**Why NPZ (not immediate Digital RF)?**
- **Single Decimation:** Performed once, consumed by multiple services
- **Embedded Metadata:** Timing/quality/tone data travels with IQ samples
- **Reprocessable:** Can regenerate Digital RF with different metadata
- **Python Native:** No external library dependencies for reading

### 2. **Separate Services for Reliability**

**Core Recorder:**
- ✅ Minimal code (~300 lines)
- ✅ Changes <5x per year
- ✅ No analytics dependencies
- ✅ Focus: Complete data capture

**Analytics Service:**
- ✅ Can restart without data loss
- ✅ Can reprocess historical data
- ✅ Independent testing with archived data
- ✅ Aggressive retry (systemd restarts safe)

**DRF Writer / Spectrogram Generator:**
- ✅ Independent from core processing
- ✅ Can run on different machines
- ✅ Can reprocess if output format changes

### 3. **Embedded Metadata in 10Hz NPZ**

Each 10 Hz NPZ file contains:

```python
{
    # Core Data
    'iq': np.ndarray,                    # Decimated IQ samples (10 Hz)
    'rtp_timestamp': int,                # RTP timestamp from source
    'sample_rate_original': 16000,
    'sample_rate_decimated': 10,
    'decimation_factor': 1600,
    'source_file': str,                  # Original 16kHz NPZ filename
    
    # Timing Metadata (for DRF quality annotations)
    'timing_metadata': {
        'quality': 'tone_locked',        # or 'ntp_synced', 'wall_clock'
        'time_snap_age_seconds': float,
        'ntp_offset_ms': float,
        'reprocessing_recommended': bool
    },
    
    # Quality Metadata (for gap/loss tracking)
    'quality_metadata': {
        'completeness_pct': float,
        'packet_loss_pct': float,
        'gaps_count': int,
        'gaps_filled': int
    },
    
    # Tone Detection Metadata (for discrimination/analysis)
    'tone_metadata': {
        'detections': [
            {
                'station': 'WWV',        # or 'WWVH', 'CHU'
                'frequency_hz': 1000,
                'timing_error_ms': float,
                'snr_db': float,
                'confidence': float
            }
        ]
    }
}
```

## Data Flow by Use Case

### Use Case 1: DRF Upload to PSWS

```
16 kHz NPZ → Analytics Service → 10 Hz NPZ → DRF Writer → Digital RF HDF5 → rsync
                  (tone + decimate)            (format only)
```

**Benefits:**
- Timing quality annotations in metadata
- Gap information preserved
- Tone detection results embedded
- Reprocessable if upload format changes

### Use Case 2: Web UI Carrier Display

```
16 kHz NPZ → Analytics Service → 10 Hz NPZ → Spectrogram → PNG
                  (tone + decimate)            (FFT analysis)
```

**Benefits:**
- Shows ionospheric Doppler (±5 Hz window)
- Much faster than processing 16 kHz
- Tone detection events visible as markers
- Gap information shown in spectrogram

### Use Case 3: WWV-H Discrimination Analysis

```
16 kHz NPZ → Analytics Service → Discrimination CSV + 10 Hz NPZ
                  (1000/1200 Hz + 440 Hz analysis)
```

**Benefits:**
- 440 Hz tone data included in CSV
- Power ratio, differential delay computed
- 10 Hz NPZ preserves carrier for Doppler analysis
- Web UI reads CSV for time-series plots

## Directory Structure

```
/tmp/grape-test/  (or /var/lib/signal-recorder in production)
├── archives/
│   └── {channel}/                # Core Recorder output
│       └── *_iq.npz              # 16 kHz, ~1 MB/minute
├── analytics/
│   └── {channel}/
│       ├── decimated/            # Analytics Service output
│       │   └── *_iq_10hz.npz     # 10 Hz, ~600 bytes/minute
│       ├── digital_rf/           # DRF Writer output
│       │   └── rf@*.h5           # Digital RF HDF5
│       ├── discrimination/       # Analytics Service output
│       │   └── *_discrimination_*.csv
│       ├── quality/              # Analytics Service output
│       │   └── *_quality.csv
│       └── status/
│           └── analytics-service-status.json
├── spectrograms/
│   └── {YYYYMMDD}/               # Spectrogram Generator output
│       └── *_carrier_spectrogram.png
└── state/
    └── analytics-{channel}.json  # Time_snap state
```

## Service Start Order

**Required:**
1. **Core Recorder** - Starts archiving immediately
2. **Analytics Service (per channel)** - Processes archives with 10s polling

**Optional (can start later or on-demand):**
3. **DRF Writer Service** - Converts 10Hz NPZ to Digital RF
4. **Spectrogram Generator** - Creates daily PNG files
5. **Web UI Monitoring Server** - Dashboard access

**Note:** Analytics can process backlog if started late. All services are independent.

## Performance Characteristics

| Service | Input Rate | CPU Usage | Memory | Bottleneck |
|---------|-----------|-----------|--------|------------|
| Core Recorder | 16k samples/s | ~5% | ~50 MB | Network I/O |
| Analytics | 1 file/min | ~10% per channel | ~100 MB | Decimation (scipy) |
| DRF Writer | 1 file/min | ~2% | ~30 MB | Disk I/O |
| Spectrogram | On-demand | ~20% (burst) | ~200 MB | FFT computation |

## Failure Recovery

### Core Recorder Crash
- **Impact:** Missing minutes in 16 kHz archives
- **Detection:** Gap in file timestamps
- **Recovery:** Automatic restart (systemd), gaps filled with zeros

### Analytics Service Crash
- **Impact:** Backlog of unprocessed 16 kHz files
- **Detection:** analytics_state.json not updating
- **Recovery:** Restart, processes backlog automatically

### DRF Writer Crash
- **Impact:** Missing Digital RF files
- **Detection:** No new HDF5 files
- **Recovery:** Restart, reprocesses unprocessed 10Hz NPZ files

### Disk Full
- **Impact:** All services stop writing
- **Detection:** Monitoring dashboard alert
- **Recovery:** Free disk space, services resume automatically

## Related Documentation

- **CONTEXT.md** - Quick reference for daily operations
- **README.md** - Installation and quick start
- **docs/API_QUICK_REFERENCE.md** - API contracts and data structures
- **ANALYTICS_SERVICE_CLEANUP_COMPLETE.md** - Service separation design
- **CORE_ANALYTICS_SPLIT_DESIGN.md** - Original architecture decision

## Version History

- **V2 (Nov 2025):** Three-service architecture with 10 Hz NPZ pivot point
- **V1 (Oct 2024):** Monolithic service with direct Digital RF writing
