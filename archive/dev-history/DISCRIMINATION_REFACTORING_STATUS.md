# Discrimination Refactoring Implementation Status
**Date:** 2025-11-20  
**Status:** IN PROGRESS

## Completed Steps

### ✅ Phase 1: Directory Structure
- Created new analytics subdirectories for all channels:
  - `tone_detections/`
  - `tick_windows/`
  - `station_id_440hz/`
  - `bcd_discrimination/`
  - `discrimination/` (already existed)
- Created `upload/` directory structure with `decimated/` and `digital_rf/` subdirectories

### ✅ Phase 2a: CSV Writer Infrastructure
- Created `src/signal_recorder/discrimination_csv_writers.py`
- Implemented `DiscriminationCSVWriters` class with methods:
  - `write_tone_detection()` - For 800ms timing tones
  - `write_tick_windows()` - For 5ms tick analysis (6 windows)
  - `write_440hz_detection()` - For station ID tones
  - `write_bcd_windows()` - For 100 Hz BCD discrimination
  - `write_discrimination_result()` - For final weighted voting
- All writers create daily CSV files with proper headers
- Thread-safe file append operations

## Next Steps

### Phase 2b: Integrate CSV Writers into Discrimination Code

Need to modify `wwvh_discrimination.py` to call CSV writers:

1. **Add tone_metadata to NPZ archives** (in analytics_service.py)
   - Modify `_create_analytics_npz()` to include `tone_metadata` field
   - Store full tone detection results in NPZ for provenance
   
2. **Update `detect_tick_windows()`** (line 532)
   - After computing results, call `csv_writers.write_tick_windows()`
   - Pass timestamp and full windows list
   
3. **Update `detect_440hz_tone()`** (line 482)
   - After detection, call `csv_writers.write_440hz_detection()`
   - Create `StationID440HzRecord` from results
   
4. **Update `detect_bcd_discrimination()`** (line 858)
   - After computing windows, call `csv_writers.write_bcd_windows()`
   - Pass timestamp and windows_data list
   
5. **Update `finalize_discrimination()`** (line 284)
   - Call `csv_writers.write_discrimination_result()`
   - Create method_weights JSON showing contribution of each method
   
6. **Update `analyze_minute_with_440hz()`** (line 1165)
   - Initialize `DiscriminationCSVWriters` instance
   - Pass to all sub-methods
   - Maintain backward compatibility with existing monolithic CSV

### Phase 3: Tone Detection Integration

Modify `tone_detector.py` to write tone detection CSVs:

1. **Add CSV writer to ToneDetector class**
   - Initialize `DiscriminationCSVWriters` in `__init__()`
   - Store data_root path
   
2. **Update `detect_tones()` method**
   - After successful detection, call `csv_writers.write_tone_detection()`
   - Create `ToneDetectionRecord` for each detection
   
3. **Return tone_metadata structure**
   - Format results for embedding in NPZ archives
   - Include all fields needed for discrimination

### Phase 4: Update Analytics Service

Modify `analytics_service.py` to include tone metadata in NPZ:

1. **Update `_create_analytics_npz()`**
   - Add `tone_metadata` parameter
   - Save tone detections in NPZ file
   - Structure: `{'detections': [list of detection dicts]}`
   
2. **Pass tone detections from buffer processing**
   - Get detections from `ToneDetector`
   - Include in NPZ creation call

### Phase 5: Update Reprocessing Scripts

Fix `reprocess_discrimination_timerange.py` to run tone detection:

1. **Import ToneDetector**
   - Already added (line 21)
   
2. **Initialize tone detector** (line 47-52)
   - Already added but incomplete
   
3. **Run tone detection on each minute** (line 84-91)
   - Load 16 kHz NPZ
   - Call `tone_detector.detect_tones(iq_samples, timestamp, ...)`
   - Pass detections to `analyze_minute_with_440hz()`
   - ⚠️ **CRITICAL FIX:** Replace `detections=[]` with actual detections

4. **Ensure all CSV writers are called**
   - Tone detections → `tone_detections/`
   - Tick windows → `tick_windows/`
   - 440 Hz → `station_id_440hz/`
   - BCD → `bcd_discrimination/`
   - Final → `discrimination/`

### Phase 6: Backward Compatibility

During transition, maintain both formats:

1. **Keep writing monolithic CSV**
   - Existing code that appends all data to single CSV
   - Don't break existing web UI or scripts
   
2. **Add new CSV writing**
   - Call new CSV writers in parallel
   - Verify data matches between old and new formats
   
3. **Deprecation plan**
   - After validation, remove old monolithic CSV writer
   - Update web UI to read from new CSVs
   - Migration utility for historical data

### Phase 7: Update Web UI

Modify web UI to read from new CSV locations:

1. **Update API endpoints** (if using monitoring server)
   - Add endpoints for each CSV type
   - Maintain backward compatibility
   
2. **Update JavaScript loaders**
   - `discrimination-enhanced.js`
   - Load from multiple CSV files
   - Combine for unified visualization
   
3. **Test with new data structure**
   - Verify all plots work
   - Confirm data integrity

### Phase 8: Migration Utilities

Create scripts to split existing monolithic CSVs:

1. **`migrate_discrimination_data.py`**
   - Read existing discrimination CSVs
   - Parse embedded JSON fields (bcd_windows, tick_windows_10sec)
   - Write to separate CSVs per method
   - Validate data integrity
   
2. **Batch migration**
   - Process all historical dates
   - Verify row counts match
   - Generate migration report

## Key Design Decisions

### Data Duplication Strategy

**Tone detections** stored in BOTH:
- NPZ `tone_metadata` field - Complete provenance
- CSV `tone_detections/` - Easy analysis

**Benefits:**
- NPZ self-contained for archival
- CSV convenient for bulk queries
- ~500 bytes/minute overhead (negligible)

### File Naming Convention

All CSV files follow pattern:
```
{channel}_{method}_YYYYMMDD.csv
```

Examples:
- `WWV_10_MHz_tones_20251120.csv`
- `WWV_10_MHz_ticks_20251120.csv`
- `WWV_10_MHz_440hz_20251120.csv`
- `WWV_10_MHz_bcd_20251120.csv`
- `WWV_10_MHz_discrimination_20251120.csv`

### Reprocessing Independence

Each method can be reprocessed independently:

```bash
# Reprocess only BCD analysis for Nov 15
python3 scripts/reprocess_bcd_only.py --date 20251115 --channel "WWV 10 MHz"

# Reprocess only tick windows for Nov 15
python3 scripts/reprocess_ticks_only.py --date 20251115 --channel "WWV 10 MHz"
```

New reprocessing scripts needed:
- `reprocess_tones_only.py`
- `reprocess_ticks_only.py`
- `reprocess_440hz_only.py`
- `reprocess_bcd_only.py`
- `reprocess_voting_only.py` (reads from other CSVs)

## Testing Plan

### Unit Tests

1. **CSV Writers**
   - Test each writer method independently
   - Verify CSV format and headers
   - Check file creation and append behavior
   
2. **Data Integrity**
   - Compare old monolithic vs new separate CSVs
   - Verify row counts match
   - Check numerical precision

### Integration Tests

1. **End-to-end processing**
   - Process one minute through full pipeline
   - Verify all CSVs created
   - Check data consistency across files
   
2. **Reprocessing**
   - Reprocess known data
   - Compare against original results
   - Verify tone detection works from archives

### Validation Tests

1. **Historical data migration**
   - Migrate sample day (Nov 15)
   - Verify all data preserved
   - Check web UI displays correctly
   
2. **Performance**
   - Measure overhead of separate CSV writes
   - Ensure acceptable (<10% slowdown)

## Issues and Risks

### Current Known Issues

1. **Reprocessing has no tone data**
   - Root cause: `detections=[]` in reprocess script
   - Impact: Power ratio graphs all zeros
   - Fix: Run tone detection during reprocessing
   
2. **NPZ files don't have tone_metadata**
   - Archives created before this change
   - Need to add in analytics_service.py
   - Historical NPZ won't have it (acceptable)

### Risks

1. **Storage overhead**
   - Mitigation: Separate CSVs use ~same space as monolithic
   - Each CSV properly sized for its data
   
2. **Code complexity**
   - Mitigation: Clear separation of concerns
   - Each method isolated and testable
   
3. **Backward compatibility**
   - Mitigation: Maintain both formats during transition
   - Gradual migration path

## Success Criteria

✅ All discrimination methods write separate CSVs  
✅ NPZ archives include tone_metadata  
✅ Reprocessing runs tone detection from 16 kHz data  
✅ Weighted voting power ratio shows real separation  
✅ Each method independently reprocessable  
✅ Web UI displays all data correctly  
✅ Historical data successfully migrated  
✅ No performance regression  

## Timeline Estimate

- **Phase 2b:** 2-3 hours (integrate CSV writers)
- **Phase 3:** 1-2 hours (tone detection CSV)
- **Phase 4:** 1 hour (analytics service NPZ metadata)
- **Phase 5:** 1 hour (fix reprocessing script)
- **Phase 6:** 1 hour (backward compatibility)
- **Phase 7:** 2-3 hours (web UI updates)
- **Phase 8:** 2-3 hours (migration utilities)

**Total: 10-15 hours** of focused work

## Current Progress

- ✅ Planning complete
- ✅ Directory structure created
- ✅ CSV writer infrastructure implemented
- ⏳ Integration into discrimination code (next)
- ⏳ Tone detection CSV writing
- ⏳ NPZ metadata updates
- ⏳ Reprocessing fixes
- ⏳ Testing and validation
