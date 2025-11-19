# DRF Writer Service - Implementation Complete
*Created: November 16, 2025, 6:00 AM*

## Overview

Created a standalone, simple Digital RF writer service that isolates format conversion from analytics processing.

## Clean Pipeline Architecture

```
Core Recorder → Raw 16kHz NPZ → Analytics Service → 10Hz NPZ → DRF Writer → Digital RF HDF5
                  (*_iq.npz)    (tone + decimate)  (*_iq_10hz.npz)  (format only)
```

### Service Responsibilities

**Analytics Service** (processes `*_iq.npz`):
- Tone detection (needs full 16kHz bandwidth)
- Establishes/updates time_snap
- Quality metrics
- Decimation (16kHz → 10Hz)
- Outputs: `*_iq_10hz.npz` with all metadata

**DRF Writer Service** (processes `*_iq_10hz.npz`):
- Format conversion ONLY
- Loads time_snap from analytics state
- Writes Digital RF HDF5
- NO decimation, NO tone detection
- Simple, isolated, debuggable

## Key Features

### 1. Strict Chronological Processing
- Files sorted by ISO timestamp in filename
- Prevents out-of-order writes that caused year 2081 bug
- Lexicographic comparison ensures monotonic order

### 2. Backwards-Time Detection
- Checks calculated index vs next_index before write
- Skips out-of-order archives rather than corrupt timeline
- Logs warnings for investigation

### 3. Time_snap Integration
- Loads current time_snap from analytics state file
- Falls back to file creation timestamp if unavailable
- Calculates precise UTC from RTP timestamp

### 4. Stateful Processing
- Tracks last processed file by name (not mtime)
- Maintains monotonic next_index across restarts
- Saves state every 10 files

## File Format

### Input: `*_iq_10hz.npz`
```python
{
    'iq_decimated': complex64 array,      # 10 Hz IQ samples
    'rtp_timestamp': int,                  # RTP at first sample
    'sample_rate_original': 16000,         # Original rate
    'sample_rate_decimated': 10,           # Decimated rate
    'decimation_factor': 1600,
    'created_timestamp': float,            # Unix timestamp
    'source_file': str                     # Original *_iq.npz file
}
```

### Output: Digital RF HDF5
- Directory structure: `digital_rf/YYYYMMDD/STATION/RECEIVER/OBS/CHANNEL/`
- Sample rate: 10 Hz
- Compression: level 9
- Format: Complex64
- Continuous: Yes (gaps filled)

## Usage

```bash
python3 -m signal_recorder.drf_writer_service \
  --input-dir /tmp/grape-test/archives/WWV_5_MHz \
  --output-dir /tmp/grape-test/analytics/WWV_5_MHz \
  --channel-name "WWV 5 MHz" \
  --frequency-hz 5000000 \
  --analytics-state-file /tmp/grape-test/state/analytics-wwv5.json \
  --poll-interval 10.0 \
  --log-level INFO \
  --callsign AC0G \
  --grid-square EM38ww \
  --receiver-name GRAPE \
  --psws-station-id S000171 \
  --psws-instrument-id 172
```

## Benefits

### 1. Separation of Concerns
- Tone detection and decimation can be refined independently
- DRF generation is straightforward format conversion
- Each service has single, clear responsibility

### 2. Easier Debugging
- Can test DRF writer with known-good 10Hz files
- No need to reprocess 16kHz data to test DRF changes
- Logs are clearer (one service = one purpose)

### 3. Performance
- DRF writer processes 10Hz (1600x less data than 16kHz)
- Faster regeneration after bugs
- Lower memory footprint

### 4. Flexibility
- Can run services on different machines
- Can batch-process old data easily
- Can upgrade analytics without touching DRF
- Can reprocess with different decimation without DRF changes

## Next Steps

### 1. Update Analytics Service
Currently analytics service does both decimation AND DRF writing. Need to:
- Remove DRF writing code from analytics
- Keep tone detection and decimation
- Ensure it outputs proper `*_iq_10hz.npz` format

### 2. Integration Testing
- Verify analytics creates correct 10Hz format
- Verify DRF writer reads and processes correctly
- Check timestamps match (no year 2081!)

### 3. Deployment
- Start analytics services (tone + decimate)
- Start DRF writer services (format conversion)
- Monitor both independently

## File Locations

- **Service:** `src/signal_recorder/drf_writer_service.py`
- **Documentation:** This file
- **Bug fix docs:** `DRF_TIMESTAMP_BUG_FIX.md`

## Architecture Decision Rationale

**Why separate DRF writing?**

1. **Tone detection needs 16kHz** - Can't be done after decimation
2. **DRF benefits from pre-decimation** - 1600x less data to process
3. **Different iteration cycles** - Tone detection/decimation need refinement, DRF is stable
4. **Debugging isolation** - Can test each stage independently
5. **Performance** - DRF regeneration much faster with 10Hz input

This follows Unix philosophy: Each service does one thing well.
