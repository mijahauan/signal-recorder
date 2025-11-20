# Digital RF Writer - Wsprdaemon Compatibility Achievement

**Date:** November 20, 2025  
**Status:** ✅ **COMPLETE - All Tests Passing**

## Summary

Successfully implemented wsprdaemon-compatible Digital RF output from 10 Hz NPZ files. The DRF writer now produces output that **exactly matches** wsprdaemon's format for upload to PSWS.

## Test Results

```
======================================================================
TEST SUMMARY
======================================================================
Directory structure: ✅ PASS
Metadata format:     ✅ PASS
Sample data:         ✅ PASS

🎉 All tests passed - wsprdaemon compatible!
```

### Verified Capabilities

1. **Metadata Format** - Matches wsprdaemon exactly:
   - ✅ Single `metadata_*.h5` file (not `station_info`)
   - ✅ Fields: `callsign`, `grid_square`, `receiver_name`, `center_frequencies`, `uuid_str`
   - ✅ NO timing quality, gap analysis, or discrimination metadata (wsprdaemon mode)

2. **Data Format** - Compatible with PSWS:
   - ✅ float32 dtype with shape (N, 2) for I/Q pairs
   - ✅ Complex data readable as complex64
   - ✅ Correct sample indices and timestamps

3. **File Structure** - Standard Digital RF layout:
   - ✅ Daily subdirectories (86400 second cadence)
   - ✅ Hourly data files (3600000 millisecond cadence)
   - ✅ Compression level 9

## Key Technical Fixes

### 1. Data Type Format
**Issue:** Used `np.complex64` with `is_complex=True`, causing index doubling.  
**Solution:** Use `np.float32` with shape `(N, 2)` and `is_complex=True` (matches wsprdaemon).

```python
# Convert complex64 to float32 (N, 2) format
iq_complex = archive.iq_samples.astype(np.complex64, copy=False)
iq_float = np.zeros((len(iq_complex), 2), dtype=np.float32)
iq_float[:, 0] = iq_complex.real
iq_float[:, 1] = iq_complex.imag

# Write with float32 dtype
self.drf_writer = drf.DigitalRFWriter(
    str(drf_dir),
    dtype=np.float32,  # float32 with (N, 2) shape for I/Q
    is_complex=True,   # True when using float32 (N, 2) format
    ...
)
```

### 2. Data Flushing
**Issue:** Data buffered in memory, not written to disk until writer closed.  
**Solution:** Explicitly close writer after each file to flush data.

```python
self.drf_writer.rf_write(iq_float, write_index)

# CRITICAL: Close writer to flush data to disk
self.drf_writer.close()
self.drf_writer = None
```

### 3. Sample Index Calculation
**Issue:** Various timing and index calculation bugs.  
**Solution:** Use calculated_index consistently, based on UTC timestamp × sample_rate.

```python
calculated_index = int(utc_timestamp * self.sample_rate)
self.drf_writer.rf_write(iq_float, calculated_index)
```

### 4. Metadata Compatibility
**Issue:** Enhanced metadata (timing, gaps, discrimination) not compatible with wsprdaemon.  
**Solution:** Conditional metadata writing based on `wsprdaemon_compatible` flag.

```python
if self.wsprdaemon_compatible:
    # Single metadata file with basic station info only
    metadata_writers['station'] = drf.DigitalMetadataWriter(
        metadata_dir=str(metadata_dir),
        file_name='metadata'  # wsprdaemon uses 'metadata' not 'station_info'
    )
    station_metadata = {
        'callsign': self.station_config['callsign'],
        'grid_square': self.station_config['grid_square'],
        'receiver_name': self.station_config['receiver_name'],
        'center_frequencies': np.array([self.frequency_hz], dtype=np.float64),
        'uuid_str': self.dataset_uuid
    }
else:
    # Enhanced mode: timing_quality/, data_quality/, etc.
    ...
```

## Usage

### Wsprdaemon-Compatible Mode (Default)

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
  --psws-station-id S000171 \
  --psws-instrument-id 172
```

### Enhanced Metadata Mode (Optional)

```bash
# Add this flag to enable enhanced metadata:
--enhanced-metadata
```

## Testing

Run the automated compatibility test:

```bash
./test-drf-quick.sh
```

Or test manually:

```bash
python test-drf-wsprdaemon-compat.py \
  /path/to/digital_rf/20251120/.../OBS.../
```

## Files Modified

1. **`src/signal_recorder/drf_writer_service.py`**
   - Two-mode metadata support (`wsprdaemon_compatible` flag)
   - float32 (N, 2) data format
   - Explicit writer close after each write
   - Correct index calculation

2. **`docs/DRF_WRITER_MODES.md`** (created)
   - Complete documentation of both modes
   - Migration guide
   - Troubleshooting

3. **`test-drf-wsprdaemon-compat.py`** (created)
   - Automated compatibility verification
   - Metadata structure checking
   - Sample data validation

4. **`test-drf-quick.sh`** (created)
   - End-to-end integration test
   - Creates test data, runs DRF writer, verifies output

5. **`SESSION_2025-11-20_WSPRDAEMON_DRF_COMPATIBILITY.md`** (created)
   - Implementation session notes
   - Technical decisions
   - Comparison tables

## Next Steps

1. **Deploy to production** - Use wsprdaemon-compatible mode by default
2. **Verify PSWS upload** - Ensure rsync succeeds and data ingests correctly
3. **Monitor for issues** - Watch logs for any DRF writing errors
4. **Future enhancement** - Coordinate with PSWS team for optional enhanced metadata

## Comparison: Digital RF Index Behavior

| Configuration | dtype | is_complex | Index Behavior | Notes |
|--------------|-------|------------|----------------|-------|
| **Wsprdaemon (CORRECT)** | float32 | True | Doubled internally | Reads as complex64 |
| complex64 | False | Normal | **NOT compatible** |
| complex64 | True | Doubled × 2 = 4x | **WRONG** |

The key insight: When `is_complex=True`, Digital RF treats each I/Q pair as TWO samples internally, so indices are doubled. This is expected and correct for the wsprdaemon format.

## Reference

- **Wsprdaemon source:** `/wsprdaemon/wav2grape.py` lines 125-139
- **Digital RF docs:** https://digital-rf.readthedocs.io/
- **Test data location:** `/tmp/grape-test/analytics/WWV_10_MHz/`
