# Architecture Refactoring Notes

## Decimation Misplacement (December 2024)

### Issue
The decimation to 10 Hz for upload is currently performed in `analytics_service.py` (Phase 2), but it should be in Phase 3 (product generation).

### Current (Incorrect) Flow
```
Phase 1: RTP → 20 kHz raw archive
Phase 2: Analytics (timing, WWV/WWVH discrimination) + DECIMATION ← wrong
Phase 3: Spectrograms, uploads
```

### Correct Flow
```
Phase 1: RTP → 20 kHz raw archive  
Phase 2: Analytics (timing, WWV/WWVH discrimination ONLY)
Phase 3: Decimation to 10 Hz, spectrograms, uploads
```

### Rationale
- Decimation is **product generation**, not analysis
- Phase 2 should only compute metrics and annotations
- The 10 Hz decimated data is an output product for upload, not an analysis result

### Code Locations to Refactor
- `analytics_service.py:35` - imports `decimate_for_upload`
- `analytics_service.py:883` - calls `_write_decimated_npz()`
- `analytics_service.py:1423-1507` - `_write_decimated_npz()` method

### Migration Plan
1. Create Phase 3 service or extend product generator
2. Move `_write_decimated_npz()` to Phase 3
3. Phase 3 reads raw archive, applies decimation, writes 10 Hz output
4. Remove decimation code from analytics_service.py

### Priority
Medium - functional but architecturally incorrect. Refactor when time permits.
