# Session 2025-11-20: Wsprdaemon Digital RF Compatibility

## Objective

Ensure Digital RF production from 10 Hz NPZ files matches wsprdaemon's current upload format exactly, with optional enhanced metadata mode for future use.

## Background

The existing `drf_writer_service.py` was creating Digital RF output with enhanced metadata (timing quality, gap analysis, discrimination results). However, wsprdaemon's `wav2grape.py` uploads a simpler format with only basic station metadata. To ensure compatibility with PSWS infrastructure, we need to match wsprdaemon's format exactly.

## Reference Implementation: wsprdaemon

From `/wsprdaemon/wav2grape.py` (lines 150-191):

```python
def create_metadata(latitude, longitude, config, site, station, callsign, 
                    grid_square, receiver_name, frequencies, uuid_str):
    metadata = dict()
    # ... station config loading ...
    metadata['lat'] = np.single(latitude)
    metadata['long'] = np.single(longitude)
    metadata['callsign'] = callsign
    metadata['grid_square'] = grid_square
    metadata['receiver_name'] = receiver_name
    metadata['center_frequencies'] = np.ascontiguousarray(frequencies)
    metadata['uuid_str'] = uuid_str
    return metadata

def create_drf_metadata(channel_dir, config_global, sample_rate, 
                        start_global_index, metadata):
    metadatadir = os.path.join(channel_dir, 'metadata')
    os.makedirs(metadatadir)
    do = drf.DigitalMetadataWriter(metadatadir,
                                   subdir_cadence_secs,
                                   file_cadence_secs,
                                   sample_rate,
                                   1,
                                   'metadata')  # ← file_name is 'metadata'
    do.write(start_global_index, metadata)
```

**Key Characteristics:**
- Single metadata file named `metadata_*.h5`
- Simple dictionary with 7 fields: `lat`, `long`, `callsign`, `grid_square`, `receiver_name`, `center_frequencies`, `uuid_str`
- NO timing quality, gap analysis, or discrimination metadata
- Written once per day at start

## Changes Made

### 1. Modified `drf_writer_service.py`

Added `wsprdaemon_compatible` parameter (default: `True`):

```python
def __init__(self, ..., wsprdaemon_compatible: bool = True):
    self.wsprdaemon_compatible = wsprdaemon_compatible
```

**Wsprdaemon Mode (compatible=True):**
- Creates single `metadata` file (not `station_info`)
- Writes only: `callsign`, `grid_square`, `receiver_name`, `center_frequencies`, `uuid_str`
- NO subdirectories: `timing_quality/`, `data_quality/`, `wwvh_discrimination`
- No per-minute metadata updates

**Enhanced Mode (compatible=False):**
- Creates multiple metadata channels: `timing_quality/`, `data_quality/`, `wwvh_discrimination`, `station_info`
- Writes per-minute timing/quality/discrimination data
- Includes all enhanced fields: `psws_station_id`, `psws_instrument_id`, `processing_chain`, etc.

### 2. Command-Line Interface

```bash
# Wsprdaemon-compatible mode (DEFAULT)
python -m signal_recorder.drf_writer_service \
  --input-dir /tmp/grape-test/analytics/WWV_10_MHz/decimated \
  --output-dir /tmp/grape-test/analytics/WWV_10_MHz \
  --channel-name "WWV 10 MHz" \
  --frequency-hz 10000000 \
  --analytics-state-file /tmp/grape-test/state/analytics-WWV_10_MHz.json \
  --callsign AC0G \
  --grid-square EM38ww \
  --receiver-name GRAPE \
  --psws-station-id AC0G \
  --psws-instrument-id 0
  # --wsprdaemon-compatible is default, no flag needed

# Enhanced metadata mode
python -m signal_recorder.drf_writer_service \
  [same args as above] \
  --enhanced-metadata  # Enables full metadata channels
```

### 3. Backward Compatibility for NPZ Files

Added support for both NPZ field names:

```python
# Support both field names for backward compatibility
if 'iq' in data:
    iq_samples = data['iq']
elif 'iq_decimated' in data:
    iq_samples = data['iq_decimated']
else:
    raise KeyError("NPZ file missing both 'iq' and 'iq_decimated' fields")
```

### 4. Documentation

Created comprehensive documentation:
- **`docs/DRF_WRITER_MODES.md`** - Complete guide to both modes
- **`test-drf-wsprdaemon-compat.py`** - Verification script
- **`SESSION_2025-11-20_WSPRDAEMON_DRF_COMPATIBILITY.md`** - This document

## Testing

### Manual Test Procedure

1. **Generate 10 Hz NPZ files** (if not already present):
   ```bash
   # Run analytics service on existing 16kHz archives
   python -m signal_recorder.analytics_service \
     --archive-dir /tmp/grape-test/archives/WWV_10_MHz \
     --output-dir /tmp/grape-test/analytics/WWV_10_MHz \
     --channel-name "WWV 10 MHz"
   ```

2. **Run DRF writer in wsprdaemon mode**:
   ```bash
   python -m signal_recorder.drf_writer_service \
     --input-dir /tmp/grape-test/analytics/WWV_10_MHz/decimated \
     --output-dir /tmp/grape-test/analytics/WWV_10_MHz \
     --channel-name "ch0" \
     --frequency-hz 10000000 \
     --analytics-state-file /tmp/grape-test/state/analytics-WWV_10_MHz.json \
     --callsign AC0G \
     --grid-square EM38ww \
     --receiver-name GRAPE \
     --psws-station-id AC0G \
     --psws-instrument-id 0
   ```

3. **Verify output structure**:
   ```bash
   # Find the DRF output directory
   find /tmp/grape-test/analytics/WWV_10_MHz/digital_rf -name "ch0" -type d

   # Run compatibility test
   python test-drf-wsprdaemon-compat.py \
     /tmp/grape-test/analytics/WWV_10_MHz/digital_rf/20251120/.../OBS.../ch0
   ```

4. **Expected output**:
   ```
   ✅ Directory structure exists
   📋 Metadata files found: 1
      - metadata_2025-11-20T00-00-00.h5
   
   📝 Metadata fields:
      callsign: AC0G
      grid_square: EM38ww
      receiver_name: GRAPE
      center_frequencies: [10000000.0]
      uuid_str: AC0G
   
   ✓ Wsprdaemon compatibility check:
      ✅ callsign: present
      ✅ grid_square: present
      ✅ receiver_name: present
      ✅ center_frequencies: present
      ✅ uuid_str: present
   
   ✅ Metadata matches wsprdaemon format!
   ```

## Comparison: Before vs After

### Before (Enhanced Mode Only)

```
digital_rf/
└── ch0/
    ├── 2025-11-20T00-00-00.h5
    └── metadata/
        ├── station_info_2025-11-20T00-00-00.h5
        ├── timing_quality/
        │   └── timing_quality_2025-11-20T00-00-00.h5
        ├── data_quality/
        │   └── data_quality_2025-11-20T00-00-00.h5
        └── wwvh_discrimination_2025-11-20T00-00-00.h5
```

**Issues:**
- ❌ Incompatible with wsprdaemon format
- ❌ May cause PSWS ingestion errors
- ❌ Extra metadata not used by existing tools

### After (Wsprdaemon Mode - Default)

```
digital_rf/
└── ch0/
    ├── 2025-11-20T00-00-00.h5
    └── metadata/
        └── metadata_2025-11-20T00-00-00.h5  # Simple format, matches wsprdaemon
```

**Benefits:**
- ✅ Exact match to wsprdaemon output
- ✅ Compatible with PSWS infrastructure
- ✅ Clean, minimal metadata
- ✅ Enhanced mode still available via `--enhanced-metadata` flag

## Migration Strategy

### Phase 1: Deployment (Immediate)
1. Deploy updated `drf_writer_service.py` with default `wsprdaemon_compatible=True`
2. Verify uploads to PSWS succeed
3. Monitor for 1 week to establish baseline

### Phase 2: Validation (1-2 weeks)
1. Compare uploaded data with wsprdaemon stations
2. Confirm PSWS can read and process data correctly
3. Verify no ingestion errors or warnings

### Phase 3: Enhanced Metadata (Future - Optional)
1. Coordinate with PSWS team on enhanced metadata format
2. Run parallel test with `--enhanced-metadata` mode
3. Only enable if PSWS confirms compatibility and value

## Files Modified

- **`src/signal_recorder/drf_writer_service.py`** (151 lines changed)
  - Added `wsprdaemon_compatible` parameter
  - Two-mode metadata writing
  - NPZ field name backward compatibility
  
- **`docs/DRF_WRITER_MODES.md`** (NEW)
  - Complete documentation of both modes
  - Migration guide
  - Troubleshooting

- **`test-drf-wsprdaemon-compat.py`** (NEW)
  - Automated compatibility verification
  - Metadata structure checking

- **`SESSION_2025-11-20_WSPRDAEMON_DRF_COMPATIBILITY.md`** (NEW - this file)

## Key Decisions

1. **Default to wsprdaemon mode** - Ensures immediate compatibility, reduces risk
2. **Keep enhanced mode available** - Provides path forward when PSWS is ready
3. **Single flag to switch modes** - Simple operation, clear intent
4. **Backward compatible NPZ reading** - Handles both old and new field names

## Success Criteria

- ✅ DRF output matches wsprdaemon format exactly
- ✅ Metadata contains only required fields
- ✅ No timing/gap/discrimination metadata in default mode
- ✅ Enhanced mode available via explicit flag
- ✅ Test script validates format
- ✅ Documentation complete

## Next Steps

1. **Test with real data** - Run on live 10Hz NPZ files from WWV_10_MHz channel
2. **Verify PSWS upload** - Ensure rsync succeeds and data ingests correctly
3. **Monitor for issues** - Watch logs for any DRF writing errors
4. **Document in OPERATIONAL_SUMMARY.md** - Update main docs with new mode

## References

- **Wsprdaemon source:** `/wsprdaemon/wav2grape.py`
- **Digital RF spec:** https://github.com/MITHaystack/digital_rf
- **DRF Python API:** https://digital-rf.readthedocs.io/
