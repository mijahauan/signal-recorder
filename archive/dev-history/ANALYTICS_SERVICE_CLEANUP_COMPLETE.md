# Analytics Service Cleanup - Complete
*Completed: November 16, 2025, 6:10 AM*

## Summary

Successfully removed all Digital RF writing code from analytics service, isolating it into standalone `drf_writer_service.py`.

## Changes Made

### Removed from `analytics_service.py`:

1. **Import:** Removed `from .digital_rf_writer import DigitalRFWriter`
2. **Initialization:** Removed `drf_writer` object creation
3. **Methods Removed:**
   - `_decimate_and_write_drf()` - Digital RF writing
   - `_write_quality_metadata_to_drf()` - Metadata writing
4. **References Removed:**
   - All `drf_writer.add_samples()` calls
   - All `drf_writer.flush()` calls
   - All `drf_writer.metadata_writer.write()` calls

### Analytics Service Now Does:

✅ **Tone Detection** - Detects WWV/CHU/WWVH tones (needs 16kHz)  
✅ **Time_snap Management** - Establishes/updates timing reference  
✅ **Quality Metrics** - Calculates completeness, packet loss, gaps  
✅ **Decimation** - Creates `*_iq_10hz.npz` files (output for DRF service)  
✅ **Discontinuity Logging** - Scientific provenance  
✅ **Discrimination** - WWV vs WWVH for dual-station channels

❌ **NO Digital RF Writing** - Moved to `drf_writer_service.py`

## Clean Pipeline

```
Core Recorder
    ↓
*_iq.npz (16 kHz raw)
    ↓
Analytics Service (tone + decimate)
    ├→ time_snap updates
    ├→ quality metrics
    └→ *_iq_10hz.npz files
         ↓
DRF Writer Service (format conversion only)
    └→ Digital RF HDF5
```

## Services Overview

### Analytics Service
**Input:** `*_iq.npz` (16 kHz raw from core recorder)  
**Output:** `*_iq_10hz.npz` (10 Hz decimated with metadata)  
**Purpose:** Tone detection, quality analysis, decimation  
**Complexity:** High (tone detection, time_snap, discrimination)

### DRF Writer Service  
**Input:** `*_iq_10hz.npz` (10 Hz from analytics)  
**Output:** Digital RF HDF5 (for PSWS upload)  
**Purpose:** Format conversion only  
**Complexity:** Low (read NPZ, write DRF)

## 10Hz NPZ Format

The analytics service already creates these files. They contain:

```python
{
    'iq_decimated': complex64,      # 10 Hz IQ samples
    'rtp_timestamp': int,            # RTP at first sample
    'sample_rate_original': 16000,
    'sample_rate_decimated': 10,
    'decimation_factor': 1600,
    'created_timestamp': float,
    'source_file': str              # Original *_iq.npz filename
}
```

## Benefits of Separation

### 1. Isolation
- Can debug/improve tone detection without touching DRF
- Can debug/improve DRF without reprocessing 16kHz data
- Each service has single, clear responsibility

### 2. Performance
- DRF processes 1600x less data (10Hz vs 16kHz)
- Faster iteration on DRF bugs
- Analytics service lighter without DRF code

### 3. Reliability
- Simpler services = fewer bugs
- DRF service is straightforward format conversion
- Analytics service focuses on signal processing

### 4. Flexibility
- Can run services on different machines
- Can stop/start independently
- Can reprocess old data with new algorithms

## Testing Plan

### 1. Verify Analytics Creates 10Hz Files
```bash
# Check that decimated files are being created
ls -lh /tmp/grape-test/archives/WWV_5_MHz/*_iq_10hz.npz | head -5
```

### 2. Test DRF Writer Standalone
```bash
# Run DRF writer on existing 10Hz files
python3 -m signal_recorder.drf_writer_service \
  --input-dir /tmp/grape-test/archives/WWV_5_MHz \
  --output-dir /tmp/grape-test/drf_test/WWV_5_MHz \
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

### 3. Verify DRF Timestamps Are Correct
```python
from pathlib import Path
from digital_rf import DigitalRFReader
from datetime import datetime, timezone

drf_path = Path('/tmp/grape-test/drf_test/WWV_5_MHz/digital_rf/20251116')
for obs_dir in drf_path.glob('*/*/OBS*'):
    reader = DigitalRFReader(str(obs_dir))
    channels = reader.get_channels()
    if channels:
        start, end = reader.get_bounds(channels[0])
        props = reader.get_properties(channels[0])
        fs = props['sample_rate_numerator'] / props['sample_rate_denominator']
        
        start_dt = datetime.fromtimestamp(start / fs, tz=timezone.utc)
        print(f"Year: {start_dt.year} (should be 2025, not 2081!)")
```

## Files Modified

- ✅ `src/signal_recorder/analytics_service.py` - Removed DRF code
- ✅ `src/signal_recorder/drf_writer_service.py` - Created standalone service
- ✅ Syntax validated - no errors

## Next Steps

1. Test DRF writer service with existing 10Hz files
2. Verify timestamps are correct (year 2025, not 2081)
3. Start both services and monitor logs
4. Regenerate spectrograms from clean DRF data

## Documentation

- **This file:** Analytics cleanup summary
- **DRF_WRITER_SERVICE_COMPLETE.md:** DRF service documentation
- **DRF_TIMESTAMP_BUG_FIX.md:** Root cause analysis of year 2081 bug
